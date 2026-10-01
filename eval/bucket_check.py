"""Bucket-specific checkers.

math     quantity v3 (essential vs reference via GSM8K <<calc>>).
         v1/v2 remain for lineage. juletxara/mgsm equation_solution is empty.
instruction
         quantity v2, markdown/bracket markers, and kwargs constraint-number
         survival. A dropped constraint count invalidates the item.
coding, extraction, toolcall, abstention, knowledge
         quantity v2. Identifiers, SKUs, dates, versions, JSON keys,
         schemas stay exact string match. Do not use math v3.
"""

from __future__ import annotations

MATH = "math"
QUANTITY_V3_BUCKETS = {MATH}

CHECKER_BY_BUCKET = {
    "math": "v3",
    "instruction": "v2",
    "extraction": "v2",
    "toolcall": "v2",
    "abstention": "v2",
    "coding": "v2",
    "knowledge": "v2",
}


def quantity_version_for_bucket(bucket: str) -> str:
    if bucket not in CHECKER_BY_BUCKET:
        raise KeyError(f"unknown bucket: {bucket}")
    return CHECKER_BY_BUCKET[bucket]


def assert_quantity_version_allowed(bucket: str, version: str) -> None:
    if version == "v3" and bucket not in QUANTITY_V3_BUCKETS:
        raise ValueError(
            f"quantity checker {version} is math-only; bucket={bucket} "
            "must keep identifier/SKU/date exact match"
        )
