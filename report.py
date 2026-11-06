"""JSON run reports — one file per command run, never overwritten."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class RunReport:
    def __init__(self, command: str, host: str, model_name: str = "", model_version: str = "",
                 namespace: str = "", dry_run: bool = True):
        self.started = datetime.now(timezone.utc)
        self.data: dict[str, Any] = {
            "tool": "kadi-lab-manager",
            "command": command,
            "dry_run": dry_run,
            "host": host,
            "model": {"name": model_name, "version": model_version, "namespace": namespace},
            "started_at": self.started.isoformat(timespec="seconds"),
            "finished_at": None,
            "summary": {},
            "operations": [],
            "warnings": [],
            "errors": [],
        }

    def op(self, action: str, kind: str, identifier: str, status: str = "planned", **detail) -> dict:
        entry = {"action": action, "kind": kind, "identifier": identifier, "status": status, **detail}
        self.data["operations"].append(entry)
        return entry

    def warn(self, message: str) -> None:
        self.data["warnings"].append(message)

    def error(self, message: str) -> None:
        self.data["errors"].append(message)

    def finish(self, **summary) -> None:
        self.data["finished_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        counts: dict[str, int] = {}
        for op in self.data["operations"]:
            key = f"{op['action']}:{op['status']}"
            counts[key] = counts.get(key, 0) + 1
        self.data["summary"] = {"operations": counts, **summary}

    def write(self, directory: Path, host_slug: str) -> Path:
        directory.mkdir(parents=True, exist_ok=True)
        stamp = self.started.strftime("%Y%m%dT%H%M%SZ")
        path = directory / f"{stamp}_{self.data['command']}_{host_slug}.json"
        path.write_text(json.dumps(self.data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return path
