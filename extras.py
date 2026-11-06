# Copyright 2020 Karlsruhe Institute of Technology
# Modifications copyright 2026 Centre for Energy and Environmental Technologies (CEET),
# VSB - Technical University of Ostrava
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# This file is a derivative work of kadi/modules/records/extras.py from Kadi4Mat
# release 1.14.0 (https://gitlab.com/iam-cms/kadi). Modifications (CEET, 2026):
#   * re-implemented as a standalone module without Flask, SQLAlchemy, marshmallow
#     and Flask-Babel (plain Python, no application context needed);
#   * ExtraSchema / _ValidationSchema / _validate_extra_value turned into the
#     functions load_extras / _load_validation / _apply_validation / _validate_extra_value
#     with the same rules, normalisation and error structure;
#   * date-time parsing re-implemented with the pattern marshmallow uses on the server,
#     plus an explicit `assume_timezone` instead of the server's implicit local zone
#     (naive values are rejected unless a zone is given);
#   * error messages are collected in English only (no translation layer);
#   * extras_to_plain_json and remove_extra_values ported unchanged in behaviour.
"""Standalone port of Kadi4Mat's extra-metadata validation (kadi 1.14.0).

Reproduces ``kadi.modules.records.extras.ExtraSchema`` (and its nested
``_ValidationSchema`` / ``_validate_extra_value``) without Flask, SQLAlchemy or
marshmallow, so that YAML/JSON metadata can be validated and normalised *offline*
exactly the way the server does it before anything is sent to the API.

The behaviour mirrors the server:

* allowed types: str, int, float, bool, date, dict, list
* ``key`` is whitespace-normalised, required (except inside ``list`` values), unique
  within one array
* string values are stripped; empty strings become ``null``
* ``int`` must be a real integer (``bool`` is rejected) within +-(2**53 - 1)
* ``float`` accepts int or float, converts to float, rejects NaN/inf
* ``date`` must be an ISO 8601 date-time (``YYYY-MM-DD[T ]HH:MM[:SS[.ffffff]][tz]``);
  it is stored normalised to UTC (``2026-08-04T06:00:00+00:00``). A naive value is
  interpreted in the *server's* local time zone, which is why this port refuses naive
  values unless ``assume_timezone`` is given.
* ``unit`` only for int/float (always present for those two types, ``null`` if unset)
* ``validation``: required / options (str,int,float) / range (int,float) / iri (str);
  not allowed on dict/list; empty instructions are dropped
* ``description`` and ``term`` (IRI) are optional
* ``is_template=True`` skips the "required" check, as templates carry no values
"""
from __future__ import annotations

import math
import re
from datetime import datetime, timezone, tzinfo
from typing import Any

EXTRAS_MAX_INTEGER = 2**53 - 1
EXTRAS_MIN_INTEGER = -EXTRAS_MAX_INTEGER
EXTRA_TYPES = ("str", "int", "float", "bool", "date", "dict", "list")
NESTED_TYPES = ("dict", "list")
INVALID_IRI_CHARS = '<>" {}|\\^`'

# Same pattern marshmallow.utils.from_iso_datetime uses on the server.
_ISO8601_DATETIME_RE = re.compile(
    r"(?P<year>\d{4})-(?P<month>\d{1,2})-(?P<day>\d{1,2})"
    r"[T ](?P<hour>\d{1,2}):(?P<minute>\d{1,2})"
    r"(?::(?P<second>\d{1,2})(?:\.(?P<microsecond>\d{1,6})\d{0,6})?)?"
    r"(?P<tzinfo>Z|[+-]\d{2}(?::?\d{2})?)?$"
)
_ISO8601_DATE_RE = re.compile(r"^(?P<year>\d{4})-(?P<month>\d{1,2})-(?P<day>\d{1,2})$")


class ExtrasValidationError(ValueError):
    """Raised with a nested ``messages`` structure like the server's 400 response."""

    def __init__(self, messages):
        super().__init__(_flatten_messages(messages))
        self.messages = messages


def _flatten_messages(messages, prefix=""):
    lines = []
    if isinstance(messages, dict):
        for key, val in messages.items():
            lines.append(_flatten_messages(val, f"{prefix}{key}."))
    elif isinstance(messages, list):
        for val in messages:
            lines.append(_flatten_messages(val, prefix))
    else:
        lines.append(f"{prefix.rstrip('.')}: {messages}")
    return "; ".join(line for line in lines if line)


