"""Utterance-only checks for abstention (BFCL irrelevance).

Gold is not calling a tool. Translation must not pull the utterance
closer to the English schema than the source was.

Schema names are not sent to the translator. New exact matches of
function names, parameter names, or enum values in the translated
utterance are flagged and not repaired.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from eval.toolcall_checker import (
    DATE_OR_ISO_RE,
    IDENT_RE,
    UNIT_RE,
    schema_canonical,
)

# Identifiers shorter than this are not matched (a, b, c, n, C, F).
# Enum values keep a floor of 2 so "12"/"24" still count.
IDENT_MIN_LEN = 3
ENUM_MIN_LEN = 2

_IDENT_TOKEN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _walk_properties(props: object) -> Iterable[tuple[str, str]]:
    if not isinstance(props, dict):
        return
    for name, spec in props.items():
        yield ("param", str(name))
        if not isinstance(spec, dict):
            continue
        for value in spec.get("enum") or []:
            yield ("enum", str(value))
        nested = spec.get("properties")
        if nested:
            yield from _walk_properties(nested)
        items = spec.get("items")
        if isinstance(items, dict):
            for value in items.get("enum") or []:
                yield ("enum", str(value))
            if items.get("properties"):
                yield from _walk_properties(items["properties"])


def schema_tokens(functions) -> list[dict]:
    """Function names (full + dotted parts), parameter names, enum values."""
    seen = set()
    out = []
    for fn in functions or []:
        if not isinstance(fn, dict):
            continue
        name = str(fn.get("name") or "").strip()
        pieces = [name] if name else []
        pieces.extend(part for part in name.split(".") if part and part != name)
        for piece in pieces:
            key = ("fn", piece)
            if key not in seen:
                seen.add(key)
                out.append({"kind": "fn", "token": piece})
        params = fn.get("parameters") or {}
        props = params.get("properties") if isinstance(params, dict) else {}
        for kind, token in _walk_properties(props):
            key = (kind, token)
            if key not in seen:
                seen.add(key)
                out.append({"kind": kind, "token": token})
    return out


def token_eligible(kind: str, token: str) -> bool:
    if not token:
        return False
    if kind == "enum":
        return len(token) >= ENUM_MIN_LEN
    return len(token) >= IDENT_MIN_LEN


def token_in_text(token: str, text: str) -> bool:
    """Case-sensitive string match. Identifiers use token boundaries."""
    if not token or not text:
        return False
    if _IDENT_TOKEN.fullmatch(token):
        return (
            re.search(
                r"(?<![A-Za-z0-9_])" + re.escape(token) + r"(?![A-Za-z0-9_])",
                text,
            )
            is not None
        )
    return token in text


def new_schema_leaks(utterance_en: str, utterance_target: str, functions) -> list[dict]:
    leaks = []
    for row in schema_tokens(functions):
        if not token_eligible(row["kind"], row["token"]):
            continue
        if token_in_text(row["token"], utterance_target) and not token_in_text(
            row["token"], utterance_en
        ):
            leaks.append(row)
    return leaks


def en_schema_overlap(utterance_en: str, functions) -> list[dict]:
    overlap = []
    for row in schema_tokens(functions):
        if not token_eligible(row["kind"], row["token"]):
            continue
        if token_in_text(row["token"], utterance_en):
            overlap.append(row)
    return overlap


def classify_quantity_residual(
    utterance_en: str, utterance_target: str, extra_qty: dict, leak: list[str]
) -> str | None:
    if leak:
        return "identifier_digit_leak"
    extra = extra_qty or {}
    tags = []
    for token, count in extra.items():
        if count <= 0:
            continue
        if re.search(
            rf"(?<!\d){re.escape(str(token))}(?:st|nd|rd|th)\b",
            utterance_en,
            re.I,
        ):
            tags.append("ordinal_quantity_promotion")
        elif str(token) == "2" and re.search(r"\btwo\b", utterance_en, re.I):
            tags.append("count_word_promotion")
        elif str(token) == "1" and re.search(r"한\s", utterance_target):
            tags.append("grammatical_one")
        elif str(token) == "1" and re.search(r"\bone\b", utterance_en, re.I):
            tags.append("count_word_promotion")
        else:
            tags.append("quantity_v2")
    if not tags:
        return None
    uniq = list(dict.fromkeys(tags))
    return uniq[0] if len(uniq) == 1 else ",".join(uniq)


def utterance_protected_literals(utterance_en: str) -> list[str]:
    found = []
    for regex in (DATE_OR_ISO_RE, IDENT_RE, UNIT_RE):
        for value in regex.findall(utterance_en or ""):
            if value not in found:
                found.append(value)
    return found


def abstention_invariants(
    utterance_en: str,
    utterance_target: str,
    function_en,
    function_held,
) -> dict:
    schema_ok = schema_canonical(function_en) == schema_canonical(function_held)
    dates = sorted(set(DATE_OR_ISO_RE.findall(utterance_en or "")))
    missing_dates = [value for value in dates if value not in (utterance_target or "")]
    units = sorted(set(UNIT_RE.findall(utterance_en or "")))
    missing_units = [value for value in units if value not in (utterance_target or "")]
    leaks = new_schema_leaks(utterance_en, utterance_target, function_en)
    overlap = en_schema_overlap(utterance_en, function_en)

    reasons = []
    if not schema_ok:
        reasons.append("schema_bytes")
    if missing_dates:
        reasons.append("date_or_iso")
    if missing_units:
        reasons.append("unit")

    return {
        "ok": not reasons,
        "invalidates_item": bool(reasons),
        "reasons": reasons,
        "schema_ok": schema_ok,
        "dates_or_iso": dates,
        "missing_dates_or_iso": missing_dates,
        "units": units,
        "missing_units": missing_units,
        "schema_leaks": leaks,
        "schema_leak_tokens": [row["token"] for row in leaks],
        "en_schema_overlap": overlap,
        "en_schema_overlap_tokens": [row["token"] for row in overlap],
        # Unique failure mode: report, do not repair, do not invalidate.
        "schema_proximity_leak": bool(leaks),
    }
