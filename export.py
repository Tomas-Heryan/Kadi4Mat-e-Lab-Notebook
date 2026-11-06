"""Exports, snapshots and the reverse direction (Kadi JSON export -> model YAML)."""
from __future__ import annotations

import hashlib
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import yaml

from .client import KadiClient
from .compile import Compiled, sha256_file
from .deploy import RECORD_FIELDS, _diff
from .errors import KadiLabError

EXPORT_EXT = {
    "records": {"json": "json", "rdf": "ttl", "pdf": "pdf", "qr": "png", "ro-crate": "eln"},
    "collections": {"json": "json", "rdf": "ttl", "qr": "png", "ro-crate": "eln"},
    "templates": {"json": "json", "json-schema": "schema.json", "shacl": "ttl"},
}


def export_resource(client: KadiClient, kind: str, identifier: str, export_type: str, out_dir: Path,
                    export_filter: dict | None = None, metadata_only: bool = False) -> dict:
    if export_type not in EXPORT_EXT.get(kind, {}):
        raise KadiLabError(f"export type '{export_type}' is not available for {kind}; "
                           f"choose from {sorted(EXPORT_EXT.get(kind, {}))}")
    resource = client.get_by_identifier(kind, identifier)
    if resource is None:
        raise KadiLabError(f"{kind[:-1]} '{identifier}' does not exist on {client.config.host}")
    export_filter = dict(export_filter or {})
    ext = EXPORT_EXT[kind][export_type]
    if export_type == "ro-crate" and metadata_only:
        export_filter["metadata_only"] = True
        ext = "ro-crate-metadata.json"
    dest = out_dir / f"{identifier}.{ext}"
    client.export(kind, resource["id"], export_type, dest, export_filter or None)
    result = {"kind": kind, "identifier": identifier, "id": resource["id"], "export_type": export_type,
              "file": str(dest), "size": dest.stat().st_size, "sha256": sha256_file(dest),
              "filter": export_filter, "exported_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    if export_type == "ro-crate" and not metadata_only:
        result["crate"] = inspect_crate(dest)
    (out_dir / f"{identifier}.{ext}.sha256").write_text(f"{result['sha256']}  {dest.name}\n", encoding="utf-8")
    return result


def inspect_crate(path: Path) -> dict:
    """Sanity-check an exported ``.eln`` RO-Crate and list what it contains."""
    with zipfile.ZipFile(path) as zf:
        names = zf.namelist()
        root = names[0].split("/")[0] if names else ""
        meta_name = f"{root}/ro-crate-metadata.json"
        problems = []
        if meta_name not in names:
            problems.append("ro-crate-metadata.json missing")
            return {"root": root, "entries": len(names), "problems": problems}
        meta = json.loads(zf.read(meta_name))
        graph = {e.get("@id"): e for e in meta.get("@graph", []) if isinstance(e, dict)}
        datasets = [e for e in graph.values() if e.get("@type") == "Dataset" and e.get("@id") != "./"]
        files = [e for e in graph.values() if e.get("@type") == "File"]
        for f in files:
            arc = f"{root}/{f['@id'][2:]}" if f["@id"].startswith("./") else f"{root}/{f['@id']}"
            from urllib.parse import unquote
            if unquote(arc) not in names and arc not in names:
                problems.append(f"file entity without archive member: {f['@id']}")
        return {"root": root, "entries": len(names), "record_datasets": len(datasets),
                "file_entities": len(files), "problems": problems,
                "kadi_version": graph.get("ro-crate-metadata.json", {}).get("version")}


def snapshot(client: KadiClient, compiled: Compiled, out_dir: Path, include_collections: bool = True,
             include_templates: bool = True, log=print) -> dict:
    """Download the JSON export of every model object and compare it with the model."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = out_dir / stamp
    manifest = {"host": client.config.host, "taken_at": stamp, "files": {}, "missing": [], "drift": {}}
    groups = [("records", compiled.records)]
    if include_collections:
        groups.append(("collections", compiled.collections))
    if include_templates:
        groups.append(("templates", compiled.templates))
    for kind, items in groups:
        for item in items:
            resource = client.get_by_identifier(kind, item.identifier)
            if resource is None:
                manifest["missing"].append(f"{kind}:{item.identifier}")
                log(f"[MISSING] {kind[:-1]} {item.identifier}")
                continue
            export_filter = {"records": True} if kind == "collections" else None
            data = client.export_json(kind, resource["id"], export_filter)
            dest = target / kind / f"{item.identifier}.json"
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            rel = str(dest.relative_to(target))
            manifest["files"][rel] = {"sha256": sha256_file(dest), "id": resource["id"]}
            if kind == "records":
                changed = _diff(item.payload, data, [f for f in RECORD_FIELDS if f != "visibility"])
                if changed:
                    manifest["drift"][item.identifier] = changed
                    log(f"[DRIFT] record {item.identifier}: {', '.join(changed)}")
                else:
                    log(f"[OK] record {item.identifier}")
            else:
                log(f"[OK] {kind[:-1]} {item.identifier}")
    (target / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"directory": str(target), "files": len(manifest["files"]), "missing": manifest["missing"],
            "drift": manifest["drift"]}


# --------------------------------------------------------------------------- reverse direction
def export_to_model(export_path: Path, out_path: Path, namespace: str = "", client: KadiClient | None = None,
                    log=print) -> dict:
    """Convert a Kadi4Mat JSON export (record or collection) into a model YAML file.

    Extras are kept verbatim (``extras:``), links become typed links by identifier and
    files are listed under ``files/<identifier>/<name>`` next to the YAML. With a client,
    the files are downloaded from the instance into that folder (checksum-verified for
    directly uploaded files).
    """
    data = json.loads(export_path.read_text(encoding="utf-8"))
    model: dict = {"schema_version": 1, "settings": {"name": f"imported from {export_path.name}",
                                                       "file_root": ".",
                                                       "strict_link_vocabulary": False,
                                                       "enforce_type_prefix": False}}
    collections, records, links = [], [], []
    seen_records: set[str] = set()
    downloads: list[str] = []
    missing_files: list[str] = []

    def add_record(rec: dict):
        if rec["identifier"] in seen_records:
            return
        seen_records.add(rec["identifier"])
        entry = {
            "identifier": rec["identifier"],
            "title": rec["title"],
            "type": rec.get("type"),
            "description": rec.get("description", ""),
            "license": rec.get("license"),
            "tags": rec.get("tags", []),
            "extras": rec.get("extras", []),
        }
        if rec.get("files"):
            entry["files"] = []
            for f in rec["files"]:
                rel = f"files/{rec['identifier']}/{f['name']}"
                entry["files"].append({"path": rel, "name": f["name"], "description": f.get("description", ""),
                                       "mimetype": f.get("mimetype")})
                dest = out_path.parent / rel
                if client is not None:
                    client.download_file(rec["id"], f["id"], dest)
                    checksum = f.get("checksum")
                    if checksum and "-" not in checksum:
                        if hashlib.md5(dest.read_bytes()).hexdigest() != checksum:
                            raise KadiLabError(f"checksum mismatch after downloading {rel}")
                    downloads.append(rel)
                    log(f"[DOWNLOAD] {rel} ({f.get('size')} B)")
                elif not dest.exists():
                    missing_files.append(rel)
        records.append(entry)
        for link in rec.get("links", []) or []:
            if "record_to" in link:
                links.append({"source": rec["identifier"], "target": link["record_to"]["identifier"],
                              "type": link["name"], **({"term": link["term"]} if link.get("term") else {})})
            elif "record_from" in link:
                links.append({"source": link["record_from"]["identifier"], "target": rec["identifier"],
                              "type": link["name"], **({"term": link["term"]} if link.get("term") else {})})

    if "records" in data and "extras" not in data:   # collection export
        collections.append({"identifier": data["identifier"], "title": data["title"],
                            "description": data.get("description", ""), "tags": data.get("tags", [])})
        for rec in data.get("records", []):
            add_record(rec)
            rec.setdefault("_collections", []).append(data["identifier"])
        for entry in records:
            entry["collections"] = [data["identifier"]]
    elif "extras" in data:                              # record export
        add_record(data)
    else:
        raise KadiLabError("the file is neither a record nor a collection export")

    # Links to records outside the export cannot be re-created; keep them as a note.
    known = {r["identifier"] for r in records}
    external = [l for l in links if l["source"] not in known or l["target"] not in known]
    links = [l for l in links if l["source"] in known and l["target"] in known]
    unique_links = []
    seen_links = set()
    for l in links:
        key = (l["source"], l["target"], l["type"])
        if key not in seen_links:
            seen_links.add(key)
            unique_links.append(l)
    if namespace:
        model["settings"]["namespace"] = namespace
    if collections:
        model["collections"] = collections
    model["records"] = records
    if unique_links:
        model["links"] = unique_links
    if external:
        model["settings"]["_external_links_not_recreated"] = external
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(yaml.safe_dump(model, sort_keys=False, allow_unicode=True, width=100), encoding="utf-8")
    return {"records": len(records), "collections": len(collections), "links": len(unique_links),
            "external_links_dropped": len(external), "files_downloaded": len(downloads),
            "files_to_place_manually": missing_files, "output": str(out_path)}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
