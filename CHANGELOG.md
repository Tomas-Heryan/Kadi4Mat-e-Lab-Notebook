# Changelog

## 1.0.1 — 2026-11-06

* Demo metadata anonymised for publication: project acronym → placeholder `PROJECT`
  (`proj-project`), all person fields → `SCIENTIST_NAME`; `.env.example` ships `TOKEN`, which
  `load_config` rejects until replaced.
* Repository URL, Apache-2.0 `LICENSE`/`NOTICE`, `CITATION.cff` and maintainer data added.

## 1.0.0 — 2026-11-05

First release of the CEET edition.

* Declarative YAML model with includes, fieldsets, deployment namespaces and a controlled
  link vocabulary (PROV-O).
* Offline validation with a verified port of Kadi4Mat 1.14's extras rules.
* `plan` / `apply` converge loop (create only, `--update` for drift), per-host state file,
  JSON reports, checksum-verified uploads (`Kadi-MD5-Checksum`, composite checksums for
  chunked uploads).
* `snapshot`, `export` (json, ro-crate/.eln with inspection, rdf, pdf, qr, json-schema,
  shacl), `import-export` with file download, `cleanup` restricted to tool-created objects.
* CEET domain model: 10 core templates, 4 area packs (26 specialised templates + 26 UI
  blocks, 2 172 field definitions), worked cross-area demo project with 46 records, 86 links
  and 5 synthetic data files.
* HTTPS-only client on kadi-apy 0.51 (TLS always verified, custom CA bundle supported).
* TLS mock server and end-to-end tests that need no real instance or token.
* Licensed under Apache-2.0 with a NOTICE file: `extras.py` is a derivative work of Kadi4Mat
  (Karlsruhe Institute of Technology, Apache-2.0); kadi-apy is used as a dependency.

Compared with the earlier `kadi_manager.py` scripts: correct API payloads for child
collections, memberships and links (`record_to`), no `--no-verify-tls` switch, dates always
time-zone aware, nested metadata supported, templates carry collections / links / roles.
