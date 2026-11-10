"""Command line interface: ``python -m kadi_lab_manager <command> ...``."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .cleanup import run_cleanup
from .compile import compile_model
from .config import load_config
from .deploy import Executor, Planner
from .errors import ApiError, ConfigError, KadiLabError, ModelError
from .export import export_resource, export_to_model, snapshot
from .model import load_model
from .report import RunReport
from .state import State


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="kadi-lab-manager",
                                description="Reproducible deployment of laboratory metadata into Kadi4Mat "
                                            "(HTTPS only, TLS always verified).")
    p.add_argument("--version", action="version", version=f"kadi-lab-manager {__version__}")
    p.add_argument("--host", help="Kadi4Mat base URL (default: $KADI_URL or https://kadi-test.vsb.cz)")
    p.add_argument("--state-dir", help="directory for state files (default: ./state)")
    p.add_argument("--report-dir", help="directory for run reports (default: ./reports)")
    p.add_argument("-q", "--quiet", action="store_true", help="print less")
    sub = p.add_subparsers(dest="command", required=True)
    # -q is also accepted after the sub-command (SUPPRESS keeps the global value otherwise).
    _add_parser = sub.add_parser

    def add_parser(name, **kwargs):
        parser = _add_parser(name, **kwargs)
        parser.add_argument("-q", "--quiet", action="store_true", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
        return parser

    sub.add_parser = add_parser

    sub.add_parser("doctor", help="check connection, token, TLS and instance version")

    s = sub.add_parser("validate", help="load + compile the model offline, report problems and statistics")
    s.add_argument("model")
    s.add_argument("--json", action="store_true", help="print statistics as JSON")

    s = sub.add_parser("compile", help="write the exact API payloads to a directory (for review / Git)")
    s.add_argument("model")
    s.add_argument("--out", default="build", help="output directory (default: ./build)")

    s = sub.add_parser("plan", help="compare the model with the server and print what apply would do")
    s.add_argument("model")
    s.add_argument("--no-file-check", action="store_true", help="skip checksum comparison of existing files")

    s = sub.add_parser("apply", help="create missing objects (and with --update, fix drifted metadata)")
    s.add_argument("model")
    s.add_argument("--update", action="store_true", help="also patch objects whose metadata differs from the model")
    s.add_argument("--continue-on-error", action="store_true")
    s.add_argument("--yes", action="store_true", help="do not ask for confirmation")
    s.add_argument("--no-file-check", action="store_true")

    s = sub.add_parser("export", help="download an export (json, ro-crate/.eln, rdf, pdf, qr, json-schema, shacl)")
    g = s.add_mutually_exclusive_group(required=True)
    g.add_argument("--record")
    g.add_argument("--collection")
    g.add_argument("--template")
    s.add_argument("--format", default="json")
    s.add_argument("--out", default="exports")
    s.add_argument("--filter", help='export filter as JSON, e.g. {"user": true, "children": true}')
    s.add_argument("--metadata-only", action="store_true", help="ro-crate: only the metadata file")

    s = sub.add_parser("snapshot", help="download the JSON export of every model object and report drift")
    s.add_argument("model")
    s.add_argument("--out", default="snapshots")

    s = sub.add_parser("import-export", help="turn a Kadi JSON export (record/collection) into a model YAML")
    s.add_argument("file")
    s.add_argument("--out", required=True)
    s.add_argument("--namespace", default="", help="suffix for all identifiers, e.g. --namespace=-copy")
    s.add_argument("--download-files", action="store_true",
                   help="download the records' files from the instance into files/<identifier>/ (needs a token)")

    s = sub.add_parser("cleanup", help="delete objects this tool created on the instance (dry-run by default)")
    s.add_argument("--namespace", help="only identifiers ending with this suffix")
    s.add_argument("--include-adopted", action="store_true",
                   help="also delete objects that existed before the tool adopted them")
    s.add_argument("--purge", action="store_true", help="purge from the trash as well (irreversible)")
    s.add_argument("--apply", action="store_true")
    s.add_argument("--yes", action="store_true")
    return p


def _say(args, msg: str = "") -> None:
    if not getattr(args, "quiet", False):
        print(msg)


def cmd_doctor(args) -> int:
    from .client import KadiClient
    cfg = load_config(args.host)
    print(f"host:        {cfg.host}")
    print(f"TLS:         verified ({'custom CA bundle ' + cfg.ca_bundle if cfg.ca_bundle else 'system trust store'})")
    try:
        from importlib import metadata
        print(f"kadi-apy:    {metadata.version('kadi-apy')}")
    except Exception:  # noqa: BLE001
        print("kadi-apy:    MISSING - python -m pip install -r requirements.txt")
        return 2
    with KadiClient(cfg) as client:
        info = client.info()
        print(f"Kadi4Mat:    {info.get('version', '?')}")
        me = client.me()
        identity = me.get("identity") or {}
        print(f"token user:  {me.get('displayname')} (id {me.get('id')}, {identity.get('username', '?')})")
        try:
            data = client.request("get", "/records", params={"per_page": 1}).json()
            print(f"records:     {data.get('_pagination', {}).get('total_items', '?')} visible to this token")
        except ApiError as exc:
            print(f"records:     not readable ({exc.status}) - check token scopes (record.read)")
    print("OK")
    return 0


def _load(args):
    model = load_model(args.model)
    compiled = compile_model(model)
    return model, compiled


def cmd_validate(args) -> int:
    model, compiled = _load(args)
    stats = compiled.stats()
    if args.json:
        print(json.dumps({"model": model.settings.name, "version": model.settings.version,
                          "namespace": model.settings.namespace, "sources": model.sources, "stats": stats,
                          "notices": compiled.notices}, ensure_ascii=False, indent=2))
        return 0
    print(f"Model '{model.settings.name}' v{model.settings.version}"
          + (f" (namespace {model.settings.namespace})" if model.settings.namespace else ""))
    print(f"  files loaded:      {len(model.sources)}")
    for key, value in stats.items():
        print(f"  {key + ':':19s}{value}")
    if compiled.notices:
        print(f"  notices:           {len(compiled.notices)}")
        for n in compiled.notices[:30]:
            print(f"    - {n}")
        if len(compiled.notices) > 30:
            print(f"    ... {len(compiled.notices) - 30} more")
    print("Model is valid: every payload passes the Kadi4Mat rules offline.")
    return 0


def cmd_compile(args) -> int:
    model, compiled = _load(args)
    out = Path(args.out)
    for sub in ("collections", "templates", "records", "links"):
        (out / sub).mkdir(parents=True, exist_ok=True)
    for col in compiled.collections:
        _dump(out / "collections" / f"{col.identifier}.json",
              {**col.payload, "_parent": col.parent, "_record_template": col.record_template})
    for t in compiled.templates:
        _dump(out / "templates" / f"{t.identifier}.json",
              {**t.payload, "data": t.data, "_collections": t.collections, "_record_links": t.record_links})
    for r in compiled.records:
        _dump(out / "records" / f"{r.identifier}.json",
              {**r.payload, "_collections": r.collections,
               "_files": [{"name": f.name, "size": f.size, "mimetype": f.mimetype} for f in r.files]})
    _dump(out / "links" / "links.json",
          [{"source": l.source, "target": l.target, "name": l.name, "term": l.term} for l in compiled.links])
    _dump(out / "summary.json", {"model": model.settings.name, "version": model.settings.version,
                                 "stats": compiled.stats(), "notices": compiled.notices})
    print(f"Compiled payloads written to {out}/ ({compiled.stats()})")
    return 0


def _dump(path: Path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _print_plan(args, plan) -> None:
    for op in plan.ops:
        if op.action == "skip":
            continue
        flag = " (needs --update)" if op.needs_update else ""
        _say(args, f"[{op.action.upper()}]{flag} {op.describe()}")
    for w in plan.warnings:
        _say(args, f"[WARN] {w}")
    _say(args, "")
    _say(args, "Summary: " + ", ".join(f"{k}: {v}" for k, v in sorted(plan.counts().items())))


def cmd_plan(args) -> int:
    from .client import KadiClient
    model, compiled = _load(args)
    cfg = load_config(args.host, state_dir=args.state_dir, report_dir=args.report_dir)
    report = RunReport("plan", cfg.host, model.settings.name, model.settings.version, model.settings.namespace,
                       dry_run=True)
    with KadiClient(cfg) as client:
        planner = Planner(client, compiled, check_files=not args.no_file_check)
        plan = planner.build()
    _print_plan(args, plan)
    for op in plan.ops:
        report.op(op.action, op.kind, op.identifier, status="planned", needs_update=op.needs_update,
                  **{k: v for k, v in op.detail.items() if k not in ("payload", "data")})
    for w in plan.warnings:
        report.warn(w)
    report.finish(stats=compiled.stats())
    path = report.write(cfg.report_dir, cfg.host_slug)
    _say(args, f"Report: {path}")
    return 0


def cmd_apply(args) -> int:
    from .client import KadiClient
    model, compiled = _load(args)
    cfg = load_config(args.host, state_dir=args.state_dir, report_dir=args.report_dir)
    state = State(cfg.state_dir / f"{cfg.host_slug}.json", cfg.host)
    report = RunReport("apply", cfg.host, model.settings.name, model.settings.version, model.settings.namespace,
                       dry_run=False)
    with KadiClient(cfg) as client:
        planner = Planner(client, compiled, state, check_files=not args.no_file_check)
        plan = planner.build()
        _print_plan(args, plan)
        if not plan.has_changes(include_updates=args.update):
            _say(args, "Nothing to do - the instance already matches the model.")
            report.finish(stats=compiled.stats())
            report.write(cfg.report_dir, cfg.host_slug)
            return 0
        if not args.yes:
            answer = input(f"Apply these changes to {cfg.host}? [y/N] ").strip().lower()
            if answer not in ("y", "yes"):
                print("Aborted.")
                return 1
        executor = Executor(client, planner, plan, state, report, update=args.update,
                            continue_on_error=args.continue_on_error, model_name=model.settings.name,
                            namespace=model.settings.namespace, log=lambda m: _say(args, m))
        executor.run()
    for w in plan.warnings:
        report.warn(w)
    report.finish(stats=compiled.stats())
    path = report.write(cfg.report_dir, cfg.host_slug)
    state.add_run("apply", str(path), report.data["summary"])
    state.save()
    failed = [op for op in plan.ops if op.status == "failed"]
    _say(args, f"Report: {path}")
    _say(args, f"State:  {state.path}")
    if failed:
        print(f"{len(failed)} operation(s) failed; see the report.", file=sys.stderr)
        return 1
    return 0


def cmd_export(args) -> int:
    from .client import KadiClient
    cfg = load_config(args.host)
    kind, identifier = (("records", args.record) if args.record else
                        ("collections", args.collection) if args.collection else ("templates", args.template))
    export_filter = json.loads(args.filter) if args.filter else None
    with KadiClient(cfg) as client:
        result = export_resource(client, kind, identifier, args.format, Path(args.out), export_filter,
                                 metadata_only=args.metadata_only)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_snapshot(args) -> int:
    from .client import KadiClient
    model, compiled = _load(args)
    cfg = load_config(args.host)
    with KadiClient(cfg) as client:
        result = snapshot(client, compiled, Path(args.out), log=lambda m: _say(args, m))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not result["drift"] and not result["missing"] else 3


def cmd_import_export(args) -> int:
    if args.download_files:
        from .client import KadiClient
        with KadiClient(load_config(args.host)) as client:
            result = export_to_model(Path(args.file), Path(args.out), namespace=args.namespace, client=client,
                                     log=lambda m: _say(args, m))
    else:
        result = export_to_model(Path(args.file), Path(args.out), namespace=args.namespace)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["files_to_place_manually"]:
        print("Place the listed files next to the YAML before 'apply', or re-run with --download-files.")
    return 0


def cmd_cleanup(args) -> int:
    from .client import KadiClient
    cfg = load_config(args.host, state_dir=args.state_dir, report_dir=args.report_dir)
    state_path = cfg.state_dir / f"{cfg.host_slug}.json"
    if not state_path.exists():
        print(f"No state file for {cfg.host} ({state_path}); nothing to clean up.")
        return 0
    state = State(state_path, cfg.host)
    if args.apply and not args.yes:
        print("Refusing to delete without --yes.", file=sys.stderr)
        return 2
    report = RunReport("cleanup", cfg.host, dry_run=not args.apply)
    with KadiClient(cfg) as client:
        result = run_cleanup(client, state, report, namespace=args.namespace, include_adopted=args.include_adopted,
                             purge=args.purge, apply=args.apply, log=lambda m: _say(args, m))
    report.finish(**result)
    path = report.write(cfg.report_dir, cfg.host_slug)
    state.add_run("cleanup", str(path), result)
    state.save()
    print(json.dumps(result, ensure_ascii=False))
    return 0 if not result["failed"] else 1


COMMANDS = {
    "doctor": cmd_doctor, "validate": cmd_validate, "compile": cmd_compile, "plan": cmd_plan,
    "apply": cmd_apply, "export": cmd_export, "snapshot": cmd_snapshot, "import-export": cmd_import_export,
    "cleanup": cmd_cleanup,
}


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):   # Czech characters on Windows consoles
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    args = build_parser().parse_args(argv)
    try:
        return COMMANDS[args.command](args)
    except BrokenPipeError:
        return 0
    except ModelError as exc:
        print("The model is not valid:", file=sys.stderr)
        for problem in exc.problems:
            print(f"  - {problem}", file=sys.stderr)
        return 2
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2
    except ApiError as exc:
        print(f"API error: {exc}", file=sys.stderr)
        return 1
    except KadiLabError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        return 130
