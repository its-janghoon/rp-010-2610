"""Quantity checkers for translation QA.

Versions
--------
v1  Surface digit-token multiset. Tokens are the raw regex strings.
    Does not map number words. This is the pre-committed math checker.
v2  Quantity-value multiset after script normalization.
    Arabic digits (ASCII + Devanagari), English/Korean/Hindi number words,
    and multiplier forms map to the same Decimal value.
    Ordinals (first/second/첫/번째/पहले) are not quantities.
    v3  math-only. Same extraction as v2, then split:
          essential = values that appear in GSM8K <<calc>> AND in the English source
          reference = all other extracted values (reported, not a fail axis)
        Grammatical determiners (one dog, a red car, 하나, एक) drop out when
        they are not in the calculation. Applies only to bucket=math.
        Other buckets keep exact string match for identifiers/SKU/dates.

Do not use v2/v3 on identifier/SKU/date/version fields.
"""

from __future__ import annotations

import re
from collections import Counter
from decimal import Decimal, InvalidOperation
from typing import Iterable

CHECKER_ID = "010.quantity_checker"
CHECKER_V1 = "v1"
CHECKER_V2 = "v2"
CHECKER_V3 = "v3"

# v1: identical to the original translate_math_verify.NUMERIC_RE
V1_NUMERIC_RE = re.compile(
    r"(?:"
    r"\d+(?:[.,]\d+)+"
    r"|\d+"
    r")"
)

DEVANAGARI_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")

# Calendar / version / SKU / identifier-like. Not quantities.
_PROTECTED = [
    re.compile(r"\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2})?(?:Z|[+-]\d{2}:\d{2})?)?"),
    re.compile(r"\b[vV]\d+\.\d+(?:\.\d+)+\b"),
    re.compile(r"\b\d+\.\d+\.\d+(?:\.\d+)*\b"),
    re.compile(r"\b[A-Z]{2,}[A-Z0-9]*-\d+\b"),
    re.compile(r"\bSKU[-_A-Z0-9]+\b", re.I),
]

_ARABIC = re.compile(
    r"(?<![A-Za-z])(?:"
    r"\d{1,3}(?:,\d{3})+(?:\.\d+)?"
    r"|\d+\.\d+"
    r"|\d+"
    r")(?![A-Za-z])"
)

# Longest-first number words. English included because the source is English.
_EN_WORDS = {
    "twelve": 12,
    "eleven": 11,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
    "twenty": 20,
    "three": 3,
    "seven": 7,
    "eight": 8,
    "zero": 0,
    "four": 4,
    "five": 5,
    "nine": 9,
    "one": 1,
    "two": 2,
    "six": 6,
    "ten": 10,
    "twice": 2,
    "thrice": 3,
    "half": Decimal("0.5"),
    "dozen": 12,
}

# Ordinals (first/second/첫/번째/पहले) are order labels, not amounts.
# Counting them as 1/2 invents quantities that v1 never saw.

_KO_FULL = {
    "열둘": 12,
    "열두": 12,
    "열하나": 11,
    "열한": 11,
    "하나": 1,
    "둘": 2,
    "셋": 3,
    "넷": 4,
    "다섯": 5,
    "여섯": 6,
    "일곱": 7,
    "여덟": 8,
    "아홉": 9,
    "열": 10,
    "절반": Decimal("0.5"),
}
_KO_SHORT_COUNTER = {
    "한": 1,
    "두": 2,
    "세": 3,
    "네": 4,
    "다섯": 5,
    "여섯": 6,
    "일곱": 7,
    "여덟": 8,
    "아홉": 9,
    "열": 10,
}
_KO_COUNTER = (
    r"(?:개|명|마리|장|대|벌|켤레|권|배|번(?!째)|곳|년|월|주|일|분|시간|살|층|"
    r"조각|포대|자루|인당|가지|쌍|세트|점|회)"
)
_KO_AFTER = r"(?:만큼|씩|째|[은는이가을를과도와의에서으로로]|[^가-힣]|$)"

