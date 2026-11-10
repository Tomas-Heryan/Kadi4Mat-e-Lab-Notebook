"""Local state: which model identifiers map to which server ids on which host.

The state file is the memory of the tool between runs. It makes re-runs cheap,
records which objects *this tool* created (so ``cleanup`` never touches anything
else) and gives every run a trace of what happened.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .errors import StateError

KINDS = ("collections", "templates", "records")


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class State:
    def __init__(self, path: Path, host: str):
        self.path = path
        self.host = host
        self.data = {"host": host, "created_at": utcnow(), "updated_at": utcnow(),
                     "resources": {k: {} for k in KINDS}, "runs": []}
        if path.exists():
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if loaded.get("host") != host:
                raise StateError(f"state file {path} belongs to host {loaded.get('host')}, not {host}")
            self.data = loaded
            for k in KINDS:
                self.data.setdefault("resources", {}).setdefault(k, {})

    # -- queries -----------------------------------------------------------------------
    def id_of(self, kind: str, identifier: str) -> int | None:
        entry = self.data["resources"][kind].get(identifier)
        return entry["id"] if entry else None

    def entries(self, kind: str) -> dict:
        return self.data["resources"][kind]

    # -- updates -----------------------------------------------------------------------
    def remember(self, kind: str, identifier: str, resource_id: int, created_by_tool: bool,
                 model_name: str = "", namespace: str = "") -> None:
        entry = self.data["resources"][kind].get(identifier) or {
            "id": resource_id, "created_by_tool": created_by_tool, "first_seen": utcnow(),
            "model": model_name, "namespace": namespace}
        entry["id"] = resource_id
        entry["last_seen"] = utcnow()
        if created_by_tool:
            entry["created_by_tool"] = True
        self.data["resources"][kind][identifier] = entry

    def forget(self, kind: str, identifier: str) -> None:
        self.data["resources"][kind].pop(identifier, None)

    def add_run(self, command: str, report_path: str, summary: dict) -> None:
        self.data["runs"].append({"at": utcnow(), "command": command, "report": report_path,
                                  "summary": summary})
        self.data["runs"] = self.data["runs"][-200:]

    def save(self) -> None:
        self.data["updated_at"] = utcnow()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=2, sort_keys=False) + "\n",
                             encoding="utf-8")
