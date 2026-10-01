"""Coding-bucket checks: translate narrative only.

Starter code, tests, example I/O, constraint notation, identifiers,
formulas, and the question_content tail (from the first Example/Input/
Constraints header) are never sent to the translator.
"""

from __future__ import annotations

import json
import re
from collections import Counter

from eval.marker_checker import compare_markers
from eval.toolcall_checker import classify_literal, identifier_digit_leak

SPLIT_RE = re.compile(
    r"(?:\r\n|\n|\r)"
    r"(?:Example(?:[ \t]+\d+)?[ \t]*:"
    r"|Constraints[ \t]*:"
    r"|Input[ \t]*(?:\r\n|\n|\r)"
    r"|Sample[ \t]+Input)",
)

PLACE_RE = re.compile(r"⟦(\d+)⟧")

LATEX_CMD_RE = re.compile(r"\\[a-zA-Z]+")
DOLLAR_RE = re.compile(r"\$[^$\n]{1,80}\$")
COMPLEXITY_RE = re.compile(r"\bO\([^)]{1,40}\)")
CARET_RE = re.compile(r"(?<![A-Za-z])\d+\s*\^\s*\{?-?\d+\}?")
SUBSCRIPT_RE = re.compile(r"\b[A-Za-z](?:_[A-Za-z0-9]+|_\{[A-Za-z0-9]+\})")
INEQUALITY_RE = re.compile(
    r"(?:[A-Za-z][A-Za-z0-9_]*|\d+|\\[a-zA-Z]+(?:\{[^}]+\})?)"
    r"(?:\s*(?:<=|>=|<|>|\\leq|\\le|\\geq|\\ge|≤|≥)\s*"
    r"(?:[A-Za-z][A-Za-z0-9_]*|\d+|\\[a-zA-Z]+(?:\{[^}]+\})?))+"
)
BACKTICK_RE = re.compile(r"`[^`\n]+`")
WORD_RE = re.compile(r"[A-Za-z][A-Za-z']*")

PY_SKIP = {
    "class",
    "def",
    "return",
    "self",
    "cls",
    "True",
    "False",
    "None",
    "int",
    "str",
    "bool",
    "float",
    "list",
    "dict",
    "set",
    "tuple",
    "Optional",
    "List",
    "Dict",
    "Set",
    "Tuple",
    "Any",
    "from",
    "import",
    "pass",
    "for",
    "while",
    "if",
    "else",
    "elif",
    "in",
    "and",
    "or",
    "not",
}

STRUCTURE_RES = [
    ("example", re.compile(r"Example(?:[ \t]+\d+)?[ \t]*:")),
    ("constraints", re.compile(r"Constraints[ \t]*:")),
    ("input_line", re.compile(r"(?m)^Input[ \t]*$")),
    ("output_line", re.compile(r"(?m)^Output[ \t]*$")),
    ("sample_input", re.compile(r"Sample[ \t]+Input")),
    ("sample_output", re.compile(r"Sample[ \t]+Output")),
    ("explanation", re.compile(r"Explanation[ \t]*:")),
    ("input_colon", re.compile(r"(?m)^Input:")),
    ("output_colon", re.compile(r"(?m)^Output:")),
]


def split_question_content(text: str) -> tuple[str, str]:
    """Head = narrative. Tail = first example/input/constraints block to EOF."""
    match = SPLIT_RE.search(text or "")
    if not match:
        return text or "", ""
    return (text or "")[: match.start()], (text or "")[match.start() :]


def starter_identifiers(starter: str, metadata: str | dict | None = None) -> list[str]:
    names = set()
    if metadata:
        meta = json.loads(metadata) if isinstance(metadata, str) else metadata
        func = (meta or {}).get("func_name")
        if func:
            names.add(str(func))
    for match in re.finditer(r"\b[A-Za-z_][A-Za-z0-9_]*\b", starter or ""):
        word = match.group()
        if word in PY_SKIP or len(word) < 2:
            continue
        names.add(word)
    return sorted(names, key=len, reverse=True)


def public_output_tokens(public_test_cases) -> list[str]:
    if not public_test_cases:
        return []
    tests = (
        json.loads(public_test_cases)
        if isinstance(public_test_cases, str)
        else public_test_cases
    )
    found = []
    seen = set()
    for row in tests or []:
        output = str((row or {}).get("output") or "")
        for word in WORD_RE.findall(output):
            if word in seen:
                continue
            seen.add(word)
            found.append(word)
    return found


def classify_output_token(token: str) -> str:
    low = token.lower()
    if low in {"yes", "no"}:
        return "print_token"
    if low in {"true", "false"}:
        return "print_token"
    kind = classify_literal(token)
    return kind or "other"


