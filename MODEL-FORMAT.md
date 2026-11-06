# Model format reference

A model is one YAML entry file plus the files it `includes`. All included files are merged:
`settings` and `vocab` of the entry file win over included ones, `fieldsets` must be unique,
`collections` / `templates` / `records` / `links` are concatenated. Paths in `includes` are
relative to the including file; a directory or a glob (`areas/*.yaml`) is allowed.

```yaml
schema_version: 1
settings: {...}
includes: [vocab.yaml, fieldsets/core.yaml, ...]
vocab: {record_types: {...}, link_types: {...}, units: {...}, unit_terms: {...}}
fieldsets: {name: [field, ...], ...}
collections: [...]
templates: [...]
records: [...]
links: [...]
```

## settings

| Key | Default | Meaning |
|---|---|---|
| `name`, `version` | — | shown in reports and the state file |
| `namespace` | `""` | suffix appended to **every** identifier (collections, templates, records, references, and string values that equal a model identifier); use `-test1` style suffixes on the test instance |
| `timezone` | `UTC` | IANA zone used to expand a bare date (`2026-08-04` → `2026-08-04T00:00:00+02:00`) or a naive date-time; each expansion is reported as a notice |
| `default_visibility` | `private` | `private` (owner + roles), `public` (all logged-in users), `open` (anonymous) |
| `default_license` | `null` | license name for records without an explicit one (`CC-BY-4.0`, `CC0-1.0`, …) |
| `drop_empty_optional_fields` | `false` | if true, fields without a value and without `required` are left out of the record (less uniform, smaller records) |
| `strict_link_vocabulary` | `true` | link types must be defined in `vocab.link_types` |
| `enforce_type_prefix` | `true` | record identifiers must start with the prefix of their record type |
| `file_root` | `.` | base directory for relative `files[].path`, relative to the entry file |

## vocab

* `record_types`: `type: {prefix, description}`. The Kadi record `type` is free text (≤ 50
  chars, lower-cased); the prefix rule keeps identifiers self-describing.
* `link_types`: `name: {term, description, sources, targets}`. `name` becomes the Kadi link
  name, `term` the link's IRI. `sources` / `targets` list allowed record types (`"*"` = any)
  and are checked by `validate`.
* `units`: alias → canonical spelling (`degC: "°C"`, `ug/L: "µg/L"`). Applied to every field
  unit; each rewrite is a notice.
* `unit_terms`: canonical unit → QUDT IRI (documentation; Kadi stores units as text).

## fields

Used in `fieldsets` and in `templates[].fields`:

| Key | Notes |
|---|---|
| `key` | field name (English snake_case); required except for list item prototypes |
| `type` | `str` `int` `float` `bool` `date` `dict` `list` (default `str`; `dict` if `fields`/`use` present; `list` if `items` present) |
| `description` | human-readable label / help text shown in Kadi |
| `term` | ontology IRI of the field |
| `unit` | `int`/`float` only |
| `required`, `options`, `range: {min, max}`, `iri` | Kadi validation rules (`options` for str/int/float, `range` for int/float, `iri` for str); not allowed on `dict`/`list` |
| `default` | template value; used for a record when no value is given |
| `fields` | children of a `dict` |
| `items` | one or more item prototypes of a `list` (one prototype = homogeneous list; several = positional) |
| `use` | insert a fieldset: `- use: name` inline, or `{key: block, type: dict, use: name}` nested |

## templates

```yaml
templates:
  - identifier: tmpl-exp-xrd        # ≤ 50 chars, [a-z0-9-_]
    kind: record                    # record | extras
    title: Experiment – X-ray diffraction
    description: ...
    visibility: private
    record:                         # kind: record only — defaults for records made from it
      type: experiment
      title: "XRD – <sample id> – <date>"      # prefill shown in the web UI
      description: ""
      license: null
      tags: [experiment, xrd]
      collections: [area-4-functional-materials]     # new records join these
      record_links:                                  # predefined links to existing records
        - {direction: out, record: inst-xrd-rigaku-miniflex-01, type: measured_on}
      roles:                                         # granted on every new record
        - {group: ceet-lab-staff, role: editor}
    fields: [...]
    roles: [{group: ceet-data-stewards, role: admin}]   # roles on the template itself
```

`kind: extras` templates (UI building blocks) have only `fields`. Record templates compile to
Kadi `data = {identifier, title, description, type, license, tags, extras, collections,
record_links, roles}` with ids resolved at apply time.

## collections

```yaml
collections:
  - identifier: cat-instruments
    title: Catalogue – instruments
    description: ...
    tags: [catalogue]
    visibility: private
    parent: ceet                      # created first automatically
    record_template: tmpl-instrument  # default template when creating records inside
    roles: [{group: ceet-lab-staff, role: member}]
```

## records

```yaml
records:
  - identifier: smpl-tio2-sg-2026-001
    template: tmpl-sample-nanomaterial   # provides fields, type, tags, collections, roles
    title: ...
    type: sample                         # optional override of the template type
    description: markdown text
    license: CC-BY-4.0                   # optional; else template/default
    tags: [extra, tags]                  # merged with template tags
    visibility: private
    collections: [proj-x]                # added to the template's collections
    values: {...}                        # nested like the template fields
    extras: [...]                        # optional raw Kadi extras appended after the template fields
    files:
      - {path: demo/file.csv, name: optional-name.csv, description: ..., mimetype: text/csv}
    links:
      - {to: other-record, type: used}            # outgoing
      - {from: other-record, type: used}          # incoming
    roles: [{user: 42, role: collaborator}]
    drop_empty: false
```

Value rules: strings for `str`, integers for `int` (no booleans, no `"12"`), numbers for
`float`, booleans for `bool`, ISO 8601 date-times with offset for `date` (YAML dates /
naive times are expanded in `settings.timezone`), mappings for `dict`, lists for `list`.
`values.files: auto` fills a `files` list field (see the `data_files` fieldset) from the
attached files with name, SHA-256, size and media type. Unknown keys are errors.

## links

Global form, equivalent to the per-record `links`:

```yaml
links:
  - {source: exp-1, target: smpl-1, type: used}
  - {source: res-1, target: raw-1, type: was_derived_from, term: http://www.w3.org/ns/prov#wasDerivedFrom}
```

Direction: `source → target`. Duplicates (same source, target, type) are errors.

## What `validate` checks

Identifier syntax and length, title/description/type/tag lengths, visibility values,
duplicate identifiers, unknown references (templates, collections, parents, link ends),
hierarchy cycles, record type prefixes, link vocabulary and allowed end types, field
definitions (units/options/range/iri vs type, duplicate keys), every record's compiled
extras against the Kadi4Mat rules (types, required, options, range, IRI, dates, nesting),
file existence and name length. Problems are listed all at once with file and identifier.
