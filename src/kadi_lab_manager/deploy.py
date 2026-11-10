"""Plan (diff) and apply (converge) a compiled model against a Kadi4Mat instance.

``plan`` never writes. ``apply`` creates what is missing and, only with
``update=True``, patches objects whose metadata drifted from the model. Nothing is
ever deleted by these two commands (see :mod:`kadi_lab_manager.cleanup`).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from .client import KadiClient
from .compile import Compiled, CompiledFile, kadi_checksum
from .errors import ApiError
from .report import RunReport
from .state import State

RECORD_FIELDS = ("title", "type", "description", "license", "visibility", "tags", "extras")
COLLECTION_FIELDS = ("title", "description", "visibility", "tags")
TEMPLATE_FIELDS = ("title", "description", "visibility")


@dataclass
class Op:
    order: int
    action: str          # create | update | add_child | set_record_template | add_member | link | update_link
    #                      | upload | replace_file | add_role | change_role | skip | drift | warn
    kind: str            # collections | templates | records | hierarchy | membership | links | files | roles
    identifier: str
    detail: dict = field(default_factory=dict)
    needs_update: bool = False   # only executed with --update
    executed: bool = False
    status: str = "planned"
    message: str = ""

    def describe(self) -> str:
        d = self.detail
        if self.action in ("create", "update", "skip", "drift"):
            extra = ""
            if "changed" in d:
                extra = " changed: " + ", ".join(d["changed"])
            return f"{self.kind[:-1] if self.kind.endswith('s') else self.kind} {self.identifier}{extra}"
        if self.action == "add_child":
            return f"collection {d['parent']} -> {self.identifier}"
        if self.action == "set_record_template":
            return f"collection {self.identifier} default template -> {d['template']}"
        if self.action == "add_member":
            return f"record {self.identifier} into collection {d['collection']}"
        if self.action in ("link", "update_link"):
            return f"{d['source']} --{d['name']}--> {d['target']}" + (f" (term: {d.get('term')})" if d.get("term") else "")
        if self.action in ("upload", "replace_file"):
            return f"{d['name']} ({d['size']} B) -> record {self.identifier}"
        if self.action in ("add_role", "change_role"):
            subject = f"group {d['group']}" if d.get("group") else f"user {d.get('user')}"
            return f"{subject} as {d['role']} on {d['resource_kind'][:-1]} {self.identifier}"
        return f"{self.kind} {self.identifier} {self.message}"


class Plan:
    def __init__(self):
        self.ops: list[Op] = []
        self.warnings: list[str] = []
        self._n = 0

    def add(self, action: str, kind: str, identifier: str, needs_update=False, **detail) -> Op:
        self._n += 1
        op = Op(self._n, action, kind, identifier, detail, needs_update)
        self.ops.append(op)
        return op

    def counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for op in self.ops:
            key = op.action + (" (needs --update)" if op.needs_update else "")
            out[key] = out.get(key, 0) + 1
        return out

    def has_changes(self, include_updates: bool) -> bool:
        return any(op.action not in ("skip", "drift", "warn") and (include_updates or not op.needs_update)
                   for op in self.ops)


# --------------------------------------------------------------------------- helpers
def _diff(desired: dict, existing: dict, fields) -> list[str]:
    changed = []
    for f in fields:
        if _norm(desired.get(f)) != _norm(existing.get(f)):
            changed.append(f)
    return changed


def _norm(value):
    if isinstance(value, list) and value and all(isinstance(v, str) for v in value):
        return sorted(value)
    return value


def _template_data_for_compare(data: Any) -> Any:
    if not isinstance(data, dict):
        return data
    out = dict(data)
    out["collections"] = sorted(out.get("collections") or [])
    out["record_links"] = sorted((json.dumps(x, sort_keys=True) for x in out.get("record_links") or []))
    out["roles"] = sorted((json.dumps(x, sort_keys=True) for x in out.get("roles") or []))
    return out


# --------------------------------------------------------------------------- planner
class Planner:
    def __init__(self, client: KadiClient, compiled: Compiled, state: State | None = None,
                 check_files: bool = True):
        self.client = client
        self.compiled = compiled
        self.state = state
        self.check_files = check_files
        self.existing: dict[str, dict[str, dict | None]] = {"collections": {}, "templates": {}, "records": {}}
        self.ids: dict[str, dict[str, int]] = {"collections": {}, "templates": {}, "records": {}}
        self.groups: dict[str, int | None] = {}
        self.plan = Plan()

    # -- lookups ------------------------------------------------------------------------
    def _lookup(self, kind: str, identifier: str) -> dict | None:
        if identifier not in self.existing[kind]:
            data = self.client.get_by_identifier(kind, identifier)
            self.existing[kind][identifier] = data
            if data is not None:
                self.ids[kind][identifier] = data["id"]
        return self.existing[kind][identifier]

    def group_id(self, identifier: str) -> int | None:
        if identifier not in self.groups:
            group = self.client.group_by_identifier(identifier)
            self.groups[identifier] = group["id"] if group else None
            if group is None:
                self.plan.warnings.append(f"group '{identifier}' does not exist on the server; its roles are skipped")
        return self.groups[identifier]

    def resolve_template_data(self, tmpl) -> Any:
        """Replace symbolic references in template data by ids (None when not yet created)."""
        if tmpl.kind != "record":
            return tmpl.data
        data = dict(tmpl.data)
        data["collections"] = [self.ids["collections"].get(c) for c in tmpl.collections]
        data["record_links"] = [{"direction": rl["direction"], "record": self.ids["records"].get(rl["record"]),
                                 "name": rl["name"], "term": rl["term"]} for rl in tmpl.record_links]
        roles = []
        for role in tmpl.roles:
            if role.group:
                gid = self.group_id(role.group)
                if gid is None:
                    continue
                roles.append({"subject_type": "group", "subject_id": gid, "role": role.role})
            else:
                roles.append({"subject_type": "user", "subject_id": role.user, "role": role.role})
        data["roles"] = roles
        return data

    # -- planning -------------------------------------------------------------------------
    def build(self) -> Plan:
        c = self.compiled
        plan = self.plan

        # 1. collections
        for col in c.collections:
            existing = self._lookup("collections", col.identifier)
            if existing is None:
                plan.add("create", "collections", col.identifier, payload=col.payload)
            else:
                changed = _diff(col.payload, existing, COLLECTION_FIELDS)
                if changed:
                    plan.add("update", "collections", col.identifier, needs_update=True, changed=changed,
                             payload={k: col.payload[k] for k in changed})
                else:
                    plan.add("skip", "collections", col.identifier)

        # 2. records (metadata only)
        for rec in c.records:
            existing = self._lookup("records", rec.identifier)
            if existing is None:
                plan.add("create", "records", rec.identifier, payload=rec.payload)
            else:
                changed = _diff(rec.payload, existing, RECORD_FIELDS)
                if changed:
                    plan.add("update", "records", rec.identifier, needs_update=True, changed=changed,
                             payload={k: rec.payload[k] for k in changed})
                else:
                    plan.add("skip", "records", rec.identifier)

        # 3. templates (need collection/record ids inside their data)
        for tmpl in c.templates:
            existing = self._lookup("templates", tmpl.identifier)
            desired_data = self.resolve_template_data(tmpl)
            if existing is None:
                plan.add("create", "templates", tmpl.identifier, payload=tmpl.payload, data=desired_data,
                         symbolic=True)
            else:
                changed = _diff(tmpl.payload, existing, TEMPLATE_FIELDS)
                if _template_data_for_compare(desired_data) != _template_data_for_compare(existing.get("data")):
                    changed.append("data")
                if changed:
                    plan.add("update", "templates", tmpl.identifier, needs_update=True, changed=changed,
                             payload={k: tmpl.payload[k] for k in changed if k != "data"},
                             data=desired_data if "data" in changed else None, symbolic=True)
                else:
                    plan.add("skip", "templates", tmpl.identifier)

        # 4. hierarchy
        children_cache: dict[str, set[str]] = {}
        for col in c.collections:
            if not col.parent:
                continue
            parent_existing = self.existing["collections"].get(col.parent)
            child_existing = self.existing["collections"].get(col.identifier)
            if parent_existing and child_existing:
                if col.parent not in children_cache:
                    children_cache[col.parent] = {
                        ch["identifier"] for ch in self.client.child_collections(parent_existing["id"])}
                if col.identifier in children_cache[col.parent]:
                    continue
            plan.add("add_child", "hierarchy", col.identifier, parent=col.parent)

        # 5. default record templates of collections
        for col in c.collections:
            if not col.record_template:
                continue
            existing = self.existing["collections"].get(col.identifier)
            tmpl_id = self.ids["templates"].get(col.record_template)
            if existing is not None and tmpl_id is not None:
                link = (existing.get("_links") or {}).get("record_template", "")
                if link.rstrip("/").endswith(f"/templates/{tmpl_id}"):
                    continue
            plan.add("set_record_template", "collections", col.identifier, template=col.record_template)

        # 6. membership
        for rec in c.records:
            existing = self.existing["records"].get(rec.identifier)
            current: set[str] = set()
            if existing is not None and rec.collections:
                current = {col["identifier"] for col in self.client.record_collections(existing["id"])}
            for col in rec.collections:
                if col not in current:
                    plan.add("add_member", "membership", rec.identifier, collection=col)

        # 7. links
        out_links: dict[str, list[dict]] = {}
        for link in c.links:
            src = self.existing["records"].get(link.source)
            dst = self.existing["records"].get(link.target)
            found = None
            if src is not None and dst is not None:
                if link.source not in out_links:
                    out_links[link.source] = self.client.record_links(src["id"], direction="out")
                for existing_link in out_links[link.source]:
                    if (existing_link.get("record_to", {}).get("identifier") == link.target
                            and existing_link.get("name") == link.name):
                        found = existing_link
                        break
            if found is None:
                plan.add("link", "links", f"{link.source}->{link.target}", source=link.source,
                         target=link.target, name=link.name, term=link.term)
            elif (found.get("term") or None) != (link.term or None):
                plan.add("update_link", "links", f"{link.source}->{link.target}", needs_update=True,
                         source=link.source, target=link.target, name=link.name, term=link.term,
                         link_id=found["id"], current_term=found.get("term"))

        # 8. files
        for rec in c.records:
            if not rec.files:
                continue
            existing = self.existing["records"].get(rec.identifier)
            current_files = {}
            if existing is not None:
                current_files = {f["name"]: f for f in self.client.files(existing["id"])}
            for cf in rec.files:
                cur = current_files.get(cf.name)
                if cur is None:
                    plan.add("upload", "files", rec.identifier, name=cf.name, size=cf.size, path=str(cf.path),
                             description=cf.description, mimetype=cf.mimetype)
                    continue
                reason = None
                if int(cur.get("size", -1)) != cf.size:
                    reason = f"size differs (server {cur.get('size')}, local {cf.size})"
                elif self.check_files and cur.get("checksum") and cf.path.exists():
                    local = kadi_checksum(cf.path)
                    if local != cur["checksum"]:
                        reason = f"checksum differs (server {cur['checksum']}, local {local})"
                if reason:
                    plan.add("replace_file", "files", rec.identifier, needs_update=True, name=cf.name, size=cf.size,
                             path=str(cf.path), description=cf.description, mimetype=cf.mimetype, reason=reason)

        # 9. roles (groups by identifier, users by id)
        for kind, items in (("collections", c.collections), ("records", c.records), ("templates", c.templates)):
            for item in items:
                roles = item.roles if kind != "templates" else item.template_roles
                if not roles:
                    continue
                existing = self.existing[kind].get(item.identifier)
                current_groups: dict[int, str] = {}
                current_users: dict[int, str] = {}
                if existing is not None:
                    current_groups = {r["group"]["id"]: r["role"]["name"] for r in self.client.group_roles(kind, existing["id"])}
                    current_users = {r["user"]["id"]: r["role"]["name"] for r in self.client.user_roles(kind, existing["id"])}
                for role in roles:
                    if role.group:
                        gid = self.group_id(role.group)
                        if gid is None:
                            continue
                        if gid not in current_groups:
                            plan.add("add_role", "roles", item.identifier, resource_kind=kind, group=role.group,
                                     group_id=gid, role=role.role)
                        elif current_groups[gid] != role.role:
                            plan.add("change_role", "roles", item.identifier, needs_update=True, resource_kind=kind,
                                     group=role.group, group_id=gid, role=role.role, current=current_groups[gid])
                    else:
                        if role.user not in current_users:
                            plan.add("add_role", "roles", item.identifier, resource_kind=kind, user=role.user,
                                     role=role.role)
        return plan


# --------------------------------------------------------------------------- executor
class Executor:
    def __init__(self, client: KadiClient, planner: Planner, plan: Plan, state: State, report: RunReport,
                 update: bool = False, continue_on_error: bool = False, model_name: str = "", namespace: str = "",
                 log=print):
        self.client = client
        self.planner = planner
        self.plan = plan
        self.state = state
        self.report = report
        self.update = update
        self.continue_on_error = continue_on_error
        self.model_name = model_name
        self.namespace = namespace
        self.log = log
        self.ids = planner.ids
        self.compiled = planner.compiled

    def _id(self, kind: str, identifier: str) -> int:
        try:
            return self.ids[kind][identifier]
        except KeyError:
            raise ApiError("-", f"{kind}/{identifier}", 0, "resource id unknown (creation failed earlier?)") from None

    def run(self) -> None:
        # Remember adopted (pre-existing) resources in the state file.
        for kind in ("collections", "templates", "records"):
            for identifier, data in self.planner.existing[kind].items():
                if data is not None:
                    self.state.remember(kind, identifier, data["id"], created_by_tool=False,
                                        model_name=self.model_name, namespace=self.namespace)
        for op in self.plan.ops:
            if op.action in ("skip", "drift", "warn"):
                op.status = "skipped"
                continue
            if op.needs_update and not self.update:
                op.status = "needs-update-flag"
                continue
            try:
                self._execute(op)
                op.executed = True
                op.status = "done"
                self.log(f"[{op.action.upper()}] {op.describe()}")
            except ApiError as exc:
                op.status = "failed"
                op.message = str(exc)
                self.report.error(f"{op.action} {op.identifier}: {exc}")
                self.log(f"[FAILED] {op.describe()}: {exc}")
                if not self.continue_on_error:
                    break
            finally:
                self.state.save()
            self.report.op(op.action, op.kind, op.identifier, status=op.status, **_json_safe(op.detail),
                           message=op.message)
        # Operations not reached (after a failure) are reported as not executed.
        for op in self.plan.ops:
            if op.status == "planned":
                op.status = "not-executed"
                self.report.op(op.action, op.kind, op.identifier, status=op.status, **_json_safe(op.detail))

    def _execute(self, op: Op) -> None:
        c = self.client
        d = op.detail
        if op.action == "create":
            if op.kind == "templates":
                tmpl = next(t for t in self.compiled.templates if t.identifier == op.identifier)
                payload = {**tmpl.payload, "data": self.planner.resolve_template_data(tmpl)}
                created = c.create("templates", payload)
            else:
                created = c.create(op.kind, d["payload"])
            self.ids[op.kind][op.identifier] = created["id"]
            self.planner.existing[op.kind][op.identifier] = created
            self.state.remember(op.kind, op.identifier, created["id"], created_by_tool=True,
                                model_name=self.model_name, namespace=self.namespace)
            d["id"] = created["id"]
        elif op.action == "update":
            payload = dict(d.get("payload") or {})
            if op.kind == "templates" and d.get("data") is not None:
                tmpl = next(t for t in self.compiled.templates if t.identifier == op.identifier)
                payload["data"] = self.planner.resolve_template_data(tmpl)
            c.patch(op.kind, self._id(op.kind, op.identifier), payload)
        elif op.action == "add_child":
            added = c.add_child_collection(self._id("collections", d["parent"]), self._id("collections", op.identifier))
            if not added:
                op.message = "server answered 409: the child already has another parent or the link would be circular"
                self.report.warn(f"hierarchy {d['parent']} -> {op.identifier}: {op.message}")
        elif op.action == "set_record_template":
            c.patch("collections", self._id("collections", op.identifier),
                    {"record_template": self._id("templates", d["template"])})
        elif op.action == "add_member":
            if not c.add_record_to_collection(self._id("collections", d["collection"]), self._id("records", op.identifier)):
                op.message = "already a member (409)"
        elif op.action == "link":
            try:
                created = c.link_records(self._id("records", d["source"]), self._id("records", d["target"]),
                                         d["name"], d.get("term"))
                d["link_id"] = created.get("id")
            except ApiError as exc:
                if exc.status == 409:
                    op.message = "already existed"
                else:
                    raise
        elif op.action == "update_link":
            c.update_link(self._id("records", d["source"]), d["link_id"], name=d["name"], term=d.get("term"))
        elif op.action in ("upload", "replace_file"):
            from pathlib import Path
            meta = c.upload_file(self._id("records", op.identifier), Path(d["path"]), d["name"],
                                 description=d.get("description") or "", mimetype=d.get("mimetype"),
                                 replace=(op.action == "replace_file"))
            d["file_id"] = meta.get("id")
            d["checksum"] = meta.get("checksum")
        elif op.action == "add_role":
            rid = self._id(d["resource_kind"], op.identifier)
            if d.get("group"):
                c.add_group_role(d["resource_kind"], rid, d["group_id"], d["role"])
            else:
                c.add_user_role(d["resource_kind"], rid, d["user"], d["role"])
        elif op.action == "change_role":
            c.change_group_role(d["resource_kind"], self._id(d["resource_kind"], op.identifier), d["group_id"],
                                d["role"])
        else:  # pragma: no cover
            raise ApiError("-", op.identifier, 0, f"unknown operation {op.action}")


def _json_safe(detail: dict) -> dict:
    out = {}
    for k, v in detail.items():
        if k in ("payload", "data"):
            continue  # keep reports compact; the model holds the payloads
        out[k] = v if isinstance(v, (str, int, float, bool, type(None), list, dict)) else str(v)
    return out


def file_summary(cf: CompiledFile) -> dict:
    return {"name": cf.name, "size": cf.size, "mimetype": cf.mimetype, "path": str(cf.path)}