def realized_execution_literals(head: str, public_test_cases) -> list[dict]:
    """Test-output tokens that also appear in the narrative. Execution gold, not string match."""
    out = []
    for token in public_output_tokens(public_test_cases):
        if not re.search(r"(?<![A-Za-z])" + re.escape(token) + r"(?![A-Za-z])", head or ""):
            continue
        out.append({"value": token, "class": classify_output_token(token)})
    return out


def _add_span(spans: list[tuple[int, int]], start: int, end: int) -> None:
    if start >= end:
        return
    for a, b in spans:
        if start < b and end > a:
            return
    spans.append((start, end))


def freeze_spans(head: str, idents: list[str], output_tokens: list[str]) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    for regex in (
        DOLLAR_RE,
        BACKTICK_RE,
        COMPLEXITY_RE,
        CARET_RE,
        INEQUALITY_RE,
        SUBSCRIPT_RE,
        LATEX_CMD_RE,
    ):
        for match in regex.finditer(head or ""):
            _add_span(spans, match.start(), match.end())
    for token in sorted(idents, key=len, reverse=True):
        for match in re.finditer(
            r"(?<![A-Za-z0-9_])" + re.escape(token) + r"(?![A-Za-z0-9_])",
            head or "",
        ):
            _add_span(spans, match.start(), match.end())
    for token in sorted(output_tokens, key=len, reverse=True):
        if len(token) < 2:
            continue
        for match in re.finditer(
            r"(?<![A-Za-z])" + re.escape(token) + r"(?![A-Za-z])",
            head or "",
        ):
            _add_span(spans, match.start(), match.end())
    return sorted(spans)


def mask_head(head: str, spans: list[tuple[int, int]]) -> tuple[str, list[str]]:
    frozen = []
    pieces = []
    cursor = 0
    for start, end in spans:
        if start < cursor:
            continue
        pieces.append(head[cursor:start])
        pieces.append(f"⟦{len(frozen)}⟧")
        frozen.append(head[start:end])
        cursor = end
    pieces.append(head[cursor:])
    return "".join(pieces), frozen


def unmask_head(masked: str, frozen: list[str]) -> tuple[str, list[int]]:
    missing = []
    out = masked or ""
    for index, token in enumerate(frozen):
        needle = f"⟦{index}⟧"
        if needle not in out:
            missing.append(index)
            continue
        out = out.replace(needle, token, 1)
    leftover = PLACE_RE.findall(out)
    return out, missing + [int(x) for x in leftover]


def structure_counts(text: str) -> dict:
    return {name: len(regex.findall(text or "")) for name, regex in STRUCTURE_RES}


def assemble(head: str, tail: str) -> str:
    return f"{head}{tail}"


def coding_invariants(
    original: str,
    translated: str,
    starter_en: str,
    starter_held: str,
    frozen_ok: bool,
    missing_placeholders: list[int],
    realized: list[dict],
) -> dict:
    orig_head, orig_tail = split_question_content(original)
    tr_head, tr_tail = split_question_content(translated)
    tail_ok = tr_tail == orig_tail
    starter_ok = starter_en == starter_held
    markers = compare_markers(original, translated)
    struct_src = structure_counts(original)
    struct_tgt = structure_counts(translated)
    struct_ok = struct_src == struct_tgt
    missing_literals = [
        row["value"] for row in realized if row["value"] not in (tr_head or "")
    ]
    reasons = []
    if not starter_ok:
        reasons.append("starter_bytes")
    if not tail_ok:
        reasons.append("frozen_tail")
    if not frozen_ok or missing_placeholders:
        reasons.append("placeholder")
    if not markers["ok"]:
        reasons.append("code_marker")
    if not struct_ok:
        reasons.append("example_structure")
    if missing_literals:
        reasons.append("execution_literal")
    return {
        "ok": not reasons,
        "invalidates_item": bool(reasons),
        "reasons": reasons,
        "starter_ok": starter_ok,
        "tail_ok": tail_ok,
        "frozen_ok": frozen_ok,
        "missing_placeholders": missing_placeholders,
        "markers": markers,
        "structure_source": struct_src,
        "structure_target": struct_tgt,
        "structure_ok": struct_ok,
        "missing_literals": missing_literals,
        "realized_literals": realized,
    }


def coding_digit_leak(source_head: str, extra_qty: dict) -> list[str]:
    """v2 extras that only exist inside identifiers or contest ids in the head."""
    leaked = identifier_digit_leak(source_head, extra_qty)
    idents = re.findall(r"\b[A-Za-z_][A-Za-z0-9_]*\b", source_head or "")
    idents += re.findall(r"`[^`]+`", source_head or "")
    for token, count in (extra_qty or {}).items():
        if count <= 0 or token in leaked:
            continue
        if any(token in ident and ident != token for ident in idents):
            leaked.append(token)
    return leaked
