"""Utterance-literal and schema checks for toolcall translation.

Only the user utterance is translated. Function schemas stay English.
possible_answer values that appear in the English utterance must survive.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable

DATE_OR_ISO_RE = re.compile(
    r"\b\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}:\d{2}Z)?\b"
)
UNIT_RE = re.compile(r"(?<!\w)\d+(?:\.\d+)? (?:g|C|cm|mm|kg|km)(?!\w)")
IDENT_RE = re.compile(
    r"\b[A-Z]{2,}[A-Z0-9]*-\d+\b"
    r"|\bSKU[-_A-Z0-9]+\b"
    r"|\b[\w.-]+\.[A-Za-z]{1,5}\b"
)

UNIT_CODES = {"cm", "mm", "km", "kg", "g", "c", "in", "ft", "lb", "oz", "ml", "l"}


def flatten(value: object) -> Iterable[object]:
    if isinstance(value, dict):
        for child in value.values():
            yield from flatten(child)
    elif isinstance(value, list):
        for child in value:
            yield from flatten(child)
    else:
        yield value


def _literal(value: object) -> str | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    return str(value)


def classify_literal(value: object) -> str | None:
    """opaque_identifier | proper_name | ordinary_word | number | other."""
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return "number"
    text = str(value).strip()
    if not text:
        return None
    if re.fullmatch(r"-?\d+(?:\.\d+)?", text):
        return "number"
    if text.lower() in UNIT_CODES:
        return "opaque_identifier"
    if re.search(r"://|@|\\|/", text) or re.search(r"\.[A-Za-z0-9]{1,5}$", text):
        return "opaque_identifier"
    if re.fullmatch(r"[A-Z0-9]+(?:-[A-Z0-9]+)+", text) or re.search(
        r"[A-Z]{2,}\d|\d[A-Z]", text
    ):
        return "opaque_identifier"
    if re.search(r"\d", text) and re.search(r"[A-Za-z]", text):
        return "proper_name" if (" " in text or text[:1].isupper()) else "opaque_identifier"
    words = text.split()
    if words and all(w[:1].isupper() for w in words) and any(
        len(w) > 1 and w[1:].islower() for w in words
    ):
        return "proper_name"
    if re.fullmatch(r"[A-Za-z][A-Za-z' -]*", text):
        return "ordinary_word"
    return "other"


def realized_answer_literals(utterance_en: str, ground_truth: object) -> list[dict]:
    seen = set()
    out = []
    for value in flatten(ground_truth):
        lit = _literal(value)
        if not lit or lit in seen:
            continue
        if lit not in utterance_en:
            continue
        seen.add(lit)
        out.append({"value": lit, "class": classify_literal(value)})
    return sorted(out, key=lambda row: (-len(row["value"]), row["value"]))


def schema_canonical(function) -> str:
    return json.dumps(function, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def identifier_digit_leak(source: str, extra_qty: dict) -> list[str]:
    """Digits counted as quantities that only exist inside identifiers."""
    idents = IDENT_RE.findall(source or "")
    leaked = []
    for token, count in (extra_qty or {}).items():
        if count <= 0:
            continue
        if any(token in ident and ident != token for ident in idents):
            leaked.append(token)
    return leaked


def toolcall_invariants(
    utterance_en: str,
    utterance_target: str,
    function_en,
    function_held,
    ground_truth,
) -> dict:
    schema_ok = schema_canonical(function_en) == schema_canonical(function_held)
    realized = realized_answer_literals(utterance_en, ground_truth)
    missing = [row["value"] for row in realized if row["value"] not in utterance_target]
    missing_by_class = {}
    for row in realized:
        if row["value"] not in utterance_target:
            missing_by_class.setdefault(row["class"] or "other", []).append(row["value"])
    dates = sorted(set(DATE_OR_ISO_RE.findall(utterance_en)))
    missing_dates = [value for value in dates if value not in utterance_target]
    units = sorted(set(UNIT_RE.findall(utterance_en)))
    missing_units = [value for value in units if value not in utterance_target]

    reasons = []
    if not schema_ok:
        reasons.append("schema_bytes")
    if missing:
        reasons.append("answer_literal")
    if missing_dates:
        reasons.append("date_or_iso")
    if missing_units:
        reasons.append("unit")

    ordinary_only = bool(missing) and set(missing_by_class) <= {"ordinary_word"}
    return {
        "ok": not reasons,
        "invalidates_item": bool(reasons),
        "ordinary_gold_only": ordinary_only,
        "reasons": reasons,
        "realized_literals": realized,
        "missing_literals": missing,
        "missing_by_class": missing_by_class,
        "schema_ok": schema_ok,
        "dates_or_iso": dates,
        "missing_dates_or_iso": missing_dates,
        "units": units,
        "missing_units": missing_units,
    }