_HI_WORDS = {
    "बारह": 12,
    "ग्यारह": 11,
    "दोगुनी": 2,
    "दोगुना": 2,
    "दोगुने": 2,
    "तिगुना": 3,
    "तिगुनी": 3,
    "चौगुना": 4,
    "चौगुनी": 4,
    "आधा": Decimal("0.5"),
    "आधे": Decimal("0.5"),
    "आधी": Decimal("0.5"),
    # Bare एक omitted: numeral "one" and also the indefinite determiner.
    # Same stance as English a/an and Korean 한 without a counter.
    # एक-एक is handled separately.
    "दो": 2,
    "तीन": 3,
    "चार": 4,
    "पांच": 5,
    "पाँच": 5,
    "छह": 6,
    "छः": 6,
    "सात": 7,
    "आठ": 8,
    "नौ": 9,
    "दस": 10,
}


def _dec(x) -> Decimal:
    if isinstance(x, Decimal):
        return x
    return Decimal(str(x))


def _protected_spans(text: str) -> list[tuple[int, int]]:
    spans = []
    for pat in _PROTECTED:
        for m in pat.finditer(text):
            spans.append((m.start(), m.end()))
    return spans


def _overlaps(i: int, j: int, spans: Iterable[tuple[int, int]]) -> bool:
    for a, b in spans:
        if i < b and j > a:
            return True
    return False


def extract_v1(text: str) -> Counter:
    return Counter(V1_NUMERIC_RE.findall(text or ""))


def _iter_script_words(text: str, word: str, script: str):
    if script == "hi":
        pat = rf"(?<![\u0900-\u097F]){re.escape(word)}(?![\u0900-\u097F])"
        flags = 0
    elif script == "ko":
        pat = rf"(?<![가-힣]){re.escape(word)}(?={_KO_AFTER})"
        flags = 0
    else:
        pat = rf"\b{re.escape(word)}\b"
        flags = re.I
    yield from re.finditer(pat, text, flags=flags)


