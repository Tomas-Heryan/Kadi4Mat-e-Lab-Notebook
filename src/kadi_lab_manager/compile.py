"""Compile the declarative model into exact Kadi4Mat API payloads.

Everything produced here is already normalised the way the server would store it
(whitespace, lower-casing, units, UTC dates, template defaults), so a later
comparison with what the server returns is a plain equality test.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import mimetypes
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .errors import ModelError
from .extras import ExtrasValidationError, load_extras, normalize
from .model import Field, Model, Record, RoleSpec, Template


@dataclass
class CompiledFile:
    path: Path
    name: str
    description: str
    mimetype: str
    size: int
    sha256: str | None = None   # computed lazily (large files)


@dataclass
class CompiledRecord:
    identifier: str
    payload: dict               # body for POST /records (without server ids)
    collections: list[str]
    files: list[CompiledFile]
    roles: list[RoleSpec]
    origin: str


@dataclass
class CompiledTemplate:
    identifier: str
    kind: str
    payload: dict               # identifier/title/description/visibility/type
    data: Any                   # record-template dict or extras list, with SYMBOLIC refs:
    collections: list[str]      #   data.collections -> these identifiers
    record_links: list[dict]    #   data.record_links -> {direction, record(identifier), name, term}
    roles: list[RoleSpec]       #   data.roles -> group identifiers / user ids
    template_roles: list[RoleSpec]
    origin: str


@dataclass
class CompiledCollection:
    identifier: str
    payload: dict
    parent: str | None
    record_template: str | None
    roles: list[RoleSpec]
    origin: str


@dataclass
class CompiledLink:
    source: str
    target: str
    name: str
    term: str | None
    origin: str


@dataclass
class Compiled:
    collections: list[CompiledCollection]
    templates: list[CompiledTemplate]
    records: list[CompiledRecord]
    links: list[CompiledLink]
    notices: list[str] = field(default_factory=list)   # non-fatal remarks (assumed time zones etc.)

    def stats(self) -> dict:
        n_extras = sum(_count_extras(r.payload.get("extras", [])) for r in self.records)
        return {
            "collections": len(self.collections),
            "templates": len(self.templates),
            "records": len(self.records),
            "links": len(self.links),
            "files": sum(len(r.files) for r in self.records),
            "metadata_values": n_extras,
        }


def _count_extras(extras) -> int:
    n = 0
    for e in extras:
        if e["type"] in ("dict", "list"):
            n += _count_extras(e["value"])
        else:
            n += 1
    return n


# ----------------------------------------------------------------------------- helpers
def _norm_tags(tags) -> list[str]:
    out = []
    for t in tags or []:
        t = normalize(str(t)).lower()
        if t and t not in out:
            out.append(t)
    return sorted(out)


def _norm_type(value) -> str | None:
    if value is None:
        return None
    return normalize(str(value)).lower()


def _to_iso(value: Any, tz: ZoneInfo, notices: list[str], label: str) -> Any:
    """Turn YAML date/datetime objects (and naive strings) into offset-aware ISO strings."""
    if isinstance(value, dt.datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=tz)
            notices.append(f"{label}: naive date-time interpreted in {tz.key}")
        return value.isoformat()
    if isinstance(value, dt.date):
        notices.append(f"{label}: bare date expanded to 00:00 {tz.key}")
        return dt.datetime(value.year, value.month, value.day, tzinfo=tz).isoformat()
    return value


class _Compiler:
    def __init__(self, model: Model):
        self.model = model
        self.problems: list[str] = []
        self.notices: list[str] = []
        try:
            self.tz = ZoneInfo(model.settings.timezone)
        except Exception:  # noqa: BLE001
            self.problems.append(f"settings.timezone '{model.settings.timezone}' is not a valid IANA zone")
            self.tz = ZoneInfo("UTC")
        self.templates = {t.identifier: t for t in model.templates}
        # With a deployment namespace, free-text values that name a model identifier
        # (e.g. "method_identifier: meth-xrd-v02") are rewritten to the suffixed identifier
        # so the text stays consistent with the links.
        ns = model.settings.namespace
        self.identifier_map: dict[str, str] = {}
        if ns:
            for item in [*model.collections, *model.templates, *model.records]:
                if item.identifier.endswith(ns):
                    self.identifier_map[item.identifier[: -len(ns)]] = item.identifier

    # -- units ---------------------------------------------------------------------------
    def unit(self, unit, label):
        if unit is None:
            return None
        unit = normalize(str(unit))
        canon = self.model.vocab.units.get(unit, unit)
        if canon != unit:
            self.notices.append(f"{label}: unit '{unit}' normalised to '{canon}'")
        return canon

    # -- template fields -> extras (template mode) ------------------------------------
    def field_to_extra(self, f: Field, label: str, in_list: bool = False) -> dict:
        extra: dict[str, Any] = {}
        if not in_list:
            extra["key"] = f.key
        extra["type"] = f.type
        if f.type == "dict":
            extra["value"] = [self.field_to_extra(c, f"{label}.{c.key}") for c in f.fields]
        elif f.type == "list":
            extra["value"] = [self.field_to_extra(c, f"{label}[]", in_list=True) for c in f.items]
        else:
            extra["value"] = _to_iso(f.default, self.tz, self.notices, label) if f.default is not None else None
            if f.type in ("int", "float"):
                extra["unit"] = self.unit(f.unit, label)
            validation = {}
            if f.required:
                validation["required"] = True
            if f.options is not None:
                validation["options"] = [
                    _to_iso(o, self.tz, self.notices, label) if f.type == "date" else o for o in f.options]
            if f.range is not None:
                validation["range"] = {"min": f.range.get("min"), "max": f.range.get("max")}
            if f.iri:
                validation["iri"] = True
            if validation:
                extra["validation"] = validation
        if f.description:
            extra["description"] = f.description
        if f.term:
            extra["term"] = f.term
        return extra

    # -- record values -> extras ------------------------------------------------------------
    def values_to_extras(self, fields: list[Field], values: Any, label: str, in_list=False) -> list[dict]:
        out = []
        if in_list:
            values = values if isinstance(values, list) else ([] if values is None else [values])
            if not fields:
                return out
            for i, item_value in enumerate(values):
                proto = fields[i] if i < len(fields) else fields[-1]
                out.append(self.value_to_extra(proto, item_value, f"{label}[{i}]", in_list=True))
            return out
        if values is None:
            values = {}
        if not isinstance(values, dict):
            self.problems.append(f"{label}: expected a mapping of field values, got {type(values).__name__}")
            values = {}
        known = {f.key for f in fields}
        for k in values:
            if k not in known:
                self.problems.append(f"{label}: unknown value key '{k}' (not a field of the template)")
        for f in fields:
            present = f.key in values
            out.append(self.value_to_extra(f, values.get(f.key) if present else _MISSING, f"{label}.{f.key}"))
        return out

    def value_to_extra(self, f: Field, value: Any, label: str, in_list=False) -> dict:
        extra: dict[str, Any] = {}
        if not in_list:
            extra["key"] = f.key
        extra["type"] = f.type
        if f.type == "dict":
            extra["value"] = self.values_to_extras(f.fields, None if value is _MISSING else value, label)
        elif f.type == "list":
            extra["value"] = self.values_to_extras(f.items, None if value is _MISSING else value, label, in_list=True)
        else:
            if value is _MISSING:
                value = f.default
            if f.type == "str" and isinstance(value, str) and value in self.identifier_map:
                value = self.identifier_map[value]
            extra["value"] = _to_iso(value, self.tz, self.notices, label)
            if f.type in ("int", "float"):
                extra["unit"] = self.unit(f.unit, label)
            validation = {}
            if f.required:
                validation["required"] = True
            if f.options is not None:
                validation["options"] = [
                    _to_iso(o, self.tz, self.notices, label) if f.type == "date" else o for o in f.options]
            if f.range is not None:
                validation["range"] = {"min": f.range.get("min"), "max": f.range.get("max")}
            if f.iri:
                validation["iri"] = True
            if validation:
                extra["validation"] = validation
        if f.description:
            extra["description"] = f.description
        if f.term:
            extra["term"] = f.term
        return extra

    def raw_extras(self, extras: list, label: str) -> list:
        """Normalise units and YAML dates inside hand-written Kadi extras."""
        out = []
        for i, e in enumerate(extras):
            if not isinstance(e, dict):
                self.problems.append(f"{label}: raw extra #{i + 1} must be a mapping")
                continue
            e = dict(e)
            if e.get("type") in ("dict", "list") and isinstance(e.get("value"), list):
                e["value"] = self.raw_extras(e["value"], f"{label}.{e.get('key', i + 1)}")
            else:
                if "value" in e:
                    if isinstance(e["value"], str) and e["value"] in self.identifier_map:
                        e["value"] = self.identifier_map[e["value"]]
                    e["value"] = _to_iso(e["value"], self.tz, self.notices, f"{label}.{e.get('key', i + 1)}")
                if "unit" in e:
                    e["unit"] = self.unit(e["unit"], f"{label}.{e.get('key', i + 1)}")
            out.append(e)
        return out

    @staticmethod
    def drop_empty(extras: list) -> list:
        out = []
        for e in extras:
            if e["type"] in ("dict", "list"):
                children = _Compiler.drop_empty(e["value"])
                if children:
                    out.append({**e, "value": children})
            elif e["value"] is not None or e.get("validation", {}).get("required"):
                out.append(e)
        return out

    def validate_extras(self, extras: list, label: str, is_template: bool) -> list:
        try:
            return load_extras(extras, is_template=is_template, assume_timezone=self.tz)
        except ExtrasValidationError as exc:
            for line in _format_extras_errors(exc.messages, extras):
                self.problems.append(f"{label}: {line}")
            return extras

    # -- resources ------------------------------------------------------------------------
    def compile_template(self, t: Template) -> CompiledTemplate:
        label = f"template '{t.identifier}'"
        extras = [self.field_to_extra(f, f"{label} field {f.key}") for f in t.fields]
        extras = self.validate_extras(extras, label, is_template=True)
        payload = {
            "identifier": t.identifier,
            "title": normalize(t.title),
            "description": t.description.strip(),
            "visibility": t.visibility,
            "type": t.kind,
        }
        if t.kind == "extras":
            data = extras
        else:
            data = {
                "identifier": "",
                "title": normalize(t.record.title),
                "description": t.record.description.strip(),
                "type": _norm_type(t.record.type),
                "license": t.record.license,
                "tags": _norm_tags(t.record.tags),
                "extras": extras,
                "collections": [],      # resolved to ids at plan/apply time
                "record_links": [],
                "roles": [],
            }
        record_links = []
        for rl in t.record.record_links:
            lt = self.model.vocab.link_types.get(rl.get("type") or "")
            record_links.append({
                "direction": rl.get("direction"),
                "record": rl.get("record"),
                "name": normalize(str(rl.get("name") or rl.get("type"))),
                "term": rl.get("term") or (lt.term if lt else None),
            })
        return CompiledTemplate(identifier=t.identifier, kind=t.kind, payload=payload, data=data,
                                collections=list(t.record.collections), record_links=record_links,
                                roles=list(t.record.roles), template_roles=list(t.roles), origin=t.origin)

    def compile_files(self, r: Record, label: str) -> list[CompiledFile]:
        files = []
        root = (self.model.base_dir / self.model.settings.file_root).resolve()
        for fs in r.files:
            path = Path(fs.path)
            if not path.is_absolute():
                path = (root / path).resolve()
            if not path.exists():
                self.problems.append(f"{label}: file not found: {path}")
                size = 0
            else:
                size = path.stat().st_size
            name = normalize(fs.name or path.name)
            if len(name) > 256:
                self.problems.append(f"{label}: file name '{name}' longer than 256 characters")
            mimetype = (fs.mimetype or mimetypes.guess_type(name)[0] or "application/octet-stream").lower()
            files.append(CompiledFile(path=path, name=name, description=(fs.description or "").strip(),
                                      mimetype=mimetype, size=size))
        return files

    def compile_record(self, r: Record) -> CompiledRecord:
        label = f"record '{r.identifier}'"
        tmpl = self.templates.get(r.template) if r.template else None
        files = self.compile_files(r, label)
        values = dict(r.values) if isinstance(r.values, dict) else r.values
        if isinstance(values, dict) and values.get("files") == "auto":
            # Fill the integrity block from the attached files (name, sha256, size, mimetype).
            values["files"] = [
                {"name": f.name, "sha256": sha256_file(f.path) if f.path.exists() else None,
                 "size_bytes": f.size, "mimetype": f.mimetype} for f in files]
        extras: list = []
        if tmpl is not None:
            extras = self.values_to_extras(tmpl.fields, values, label)
        elif r.values:
            self.problems.append(f"{label}: 'values' given but no template to interpret them; use 'extras'")
        extras += self.raw_extras(r.extras, label)
        drop = r.drop_empty if r.drop_empty is not None else self.model.settings.drop_empty_optional_fields
        if drop:
            extras = self.drop_empty(extras)
        extras = self.validate_extras(extras, label, is_template=False)

        rtype = _norm_type(r.type or (tmpl.record.type if tmpl else None))
        license_ = r.license
        if license_ == "__default__":
            license_ = tmpl.record.license if (tmpl and tmpl.record.license) else self.model.settings.default_license
        tags = _norm_tags(list(r.tags) + (list(tmpl.record.tags) if tmpl else []))
        payload = {
            "identifier": r.identifier,
            "title": normalize(r.title),
            "type": rtype,
            "description": r.description.strip(),
            "license": license_,
            "visibility": r.visibility,
            "tags": tags,
            "extras": extras,
        }
        # Template default collections plus the record's own ones (union, order kept).
        collections = list(tmpl.record.collections) if tmpl else []
        for col in (r.collections or []):
            if col not in collections:
                collections.append(col)
        roles = list(r.roles) + (list(tmpl.record.roles) if tmpl else [])
        return CompiledRecord(identifier=r.identifier, payload=payload, collections=list(collections),
                              files=files, roles=roles, origin=r.origin)

    def compile(self) -> Compiled:
        m = self.model
        collections = [CompiledCollection(
            identifier=c.identifier,
            payload={"identifier": c.identifier, "title": normalize(c.title), "description": c.description.strip(),
                     "visibility": c.visibility, "tags": _norm_tags(c.tags)},
            parent=c.parent, record_template=c.record_template, roles=list(c.roles), origin=c.origin)
            for c in m.ordered_collections()]
        templates = [self.compile_template(t) for t in m.templates]
        records = [self.compile_record(r) for r in m.records]
        links = []
        for l in m.links:
            lt = m.vocab.link_types.get(l.type)
            links.append(CompiledLink(source=l.source, target=l.target, name=normalize(l.type),
                                      term=l.term or (lt.term if lt else None), origin=l.origin))
        return Compiled(collections=collections, templates=templates, records=records, links=links,
                        notices=self.notices)


_MISSING = object()


def _format_extras_errors(messages, extras, prefix="") -> list[str]:
    """Turn the server-style nested error structure into readable 'path: message' lines."""
    lines = []
    if isinstance(messages, dict):
        for idx, fields in messages.items():
            if isinstance(idx, int) and isinstance(extras, list) and idx < len(extras):
                key = extras[idx].get("key", f"[{idx}]") if isinstance(extras[idx], dict) else f"[{idx}]"
                path = f"{prefix}.{key}" if prefix else str(key)
                if isinstance(fields, dict):
                    for fname, msgs in fields.items():
                        if fname == "value" and isinstance(msgs, dict):
                            child = extras[idx].get("value") if isinstance(extras[idx], dict) else None
                            lines += _format_extras_errors(msgs, child, path)
                        else:
                            for msg in (msgs if isinstance(msgs, list) else [msgs]):
                                lines.append(f"{path} ({fname}): {msg}")
                else:
                    lines.append(f"{path}: {fields}")
            else:
                lines.append(f"{prefix or '<extras>'} {idx}: {fields}")
    else:
        lines.append(f"{prefix or '<extras>'}: {messages}")
    return lines


def compile_model(model: Model, strict: bool = True) -> Compiled:
    """Compile and validate; raises :class:`ModelError` with all problems when strict."""
    c = _Compiler(model)
    compiled = c.compile()
    if c.problems and strict:
        raise ModelError(c.problems)
    compiled.notices = c.notices + ([f"PROBLEM: {p}" for p in c.problems] if not strict else [])
    return compiled


def sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def kadi_checksum(path: Path, boundary: int = 50 * 1024 * 1024, chunk_size: int = 10 * 1024 * 1024) -> str:
    """Reproduce the checksum Kadi4Mat stores for an uploaded file.

    Direct uploads (size <= 50 MB): MD5 of the content. Chunked uploads: MD5 of the
    concatenated per-chunk MD5 digests, followed by "-<chunk count>".
    """
    size = os.path.getsize(path)
    if size <= boundary:
        h = hashlib.md5()
        with path.open("rb") as f:
            for block in iter(lambda: f.read(1 << 20), b""):
                h.update(block)
        return h.hexdigest()
    digests = []
    with path.open("rb") as f:
        while True:
            block = f.read(chunk_size)
            if not block:
                break
            digests.append(hashlib.md5(block).hexdigest())
    return hashlib.md5(bytes.fromhex("".join(digests))).hexdigest() + f"-{len(digests)}"
