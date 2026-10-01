"""Literal-preservation checks for extraction document translation.

Only the document is translated. Proper names, identifiers, dates, numbers,
and unit expressions that appear in the English document are immutable.
Categorical gold values live in the English schema as enums and may be
paraphrased in the document.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

DATE_OR_ISO_RE = re.compile(
    r"\b\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}:\d{2}Z)?\b"
)
UNIT_RE = re.compile(r"(?<!\w)\d+(?:\.\d+)? (?:g|C)(?!\w)")


def flatten_gold(value: object) -> Iterable[object]:
    if isinstance(value, dict):
        for child in value.values():
            yield from flatten_gold(child)
    elif isinstance(value, list):
        for child in value:
            yield from flatten_gold(child)
    else:
        yield value


def _literal(value: object) -> str:
    if value is True:
        return "true"
    if value is False:
        return "false"
    return str(value)


def enum_literals(schema_enums: dict | None) -> set[str]:
    out: set[str] = set()
    for options in (schema_enums or {}).values():
        out.update(str(option) for option in options)
    return out


def query_schema(field_types: Iterable[str], schema_enums: dict | None = None) -> str:
    keys = list(field_types)
    parts = ["Extract a JSON object with exactly these keys: " + ", ".join(keys) + "."]
    for field, options in (schema_enums or {}).items():
        parts.append(f"{field} must be chosen from: " + ", ".join(str(x) for x in options) + ".")
    return " ".join(parts)


def protected_gold_literals(
    document_en: str,
    gold: dict,
    schema_enums: dict | None = None,
) -> list[str]:
    """Gold leaves realized in the source, excluding schema-enum categories."""
    skip = enum_literals(schema_enums)
    values = set()
    for value in flatten_gold(gold):
        if isinstance(value, bool):
            continue
        values.add(_literal(value))
    keep = [
        value
        for value in values
        if value in document_en and value not in skip
    ]
    return sorted(keep, key=lambda x: (-len(x), x))


def extraction_invariants(
    document_en: str,
    document_target: str,
    gold: dict,
    schema_keys: Iterable[str],
    query_schema_text: str,
    schema_enums: dict | None = None,
) -> dict:
    literals = protected_gold_literals(document_en, gold, schema_enums)
    missing_literals = [value for value in literals if value not in document_target]

    dates = sorted(set(DATE_OR_ISO_RE.findall(document_en)))
    missing_dates = [value for value in dates if value not in document_target]

    units = sorted(set(UNIT_RE.findall(document_en)))
    missing_units = [value for value in units if value not in document_target]

    keys = list(schema_keys)
    missing_schema_keys = [key for key in keys if key not in query_schema_text]
    enum_opts = sorted(enum_literals(schema_enums), key=lambda x: (-len(x), x))
    missing_enum_options = [opt for opt in enum_opts if opt not in query_schema_text]

    reasons = []
    if missing_literals:
        reasons.append("gold_literal")
    if missing_dates:
        reasons.append("date_or_iso")
    if missing_units:
        reasons.append("unit")
    if missing_schema_keys:
        reasons.append("schema_key")
    if missing_enum_options:
        reasons.append("schema_enum")

    return {
        "ok": not reasons,
        "invalidates_item": bool(reasons),
        "reasons": reasons,
        "protected_gold_literals": literals,
        "missing_gold_literals": missing_literals,
        "dates_or_iso": dates,
        "missing_dates_or_iso": missing_dates,
        "units": units,
        "missing_units": missing_units,
        "schema_keys": keys,
        "missing_schema_keys": missing_schema_keys,
        "schema_enum_options": enum_opts,
        "missing_schema_enum_options": missing_enum_options,
    }
