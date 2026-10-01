"""Instruction-bucket markdown/bracket marker preservation.

Counts must match between source prompt and translation.
Longest-first so ****** is not six * and *** is not three *.
Hyphen is counted only as a standalone token, not inside 7-day / URLs.

kwargs are not scored here. They are not sent to the translator.
"""

from __future__ import annotations

import re
from collections import Counter

CHECKER_ID = "010.marker_checker"

# User-listed instruction markers, plus markdown ticks used by json_format examples.
STAR_TOKENS = ("******", "***", "**", "*")
PAIR_TOKENS = ("<<", ">>")
BRACKETS = ("[", "]")
FENCE = "```"

# Markdown hyphen: line-start bullet or a hyphen token with whitespace
# on both sides. Not 7-day, not Hindi  अलग-अलग.
_HYPHEN = re.compile(r"(?m)(?:^[ \t]*-(?:\s|$)|(?<=\s)-(?=\s))")


def extract_markers(text: str) -> Counter:
    raw = text or ""
    counts: Counter = Counter()
    i = 0
    n = len(raw)
    while i < n:
        if raw.startswith(FENCE, i):
            counts[FENCE] += 1
            i += len(FENCE)
            continue
        hit = None
        for tok in STAR_TOKENS + PAIR_TOKENS:
            if raw.startswith(tok, i):
                hit = tok
                break
        if hit:
            counts[hit] += 1
            i += len(hit)
            continue
        ch = raw[i]
        if ch in BRACKETS:
            counts[ch] += 1
        i += 1
    counts["-"] = len(_HYPHEN.findall(raw))
    return counts


def compare_markers(source: str, target: str) -> dict:
    src = extract_markers(source)
    tgt = extract_markers(target)
    keys = set(src) | set(tgt)
    missing = {}
    extra = {}
    for k in keys:
        d = tgt.get(k, 0) - src.get(k, 0)
        if d < 0:
            missing[k] = -d
        elif d > 0:
            extra[k] = d
    return {
        "checker_id": CHECKER_ID,
        "ok": not missing and not extra,
        "source": dict(src),
        "target": dict(tgt),
        "missing": missing,
        "extra": extra,
    }