def normalize(value):
    return " ".join(value.split()) if isinstance(value, str) else value


def strip(value):
    return value.strip() if isinstance(value, str) else value


def pretty_type_name(value_type):
    return {"str": "string", "int": "integer", "bool": "boolean", "dict": "dictionary"}.get(
        value_type, value_type
    )


def is_nested_type(value_type):
    return value_type in NESTED_TYPES


def validate_iri(value):
    for char in INVALID_IRI_CHARS:
        if char in value:
            raise ValueError("Not a valid IRI.")


def parse_datetime_string(value: str, assume_timezone: tzinfo | None = None):
    """Parse like the server (marshmallow ``from_iso_datetime``) and return UTC.

    Returns ``None`` for invalid strings. A naive value is only accepted when
    ``assume_timezone`` is given (the server would silently use its own local zone).
    """
    if not isinstance(value, str):
        return None
    match = _ISO8601_DATETIME_RE.match(value.strip())
    if not match:
        return None
    parts = match.groupdict()
    tz = None
    if parts["tzinfo"] == "Z":
        tz = timezone.utc
    elif parts["tzinfo"]:
        sign = 1 if parts["tzinfo"][0] == "+" else -1
        digits = parts["tzinfo"][1:].replace(":", "")
        hours, minutes = int(digits[:2]), int(digits[2:] or 0)
        from datetime import timedelta

        tz = timezone(sign * timedelta(hours=hours, minutes=minutes))
    micro = parts["microsecond"]
    try:
        dt = datetime(
            int(parts["year"]),
            int(parts["month"]),
            int(parts["day"]),
            int(parts["hour"]),
            int(parts["minute"]),
            int(parts["second"] or 0),
            int(micro.ljust(6, "0")) if micro else 0,
            tzinfo=tz,
        )
    except ValueError:
        return None
    if dt.tzinfo is None:
        if assume_timezone is None:
            raise NaiveDatetimeError(value)
        dt = dt.replace(tzinfo=assume_timezone)
    return dt.astimezone(timezone.utc)


class NaiveDatetimeError(ValueError):
    """A date-time without time zone; the server would guess, so we refuse."""


def _validate_extra_value(value, value_type, assume_timezone=None):
    type_name = type(value).__name__
    if value_type == "int":
        if type_name == "int":
            if EXTRAS_MIN_INTEGER <= value <= EXTRAS_MAX_INTEGER:
                return value
            raise ValueError(
                f"Integer values must be between {EXTRAS_MIN_INTEGER} and"
                f" {EXTRAS_MAX_INTEGER}."
            )
    elif value_type == "float":
        if type_name in {"int", "float"}:
            value = float(value)
            if not (math.isnan(value) or math.isinf(value)):
                return value
    elif value_type == "date":
        if isinstance(value, datetime):
            if value.tzinfo is None:
                if assume_timezone is None:
                    raise NaiveDatetimeError(str(value))
                value = value.replace(tzinfo=assume_timezone)
        else:
            value = parse_datetime_string(value, assume_timezone)
        if value is not None:
            return value.astimezone(timezone.utc).isoformat()
    elif type_name == value_type:
        return value
    raise ValueError(f"Not a valid {pretty_type_name(value_type)}.")


