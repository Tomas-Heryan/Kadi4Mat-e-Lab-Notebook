"""Remove what this tool created on a (test) instance — and nothing else.

Safety rules: dry-run by default; ``--apply --yes`` required to delete; only
objects recorded in the state file as ``created_by_tool`` are touched unless
``include_adopted`` is set; an optional namespace suffix narrows the selection
further; every object is re-checked by identifier right before deletion.
"""
from __future__ import annotations

from .client import KadiClient
from .errors import ApiError
from .report import RunReport
from .state import State

ORDER = ("records", "templates", "collections")


def select_targets(state: State, namespace: str | None, include_adopted: bool) -> list[tuple[str, str, dict]]:
    targets = []
    for kind in ORDER:
        entries = state.entries(kind)
        for identifier, entry in entries.items():
            if not include_adopted and not entry.get("created_by_tool"):
                continue
            if namespace and not identifier.endswith(namespace):
                continue
            targets.append((kind, identifier, entry))
    # newest first inside each kind, so child collections go before their parents
    targets.sort(key=lambda t: (ORDER.index(t[0]), t[2].get("first_seen", ""), t[1]), reverse=False)
    out = []
    for kind in ORDER:
        group = [t for t in targets if t[0] == kind]
        group.sort(key=lambda t: t[2].get("first_seen", ""), reverse=True)
        out.extend(group)
    return out


def run_cleanup(client: KadiClient, state: State, report: RunReport, namespace: str | None = None,
                include_adopted: bool = False, purge: bool = False, apply: bool = False, log=print) -> dict:
    targets = select_targets(state, namespace, include_adopted)
    deleted, skipped, failed = 0, 0, 0
    for kind, identifier, entry in targets:
        current = client.get_by_identifier(kind, identifier)
        if current is None:
            state.forget(kind, identifier)
            report.op("forget", kind, identifier, status="gone")
            log(f"[GONE] {kind[:-1]} {identifier} (already deleted; removed from state)")
            skipped += 1
            continue
        if current["id"] != entry["id"]:
            report.op("delete", kind, identifier, status="id-mismatch", state_id=entry["id"], server_id=current["id"])
            log(f"[SKIP] {kind[:-1]} {identifier}: server id {current['id']} differs from state {entry['id']}")
            skipped += 1
            continue
        if not apply:
            report.op("delete", kind, identifier, status="planned", id=current["id"])
            log(f"[PLAN DELETE] {kind[:-1]} {identifier} (id {current['id']})")
            continue
        try:
            client.delete(kind, current["id"])
            if purge:
                client.purge(kind, current["id"])
            state.forget(kind, identifier)
            state.save()
            deleted += 1
            report.op("delete", kind, identifier, status="done", id=current["id"], purged=purge)
            log(f"[DELETED] {kind[:-1]} {identifier} (id {current['id']}){' + purged' if purge else ''}")
        except ApiError as exc:
            failed += 1
            report.op("delete", kind, identifier, status="failed", id=current["id"], message=str(exc))
            report.error(f"delete {kind} {identifier}: {exc}")
            log(f"[FAILED] {kind[:-1]} {identifier}: {exc}")
    return {"targets": len(targets), "deleted": deleted, "skipped": skipped, "failed": failed, "apply": apply}
