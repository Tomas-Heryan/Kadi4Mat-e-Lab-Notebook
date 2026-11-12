# Kadi Lab Manager — CEET edition

Repository: https://github.com/Tomas-Heryan/Kadi4Mat-e-Lab-Notebook

Reproducible, declarative deployment of laboratory metadata into **Kadi4Mat**
(`https://kadi-test.vsb.cz`, later production) for the Centre for Energy and Environmental
Technologies, VŠB-TUO. You describe collections, templates, records, links and files in
versioned YAML; the tool compiles that into exact Kadi4Mat API payloads, validates them
**offline with the server's own rules**, shows a plan, applies only what is missing, and
can prove afterwards that the instance still matches the model.

Four scientific areas are modelled out of the box: 1 Environmental Electricity &
Engineering, 2 Applied Chemistry in Waste Management, Water and Air Pollution, 3 Environmental
Nanotechnology, 4 Development of New Functional Materials — 36 record templates and 26
reusable metadata blocks with 2 172 field definitions (units, ontology terms, controlled
options, required flags), plus a worked demo project that links devices, equipment,
materials, samples, sample preparations, experiments, raw data and results with PROV-O.

Placeholders to replace before a real deployment: `PROJECT` (project acronym; lower-case
`proj-project` in identifiers), `SCIENTIST_NAME` (every person field in the demo metadata)
and `TOKEN` in `.env` (the tool refuses to run while it is still there).

Security rules are built in and cannot be switched off: only `https://` hosts, TLS always
verified (an internal CA is given as a bundle file), the token only from the environment.

Kadi4Mat is developed by the Karlsruhe Institute of Technology (KIT); this repository is an
independent tool for using it at CEET and is not affiliated with or endorsed by KIT. See
*License, attribution and citation* below.


## Quick start (Windows, PowerShell, VS Code)

**One-file launcher.** On Windows the whole procedure — download of release `v1.0.1`, virtual
environment, installation, checks, access token, `doctor`, `plan` and `apply` of the demo —
can be run with a single script. Open
[`Kadi4Mat_Windows-1.6.cmd`](Kadi4Mat_Windows-1.6.cmd), choose *Download raw
file*, unblock the downloaded file (*Properties → Unblock*) and double-click it. The script
asks for the access token and for confirmation before anything is written to the server.
Deployments made with it get a timestamp at the end of all identifiers instead of the suffix
`-demo`. Details: [`WINDOWS-LAUNCHER.md`](WINDOWS-LAUNCHER.md).


The same steps by hand:
```powershell
cd C:\path\to\kadi_lab_manager_ceet
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1            # if blocked: Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
python -m pip install --upgrade pip
python -m pip install -e .              # installs kadi-apy, PyYAML (+ tzdata) and the kadi-lab-manager command
Copy-Item .env.example .env             # then replace TOKEN in .env with your access token (file is git-ignored)
kadi-lab-manager doctor                 # connection, token, TLS, Kadi4Mat version
kadi-lab-manager validate model\demo.yaml                 # offline
kadi-lab-manager plan     model\demo.yaml                 # dry run against kadi-test
kadi-lab-manager apply    model\demo.yaml --yes           # creates the demo (suffix -demo)
kadi-lab-manager snapshot model\demo.yaml                 # exports + drift report
kadi-lab-manager cleanup  --namespace=-demo --apply --yes  # removes the demo again
```

Without installing the package, `python -m kadi_lab_manager …` works the same once
`PYTHONPATH` points to `src` (VS Code does that for you, see `.vscode/settings.json`).

Open the folder in VS Code: `.vscode/launch.json` has one run configuration per command
(F5), `.vscode/tasks.json` has validate/compile/test tasks, and the Python extension picks
up `.venv` and `.env`. The tool also reads `.env` itself, so the plain terminal works too.

Create the personal access token in Kadi4Mat under *Settings → Access tokens* (it starts
with `pat_`). Scopes needed: `record.read record.create record.update record.link`,
`collection.read collection.create collection.update collection.link`, `template.read
template.create template.update`, `group.read`, `user.read`; add `record.permissions
collection.permissions template.permissions` if the model deploys roles, and
`record.delete collection.delete template.delete` (plus `misc.manage_trash` for `--purge`)
only on a token used for `cleanup` on the test instance. Never put the token in YAML, code
or Git — `.env` is git-ignored, and `doctor` tells you which user the token belongs to.

Linux / macOS: `python3 -m venv .venv && source .venv/bin/activate`, otherwise identical.

## Commands

