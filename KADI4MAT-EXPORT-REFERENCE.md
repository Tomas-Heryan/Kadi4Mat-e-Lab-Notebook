# Kadi4Mat JSON exports — complete metadata reference

> Provenance: written from the source code of Kadi4Mat 1.14.0 (Copyright 2020 Karlsruhe Institute of Technology, Apache License 2.0, https://gitlab.com/iam-cms/kadi) and kadi-apy 0.51.0 (same author and license), plus the public documentation at https://kadi4mat.readthedocs.io. Kadi4Mat is a KIT project; this document is an independent description, not KIT documentation.

Derived from the Kadi4Mat server source (PyPI package `kadi` 1.14.0, the current release; files `kadi/modules/records/{export,extras,schemas,models,imports}.py`, `kadi/modules/collections/{export,schemas}.py`, `kadi/modules/templates/{export,schemas,models,imports}.py`, `kadi/lib/export.py`, `kadi/plugins/zenodo/*`) and from `kadi-apy` 0.51.0. The published HTTP-API reference only says "Return the record"; the shapes below are what the code actually produces. Every rule in §3 was verified by running Kadi's own `ExtraSchema` against 51 edge cases and the worked examples (0 discrepancies).

Worked example files (generated to match the server byte-for-byte in structure): `record_export_*.json`, `extras_export_{standard,plain}_*.json`, `collection_export_*.json`, `template_export_*.json`, `template_export_json-schema_*.json`, `ro-crate-metadata_*.json`, `api_record_revision_example.json`.

## 1. Which exports exist

| Resource | `GET /api/v1/<res>/{id}/export/<type>` | Types | File ext |
|---|---|---|---|
| record | `records/{id}/export/…` | `json`, `rdf` (Turtle), `pdf`, `qr` (PNG), `ro-crate` | json, ttl, pdf, png, **eln** |
| record extras only | `records/{id}/extras/export/json` | `json` (format `standard` or `plain`) | json |
| collection | `collections/{id}/export/…` | `json`, `rdf`, `qr`, `ro-crate` | json, ttl, png, eln |
| template | `templates/{id}/export/…` | `json`, `json-schema`, `shacl` (Turtle) | json, json, ttl |

All take `?filter=<URL-encoded JSON>`; scope `record.read` (resp. collection/template). If the token lacks `user.read`, the server forces `filter.user = true` (no creator data). Serialisation is `json.dumps(ensure_ascii=False, sort_keys=True, indent=2)`: keys alphabetically sorted, UTF-8, 2-space indent.

Export filter keys (defaults): `user: false` (exclude creator info), `links: false | "in" | "out" | true` (exclude incoming/outgoing/all record links), `extras: {}` (mask of keys to exclude, nested, list indices as strings from "0"), `propagate_extras: false` (apply mask to linked records too), `export_data: ["json","rdf"]` (which per-record files go into an RO-Crate; `pdf` may be added), `metadata_only: false` (RO-Crate: return only `ro-crate-metadata.json`). Collections add `records: false` (exclude records), `children: false` (include records of child collections), `hierarchy: false` (keep child-collection directories in the crate). Extras export adds `format: "standard" | "plain"`.

## 2. Record JSON export — field by field

Top level (alphabetical, as emitted):

| Key | Type | Notes |
|---|---|---|
| `created_at` | string | ISO 8601 UTC with microseconds, e.g. `2026-08-04T06:20:31.905512+00:00` |
| `creator` | object \| absent | `{id, displayname, orcid}`; `orcid` may be `null`; absent when `filter.user=true` or no `user.read` scope |
| `description` | string | Markdown, may be `""`, ≤ 50 000 chars |
| `extras` | array | see §3 |
| `files` | array | active files, newest `last_modified` first; see 2.1 |
| `id` | integer | database id (instance-specific, not portable) |
| `identifier` | string | `^[a-z0-9-_]+$`, ≤ 50, unique per instance (portable key) |
| `last_modified` | string | ISO 8601 UTC |
| `license` | string \| null | the license *name* (SPDX-like, e.g. `CC-BY-4.0`); title/url not exported |
| `links` | array | record links, newest first; omitted entirely when `filter.links=true`; see 2.2 |
| `tags` | array[string] | lower-cased, whitespace-normalised, sorted |
| `title` | string | ≤ 150, whitespace-normalised |
| `type` | string \| null | ≤ 50, lower-cased (`sample-preparation`); free text, not an enum |

Deliberately **not** exported: `visibility`, `state`, `plain_description`, `_links`, `_actions`, collection memberships, roles/permissions, revisions, uploads.

### 2.1 `files[]`

`checksum` (string|null), `created_at`, `creator` (same rules as above), `description` (string, `""` if none), `id` (UUID v4 string — stable identity of the file), `last_modified`, `magic_mimetype` (detected from content, may be null), `mimetype` (declared, `^[a-z]+/[a-z0-9-+.]+$`), `name` (≤ 256, unique within the record), `size` (bytes). Not exported: `storage_type`, `state`.

Checksum semantics: direct upload (file ≤ 50 MB) → plain MD5 of the content; chunked upload (> 50 MB, 10 MB chunks) → `md5(concat(md5 of each chunk)) + "-" + chunk_count`, e.g. `3c2e…3f40-7` (S3-ETag style, **not** an MD5 of the file). Kadi never stores SHA-256 — if you need it, put it in the extras of the record.

### 2.2 `links[]`

Each link: `created_at`, `creator`, `id` (link id, ≠ record id), `last_modified`, `name` (≤ 150, whitespace-normalised), `term` (IRI string or `null`, ≤ 2048), and exactly one of `record_to` (outgoing link, this record is the subject) or `record_from` (incoming link). The nested record is a full record object **without** `files` and `links` (so: `created_at, creator, description, extras, id, identifier, last_modified, license, tags, title, type`). Only links whose other record the exporting user may read are included. Direction convention used by the RDF export: `record_from` = `rdf:subject`, `record_to` = `rdf:object`, link `term` = `rdf:type` of the link.

### 2.3 What the API accepts back (round-trip)

There is **no import endpoint in the HTTP API**; JSON import exists only in the web UI (`Records → New → Import`, max 10 MB, accepts a record export, a record template export, or an extras template export; values are taken as prefill). To reproduce a record programmatically from its export you map: `identifier, title, type, description, license, visibility (default private), tags, extras` → `POST /api/v1/records` (201; 409 on identifier clash); each `links[]` → `POST /api/v1/records/{from}/records` with `{"record_to": {"id": …}, "name": …, "term": …}` (201; 409 duplicate or self-link); memberships → `POST /api/v1/collections/{id}/records` `{"id": record_id}` or `POST /api/v1/records/{id}/collections` `{"id": collection_id}` (201/409); files → the upload protocol (`POST /records/{id}/uploads` → `PUT …/uploads/{uuid}` [chunks] → `POST …/finish`; kadi-apy implements it). Unknown JSON fields are silently ignored by every schema (`unknown = EXCLUDE`) — a typo in a field name therefore does not fail, it is just dropped.

## 3. Extras — the metadata type system

An extra is an object; an extras value is an **array** of extras (order is preserved and meaningful).

| Property | Rule |
|---|---|
| `type` | required; exactly one of `str`, `int`, `float`, `bool`, `date`, `dict`, `list` (case-sensitive; `STR` is rejected) |
| `key` | required except for items inside a `list`; whitespace-normalised (`" Sample  ID "` → `"Sample ID"`); must be unique within its array; keys given on list items are silently dropped |
| `value` | per type below; defaults to `null` (literal types) or `[]` (`dict`/`list`); strings are stripped and `""` becomes `null` |
| `unit` | **only** `int`/`float`; for those two it is *always present* in stored/exported data (`null` if unset); on any other type a non-null unit is a 400 |
| `description` | optional string, stripped, must be non-empty if present |
| `term` | optional IRI (no `<>" {}\|\^\`` and no space), stripped |
| `validation` | optional object; not allowed on `dict`/`list`; dropped when empty |

Value rules (as enforced by `_validate_extra_value`):

* `str` — must be a JSON string.
* `int` — must be a JSON integer (`true/false` are rejected, `7.0` is rejected), within ±(2⁵³−1) so it stays exact in JavaScript/Elasticsearch.
* `float` — integer or float accepted, stored as float (`500` → `500.0`); `NaN`/`±inf` rejected.
* `bool` — JSON boolean only.
* `date` — ISO 8601 **date-time**: `YYYY-MM-DD[T ]HH:MM[:SS[.ffffff]][Z|±HH[:MM]]`. A bare date `2026-08-04` is rejected. Stored normalised to UTC: `2026-08-04T08:15:00+02:00` → `2026-08-04T06:15:00+00:00`. A value **without** offset is interpreted in the server's local time zone — never send naive timestamps.
* `dict` — `value` is an array of extras with keys (an ordered object).
* `list` — `value` is an array of extras **without** keys (items may be of mixed types, including nested dicts).

`validation` sub-keys: `required: true` (value must not be null — not enforced inside templates), `options: [...]` (distinct enumeration, same type as the value; `str`/`int`/`float` only), `range: {min, max}` (inclusive, either side may be `null`; `int`/`float` only; `min ≤ max`), `iri: true` (value must be a valid IRI; `str` only; combined with `options`, the options are IRI-checked too). `required: false`, `iri: false`, empty `options`, and `range` with both bounds null are removed on save.

Normalisation summary — what you send vs. what is stored and later exported:

| Sent | Stored |
|---|---|
| `{"key":"x","type":"int","value":1}` | `{"key":"x","type":"int","unit":null,"value":1}` |
| `{"key":"x","type":"float","value":500,"unit":" mL "}` | `{"key":"x","type":"float","unit":"mL","value":500.0}` |
| `{"key":"x","type":"str","value":"  "}` | `{"key":"x","type":"str","value":null}` |
| `{"key":"x","type":"date","value":"2026-08-04T08:15:00+02:00"}` | `{"key":"x","type":"date","value":"2026-08-04T06:15:00+00:00"}` |
| `{"key":"d","type":"dict"}` | `{"key":"d","type":"dict","value":[]}` |
| `{"key":"x","type":"str","value":"a","validation":{"required":false}}` | `{"key":"x","type":"str","value":"a"}` |
| `{"key":"x","type":"str","value":"a","foo":1}` | `{"key":"x","type":"str","value":"a"}` (unknown property dropped) |

Searching by extras (`GET /api/v1/records?extras=<JSON array>`): each query has `key` (nested keys as `a.b`, list items by 1-based index), `type` ∈ `str | numeric | bool | date`, and `str` / `numeric: {min,max,unit}` / `bool` / `date: {min,max}` restrictions, chained with `link: "and"|"or"`. Units are matched exactly, which is one more reason to standardise unit strings.

### 3.1 Extras export (`/records/{id}/extras/export/json`)

`format=standard` → the bare extras array exactly as in the record export. `format=plain` → a plain JSON object: `dict` → object, `list` → array, literals as-is; **types, units, terms, descriptions and validation are lost** (see `extras_export_plain_*.json`). The plain form is what the Zenodo plugin reads from its "custom metadata" field, and what `kadi-apy`'s `conversion.json_to_kadi()` reverses (guessing types; strings that parse as ISO dates become `date`).

## 4. Collection JSON export

`created_at, creator, description, id, identifier, last_modified, records, tags, title` — same rules as records (no `visibility`, no `parent`, no `record_template`). `records` is an array of **full record exports** (each with its own `files` and `links`), newest-modified first; by default only direct members, with `children: true` also records of all accessible child collections (flattened — the JSON export has no hierarchy; only the RO-Crate keeps directories). A record in several collections appears once per collection export. The parent/child structure itself must be read from the API (`GET /collections/{id}/collections`, `_links.parent`).

## 5. Template JSON export

Common envelope: `created_at, creator, data, description, id, identifier, last_modified, title, type` where `type` is `record` or `extras`.

**`type: "extras"`** — `data` is an extras array validated in *template mode* (values may stay `null` even when `required`).

**`type: "record"`** — `data` is an object with *all* of these keys (defaults are filled in on save):

| Key | Content |
|---|---|
| `identifier` | prefilled identifier, may be `""` |
| `title`, `description` | prefills, may be `""` |
| `type` | record type prefill or `null` |
| `license` | license name or `null` |
| `tags` | array of tag names |
| `extras` | extras array (template mode) |
| `collections` | array of **collection ids** the new record is added to |
| `record_links` | array of `{"direction": "out"\|"in", "record": <record id>, "name": "...", "term": <IRI\|null>}` — predefined links to existing records (e.g. the instrument or the SPE manifold) |
| `roles` | array of `{"subject_type": "user"\|"group", "subject_id": <id>, "role": "member"\|"collaborator"\|"editor"\|"admin"}` granted on each new record |

These last three are what make "the record is born already linked to its device, in its project collection, visible to the right group" possible from the web UI. Collections additionally carry a load-only `record_template` (template id) which the UI uses when creating a record inside that collection; it is not exported.

### 5.1 JSON Schema export (templates)

Draft 2020-12, `type: object`, `properties` keyed by extra key, plus the non-standard `propertiesOrder` (Kadi preserves order) and `required`. Type mapping: `str` → `{"type":"string","minLength":1}`, `int` → `integer`, `float` → `number`, `bool` → `boolean`, `date` → `{"type":"string","format":"date-time"}`, `dict` → `object` with nested `properties/propertiesOrder/required`, `list` → `array` with `prefixItems` (tuple validation, one schema per present item). Per field: `default` (from `value`), `description`, `enum` (from `options`), `minimum`/`maximum` (from `range`), and the custom `unit: {"type":"string","minLength":1,"default": <unit>}`. `term` and `iri` are **not** representable in JSON Schema (lost). Kadi can import such a schema back as a template (and `kadi-apy misc import-json-schema`), so JSON Schema is a reasonable interchange for *structure*, not for semantics.

### 5.2 SHACL export (templates)

A `sh:NodeShape` per template (and per nested `dict`/`list`, via `sh:qualifiedValueShape` + `owl:imports`), one `sh:property` per extra with `sh:name`, `sh:order`, `sh:maxCount 1`, `sh:path` = the extra's `term` IRI when present (otherwise a Kadi-instance IRI `…/templates/{id}#key`), `sh:datatype` (`xsd:string|integer|float|boolean|dateTime`, `xsd:anyURI` when `iri`), `sh:defaultValue`, `sh:minCount 1` for required, `sh:in` for options, `sh:minInclusive`/`sh:maxInclusive` for range, `sh:description`. SHACL keeps the terms — it is the semantics-preserving template interchange. Units are not expressed.

## 6. RO-Crate (`.eln`) export — what a Zenodo deposit contains

ZIP layout for a record (root directory = record identifier):

```
<identifier>/
  ro-crate-metadata.json
  <identifier>.json        # the record JSON export (§2), default
  <identifier>.ttl         # the RDF export, default   (export_data filter)
  <identifier>.pdf         # only if export_data includes "pdf"
  files/<file name>        # every active file; "/" in names replaced by "_"
```

For a collection: root = collection identifier; without `hierarchy` all records sit directly under the root, with `children + hierarchy` each collection level has `records/<record identifier>/` and `collections/<child identifier>/…`. Records shared by several collections are included once and referenced from each dataset's `hasPart`.

`ro-crate-metadata.json` (`@context` `https://w3id.org/ro/crate/1.1/context`, following the ELN Consortium file-format spec):

* `ro-crate-metadata.json` entity: `CreativeWork`, `conformsTo` RO-Crate 1.1, `dateCreated`, `sdPublisher → https://kadi.iam.kit.edu` (an `Organization` entity named "Kadi4Mat"), `version` = Kadi version.
* Root `./` `Dataset`: `name`, `datePublished`, generic `description`/`license` text, `genre: "record"|"collection"`, `hasPart` → record datasets (and child-collection datasets).
* One `Dataset` per record (`@id` `./<dir>/`): `identifier`, `name` (title), `dateCreated`, `dateModified`, `keywords` (tags comma-joined), `author → Person` (`@id` = `https://orcid.org/<orcid>` if the creator has an ORCID, else the Kadi user URL; omitted with `user: true`), `description → TextObject` (`encodingFormat: text/markdown`), `license → CreativeWork` (`identifier` = license name, `name`, `url`), `hasPart` → the export files and the data files, and **`variableMeasured`** → one `PropertyValue` per *leaf* extra with a non-null value: `propertyID` = dotted key path (`cartridge.sorbent_mass`, list items by 0-based index `elution_steps.0.volume`), `value`, `unitText` (unit), `identifier` (the `term` IRI), `description`, `minValue`/`maxValue` (range). Booleans, types and `options` are not expressed here — they survive only in `<identifier>.json`.
* One `File` entity per data file: `identifier` (file UUID), `name`, `contentSize` (string), `encodingFormat` (declared mimetype), `dateCreated`, `dateModified`, `author`, optional `description → TextObject`. No checksum is written into the crate (the JSON export inside it carries the Kadi checksum).
* Record **links are not part of the crate graph**; they are only inside each `<identifier>.json` (`links[]`). `kadi-apy misc import-eln` uses exactly that file to restore `extras`, `license`, `type` and the links between records contained in the same crate.

RDF (`.ttl`) mapping in one paragraph: record = `schema:Dataset` with `schema:identifier/name/dateCreated/dateModified/additionalType(type)/description/keywords/author/license`; extras hang off a blank node via `rdfs:isDefinedBy`, each predicate = the `term` IRI if present else `<record URL>#<key>`; `int`/`float` values become `schema:QuantitativeValue` with `schema:value` and `schema:unitText`; `date` is `xsd:dateTime`; `str` with `iri: true` becomes a URI reference; nested dicts are nested blank nodes, lists are RDF collections; files are `schema:MediaObject isPartOf record`; each link is a node with `rdf:subject` (record_from), `rdf:object` (record_to), `schema:name` and `rdf:type` = link `term`.

## 7. Revisions (API, not export)

`GET /api/v1/records/{id}/revisions` items: `id`, `timestamp`, `user`, `object_id`, `data`, `diff`, `_links{self,parent,child}`. `data` holds the revisioned columns: `identifier, title, type, description, extras, visibility, state, license (name), tags (names), links_to[{id, record_to_id, name, term}], linked_from[{id, record_from_id, name, term}]`. `diff` maps each changed key to its **previous** value. Files have their own revisions (`name, description, size, mimetype, checksum, state`). Collections revision `identifier, title, description, visibility, state, tags, record_template[id]` (the parent link is **not** revisioned); templates revision `identifier, title, description, visibility, data, state`. Every API/CLI write creates a revision — reproducibility auditing comes for free, and your tooling should avoid no-op PATCHes that would only add noise revisions.

## 8. Zenodo publication (built-in plugin, InvenioRDM API)

What leaves Kadi when a user clicks *Publish → Zenodo*: a draft record is created with `metadata = {resource_type: dataset, title, publication_date: today, creators: [{person_or_org: {given_name, family_name, identifiers: [orcid]}}] (from the publishing user's display name), description: record description rendered to HTML, rights: [{id: <record license name lower-cased, if Zenodo knows it, else "cc-by-4.0">}], subjects: tags, publisher: "Zenodo"}`; the "Customize import metadata" extras (plain JSON) are merged — key `metadata` extends/overrides the block above, key `community` requests a community review, any other top-level keys are passed to InvenioRDM as-is (e.g. `access`, `custom_fields`). Then **one file** `<identifier>.zip` is uploaded: the RO-Crate of §6, with export filter default `{"user": true}` (no creator data unless the user changes the filter). The Kadi record/collection itself is not altered; the DOI is not written back. So what Zenodo's machine readers see is: InvenioRDM metadata + the crate's `ro-crate-metadata.json` (`variableMeasured` with units and term IRIs) + the Kadi JSON/TTL + raw files.

## 9. Limits and constraints (server-enforced)

identifier `^[a-z0-9-_]+$` ≤ 50 (lower-cased on save) · title ≤ 150 · description ≤ 50 000 · record `type` ≤ 50 (lower-cased) · tag ≤ 50 (lower-cased) · link `name` ≤ 150 · link `term` ≤ 2048 · file `name` ≤ 256, `mimetype` ≤ 256 and `^[a-z]+/[a-z0-9-+.]+$` · integer extras ±(2⁵³−1) · uploads: direct ≤ 50 MB, otherwise chunked in 10 MB chunks · UI import file ≤ 10 MB · visibility `private` (default) | `public` (all logged-in users) | `open` (anonymous) · roles record/collection `member < collaborator < editor < admin`, template/group `member < editor < admin` · built-in licenses: 111 Open Definition names (`CC-BY-4.0`, `CC-BY-SA-4.0`, `CC0-1.0`, `CC-BY-NC-4.0`, `ODbL-1.0`, `MIT`, …).

## 10. Consequences for our reproducible toolkit

1. The record JSON export is the canonical, lossless machine-readable form (extras with types/units/terms/validation, links with terms, file checksums). Our YAML/JSON model should therefore be a thin, human-friendly layer that compiles **to exactly this structure**, and our offline validator must apply the server rules of §3 (ported and verified: `kadi_extras_schema.py`).
2. Dates must always be written with a time-zone offset; the toolkit should refuse naive timestamps or expand a bare date with an explicit lab time zone and say so.
3. Units go into `unit`, never into the key or the value; standardise unit spellings (search matches them exactly) and attach `term` IRIs for keys and QUDT/ontology IRIs where they exist.
4. Links need a controlled vocabulary of `name` + `term` (e.g. PROV-O `used`, `wasGeneratedBy`, `wasDerivedFrom`, `wasAssociatedWith`); the crate does not export links, so the JSON inside it is what preserves the graph.
5. Record templates can carry `collections`, `record_links` and `roles` — the toolkit should generate templates with these filled (project collection id, device/equipment link, lab group role) so that records created by scientists in the UI are automatically placed, linked and shared.
6. Identifiers are the portable keys; numeric ids are instance-specific. Everything the toolkit writes should be keyed by identifier (idempotent lookups via `GET …/identifier/{identifier}`), and the state file should map identifier → id per instance (kadi-test vs. production).
7. Kadi stores MD5-style checksums only; for data integrity across Zenodo we keep SHA-256 in a `files`-oriented extra (dict per file: name, sha256, size) and verify after upload.
8. There is no API import; "re-deploy from export" is a mapping we implement ourselves (§2.3), which also gives us a tested disaster-recovery path from a Zenodo-deposited `.eln`.