def _load_validation(validation, value_type, assume_timezone):
    """Port of ``_ValidationSchema`` (load + post_load + validates_schema)."""
    if not isinstance(validation, dict):
        raise ValueError("Not a valid mapping type.")
    data: dict[str, Any] = {}
    errors: list[str] = []
    known = {"required", "range", "options", "iri"}
    for key in validation:
        if key not in known:
            continue  # unknown fields are silently excluded on the server
    if "required" in validation:
        if not isinstance(validation["required"], bool):
            errors.append("Required: Not a valid boolean.")
        elif validation["required"]:
            data["required"] = True
    if "range" in validation:
        rng = validation["range"]
        if not isinstance(rng, dict):
            errors.append("Range: Not a valid mapping type.")
        else:
            rng = {"min": rng.get("min"), "max": rng.get("max")}
            if rng["min"] is not None or rng["max"] is not None:
                data["range"] = rng
    if "options" in validation:
        if not isinstance(validation["options"], list):
            errors.append("Options: Not a valid list.")
        elif validation["options"]:
            data["options"] = list(validation["options"])
    if "iri" in validation:
        if not isinstance(validation["iri"], bool):
            errors.append("IRI: Not a valid boolean.")
        elif validation["iri"]:
            data["iri"] = True
    if errors:
        raise ValueError("; ".join(errors))

    if "range" in data:
        if value_type not in ("int", "float"):
            raise ValueError(
                f"Range: Cannot be used together with {pretty_type_name(value_type)}."
            )
        for key, val in data["range"].items():
            if val is not None:
                try:
                    data["range"][key] = _validate_extra_value(val, value_type)
                except ValueError as exc:
                    raise ValueError(f"Range: {exc}") from exc
        lo, hi = data["range"]["min"], data["range"]["max"]
        if lo is not None and hi is not None and lo > hi:
            raise ValueError("Range: Minimum value cannot be greater than maximum value.")
    if "options" in data:
        if value_type not in ("str", "int", "float"):
            raise ValueError(
                f"Options: Cannot be used together with {pretty_type_name(value_type)}."
            )
        options = []
        for option in data["options"]:
            try:
                opt = _validate_extra_value(option, value_type, assume_timezone)
                if data.get("iri", False):
                    validate_iri(opt)
                if opt not in options:
                    options.append(opt)
            except ValueError as exc:
                raise ValueError(f"Options: {exc}") from exc
        data["options"] = options
    if "iri" in data and value_type != "str":
        raise ValueError(f"IRI: Cannot be used together with {pretty_type_name(value_type)}.")
    return data


def _apply_validation(extra, is_template):
    value = extra["value"]
    validation = extra["validation"]
    msgs = []
    if validation.get("required", False) and not is_template and value is None:
        msgs.append("Value is required.")
    if "range" in validation and value is not None:
        lo, hi = validation["range"]["min"], validation["range"]["max"]
        if lo is not None and value < lo:
            msgs.append(f"Must be equal to or greater than {lo}.")
        if hi is not None and value > hi:
            msgs.append(f"Must be equal to or smaller than {hi}.")
    if "options" in validation and value is not None and value not in validation["options"]:
        msgs.append("Must be one of: " + ", ".join(str(v) for v in validation["options"]) + ".")
    if validation.get("iri", False) and value is not None:
        try:
            validate_iri(value)
        except ValueError as exc:
            msgs.append(str(exc))
    return msgs