| Command | What it does | Needs token |
|---|---|---|
| `doctor` | shows host, TLS mode, kadi-apy and Kadi4Mat version, token user, record visibility | yes |
| `validate MODEL` | loads the YAML (with includes), compiles every payload, runs the server rules offline, prints statistics and notices | no |
| `compile MODEL --out DIR` | writes the exact API payloads as JSON (review them, diff them in Git) | no |
| `plan MODEL` | compares model and instance; lists create / add / link / upload operations and metadata drift | yes |
| `apply MODEL [--update] [--yes]` | creates what is missing (idempotent); with `--update` also patches drifted metadata and files; never deletes | yes |
| `snapshot MODEL [--out DIR]` | downloads the JSON export of every model object into a time-stamped folder with a SHA-256 manifest and a drift report (exit 3 on drift) | yes |
| `export --record/--collection/--template ID --format json\|ro-crate\|rdf\|pdf\|qr\|json-schema\|shacl` | downloads one export; `.eln` RO-Crates are inspected and get a `.sha256` file | yes |
| `import-export FILE --out model.yaml [--namespace=-x] [--download-files]` | turns a Kadi JSON export (record or collection) back into a deployable model, optionally downloading and checksum-verifying its files | only with `--download-files` |
| `cleanup [--namespace=-x] [--apply --yes] [--purge] [--include-adopted]` | deletes objects *this tool created* on the instance, dry-run by default | yes |

Every online command writes a JSON report to `reports/`; `apply` and `cleanup` keep the
per-host state file `state/<host>.json` (identifier → id, created-by-tool flag, run log).

## How the model is organised

```
model/
  ceet.yaml                 entry point: settings + includes (production structure)
  demo.yaml                 same + the worked example project, namespace "-demo"
  vocab.yaml                record types & prefixes, link vocabulary (PROV-O), units
  fieldsets/core.yaml       reusable field blocks (activity header, asset identity, geo origin, QC, ...)
  collections.yaml          CEET root, catalogues, four areas, projects
  templates/core.yaml       core record templates: project, instrument, equipment, material,
                            sample, sample-preparation, experiment, method, raw-data, result
  areas/area-1..4*.yaml     technique blocks + specialised templates + UI building blocks
  projects/demo-*.yaml      the worked example (46 records, 86 links, 5 files)
data/demo/                  synthetic demo files (make_demo_data.py regenerates them)
```

A **template** declares fields once (type, unit, term, options, range, required, default,
nested `dict`/`list`), the record type it creates, default tags, the collections a new record
joins, predefined links and roles. A **record** names its template and gives `values` keyed
by field name — nested exactly like the fields — plus its collections, links and files:

```yaml
records:
  - identifier: exp-xrd-tio2-c450-2026-07-27
    template: tmpl-exp-xrd
    title: XRD – TIO2-SG-2026-001-C450 – 2026-07-27
    collections: [proj-project]
    values:
      experiment_class: characterisation
      technique: X-ray diffraction
      performed_by: SCIENTIST_NAME
      started_at: 2026-07-27T09:15:00+02:00
      status: completed
      instrument_identifier: inst-xrd-rigaku-miniflex-01
      xrd:
        radiation: Cu Kα
        scan: {two_theta_start: 10, two_theta_end: 80, step_size: 0.02, time_per_step: 1.0}
    files:
      - {path: demo/xrd_tio2-sg-2026-001-c450.xy, mimetype: text/csv}
    links:
      - {to: inst-xrd-rigaku-miniflex-01, type: measured_on}
      - {to: smpl-tio2-sg-2026-001-c450, type: used}
      - {to: meth-xrd-powder-phase-v02, type: follows_plan}
```

Unknown value keys, wrong types, values outside `options`/`range`, missing required values,
units on non-numeric fields, bare dates without time, identifiers that break the prefix
rule and links that violate the vocabulary are all reported by `validate` — before anything
touches the server. Full reference: `docs/MODEL-FORMAT.md`; naming, link and unit
conventions: `docs/CONVENTIONS.md`.

## What makes a deployment reproducible

* **One source of truth in Git.** The YAML model compiles deterministically to the payloads
  Kadi4Mat stores (`compile` writes them out, so a pull request shows the exact metadata
  change). Identifiers are the portable keys; numeric ids are instance-specific and live only
  in the state file.
* **Server rules offline.** `kadi_lab_manager/extras.py` is a port of Kadi4Mat 1.14's
  `ExtraSchema`, cross-checked against the real server code on 51 edge cases. What passes
  `validate` is what the server accepts and stores — including its normalisation (whitespace,
  `500` → `500.0`, dates to UTC, unit/`validation` clean-up).
* **Idempotent converge.** `apply` looks every object up by identifier and creates only what
  is missing; a second run makes zero write requests. Drift (someone edited a record in the web
  UI) is listed by `plan` and only fixed with an explicit `--update`. Nothing is ever deleted
  by `apply`.
* **Verified files.** Uploads send `Kadi-MD5-Checksum` per chunk, and the stored checksum
  (MD5, or the composite `md5-of-md5s-N` for chunked uploads > 50 MB) is recomputed locally and
  compared; raw-data records keep SHA-256 per file (`files: auto`) for Zenodo-grade integrity.
