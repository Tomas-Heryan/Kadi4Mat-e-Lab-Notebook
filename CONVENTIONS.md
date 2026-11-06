# Conventions of the CEET model

## Identifiers

Lower-case ASCII, digits, `-` (and `_`), at most 50 characters including the namespace
suffix. Pattern: `<prefix><what>-<when or batch>-<sequence>`.

| Record type (`type`) | Prefix | Example |
|---|---|---|
| project | `proj-` | `proj-photocat-pharma-2026` (the demo uses the placeholder `proj-project`) |
| instrument | `inst-` | `inst-xrd-rigaku-miniflex-01` |
| equipment | `eqp-` | `eqp-furnace-nabertherm-l9-01` |
| material | `mat-` | `mat-ttip-sigma-205273-lot-mkcq1234` |
| sample | `smpl-` | `smpl-ww-ov-2026-08-03-eff` |
| sample-preparation | `prep-` | `prep-spe-photocat-r01-2026-08-04` |
| experiment | `exp-` | `exp-lcms-pharma-2026-08-05-s01` |
| method | `meth-` | `meth-lcms-pharma-ww-v03` |
| raw-data | `raw-` | `raw-xrd-tio2-c450-2026-07-27` |
| result | `res-` | `res-xrd-phases-tio2-c450-2026-07-27` |

Collections: `ceet` (root), `cat-*` (catalogues), `area-<n>-*`, `projects`, `proj-*`
(one per project, same identifier as the project cover record). Templates: `tmpl-*`
(record templates) and `xtr-*` (extras templates = UI building blocks).

Methods are versioned by identifier (`-v02`, `-v03`); a validated version is never edited —
a new record is created and linked with `supersedes`.

## Link vocabulary (PROV-O first)

| Link `type` | IRI (`term`) | From → to | Read as |
|---|---|---|---|
| `used` | prov:used | activity → sample, material, equipment, instrument, method, raw-data, result | the preparation/experiment consumed or employed it |
| `was_generated_by` | prov:wasGeneratedBy | sample, raw-data, result, material → activity | produced by |
| `was_derived_from` | prov:wasDerivedFrom | entity → entity | aliquot from sample, result from raw data, calcined from as-dried |
| `was_informed_by` | prov:wasInformedBy | activity → activity | an experiment that depended on an earlier preparation/experiment |
| `follows_plan` | prov:hadPlan | activity → method | protocol / SOP / method followed |
| `measured_on` | schema:instrument | experiment → instrument | the measuring device |
| `calibrated_with` | prov:used | experiment → material | reference / calibration material |
| `part_of_project` | schema:isPartOf | any → project | project membership (in addition to the collection) |
| `supersedes` | dcterms:replaces | method → method | newer version |
| `documented_in` | schema:subjectOf | instrument, equipment → method | manual / SOP |

Activities are `sample-preparation` and `experiment`; everything else is an entity. Write
links from the record that "knows" about the relation (the experiment knows its instrument,
the aliquot knows its parent).

## Metadata keys and blocks

English `snake_case` keys; the `description` of a field is the human-readable label. Common
blocks are fieldsets: `activity_header` (performed_by, started_at, ended_at, laboratory,
status), `asset_identity`, `maintenance_calibration`, `software_block`, `geo_origin`,
`ambient_conditions`, `quality_control`, `data_files`, `reagents_used`, `process_parameters`.
Technique blocks live in the area files (`xrd_measurement`, `chromatography_ms`, …) and are
added to the generic experiment / preparation cores by the specialised templates.

Identifier-valued strings (`instrument_identifier`, `method_identifier`, `sample_identifiers`,
`material_record`, …) duplicate the links on purpose: they survive in every export format,
links only in the JSON export. They are rewritten automatically when a namespace is used.

## Units, numbers, dates

* Units go into the field's `unit`, never into the key or the value. Canonical spellings:
  `°C`, `K`, `s`, `min`, `h`, `g`, `mg`, `µg`, `kg`, `L`, `mL`, `µL`, `m³`, `cm³`, `mm`, `µm`,
  `nm`, `Å`, `m²`, `m²/g`, `g/cm³`, `mg/L`, `µg/L`, `ng/L`, `µg/m³`, `mol/L`, `%`, `V`, `mV`,
  `kV`, `A`, `mA`, `W`, `kW`, `kWh`, `Hz`, `Pa`, `hPa`, `kPa`, `MPa`, `GPa`, `bar`, `mbar`,
  `W/m²`, `mW/cm²`, `µS/cm`, `mS/cm`, `rpm`, `°`, `L/min`, `mL/min`, `K/min`, `mm/min`,
  `mA/cm²`, `mV/s`, `eV`. Aliases (`degC`, `ug/L`, `hrs`, …) are normalised by `vocab.units`.
  QUDT IRIs for these are listed in `vocab.unit_terms`.
* Quantities with a unit are `float` (or `int` for counts); a value below LOQ is `null` with
  `below_loq: true` in result tables.
* Dates are ISO 8601 with an offset (`2026-08-04T10:00:00+02:00`); Kadi stores them in UTC.
  Bare dates are allowed in the YAML and expanded at 00:00 in `settings.timezone` — the
  validator says so for each one.

## Ontology terms

PROV-O for provenance (links, `started_at`, `ended_at`), schema.org for descriptive
properties (manufacturer, model, serialNumber, latitude, longitude, softwareVersion,
measurementTechnique, isPartOf, instrument), QUDT quantity kinds for physical quantities
(Temperature, Pressure, Time, Volume, Mass, Voltage, ElectricCurrent, Power, Energy,
Frequency, Irradiance, Wavelength, PH, RelativeHumidity, Density, Area), CHMO for techniques
(X-ray diffraction `CHMO_0000156`, scanning electron microscopy `CHMO_0000073`, electron
microscopy `CHMO_0000068`, LC-MS `CHMO_0000524`) and ENVO for environmental matrices.
Terms are optional; adding or correcting them in the template does not break existing
records.

## Visibility, roles, Zenodo

Everything is `private` by default and shared through group roles on collections and
records (`member < collaborator < editor < admin`). Confidential projects
(`data_management.confidentiality: confidential`) must not be published to Zenodo — Zenodo
stores files unencrypted even in restricted mode. Publication of public data goes through
the Kadi4Mat web UI (Publish → Zenodo); the RO-Crate it uploads is the same one
`export --format ro-crate` produces, so it can be checked and checksummed beforehand.
