"""A faithful-enough in-memory mock of the Kadi4Mat HTTP API v1 for offline testing.

It speaks HTTPS with the self-signed localhost certificate in ``tests/fixtures`` (so the
client's TLS verification stays switched on, exactly as against the real instance),
validates extras with the same rules as the server (``kadi_lab_manager.extras``),
answers 201/409/400 like Kadi, paginates, implements the upload protocol with
``Kadi-MD5-Checksum`` verification and produces JSON / RO-Crate exports in the
server's shape. Standard library only.

Run standalone:  python tests/mock_kadi.py 8443

Attribution: the API behaviour reproduced here (endpoints, status codes, response
shapes and a few error messages) is that of Kadi4Mat, Copyright 2020 Karlsruhe
Institute of Technology, Apache License 2.0 (https://gitlab.com/iam-cms/kadi). This
mock is an independent re-implementation for testing; see NOTICE.
"""
from __future__ import annotations

import hashlib
import io
import json
import re
import ssl
import sys
import threading
import uuid
import zipfile
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from kadi_lab_manager.extras import ExtrasValidationError, load_extras  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"
IDENTIFIER_RE = re.compile(r"^[a-z0-9-_]+$")
VISIBILITIES = ("private", "public", "open")


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class MockState:
    def __init__(self, chunk_boundary: int = 50 * 1024 * 1024, chunk_size: int = 10 * 1024 * 1024,
                 groups: dict[str, int] | None = None):
        self.lock = threading.RLock()
        self.counter = 100
        self.resources: dict[str, dict[int, dict]] = {"records": {}, "collections": {}, "templates": {}}
        self.links: dict[int, dict] = {}
        self.memberships: set[tuple[int, int]] = set()          # (collection_id, record_id)
        self.files: dict[str, dict] = {}                        # file_id -> meta (+ "_data")
        self.uploads: dict[str, dict] = {}
        self.roles: dict[tuple[str, int], dict] = {}            # (kind, id) -> {"groups": {gid: role}, "users": {...}}
        self.groups = {name: {"id": gid, "identifier": name, "title": name} for name, gid in (groups or {}).items()}
        self.chunk_boundary = chunk_boundary
        self.chunk_size = chunk_size
        self.requests: list[tuple[str, str]] = []
        self.user = {"id": 1, "displayname": "Mock User", "orcid": None}

    def next_id(self) -> int:
        self.counter += 1
        return self.counter

    def by_identifier(self, kind: str, identifier: str) -> dict | None:
        for res in self.resources[kind].values():
            if res["identifier"] == identifier and res["state"] == "active":
                return res
        return None


class ApiError(Exception):
    def __init__(self, status: int, description: str = "", errors=None):
        self.status, self.description, self.errors = status, description, errors
        super().__init__(description)


def _norm(value):
    return " ".join(value.split()) if isinstance(value, str) else value