def load_extras(extras, is_template=False, assume_timezone: tzinfo | None = None, _in_list=False):
    """Validate and normalise a list of extras exactly like ``ExtraSchema(many=True).load``.

    :param extras: list of extra dicts (the Kadi structure).
    :param is_template: skip "required" checks (template data carries no values).
    :param assume_timezone: zone used for naive ``date`` strings; ``None`` = reject them.
    :return: the normalised extras (new list), as the server would store them.
    :raises ExtrasValidationError: with ``messages`` nested like the server's response.
    """
    if not isinstance(extras, list):
        raise ExtrasValidationError({"_schema": ["Invalid input type."]})
    result = []
    errors: dict[int, dict[str, list]] = {}
    prev_keys = set()

    def add_error(index, field, message):
        errors.setdefault(index, {}).setdefault(field, []).append(message)

    for index, raw in enumerate(extras):
        if not isinstance(raw, dict):
            errors[index] = {"_schema": ["Invalid input type."]}
            result.append(None)
            continue
        extra: dict[str, Any] = {}
        # --- field-level (de)serialisation, as marshmallow would do it ---------------
        if "type" not in raw:
            add_error(index, "type", "Missing data for required field.")
        elif not isinstance(raw["type"], str):
            add_error(index, "type", "Not a valid string.")
        elif not raw["type"].strip():
            add_error(index, "type", "String must not be empty.")
        else:
            extra["type"] = strip(raw["type"])
        if not _in_list:
            if "key" not in raw:
                add_error(index, "key", "Missing data for required field.")
            elif not isinstance(raw["key"], str):
                add_error(index, "key", "Not a valid string.")
            elif not raw["key"].strip():
                add_error(index, "key", "String must not be empty.")
            else:
                extra["key"] = normalize(raw["key"])
        extra["value"] = raw.get("value")
        unit = raw.get("unit")
        if unit is not None and not isinstance(unit, str):
            add_error(index, "unit", "Not a valid string.")
            unit = None
        elif isinstance(unit, str) and not unit.strip():
            add_error(index, "unit", "String must not be empty.")
            unit = None
        extra["unit"] = normalize(unit) if unit is not None else None
        if "description" in raw:
            desc = raw["description"]
            if not isinstance(desc, str):
                add_error(index, "description", "Not a valid string.")
            elif not desc.strip():
                add_error(index, "description", "String must not be empty.")
            else:
                extra["description"] = strip(desc)
        if "term" in raw:
            term = raw["term"]
            if not isinstance(term, str):
                add_error(index, "term", "Not a valid string.")
            elif not term.strip():
                add_error(index, "term", "String must not be empty.")
            else:
                term = strip(term)
                try:
                    validate_iri(term)
                    extra["term"] = term
                except ValueError as exc:
                    add_error(index, "term", str(exc))
        if "validation" in raw:
            if not isinstance(raw["validation"], dict):
                add_error(index, "validation", "Not a valid mapping type.")
            else:
                extra["validation"] = dict(raw["validation"])

        # --- schema-level validation (``_validate_schema``) ----------------------------
        if isinstance(extra.get("value"), str):
            extra["value"] = extra["value"].strip() or None
        value_type = extra.get("type")
        if value_type in EXTRA_TYPES:
            if is_nested_type(value_type):
                if extra.get("value") is None:
                    extra["value"] = []
                try:
                    extra["value"] = load_extras(
                        extra["value"],
                        is_template=is_template,
                        assume_timezone=assume_timezone,
                        _in_list=(value_type == "list"),
                    )
                except ExtrasValidationError as exc:
                    errors[index] = {"value": exc.messages}
                if "validation" in extra:
                    add_error(
                        index,
                        "validation",
                        f"Cannot be used together with {pretty_type_name(value_type)}.",
                    )
            else:
                if extra.get("value") is not None:
                    try:
                        extra["value"] = _validate_extra_value(
                            extra["value"], value_type, assume_timezone
                        )
                    except NaiveDatetimeError as exc:
                        add_error(
                            index,
                            "value",
                            f"Date-time '{exc}' has no time zone; add an offset such as"
                            " +01:00 or Z (the server would guess its own zone).",
                        )
                    except ValueError as exc:
                        add_error(index, "value", str(exc))
                if "validation" in extra:
                    try:
                        extra["validation"] = _load_validation(
                            extra["validation"], value_type, assume_timezone
                        )
                        for msg in _apply_validation(extra, is_template):
                            add_error(index, "value", msg)
                    except ValueError as exc:
                        add_error(index, "validation", str(exc))
            if value_type not in ("int", "float") and extra.get("unit") is not None:
                add_error(
                    index, "unit", f"Cannot be used together with {pretty_type_name(value_type)}."
                )
        elif value_type is not None:
            add_error(index, "type", "Invalid value.")

        key = extra.get("key")
        if key in prev_keys:
            add_error(index, "key", "Duplicate value.")
        if key:
            prev_keys.add(key)

        # --- post_load ----------------------------------------------------------------
        if extra.get("type") not in ("int", "float"):
            extra.pop("unit", None)
        if "validation" in extra and not extra["validation"]:
            del extra["validation"]
        result.append(extra)

    if errors:
        raise ExtrasValidationError(errors)
    return result


def extras_to_plain_json(extras, _nested_type=None):
    """Port of ``extras_to_plain_json`` (the "plain" extras export format)."""
    converted = [] if _nested_type == "list" else {}
    for extra in extras:
        if is_nested_type(extra["type"]):
            value = extras_to_plain_json(extra["value"], extra["type"])
        else:
            value = extra["value"]
        if _nested_type == "list":
            converted.append(value)
        else:
            converted[extra["key"]] = value
    return converted


def remove_extra_values(extras):
    """Port of ``remove_extra_values`` (record data -> template data)."""
    out = []
    for extra in extras:
        new = dict(extra)
        if is_nested_type(extra["type"]):
            new["value"] = remove_extra_values(extra["value"])
        else:
            new["value"] = None
        out.append(new)
    return out
