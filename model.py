"""Declarative model: load YAML (with includes), expand fieldsets, apply the
deployment namespace and resolve cross references.

The model is the single source of truth that gets compiled into exact Kadi4Mat
API payloads (see :mod:`kadi_lab_manager.compile`). Nothing here talks to a server.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .errors import ModelError

IDENTIFIER_RE = re.compile(r"^[a-z0-9-_]+$")  # the server rule
IDENTIFIER_MAX = 50
TITLE_MAX = 150
DESCRIPTION_MAX = 50_000
TYPE_MAX = 50
TAG_MAX = 50
LINK_NAME_MAX = 150
TERM_MAX = 2048
VISIBILITIES = ("private", "public", "open")
EXTRA_TYPES = ("str", "int", "float", "bool", "date", "dict", "list")
ROLES_RECORD = ("member", "collaborator", "editor", "admin")
ROLES_TEMPLATE = ("member", "editor", "admin")


# ----------------------------------------------------------------------------- fields
@dataclass
class Field:
    """One metadata field (compiles to one Kadi extra)."""

    key: str | None
    type: str
    description: str | None = None
    term: str | None = None
    unit: str | None = None
    required: bool = False
    options: list | None = None
    range: dict | None = None
    iri: bool = False
    default: Any = None
    fields: list["Field"] = field(default_factory=list)   # dict children
    items: list["Field"] = field(default_factory=list)    # list item prototypes
    source: str = ""                                      # where it was defined (for messages)

    def path_label(self, parent: str = "") -> str:
        name = self.key if self.key is not None else "[]"
        return f"{parent}.{name}" if parent else name


@dataclass
class LinkSpec:
    source: str
    target: str
    type: str                 # link type name from vocab (becomes the link "name")
    term: str | None = None   # explicit IRI override
    origin: str = ""


@dataclass
class RoleSpec:
    role: str
    group: str | None = None  # group identifier
    user: int | None = None   # numeric user id


@dataclass
class FileSpec:
    path: str
    name: str | None = None
    description: str | None = None
    mimetype: str | None = None


@dataclass
class Collection:
    identifier: str
    title: str
    description: str = ""
    tags: list[str] = field(default_factory=list)
    visibility: str = "private"
    parent: str | None = None
    record_template: str | None = None
    roles: list[RoleSpec] = field(default_factory=list)
    origin: str = ""


@dataclass
class TemplateRecordDefaults:
    type: str | None = None
    title: str = ""
    description: str = ""
    license: str | None = None
    tags: list[str] = field(default_factory=list)
    collections: list[str] = field(default_factory=list)
    record_links: list[dict] = field(default_factory=list)   # {direction, record, type|name, term}
    roles: list[RoleSpec] = field(default_factory=list)


@dataclass
class Template:
    identifier: str
    kind: str                       # "record" | "extras"
    title: str
    description: str = ""
    visibility: str = "private"
    fields: list[Field] = field(default_factory=list)
    record: TemplateRecordDefaults = field(default_factory=TemplateRecordDefaults)
    roles: list[RoleSpec] = field(default_factory=list)
    origin: str = ""


@dataclass
class Record:
    identifier: str
    title: str
    template: str | None = None
    type: str | None = None
    description: str = ""
    license: str | None = None
    tags: list[str] = field(default_factory=list)
    visibility: str = "private"
    collections: list[str] = field(default_factory=list)
    values: dict = field(default_factory=dict)
    extras: list = field(default_factory=list)       # raw Kadi extras appended after template fields
    files: list[FileSpec] = field(default_factory=list)
    roles: list[RoleSpec] = field(default_factory=list)
    drop_empty: bool | None = None
    origin: str = ""


@dataclass
class LinkType:
    name: str
    term: str | None = None
    description: str = ""
    sources: list[str] = field(default_factory=list)   # allowed source record types ("*" = any)
    targets: list[str] = field(default_factory=list)


@dataclass
class Vocab:
    link_types: dict[str, LinkType] = field(default_factory=dict)
    record_types: dict[str, dict] = field(default_factory=dict)   # type -> {prefix, description}
    units: dict[str, str] = field(default_factory=dict)          # alias -> canonical unit string
    unit_terms: dict[str, str] = field(default_factory=dict)     # canonical unit -> IRI (documentation)


@dataclass
class Settings:
    name: str = "unnamed model"
    version: str = "0"
    namespace: str = ""
    timezone: str = "UTC"
    default_visibility: str = "private"
    default_license: str | None = None
    drop_empty_optional_fields: bool = False
    strict_link_vocabulary: bool = True
    enforce_type_prefix: bool = True
    file_root: str = "."


@dataclass
class Model:
    settings: Settings
    vocab: Vocab
    collections: list[Collection]
    templates: list[Template]
    records: list[Record]
    links: list[LinkSpec]
    fieldsets: dict[str, list[Field]]
    base_dir: Path
    sources: list[str]

    # --- lookups ---------------------------------------------------------------------
    def collection(self, identifier: str) -> Collection | None:
        return next((c for c in self.collections if c.identifier == identifier), None)

    def template(self, identifier: str) -> Template | None:
        return next((t for t in self.templates if t.identifier == identifier), None)

    def record(self, identifier: str) -> Record | None:
        return next((r for r in self.records if r.identifier == identifier), None)

    def ordered_collections(self) -> list[Collection]:
        """Parents before children (stable), cycles reported by validation."""
        done: list[Collection] = []
        seen: set[str] = set()
        pending = list(self.collections)
        guard = 0
        while pending and guard < 10_000:
            guard += 1
            col = pending.pop(0)
            if col.parent is None or col.parent in seen:
                done.append(col)
                seen.add(col.identifier)
            else:
                pending.append(col)
        done.extend(pending)
        return done


# ----------------------------------------------------------------------------- loading
class _Loader:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.problems: list[str] = []
        self.sources: list[str] = []
        self.raw: dict[str, Any] = {
            "settings": {},
            "vocab": {"link_types": {}, "record_types": {}, "units": {}, "unit_terms": {}},
            "fieldsets": {},
            "collections": [],
            "templates": [],
            "records": [],
            "links": [],
        }
        self._loaded: set[Path] = set()

    # -- include handling ------------------------------------------------------------
    def load_file(self, path: Path) -> None:
        path = path.resolve()
        if path in self._loaded:
            return
        self._loaded.add(path)
        if not path.exists():
            self.problems.append(f"include not found: {path}")
            return
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            self.problems.append(f"{path}: YAML syntax error: {exc}")
            return
        if not isinstance(data, dict):
            self.problems.append(f"{path}: top level must be a mapping")
            return
        self.sources.append(str(path))
        rel = str(path.relative_to(self.root)) if path.is_relative_to(self.root) else str(path)

        for inc in data.get("includes", []) or []:
            inc_path = (path.parent / inc) if not Path(inc).is_absolute() else Path(inc)
            if inc_path.is_dir():
                for child in sorted(inc_path.glob("*.yaml")):
                    self.load_file(child)
            elif any(ch in inc for ch in "*?["):
                for child in sorted(path.parent.glob(inc)):
                    self.load_file(child)
            else:
                self.load_file(inc_path)

        for key in ("settings",):
            if isinstance(data.get(key), dict):
                self.raw[key].update(data[key])
        vocab = data.get("vocab") or {}
        for key in ("link_types", "record_types", "units", "unit_terms"):
            if isinstance(vocab.get(key), dict):
                self.raw["vocab"][key].update(vocab[key])
        if isinstance(data.get("fieldsets"), dict):
            for name, fields in data["fieldsets"].items():
                if name in self.raw["fieldsets"]:
                    self.problems.append(f"{rel}: duplicate fieldset '{name}'")
                self.raw["fieldsets"][name] = fields
        for key in ("collections", "templates", "records", "links"):
            items = data.get(key) or []
            if not isinstance(items, list):
                self.problems.append(f"{rel}: '{key}' must be a list")
                continue
            for item in items:
                if isinstance(item, dict):
                    item.setdefault("_origin", rel)
                self.raw[key].append(item)

        known = {"includes", "schema_version", "settings", "vocab", "fieldsets",
                 "collections", "templates", "records", "links"}
        for key in data:
            if key not in known:
                self.problems.append(f"{rel}: unknown top-level key '{key}'")

    # -- fields ------------------------------------------------------------------------
    def parse_fields(self, items, origin: str, parent: str = "", depth: int = 0) -> list[Field]:
        out: list[Field] = []
        if items is None:
            return out
        if not isinstance(items, list):
            self.problems.append(f"{origin}: fields under '{parent or '<root>'}' must be a list")
            return out
        if depth > 10:
            self.problems.append(f"{origin}: nesting deeper than 10 levels under '{parent}'")
            return out
        for item in items:
            if not isinstance(item, dict):
                self.problems.append(f"{origin}: field entry under '{parent}' must be a mapping")
                continue
            if "use" in item and "key" not in item:
                out.extend(self.expand_fieldset(item["use"], origin, parent, depth))
                continue
            key = item.get("key")
            ftype = item.get("type", "dict" if ("fields" in item or "use" in item) else None)
            if ftype is None:
                ftype = "list" if "items" in item else "str"
            label = f"{parent}.{key}" if parent else str(key)
            if ftype not in EXTRA_TYPES:
                self.problems.append(f"{origin}: field '{label}' has unknown type '{ftype}'")
                continue
            if key is None and parent and not parent.endswith("[]"):
                self.problems.append(f"{origin}: field under '{parent}' is missing 'key'")
            f = Field(
                key=str(key) if key is not None else None,
                type=ftype,
                description=item.get("description"),
                term=item.get("term"),
                unit=item.get("unit"),
                required=bool(item.get("required", False)),
                options=item.get("options"),
                range=item.get("range"),
                iri=bool(item.get("iri", False)),
                default=item.get("default"),
                source=origin,
            )
            if ftype == "dict":
                children = list(item.get("fields") or [])
                if "use" in item:
                    f.fields = self.expand_fieldset(item["use"], origin, label, depth + 1)
                f.fields += self.parse_fields(children, origin, label, depth + 1)
            elif ftype == "list":
                protos = item.get("items")
                if protos is None:
                    protos = [{"type": "str"}]
                if isinstance(protos, dict):
                    protos = [protos]
                f.items = self.parse_fields(protos, origin, label + "[]", depth + 1)
            for unknown in set(item) - {"key", "type", "description", "term", "unit", "required",
                                         "options", "range", "iri", "default", "fields", "items",
                                         "use"}:
                self.problems.append(f"{origin}: field '{label}' has unknown property '{unknown}'")
            out.append(f)
        return out

    def expand_fieldset(self, name: str, origin: str, parent: str, depth: int) -> list[Field]:
        if name not in self.raw["fieldsets"]:
            self.problems.append(f"{origin}: unknown fieldset '{name}' used under '{parent or '<root>'}'")
            return []
        return self.parse_fields(self.raw["fieldsets"][name], f"fieldset {name}", parent, depth + 1)

    # -- resources ---------------------------------------------------------------------
    @staticmethod
    def _roles(items, origin, problems) -> list[RoleSpec]:
        roles = []
        for item in items or []:
            if not isinstance(item, dict) or "role" not in item:
                problems.append(f"{origin}: role entries need 'role' and 'group' or 'user'")
                continue
            if ("group" in item) == ("user" in item):
                problems.append(f"{origin}: role '{item.get('role')}' needs exactly one of 'group'/'user'")
                continue
            roles.append(RoleSpec(role=str(item["role"]), group=item.get("group"),
                                  user=int(item["user"]) if "user" in item else None))
        return roles

    def build(self) -> Model:
        s = self.raw["settings"]
        settings = Settings(
            name=str(s.get("name", "unnamed model")),
            version=str(s.get("version", "0")),
            namespace=str(s.get("namespace", "") or ""),
            timezone=str(s.get("timezone", "UTC")),
            default_visibility=str(s.get("default_visibility", "private")),
            default_license=s.get("default_license"),
            drop_empty_optional_fields=bool(s.get("drop_empty_optional_fields", False)),
            strict_link_vocabulary=bool(s.get("strict_link_vocabulary", True)),
            enforce_type_prefix=bool(s.get("enforce_type_prefix", True)),
            file_root=str(s.get("file_root", ".")),
        )
        ns = settings.namespace
        if ns and not re.fullmatch(r"[a-z0-9_-]+", ns):
            self.problems.append(f"settings.namespace '{ns}' may only contain a-z 0-9 - _")

        def nsid(identifier):
            if identifier is None:
                return None
            identifier = str(identifier)
            if ns and not identifier.endswith(ns):
                return identifier + ns
            return identifier

        vocab = Vocab()
        for name, spec in (self.raw["vocab"]["link_types"] or {}).items():
            spec = spec or {}
            vocab.link_types[name] = LinkType(
                name=name, term=spec.get("term"), description=spec.get("description", ""),
                sources=list(spec.get("sources", ["*"])), targets=list(spec.get("targets", ["*"])))
        vocab.record_types = {k: (v or {}) for k, v in (self.raw["vocab"]["record_types"] or {}).items()}
        vocab.units = {str(k): str(v) for k, v in (self.raw["vocab"]["units"] or {}).items()}
        vocab.unit_terms = {str(k): str(v) for k, v in (self.raw["vocab"]["unit_terms"] or {}).items()}

        fieldsets = {name: self.parse_fields(items, f"fieldset {name}")
                     for name, items in self.raw["fieldsets"].items()}

        collections = []
        for item in self.raw["collections"]:
            origin = item.get("_origin", "?")
            if not isinstance(item, dict) or "identifier" not in item:
                self.problems.append(f"{origin}: collection without identifier")
                continue
            collections.append(Collection(
                identifier=nsid(item["identifier"]), title=str(item.get("title") or ""),
                description=str(item.get("description") or ""), tags=[str(t) for t in item.get("tags") or []],
                visibility=str(item.get("visibility") or settings.default_visibility),
                parent=nsid(item.get("parent")), record_template=nsid(item.get("record_template")),
                roles=self._roles(item.get("roles"), f"{origin} collection {item['identifier']}", self.problems),
                origin=origin))

        templates = []
        for item in self.raw["templates"]:
            origin = item.get("_origin", "?")
            if not isinstance(item, dict) or "identifier" not in item:
                self.problems.append(f"{origin}: template without identifier")
                continue
            ident = item["identifier"]
            kind = str(item.get("kind", "record"))
            if kind not in ("record", "extras"):
                self.problems.append(f"{origin}: template '{ident}' kind must be 'record' or 'extras'")
            rec = item.get("record") or {}
            defaults = TemplateRecordDefaults(
                type=rec.get("type"), title=str(rec.get("title") or ""),
                description=str(rec.get("description") or ""), license=rec.get("license"),
                tags=[str(t) for t in rec.get("tags") or []],
                collections=[nsid(c) for c in rec.get("collections") or []],
                record_links=[{**l, "record": nsid(l.get("record"))} for l in rec.get("record_links") or []],
                roles=self._roles(rec.get("roles"), f"{origin} template {ident} record.roles", self.problems))
            templates.append(Template(
                identifier=nsid(ident), kind=kind, title=str(item.get("title") or ""),
                description=str(item.get("description") or ""),
                visibility=str(item.get("visibility") or settings.default_visibility),
                fields=self.parse_fields(item.get("fields"), f"{origin} template {ident}"),
                record=defaults,
                roles=self._roles(item.get("roles"), f"{origin} template {ident}", self.problems),
                origin=origin))

        records = []
        links = []
        for item in self.raw["records"]:
            origin = item.get("_origin", "?")
            if not isinstance(item, dict) or "identifier" not in item:
                self.problems.append(f"{origin}: record without identifier")
                continue
            ident = item["identifier"]
            files = []
            for fitem in item.get("files") or []:
                if isinstance(fitem, str):
                    files.append(FileSpec(path=fitem))
                elif isinstance(fitem, dict) and "path" in fitem:
                    files.append(FileSpec(path=str(fitem["path"]), name=fitem.get("name"),
                                          description=fitem.get("description"), mimetype=fitem.get("mimetype")))
                else:
                    self.problems.append(f"{origin}: record '{ident}' has an invalid files entry")
            for litem in item.get("links") or []:
                if not isinstance(litem, dict) or ("to" in litem) == ("from" in litem):
                    self.problems.append(f"{origin}: record '{ident}' link needs exactly one of 'to'/'from'")
                    continue
                ltype = litem.get("type") or litem.get("name")
                if "to" in litem:
                    links.append(LinkSpec(nsid(ident), nsid(litem["to"]), str(ltype), litem.get("term"),
                                          f"{origin} record {ident}"))
                else:
                    links.append(LinkSpec(nsid(litem["from"]), nsid(ident), str(ltype), litem.get("term"),
                                          f"{origin} record {ident}"))
            records.append(Record(
                identifier=nsid(ident), title=str(item.get("title") or ""), template=nsid(item.get("template")),
                type=item.get("type"), description=str(item.get("description") or ""),
                license=item.get("license", "__default__"), tags=[str(t) for t in item.get("tags") or []],
                visibility=str(item.get("visibility") or settings.default_visibility),
                collections=[nsid(c) for c in item.get("collections") or []] if "collections" in item else None,
                values=item.get("values") or {}, extras=item.get("extras") or [], files=files,
                roles=self._roles(item.get("roles"), f"{origin} record {ident}", self.problems),
                drop_empty=item.get("drop_empty"), origin=origin))

        for item in self.raw["links"]:
            origin = item.get("_origin", "?") if isinstance(item, dict) else "?"
            if not isinstance(item, dict) or not {"source", "target"} <= set(item):
                self.problems.append(f"{origin}: global link needs 'source', 'target' and 'type'")
                continue
            links.append(LinkSpec(nsid(item["source"]), nsid(item["target"]),
                                  str(item.get("type") or item.get("name")), item.get("term"), origin))

        return Model(settings=settings, vocab=vocab, collections=collections, templates=templates,
                     records=records, links=links, fieldsets=fieldsets, base_dir=self.root,
                     sources=self.sources)


def load_model(path: str | Path) -> Model:
    """Load a model file (and everything it includes). Raises :class:`ModelError`."""
    path = Path(path)
    loader = _Loader(path.parent)
    loader.load_file(path)
    model = loader.build()
    problems = loader.problems + validate_structure(model)
    if problems:
        raise ModelError(problems)
    return model


# ----------------------------------------------------------------------------- structural checks
def _check_identifier(kind: str, ident: str, origin: str, problems: list[str]) -> None:
    if not IDENTIFIER_RE.fullmatch(ident):
        problems.append(f"{origin}: {kind} identifier '{ident}' must match ^[a-z0-9-_]+$")
    if len(ident) > IDENTIFIER_MAX:
        problems.append(f"{origin}: {kind} identifier '{ident}' is longer than {IDENTIFIER_MAX} characters")


def _check_text(kind: str, ident: str, title: str, description: str, origin: str, problems: list[str]) -> None:
    if not title.strip():
        problems.append(f"{origin}: {kind} '{ident}' has an empty title")
    if len(title) > TITLE_MAX:
        problems.append(f"{origin}: {kind} '{ident}' title longer than {TITLE_MAX} characters")
    if len(description) > DESCRIPTION_MAX:
        problems.append(f"{origin}: {kind} '{ident}' description longer than {DESCRIPTION_MAX} characters")


def validate_structure(model: Model) -> list[str]:
    """Checks that do not need a server: identifiers, references, vocabulary, hierarchy."""
    p: list[str] = []
    seen: dict[str, str] = {}
    for kind, items in (("collection", model.collections), ("template", model.templates),
                        ("record", model.records)):
        for item in items:
            _check_identifier(kind, item.identifier, item.origin, p)
            _check_text(kind, item.identifier, item.title, item.description, item.origin, p)
            if item.visibility not in VISIBILITIES:
                p.append(f"{item.origin}: {kind} '{item.identifier}' visibility must be one of {VISIBILITIES}")
            key = f"{kind}:{item.identifier}"
            if key in seen:
                p.append(f"{item.origin}: duplicate {kind} identifier '{item.identifier}' (also in {seen[key]})")
            seen[key] = item.origin
            for tag in getattr(item, "tags", []):
                if len(tag) > TAG_MAX or not tag.strip():
                    p.append(f"{item.origin}: {kind} '{item.identifier}' has an invalid tag '{tag}'")

    col_ids = {c.identifier for c in model.collections}
    tmpl = {t.identifier: t for t in model.templates}
    rec_ids = {r.identifier for r in model.records}
    rec_types = {r.identifier: r for r in model.records}

    for c in model.collections:
        if c.parent and c.parent not in col_ids:
            p.append(f"{c.origin}: collection '{c.identifier}' has unknown parent '{c.parent}'")
        if c.parent == c.identifier:
            p.append(f"{c.origin}: collection '{c.identifier}' is its own parent")
        if c.record_template and c.record_template not in tmpl:
            p.append(f"{c.origin}: collection '{c.identifier}' has unknown record_template '{c.record_template}'")
        elif c.record_template and tmpl[c.record_template].kind != "record":
            p.append(f"{c.origin}: collection '{c.identifier}' record_template must be a record template")
        for role in c.roles:
            if role.role not in ROLES_RECORD:
                p.append(f"{c.origin}: collection '{c.identifier}' role '{role.role}' not in {ROLES_RECORD}")
    # cycles
    for c in model.collections:
        chain, cur = set(), c
        while cur and cur.parent:
            if cur.parent in chain or cur.parent == c.identifier:
                p.append(f"{c.origin}: collection hierarchy cycle involving '{c.identifier}'")
                break
            chain.add(cur.parent)
            cur = model.collection(cur.parent)

    for t in model.templates:
        _validate_fields(t.fields, f"{t.origin} template {t.identifier}", p)
        for col in t.record.collections:
            if col not in col_ids:
                p.append(f"{t.origin}: template '{t.identifier}' record.collections has unknown '{col}'")
        for rl in t.record.record_links:
            if rl.get("direction") not in ("out", "in"):
                p.append(f"{t.origin}: template '{t.identifier}' record_links direction must be out/in")
            if rl.get("record") not in rec_ids:
                p.append(f"{t.origin}: template '{t.identifier}' record_links has unknown record '{rl.get('record')}'")
            lt = rl.get("type") or rl.get("name")
            if not lt:
                p.append(f"{t.origin}: template '{t.identifier}' record_links entry needs 'type'")
            elif model.settings.strict_link_vocabulary and lt not in model.vocab.link_types and "name" not in rl:
                p.append(f"{t.origin}: template '{t.identifier}' record_links uses unknown link type '{lt}'")
        if t.visibility == "open":
            p.append(f"{t.origin}: template '{t.identifier}' visibility 'open' is not allowed for templates")
        for role in list(t.roles):
            if role.role not in ROLES_TEMPLATE:
                p.append(f"{t.origin}: template '{t.identifier}' role '{role.role}' not in {ROLES_TEMPLATE}")
        for role in t.record.roles:
            if role.role not in ROLES_RECORD:
                p.append(f"{t.origin}: template '{t.identifier}' record.roles role '{role.role}' invalid")
        if t.record.type and len(t.record.type) > TYPE_MAX:
            p.append(f"{t.origin}: template '{t.identifier}' record.type longer than {TYPE_MAX}")

    for r in model.records:
        if r.template and r.template not in tmpl:
            p.append(f"{r.origin}: record '{r.identifier}' uses unknown template '{r.template}'")
        rtype = r.type or (tmpl[r.template].record.type if r.template in tmpl else None)
        if rtype and len(rtype) > TYPE_MAX:
            p.append(f"{r.origin}: record '{r.identifier}' type longer than {TYPE_MAX}")
        if model.settings.enforce_type_prefix and rtype in model.vocab.record_types:
            prefix = model.vocab.record_types[rtype].get("prefix")
            if prefix and not r.identifier.startswith(prefix):
                p.append(f"{r.origin}: record '{r.identifier}' of type '{rtype}' must start with '{prefix}'")
        cols = list(r.collections or []) + (
            list(tmpl[r.template].record.collections) if r.template in tmpl else [])
        for col in cols:
            if col not in col_ids:
                p.append(f"{r.origin}: record '{r.identifier}' references unknown collection '{col}'")
        for role in r.roles:
            if role.role not in ROLES_RECORD:
                p.append(f"{r.origin}: record '{r.identifier}' role '{role.role}' not in {ROLES_RECORD}")
        if not isinstance(r.values, dict):
            p.append(f"{r.origin}: record '{r.identifier}' values must be a mapping")

    seen_links: set[tuple] = set()
    for l in model.links:
        if l.source not in rec_ids:
            p.append(f"{l.origin}: link source '{l.source}' is not a record in the model")
        if l.target not in rec_ids:
            p.append(f"{l.origin}: link target '{l.target}' is not a record in the model")
        if l.source == l.target:
            p.append(f"{l.origin}: link from '{l.source}' to itself is not allowed")
        if not l.type:
            p.append(f"{l.origin}: link {l.source} -> {l.target} has no type")
        elif len(l.type) > LINK_NAME_MAX:
            p.append(f"{l.origin}: link type '{l.type}' longer than {LINK_NAME_MAX}")
        lt = model.vocab.link_types.get(l.type)
        if lt is None:
            if model.settings.strict_link_vocabulary:
                p.append(f"{l.origin}: link type '{l.type}' ({l.source} -> {l.target}) is not in vocab.link_types")
        else:
            st = _record_type(model, l.source)
            tt = _record_type(model, l.target)
            if st and lt.sources and "*" not in lt.sources and st not in lt.sources:
                p.append(f"{l.origin}: link '{l.type}' does not allow source type '{st}' ({l.source})")
            if tt and lt.targets and "*" not in lt.targets and tt not in lt.targets:
                p.append(f"{l.origin}: link '{l.type}' does not allow target type '{tt}' ({l.target})")
        if l.term and len(l.term) > TERM_MAX:
            p.append(f"{l.origin}: link term longer than {TERM_MAX}")
        key = (l.source, l.target, l.type)
        if key in seen_links:
            p.append(f"{l.origin}: duplicate link {l.source} --{l.type}--> {l.target}")
        seen_links.add(key)
    return p


def _record_type(model: Model, identifier: str) -> str | None:
    rec = model.record(identifier)
    if rec is None:
        return None
    if rec.type:
        return rec.type
    t = model.template(rec.template) if rec.template else None
    return t.record.type if t else None


def _validate_fields(fields: list[Field], origin: str, p: list[str], parent: str = "", in_list=False) -> None:
    keys: set[str] = set()
    for f in fields:
        label = f.path_label(parent)
        if not in_list:
            if not f.key or not f.key.strip():
                p.append(f"{origin}: field under '{parent or '<root>'}' has an empty key")
            norm = " ".join((f.key or "").split())
            if norm in keys:
                p.append(f"{origin}: duplicate field key '{norm}' under '{parent or '<root>'}'")
            keys.add(norm)
        if f.unit is not None and f.type not in ("int", "float"):
            p.append(f"{origin}: field '{label}' has a unit but type '{f.type}' (units only for int/float)")
        if f.options is not None and f.type not in ("str", "int", "float"):
            p.append(f"{origin}: field '{label}' options only allowed for str/int/float")
        if f.range is not None and f.type not in ("int", "float"):
            p.append(f"{origin}: field '{label}' range only allowed for int/float")
        if f.iri and f.type != "str":
            p.append(f"{origin}: field '{label}' iri only allowed for str")
        if f.type in ("dict", "list") and (f.required or f.options or f.range or f.iri):
            p.append(f"{origin}: field '{label}' is nested ({f.type}) and cannot carry validation")
        if f.type == "dict":
            _validate_fields(f.fields, origin, p, label)
        if f.type == "list":
            _validate_fields(f.items, origin, p, label + "[]", in_list=True)