class Handler(BaseHTTPRequestHandler):
    server_version = "MockKadi/1.14"
    state: MockState = None  # set by factory

    # ------------------------------------------------------------------ plumbing
    def log_message(self, fmt, *args):  # quiet
        pass

    def _base(self) -> str:
        return f"https://{self.headers.get('Host', '127.0.0.1')}/api/v1"

    def _send(self, status: int, body=None, raw: bytes | None = None, content_type="application/json"):
        if raw is None:
            raw = b"" if body is None else json.dumps(body, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        if raw:
            self.wfile.write(raw)

    def _error(self, exc: ApiError):
        body = {"code": exc.status, "message": {400: "Bad Request", 401: "Unauthorized", 404: "Not Found",
                                                409: "Conflict", 413: "Payload Too Large"}.get(exc.status, "Error"),
                "description": exc.description or ""}
        if exc.errors:
            body["errors"] = exc.errors
        self._send(exc.status, body)

    def _body_json(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        if not raw:
            return {}
        try:
            return json.loads(raw)
        except ValueError:
            raise ApiError(400, "Failed to decode JSON object.")

    def _body_bytes(self) -> bytes:
        length = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(length) if length else b""

    def _auth(self):
        auth = self.headers.get("Authorization", "")
        if not auth.startswith("Bearer ") or len(auth) < 12:
            raise ApiError(401, "No valid access token.")

    def _paginate(self, items: list, query: dict, link_base: str) -> dict:
        page = int(query.get("page", ["1"])[0])
        per_page = min(int(query.get("per_page", ["10"])[0]), 100)
        total = len(items)
        total_pages = max(1, (total + per_page - 1) // per_page)
        chunk = items[(page - 1) * per_page: page * per_page]
        return {"items": chunk, "_pagination": {"page": page, "per_page": per_page, "total_pages": total_pages,
                                                "total_items": total},
                "_links": {"self": f"{link_base}?page={page}&per_page={per_page}"}}

    # ------------------------------------------------------------------ serialisation
    def _user(self):
        return dict(self.state.user)

    def _resource_json(self, kind: str, res: dict, export: bool = False) -> dict:
        base = self._base()
        out = {k: v for k, v in res.items() if not k.startswith("_") and k not in ("parent_id", "record_template_id")}
        out["creator"] = self._user()
        if export:
            for k in ("visibility", "plain_description", "state"):
                out.pop(k, None)
            return out
        rid = res["id"]
        if kind == "records":
            out["_links"] = {"self": f"{base}/records/{rid}", "files": f"{base}/records/{rid}/files",
                             "collections": f"{base}/records/{rid}/collections",
                             "records_to": f"{base}/records/{rid}/records?direction=out",
                             "records_from": f"{base}/records/{rid}/records?direction=in",
                             "view": f"https://{self.headers.get('Host')}/records/{rid}"}
            out["_actions"] = {"edit": f"{base}/records/{rid}", "delete": f"{base}/records/{rid}",
                               "new_upload": f"{base}/records/{rid}/uploads",
                               "link_record": f"{base}/records/{rid}/records",
                               "link_collection": f"{base}/records/{rid}/collections"}
        elif kind == "collections":
            out["_links"] = {"self": f"{base}/collections/{rid}", "records": f"{base}/collections/{rid}/records",
                             "children": f"{base}/collections/{rid}/collections"}
            if res.get("parent_id"):
                out["_links"]["parent"] = f"{base}/collections/{res['parent_id']}"
            if res.get("record_template_id"):
                out["_links"]["record_template"] = f"{base}/templates/{res['record_template_id']}"
            out["_actions"] = {"edit": f"{base}/collections/{rid}", "delete": f"{base}/collections/{rid}"}
        else:
            out["_links"] = {"self": f"{base}/templates/{rid}"}
            out["_actions"] = {"edit": f"{base}/templates/{rid}", "delete": f"{base}/templates/{rid}"}
        return out

    def _file_json(self, meta: dict, export: bool = False) -> dict:
        out = {k: v for k, v in meta.items() if not k.startswith("_") and k not in ("record_id",)}
        out["creator"] = self._user()
        if export:
            out.pop("storage_type", None)
            out.pop("state", None)
        return out

    def _link_json(self, link: dict, perspective_record: int | None = None, export: bool = False) -> dict:
        out = {"id": link["id"], "name": link["name"], "term": link["term"], "created_at": link["created_at"],
               "last_modified": link["last_modified"], "creator": self._user()}
        rf = self._resource_json("records", self.state.resources["records"][link["from"]], export=export)
        rt = self._resource_json("records", self.state.resources["records"][link["to"]], export=export)
        if export and perspective_record is not None:
            if link["from"] == perspective_record:
                out["record_to"] = rt
            else:
                out["record_from"] = rf
        else:
            out["record_from"], out["record_to"] = rf, rt
        return out

    def _record_export(self, rec: dict, export_filter: dict) -> dict:
        data = self._resource_json("records", rec, export=True)
        if export_filter.get("user"):
            data.pop("creator", None)
        files = [self._file_json(f, export=True) for f in self.state.files.values()
                 if f["record_id"] == rec["id"] and f["state"] == "active"]
        files.sort(key=lambda f: f["last_modified"], reverse=True)
        data["files"] = files
        if export_filter.get("links") is not True:
            links = [l for l in self.state.links.values() if rec["id"] in (l["from"], l["to"])]
            if export_filter.get("links") == "in":
                links = [l for l in links if l["to"] == rec["id"]]
            elif export_filter.get("links") == "out":
                links = [l for l in links if l["from"] == rec["id"]]
            links.sort(key=lambda l: l["created_at"], reverse=True)
            data["links"] = [self._link_json(l, perspective_record=rec["id"], export=True) for l in links]
        return data

    # ------------------------------------------------------------------ validation (server rules)
    def _validate_common(self, kind: str, payload: dict, existing: dict | None, partial: bool) -> dict:
        errors = {}
        out = {}
        if "identifier" in payload or not partial:
            ident = payload.get("identifier")
            if not isinstance(ident, str) or not ident.strip():
                errors["identifier"] = ["Missing data for required field."]
            else:
                ident = ident.strip().lower()
                if len(ident) > 50:
                    errors["identifier"] = ["Longer than maximum length 50."]
                elif not IDENTIFIER_RE.fullmatch(ident):
                    errors["identifier"] = ["Not a valid identifier."]
                else:
                    other = self.state.by_identifier(kind, ident)
                    if other is not None and (existing is None or other["id"] != existing["id"]):
                        raise ApiError(409, "Identifier is already in use.")
                    out["identifier"] = ident
        if "title" in payload or not partial:
            title = payload.get("title")
            if not isinstance(title, str) or not title.strip():
                errors["title"] = ["Missing data for required field."]
            elif len(title) > 150:
                errors["title"] = ["Longer than maximum length 150."]
            else:
                out["title"] = _norm(title)
        if "description" in payload:
            desc = payload.get("description")
            if not isinstance(desc, str):
                errors["description"] = ["Not a valid string."]
            elif len(desc) > 50_000:
                errors["description"] = ["Longer than maximum length 50000."]
            else:
                out["description"] = desc.strip()
                out["plain_description"] = _norm(desc)
        if "visibility" in payload:
            vis = payload["visibility"]
            if vis not in VISIBILITIES:
                errors["visibility"] = ["Must be one of: private, public, open."]
            else:
                out["visibility"] = vis
        if "tags" in payload:
            tags = payload["tags"]
            if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
                errors["tags"] = ["Not a valid list."]
            else:
                norm = sorted({_norm(t).lower() for t in tags if _norm(t)})
                if any(len(t) > 50 for t in norm):
                    errors["tags"] = ["Longer than maximum length 50."]
                out["tags"] = norm
        if errors:
            raise ApiError(400, errors=errors)
        return out

    def _validate_record(self, payload: dict, existing: dict | None, partial: bool) -> dict:
        out = self._validate_common("records", payload, existing, partial)
        errors = {}
        if "type" in payload:
            t = payload["type"]
            if t is None:
                out["type"] = None
            elif not isinstance(t, str):
                errors["type"] = ["Not a valid string."]
            elif len(t) > 50:
                errors["type"] = ["Longer than maximum length 50."]
            else:
                out["type"] = _norm(t).lower()
        if "license" in payload:
            lic = payload["license"]
            if lic is not None and not isinstance(lic, str):
                errors["license"] = ["Not a valid string."]
            else:
                out["license"] = lic
        if "extras" in payload:
            try:
                out["extras"] = load_extras(payload["extras"], is_template=False, assume_timezone=timezone.utc)
            except ExtrasValidationError as exc:
                errors["extras"] = exc.messages
        if errors:
            raise ApiError(400, errors=errors)
        return out

    def _validate_template(self, payload: dict, existing: dict | None, partial: bool) -> dict:
        out = self._validate_common("templates", payload, existing, partial)
        errors = {}
        ttype = payload.get("type", existing["type"] if existing else None)
        if ttype not in ("record", "extras"):
            errors["type"] = ["Must be one of: record, extras."]
        if "data" in payload or not partial:
            data = payload.get("data")
            try:
                if ttype == "extras":
                    if not isinstance(data, list):
                        raise ExtrasValidationError({"_schema": ["Invalid input type."]})
                    out["data"] = load_extras(data, is_template=True, assume_timezone=timezone.utc)
                elif ttype == "record":
                    if not isinstance(data, dict):
                        raise ExtrasValidationError({"_schema": ["Invalid input type."]})
                    rec = {
                        "identifier": (data.get("identifier") or "").strip().lower(),
                        "title": _norm(data.get("title") or ""),
                        "description": (data.get("description") or "").strip(),
                        "type": _norm(data.get("type")).lower() if data.get("type") else None,
                        "license": data.get("license"),
                        "tags": sorted({_norm(t).lower() for t in (data.get("tags") or [])}),
                        "extras": load_extras(data.get("extras") or [], is_template=True, assume_timezone=timezone.utc),
                        "collections": [int(c) for c in data.get("collections") or []],
                        "record_links": [{"direction": rl["direction"], "record": int(rl["record"]),
                                          "name": _norm(rl["name"]), "term": rl.get("term")}
                                         for rl in data.get("record_links") or []],
                        "roles": [{"subject_type": r["subject_type"], "subject_id": int(r["subject_id"]),
                                   "role": r["role"]} for r in data.get("roles") or []],
                    }
                    for rl in rec["record_links"]:
                        if rl["direction"] not in ("out", "in"):
                            raise ExtrasValidationError({"record_links": ["direction must be out or in"]})
                    out["data"] = rec
            except (ExtrasValidationError, KeyError, TypeError, ValueError) as exc:
                errors["data"] = getattr(exc, "messages", str(exc))
        if "type" in payload:
            out["type"] = ttype
        if errors:
            raise ApiError(400, errors=errors)
        return out

    def _validate_collection(self, payload: dict, existing: dict | None, partial: bool) -> dict:
        out = self._validate_common("collections", payload, existing, partial)
        if "record_template" in payload:
            tid = payload["record_template"]
            if tid is None:
                out["record_template_id"] = None
            else:
                tmpl = self.state.resources["templates"].get(int(tid))
                if tmpl is None or tmpl["type"] != "record":
                    raise ApiError(400, errors={"record_template": ["No accessible record template with this ID exists."]})
                out["record_template_id"] = int(tid)
        return out

    # ------------------------------------------------------------------ dispatch
    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def do_PATCH(self):
        self._dispatch("PATCH")

    def do_PUT(self):
        self._dispatch("PUT")

    def do_DELETE(self):
        self._dispatch("DELETE")

    def _dispatch(self, method: str):
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)
        with self.state.lock:
            self.state.requests.append((method, path))
            try:
                self._auth()
                if not path.startswith("/api/v1/"):
                    raise ApiError(404, "The requested URL could not be found.")
                parts = [unquote(p) for p in path[len("/api/v1/"):].split("/") if p]
                handler = getattr(self, f"route_{method.lower()}")
                result = handler(parts, query)
                if result is None:
                    raise ApiError(404, "The requested URL could not be found.")
                status, body = result
                if isinstance(body, tuple):  # raw bytes with content type
                    self._send(status, raw=body[0], content_type=body[1])
                else:
                    self._send(status, body)
            except ApiError as exc:
                self._error(exc)
            except Exception as exc:  # noqa: BLE001
                self._send(500, {"code": 500, "message": "Internal Server Error", "description": repr(exc)})

    # ------------------------------------------------------------------ GET
    def route_get(self, p: list[str], q: dict):
        st = self.state
        base = self._base()
        if p == ["info"]:
            return 200, {"version": "1.14.0", "mock": True}
        if p == ["users", "me"]:
            return 200, {**self._user(), "identity": {"username": "mock", "type": "local"}}
        if len(p) == 1 and p[0] in st.resources:
            items = [self._resource_json(p[0], r) for r in st.resources[p[0]].values() if r["state"] == "active"]
            return 200, self._paginate(items, q, f"{base}/{p[0]}")
        if len(p) == 3 and p[0] in st.resources and p[1] == "identifier":
            res = st.by_identifier(p[0], p[2])
            if res is None:
                raise ApiError(404, "The requested URL could not be found.")
            return 200, self._resource_json(p[0], res)
        if len(p) == 2 and p[0] in ("groups",) and p[1] == "identifier":
            return None
        if len(p) == 3 and p[0] == "groups" and p[1] == "identifier":
            group = st.groups.get(p[2])
            if group is None:
                raise ApiError(404, "The requested URL could not be found.")
            return 200, group
        if len(p) >= 2 and p[0] in st.resources:
            kind, res = p[0], self._get_resource(p[0], p[1])
            rest = p[2:]
            if not rest:
                return 200, self._resource_json(kind, res)
            if rest == ["records"] and kind == "records":
                direction = q.get("direction", [None])[0]
                links = [l for l in st.links.values() if res["id"] in (l["from"], l["to"])]
                if direction == "out":
                    links = [l for l in links if l["from"] == res["id"]]
                elif direction == "in":
                    links = [l for l in links if l["to"] == res["id"]]
                return 200, self._paginate([self._link_json(l) for l in links], q, f"{base}/records/{res['id']}/records")
            if rest == ["collections"] and kind == "records":
                cols = [self._resource_json("collections", st.resources["collections"][c])
                        for c, r in sorted(st.memberships) if r == res["id"]]
                return 200, self._paginate(cols, q, f"{base}/records/{res['id']}/collections")
            if rest == ["records"] and kind == "collections":
                recs = [self._resource_json("records", st.resources["records"][r])
                        for c, r in sorted(st.memberships) if c == res["id"]]
                return 200, self._paginate(recs, q, f"{base}/collections/{res['id']}/records")
            if rest == ["collections"] and kind == "collections":
                children = [self._resource_json("collections", c) for c in st.resources["collections"].values()
                            if c.get("parent_id") == res["id"] and c["state"] == "active"]
                return 200, self._paginate(children, q, f"{base}/collections/{res['id']}/collections")
            if rest[:2] == ["roles", "groups"] and len(rest) == 2:
                roles = st.roles.get((kind, res["id"]), {"groups": {}, "users": {}})["groups"]
                items = [{"group": next(g for g in st.groups.values() if g["id"] == gid), "role": {"name": role}}
                         for gid, role in roles.items()]
                return 200, self._paginate(items, q, f"{base}/{kind}/{res['id']}/roles/groups")
            if rest[:2] == ["roles", "users"] and len(rest) == 2:
                roles = st.roles.get((kind, res["id"]), {"groups": {}, "users": {}})["users"]
                items = [{"user": {"id": uid, "displayname": f"user {uid}"}, "role": {"name": role}}
                         for uid, role in roles.items()]
                return 200, self._paginate(items, q, f"{base}/{kind}/{res['id']}/roles/users")
            if rest == ["files"] and kind == "records":
                files = [self._file_json(f) for f in st.files.values()
                         if f["record_id"] == res["id"] and f["state"] == "active"]
                return 200, self._paginate(files, q, f"{base}/records/{res['id']}/files")
            if len(rest) == 3 and rest[0] == "files" and rest[1] == "name" and kind == "records":
                for f in st.files.values():
                    if f["record_id"] == res["id"] and f["name"] == rest[2] and f["state"] == "active":
                        return 200, self._file_json(f)
                raise ApiError(404, "The requested URL could not be found.")
            if len(rest) == 2 and rest[0] == "files" and kind == "records":
                f = st.files.get(rest[1])
                if f is None or f["record_id"] != res["id"]:
                    raise ApiError(404, "The requested URL could not be found.")
                return 200, self._file_json(f)
            if len(rest) == 3 and rest[0] == "files" and rest[2] == "download" and kind == "records":
                f = st.files.get(rest[1])
                if f is None or f["record_id"] != res["id"]:
                    raise ApiError(404, "The requested URL could not be found.")
                return 200, (f["_data"], f["mimetype"])
            if len(rest) == 2 and rest[0] == "uploads" and kind == "records":
                up = st.uploads.get(rest[1])
                if up is None:
                    raise ApiError(404, "The requested URL could not be found.")
                return 200, self._upload_json(up)
            if len(rest) == 2 and rest[0] == "export":
                return self._export(kind, res, rest[1], q)
        return None

    def _get_resource(self, kind: str, raw_id: str) -> dict:
        try:
            rid = int(raw_id)
        except ValueError:
            raise ApiError(404, "The requested URL could not be found.")
        res = self.state.resources[kind].get(rid)
        if res is None or res["state"] != "active":
            raise ApiError(404, "The requested URL could not be found.")
        return res

    # ------------------------------------------------------------------ exports
    def _export(self, kind: str, res: dict, export_type: str, q: dict):
        export_filter = {}
        if q.get("filter"):
            try:
                export_filter = json.loads(q["filter"][0])
            except ValueError:
                raise ApiError(400, "Invalid filter.")
        if kind == "records" and export_type == "json":
            return 200, (json.dumps(self._record_export(res, export_filter), ensure_ascii=False, sort_keys=True,
                                    indent=2).encode(), "application/json")
        if kind == "collections" and export_type == "json":
            data = self._resource_json("collections", res, export=True)
            if not export_filter.get("records"):
                recs = [self.state.resources["records"][r] for c, r in sorted(self.state.memberships) if c == res["id"]]
                data["records"] = [self._record_export(r, export_filter) for r in recs]
            return 200, (json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2).encode(), "application/json")
        if kind == "templates" and export_type == "json":
            data = self._resource_json("templates", res, export=True)
            return 200, (json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2).encode(), "application/json")
        if export_type == "ro-crate" and kind in ("records", "collections"):
            return 200, (self._ro_crate(kind, res, export_filter), "application/zip")
        raise ApiError(404, "The requested URL could not be found.")

    def _ro_crate(self, kind: str, res: dict, export_filter: dict) -> bytes:
        root = res["identifier"]
        if kind == "records":
            records = [res]
        else:
            records = [self.state.resources["records"][r] for c, r in sorted(self.state.memberships) if c == res["id"]]
        graph = [
            {"@id": "ro-crate-metadata.json", "@type": "CreativeWork", "about": {"@id": "./"},
             "conformsTo": {"@id": "https://w3id.org/ro/crate/1.1"}, "dateCreated": now(),
             "sdPublisher": {"@id": "https://kadi.iam.kit.edu"}, "version": "1.14.0"},
            {"@id": "./", "@type": "Dataset", "datePublished": now()[:10], "genre": kind[:-1],
             "description": "An RO-Crate exported from Kadi4Mat following the ELN file format specification.",
             "license": "For license information, please refer to the individual dataset nodes, if applicable.",
             "name": res["title"], "hasPart": [{"@id": f"./{r['identifier']}/"} for r in records]},
            {"@id": "https://kadi.iam.kit.edu", "@type": "Organization", "name": "Kadi4Mat",
             "description": "A generic and open source virtual research environment.", "url": "https://kadi.iam.kit.edu"},
        ]
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for rec in records:
                rdir = f"{root}/{rec['identifier']}" if kind == "collections" else root
                data = self._record_export(rec, export_filter)
                payload = json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2).encode()
                zf.writestr(f"{rdir}/{rec['identifier']}.json", payload)
                parts = [{"@id": f"./{rec['identifier']}/{rec['identifier']}.json"}]
                graph.append({"@id": f"./{rec['identifier']}/{rec['identifier']}.json", "@type": "File",
                              "contentSize": str(len(payload)), "encodingFormat": "application/json",
                              "name": f"{rec['identifier']}.json", "dateCreated": now()})
                for f in self.state.files.values():
                    if f["record_id"] == rec["id"] and f["state"] == "active":
                        zf.writestr(f"{rdir}/files/{f['name']}", f["_data"])
                        fid = f"./{rec['identifier']}/files/{f['name']}"
                        parts.append({"@id": fid})
                        graph.append({"@id": fid, "@type": "File", "contentSize": str(f["size"]),
                                      "encodingFormat": f["mimetype"], "identifier": f["id"], "name": f["name"],
                                      "dateCreated": f["created_at"], "dateModified": f["last_modified"]})
                graph.append({"@id": f"./{rec['identifier']}/", "@type": "Dataset", "identifier": rec["identifier"],
                              "name": rec["title"], "dateCreated": rec["created_at"],
                              "dateModified": rec["last_modified"], "hasPart": parts})
            zf.writestr(f"{root}/ro-crate-metadata.json",
                        json.dumps({"@context": "https://w3id.org/ro/crate/1.1/context", "@graph": graph},
                                   ensure_ascii=False, indent=2))
        return buf.getvalue()

    # ------------------------------------------------------------------ POST
    def route_post(self, p: list[str], q: dict):
        st = self.state
        if len(p) == 1 and p[0] in st.resources:
            payload = self._body_json()
            kind = p[0]
            if kind == "records":
                data = self._validate_record(payload, None, partial=False)
                data.setdefault("type", None)
                data.setdefault("license", None)
                data.setdefault("extras", [])
            elif kind == "templates":
                data = self._validate_template(payload, None, partial=False)
            else:
                data = self._validate_collection(payload, None, partial=False)
            data.setdefault("description", "")
            data.setdefault("plain_description", "")
            data.setdefault("visibility", "private")
            data.setdefault("tags", [])
            res = {"id": st.next_id(), **data, "state": "active", "created_at": now(), "last_modified": now()}
            if kind == "collections":
                res.setdefault("parent_id", None)
                res.setdefault("record_template_id", None)
            st.resources[kind][res["id"]] = res
            return 201, self._resource_json(kind, res)
        if len(p) >= 2 and p[0] in st.resources:
            kind, res = p[0], self._get_resource(p[0], p[1])
            rest = p[2:]
            if rest == ["records"] and kind == "records":
                payload = self._body_json()
                try:
                    to_id = int(payload["record_to"]["id"])
                    name = payload["name"]
                except (KeyError, TypeError, ValueError):
                    raise ApiError(400, errors={"record_to": ["Missing data for required field."]})
                if not isinstance(name, str) or not name.strip():
                    raise ApiError(400, errors={"name": ["Missing data for required field."]})
                name = _norm(name)
                term = payload.get("term")
                if term is not None and (not isinstance(term, str) or any(ch in term for ch in '<>" {}|\\^`')):
                    raise ApiError(400, errors={"term": ["Not a valid IRI."]})
                target = st.resources["records"].get(to_id)
                if target is None or target["state"] != "active":
                    raise ApiError(400, errors={"record_to": ["No record with this ID exists."]})
                if to_id == res["id"]:
                    raise ApiError(409, "Cannot link a record with itself.")
                for l in st.links.values():
                    if l["from"] == res["id"] and l["to"] == to_id and l["name"] == name:
                        raise ApiError(409, "Link already exists.")
                link = {"id": st.next_id(), "from": res["id"], "to": to_id, "name": name, "term": term or None,
                        "created_at": now(), "last_modified": now()}
                st.links[link["id"]] = link
                return 201, self._link_json(link)
            if rest == ["records"] and kind == "collections":
                rid = int(self._body_json().get("id", 0))
                if rid not in st.resources["records"]:
                    raise ApiError(400, errors={"id": ["No record with this ID exists."]})
                if (res["id"], rid) in st.memberships:
                    raise ApiError(409, "Record is already part of the collection.")
                st.memberships.add((res["id"], rid))
                return 201, {"id": rid}
            if rest == ["collections"] and kind == "records":
                cid = int(self._body_json().get("id", 0))
                if cid not in st.resources["collections"]:
                    raise ApiError(400, errors={"id": ["No collection with this ID exists."]})
                if (cid, res["id"]) in st.memberships:
                    raise ApiError(409, "Record is already part of the collection.")
                st.memberships.add((cid, res["id"]))
                return 201, {"id": cid}
            if rest == ["collections"] and kind == "collections":
                cid = int(self._body_json().get("id", 0))
                child = st.resources["collections"].get(cid)
                if child is None:
                    raise ApiError(400, errors={"id": ["No collection with this ID exists."]})
                if child.get("parent_id") == res["id"]:
                    raise ApiError(409, "Collection is already a child.")
                if cid == res["id"]:
                    raise ApiError(409, "A collection cannot be its own child.")
                child["parent_id"] = res["id"]
                return 201, {"id": cid}
            if rest == ["roles", "groups"]:
                payload = self._body_json()
                gid = int(payload["group"]["id"])
                role = payload["role"]["name"]
                roles = st.roles.setdefault((kind, res["id"]), {"groups": {}, "users": {}})
                if gid in roles["groups"]:
                    raise ApiError(409, "Group role already exists.")
                roles["groups"][gid] = role
                return 201, {"group": {"id": gid}, "role": {"name": role}}
            if rest == ["roles", "users"]:
                payload = self._body_json()
                uid = int(payload["user"]["id"])
                role = payload["role"]["name"]
                roles = st.roles.setdefault((kind, res["id"]), {"groups": {}, "users": {}})
                if uid in roles["users"]:
                    raise ApiError(409, "User role already exists.")
                roles["users"][uid] = role
                return 201, {"user": {"id": uid}, "role": {"name": role}}
            if rest == ["uploads"] and kind == "records":
                payload = self._body_json()
                return self._new_upload(res, payload)
            if len(rest) == 2 and rest[0] == "uploads" and kind == "records":
                up = st.uploads.get(rest[1])
                if up is None or up["state"] != "active":
                    raise ApiError(404, "The requested URL could not be found.")
                if up["upload_type"] != "chunked":
                    raise ApiError(400, "Only chunked uploads can be finished.")
                if len(up["_chunks"]) != up["chunk_count"]:
                    raise ApiError(400, "Not all chunks have been uploaded yet.")
                self._finish_chunked(up)
                return 202, self._upload_json(up)
            if rest == ["purge"]:
                st.resources[kind].pop(res["id"], None) if res["state"] == "deleted" else None
                return 204, None
            if rest == ["restore"]:
                res["state"] = "active"
                return 200, self._resource_json(kind, res)
        return None

    # ------------------------------------------------------------------ uploads
    def _new_upload(self, rec: dict, payload: dict, replacing_file: dict | None = None):
        st = self.state
        name = payload.get("name") if replacing_file is None else replacing_file["name"]
        size = payload.get("size")
        if not isinstance(name, str) or not name.strip():
            raise ApiError(400, errors={"name": ["Missing data for required field."]})
        if not isinstance(size, int) or size < 0:
            raise ApiError(400, errors={"size": ["Missing data for required field."]})
        name = _norm(name)
        if replacing_file is None:
            for f in st.files.values():
                if f["record_id"] == rec["id"] and f["name"] == name and f["state"] == "active":
                    body = {"code": 409, "message": "Conflict", "description": "A file with that name already exists.",
                            "file": self._file_json(f)}
                    body["file"]["_actions"] = {"edit_data": f"{self._base()}/records/{rec['id']}/files/{f['id']}"}
                    raise _RawResponse(409, body)
        upload_type = "direct" if size <= st.chunk_boundary else "chunked"
        chunk_size = size if upload_type == "direct" else st.chunk_size
        chunk_count = 1 if upload_type == "direct" else max(1, -(-size // chunk_size))
        up = {"id": str(uuid.uuid4()), "record_id": rec["id"], "name": name, "size": size,
              "description": (payload.get("description") or "").strip(),
              "mimetype": (payload.get("mimetype") or "application/octet-stream").lower(),
              "upload_type": upload_type, "chunk_count": chunk_count, "state": "active",
              "created_at": now(), "last_modified": now(), "_chunks": {}, "_chunk_size": chunk_size,
              "_replace": replacing_file["id"] if replacing_file else None, "_task": None}
        st.uploads[up["id"]] = up
        return 201, self._upload_json(up)

    def _upload_json(self, up: dict) -> dict:
        base = self._base()
        out = {k: v for k, v in up.items() if not k.startswith("_") and k != "record_id"}
        out["creator"] = self._user()
        out["_meta"] = {"chunk_size": up["_chunk_size"]}
        if up["_task"] is not None:
            out["_meta"]["task"] = up["_task"]
        out["_actions"] = {"upload_data": f"{base}/records/{up['record_id']}/uploads/{up['id']}",
                           "delete": f"{base}/records/{up['record_id']}/uploads/{up['id']}"}
        if up["upload_type"] == "chunked":
            out["_actions"]["finish"] = f"{base}/records/{up['record_id']}/uploads/{up['id']}"
        out["_links"] = {"self": f"{base}/records/{up['record_id']}/uploads/{up['id']}"}
        return out

    def _store_file(self, up: dict, data: bytes, checksum: str) -> dict:
        st = self.state
        if up["_replace"] and up["_replace"] in st.files:
            f = st.files[up["_replace"]]
            f.update({"size": len(data), "checksum": checksum, "mimetype": up["mimetype"],
                      "description": up["description"] or f["description"], "last_modified": now(), "_data": data})
        else:
            f = {"id": str(uuid.uuid4()), "record_id": up["record_id"], "name": up["name"],
                 "description": up["description"], "mimetype": up["mimetype"], "magic_mimetype": None,
                 "size": len(data), "checksum": checksum, "storage_type": "local", "state": "active",
                 "created_at": now(), "last_modified": now(), "_data": data}
            st.files[f["id"]] = f
        up["state"] = "inactive"
        return f

    def _finish_chunked(self, up: dict) -> None:
        data = b"".join(up["_chunks"][i] for i in range(up["chunk_count"]))
        digests = "".join(hashlib.md5(up["_chunks"][i]).hexdigest() for i in range(up["chunk_count"]))
        checksum = hashlib.md5(bytes.fromhex(digests)).hexdigest() + f"-{up['chunk_count']}"
        if len(data) != up["size"]:
            up["_task"] = {"state": "failure", "error": "File size mismatch."}
            return
        f = self._store_file(up, data, checksum)
        up["_task"] = {"state": "success", "file": self._file_json(f)}

    # ------------------------------------------------------------------ PUT
    def route_put(self, p: list[str], q: dict):
        st = self.state
        if len(p) == 4 and p[0] == "records" and p[2] == "uploads":
            rec = self._get_resource("records", p[1])
            up = st.uploads.get(p[3])
            if up is None or up["state"] != "active" or up["record_id"] != rec["id"]:
                raise ApiError(404, "The requested URL could not be found.")
            data = self._body_bytes()
            checksum = self.headers.get("Kadi-MD5-Checksum")
            if up["upload_type"] == "direct":
                if len(data) != up["size"]:
                    raise ApiError(400, "Upload size does not match the declared size.")
                md5 = hashlib.md5(data).hexdigest()
                if checksum and checksum != md5:
                    raise ApiError(400, f"File checksum mismatch (expected: {checksum}, actual: {md5}).")
                f = self._store_file(up, data, md5)
                return 201, self._file_json(f)
            index = int(self.headers.get("Kadi-Chunk-Index", "-1"))
            size = int(self.headers.get("Kadi-Chunk-Size", "-1"))
            if index < 0 or index >= up["chunk_count"] or size != len(data):
                raise ApiError(400, errors={"index": ["Invalid chunk index or size."]})
            if index < up["chunk_count"] - 1 and size != up["_chunk_size"]:
                raise ApiError(400, errors={"size": ["Only the last chunk may be smaller than the chunk size."]})
            md5 = hashlib.md5(data).hexdigest()
            if checksum and checksum != md5:
                raise ApiError(400, f"Chunk checksum mismatch (expected: {checksum}, actual: {md5}).")
            up["_chunks"][index] = data
            up["last_modified"] = now()
            return 200, self._upload_json(up)
        if len(p) == 4 and p[0] == "records" and p[2] == "files":
            rec = self._get_resource("records", p[1])
            f = st.files.get(p[3])
            if f is None or f["record_id"] != rec["id"]:
                raise ApiError(404, "The requested URL could not be found.")
            payload = self._body_json()
            return self._new_upload(rec, payload, replacing_file=f)
        return None

    # ------------------------------------------------------------------ PATCH
    def route_patch(self, p: list[str], q: dict):
        st = self.state
        if len(p) == 2 and p[0] in st.resources:
            kind, res = p[0], self._get_resource(p[0], p[1])
            payload = self._body_json()
            if kind == "records":
                data = self._validate_record(payload, res, partial=True)
            elif kind == "templates":
                data = self._validate_template(payload, res, partial=True)
            else:
                data = self._validate_collection(payload, res, partial=True)
            res.update(data)
            res["last_modified"] = now()
            return 200, self._resource_json(kind, res)
        if len(p) == 4 and p[0] == "records" and p[2] == "records":
            rec = self._get_resource("records", p[1])
            link = st.links.get(int(p[3]))
            if link is None or link["from"] != rec["id"]:
                raise ApiError(404, "The requested URL could not be found.")
            payload = self._body_json()
            if "name" in payload and isinstance(payload["name"], str) and payload["name"].strip():
                link["name"] = _norm(payload["name"])
            if "term" in payload:
                link["term"] = payload["term"] or None
            link["last_modified"] = now()
            return 200, self._link_json(link)
        if len(p) == 5 and p[0] in st.resources and p[2] == "roles" and p[3] == "groups":
            kind, res = p[0], self._get_resource(p[0], p[1])
            roles = st.roles.setdefault((kind, res["id"]), {"groups": {}, "users": {}})
            gid = int(p[4])
            if gid not in roles["groups"]:
                raise ApiError(404, "The requested URL could not be found.")
            roles["groups"][gid] = self._body_json().get("name", roles["groups"][gid])
            return 204, None
        return None

    # ------------------------------------------------------------------ DELETE
    def route_delete(self, p: list[str], q: dict):
        st = self.state
        if len(p) == 2 and p[0] in st.resources:
            kind, res = p[0], self._get_resource(p[0], p[1])
            res["state"] = "deleted"
            if kind == "records":
                for lid in [l for l, link in st.links.items() if res["id"] in (link["from"], link["to"])]:
                    del st.links[lid]
                st.memberships = {m for m in st.memberships if m[1] != res["id"]}
            if kind == "collections":
                st.memberships = {m for m in st.memberships if m[0] != res["id"]}
                for c in st.resources["collections"].values():
                    if c.get("parent_id") == res["id"]:
                        c["parent_id"] = None
            return 204, None
        if len(p) == 4 and p[0] == "records" and p[2] == "records":
            rec = self._get_resource("records", p[1])
            link = st.links.get(int(p[3]))
            if link is None or link["from"] != rec["id"]:
                raise ApiError(404, "The requested URL could not be found.")
            del st.links[link["id"]]
            return 204, None
        return None


class _RawResponse(ApiError):
    """A 409 that carries extra JSON (the existing file), like Kadi does for uploads."""

    def __init__(self, status: int, body: dict):
        super().__init__(status, body.get("description", ""))
        self.body = body


def _patched_error(self, exc):
    if isinstance(exc, _RawResponse):
        self._send(exc.status, exc.body)
    else:
        Handler._error_original(self, exc)


Handler._error_original = Handler._error
Handler._error = _patched_error


class MockKadiServer:
    """Threaded HTTPS mock server; use as a context manager in tests."""

    def __init__(self, port: int = 0, state: MockState | None = None):
        self.state = state or MockState()
        handler = type("BoundHandler", (Handler,), {"state": self.state})
        self.httpd = ThreadingHTTPServer(("127.0.0.1", port), handler)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(FIXTURES / "mock-kadi-cert.pem", FIXTURES / "mock-kadi-key.pem")
        self.httpd.socket = context.wrap_socket(self.httpd.socket, server_side=True)
        self.port = self.httpd.server_address[1]
        self.url = f"https://127.0.0.1:{self.port}"
        self.ca_bundle = str(FIXTURES / "mock-kadi-cert.pem")
        self._thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self.httpd.shutdown()
        self.httpd.server_close()


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8443
    with MockKadiServer(port, MockState(groups={"ceet-data-stewards": 10, "ceet-lab-staff": 11})) as server:
        print(f"Mock Kadi4Mat listening on {server.url}  (CA bundle: {server.ca_bundle})")
        print("Use any token, e.g.  set KADI_TOKEN=mock-token")
        try:
            threading.Event().wait()
        except KeyboardInterrupt:
            pass