def extract_v2(text: str) -> Counter:
    """Return a multiset of quantity values (Decimal)."""
    raw = text or ""
    t = raw.translate(DEVANAGARI_DIGITS)
    used: list[tuple[int, int]] = _protected_spans(t)
    found: list[tuple[int, int, Decimal]] = []

    def add(i: int, j: int, val) -> None:
        if i >= j:
            return
        if _overlaps(i, j, used):
            return
        found.append((i, j, _dec(val)))
        used.append((i, j))

    for m in _ARABIC.finditer(t):
        tok = m.group(0)
        if re.fullmatch(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?", tok):
            num = tok.replace(",", "")
        else:
            num = tok
        try:
            add(m.start(), m.end(), Decimal(num))
        except InvalidOperation:
            continue

    # English words
    for word, val in sorted(_EN_WORDS.items(), key=lambda kv: -len(kv[0])):
        for m in _iter_script_words(t, word, "en"):
            add(m.start(), m.end(), val)

    for word, val in sorted(_KO_FULL.items(), key=lambda kv: -len(kv[0])):
        for m in _iter_script_words(t, word, "ko"):
            add(m.start(), m.end(), val)
    short_alt = "|".join(sorted(_KO_SHORT_COUNTER, key=len, reverse=True))
    for m in re.finditer(rf"({short_alt})\s*{_KO_COUNTER}", t):
        add(m.start(), m.start() + len(m.group(1)), _KO_SHORT_COUNTER[m.group(1)])

    for m in re.finditer(r"(?<![\u0900-\u097F])एक-एक(?![\u0900-\u097F])", t):
        add(m.start(), m.end(), 1)
    _HI_COUNTER = r"(?:जोड़ी|जोड़ी|बार|गुना|टुकड़े|टुकड़ों|टुकड़े)"
    for m in re.finditer(rf"(?<![\u0900-\u097F])एक(?=\s*{_HI_COUNTER})", t):
        add(m.start(), m.start() + 2, 1)
    for word, val in sorted(_HI_WORDS.items(), key=lambda kv: -len(kv[0])):
        for m in _iter_script_words(t, word, "hi"):
            add(m.start(), m.end(), val)

    counts: Counter = Counter()
    for _, _, val in found:
        counts[val] += 1
    return counts


def extract(text: str, version: str) -> Counter:
    if version == CHECKER_V1:
        return extract_v1(text)
    if version in (CHECKER_V2, CHECKER_V3):
        return extract_v2(text)
    raise ValueError(f"unknown checker version: {version}")


_CALC_ANN = re.compile(r"<<([^>]+)>>")
_CALC_NUM = re.compile(r"(?:\d+(?:\.\d+)+|\.\d+|\d+)")


def parse_calc_values(equation_text: str, answer_number=None) -> set[Decimal]:
    """Numbers inside GSM8K <<expr>> annotations, plus answer_number."""
    vals: set[Decimal] = set()
    for m in _CALC_ANN.finditer(equation_text or ""):
        expr = m.group(1).replace(",", "")
        for tok in _CALC_NUM.findall(expr):
            try:
                vals.add(_dec(tok))
            except InvalidOperation:
                continue
    if answer_number is not None and str(answer_number).strip() not in ("", "nan"):
        try:
            vals.add(_dec(str(answer_number).replace(",", "")))
        except InvalidOperation:
            pass
    return vals


def split_essential_reference(extracted: Counter, calc_values: set[Decimal]) -> tuple[Counter, Counter]:
    ess: Counter = Counter()
    ref: Counter = Counter()
    for k, n in extracted.items():
        if k in calc_values:
            ess[k] = n
        else:
            ref[k] = n
    return ess, ref


def question_essential(source: str, calc_values: set[Decimal]) -> Counter:
    """Essential = v2 extract(source) keys that appear in the calculation."""
    src = extract_v2(source)
    ess, _ = split_essential_reference(src, calc_values)
    return ess


def compare(source: str, target: str, version: str, *, calc_values: set | None = None) -> dict:
    from eval.bucket_check import assert_quantity_version_allowed

    if version != CHECKER_V3:
        src = extract(source, version)
        tgt = extract(target, version)
        missing, extra = diff_counts(src, tgt)
        return {
            "checker_id": CHECKER_ID,
            "checker_version": version,
            "bucket": "math",
            "ok": not missing and not extra,
            "source": _jsonable(src),
            "target": _jsonable(tgt),
            "missing": _jsonable(missing),
            "extra": _jsonable(extra),
        }

    assert_quantity_version_allowed("math", CHECKER_V3)
    if calc_values is None:
        raise ValueError("v3 requires calc_values from GSM8K << >> (math only)")
    calc_values = {_dec(x) for x in calc_values}
    src_all = extract_v2(source)
    tgt_all = extract_v2(target)
    src_ess, src_ref = split_essential_reference(src_all, calc_values)
    _, tgt_ref = split_essential_reference(tgt_all, calc_values)
    # Only keys that are essential *in the English question*. Target extras of
    # calc-only intermediates (the answer 1, etc.) are reference, not fail.
    q_keys = set(src_ess)
    tgt_ess = Counter({k: tgt_all.get(k, 0) for k in q_keys})
    missing, extra = diff_counts(src_ess, tgt_ess)
    return {
        "checker_id": CHECKER_ID,
        "checker_version": version,
        "bucket": "math",
        "ok": not missing and not extra,
        "calc_values": sorted(str(x) for x in calc_values),
        "source_essential": _jsonable(src_ess),
        "target_essential": _jsonable(tgt_ess),
        "source_reference": _jsonable(src_ref),
        "target_reference": _jsonable(tgt_ref),
        "source": _jsonable(src_ess),
        "target": _jsonable(tgt_ess),
        "missing": _jsonable(missing),
        "extra": _jsonable(extra),
    }


def diff_counts(src: Counter, tgt: Counter) -> tuple[dict, dict]:
    missing = {}
    extra = {}
    keys = set(src) | set(tgt)
    for k in keys:
        d = tgt.get(k, 0) - src.get(k, 0)
        if d < 0:
            missing[k] = -d
        elif d > 0:
            extra[k] = d
    return missing, extra


def _jsonable(counter: Counter) -> dict[str, int]:
    out = {}
    for k, v in counter.items():
        out[str(k)] = int(v)
    return out