* **Evidence.** JSON reports per run, a state file per host, `snapshot` for a SHA-256
  manifested copy of every object's export plus a drift verdict, `export` for `.eln` RO-Crates
  (the format the Zenodo plugin uploads) with inspection and checksum.
* **Round trip.** `import-export` rebuilds a model (with files) from any Kadi JSON export, so a
  project can be re-created on another instance or restored from a Zenodo deposit.
* **Namespaces.** `settings.namespace: "-test1"` suffixes every identifier (also inside
  identifier-valued metadata strings), so trial deployments on kadi-test can be removed
  completely with `cleanup --namespace=-test1`.

## Roles, groups and the web UI

Templates may carry `record.roles` (`group: <identifier>` or `user: <id>`) and
`record.record_links`; collections, records and templates may carry `roles`. Groups must
already exist in Kadi4Mat (IT/admin task) — if a group is missing, the plan warns and skips
that role, nothing else fails. Records created by scientists *in the web UI* from a deployed
record template are automatically placed in the right collections, pre-linked to the
device/equipment and shared with the group — that is the mechanism that makes the structure
usable without the CLI.

## Testing without a token

`tests/mock_kadi.py` is an in-memory HTTPS mock of the Kadi4Mat API (self-signed localhost
certificate in `tests/fixtures`, used as the CA bundle so TLS verification stays on). The test
suite runs the whole lifecycle against it: plan → apply (119 objects, 86 links, 5 files) →
idempotent re-run → drift → `--update` → snapshot → export → import → cleanup.

```powershell
python -m unittest discover -s tests -v
python tests\mock_kadi.py 8443          # or run the CLI against the mock by hand:
$env:KADI_URL="https://127.0.0.1:8443"; $env:KADI_TOKEN="mock"; $env:KADI_CA_BUNDLE="$PWD\tests\fixtures\mock-kadi-cert.pem"
```

## Known limits

* Group and user roles are only granted when the group exists; the tool never creates groups.
* Records are never deleted by `apply`; removing a record from the model leaves it on the
  instance (use `cleanup` on test deployments, or delete manually in production).
* Ontology IRIs (`term`) are taken from PROV-O, schema.org, QUDT and a few CHMO/ENVO classes
  that are well established; review them with the domain experts before production use.
* The Zenodo publication itself is done in the Kadi4Mat web UI (Publish → Zenodo); this tool
  prepares and verifies the content and can export the identical RO-Crate.

## License, attribution and citation

This project is licensed under the **Apache License 2.0** (`LICENSE`), the same license as
Kadi4Mat and kadi-apy, and ships a `NOTICE` file that must stay with any copy or fork:

* `src/kadi_lab_manager/extras.py` is a **derivative work of Kadi4Mat**
  (`kadi/modules/records/extras.py`, Copyright 2020 Karlsruhe Institute of Technology,
  Apache-2.0). The file keeps KIT's copyright line and lists the modifications in its header.
* `tests/mock_kadi.py` re-implements the behaviour of the Kadi4Mat HTTP API for testing and
  `docs/KADI4MAT-EXPORT-REFERENCE.md` describes Kadi4Mat's export formats; both were written
  from the Kadi4Mat source code and documentation.
* [kadi-apy](https://gitlab.com/iam-cms/kadi-apy) (KIT, Apache-2.0) is a runtime dependency.
* The template structure was informed by the public KNMFi template library (KIT); none of its
  content is included.

If this tool or the metadata model supports a publication, please cite Kadi4Mat:

> Brandt, N., Griem, L., Herrmann, C., Schoof, E., Tosato, G., Zhao, Y., Zschumme, P., &
> Selzer, M. (2021). Kadi4Mat: A Research Data Infrastructure for Materials Science.
> *Data Science Journal*, 20(1), 8. https://doi.org/10.5334/dsj-2021-008

and this repository via `CITATION.cff` (GitHub shows a "Cite this repository" button for it).

Author and maintainer: **Tomas Heryan**, Data Steward & Open Science, Centre for Energy and
Environmental Technologies (CEET), VSB - Technical University of Ostrava, Ostrava, CZ —
tomas.heryan@vsb.cz, ORCID [0000-0003-2027-7149](https://orcid.org/0000-0003-2027-7149).

`tests/fixtures/mock-kadi-key.pem` is a throw-away private key for the localhost test server
only; it protects nothing and is committed on purpose.

## Layout

```
src/kadi_lab_manager/   extras.py (server rules), model.py (YAML), compile.py (payloads),
                        client.py (kadi-apy based HTTPS client), deploy.py (plan/apply),
                        export.py, cleanup.py, state.py, report.py, config.py, cli.py
model/                  the CEET model (see above)
tests/                  mock_kadi.py, test_kadi_lab_manager.py, fixtures/
docs/                   MODEL-FORMAT.md, CONVENTIONS.md, KADI4MAT-EXPORT-REFERENCE.md
LICENSE, NOTICE, CITATION.cff
```
