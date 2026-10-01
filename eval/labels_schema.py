"""What a public labels row may contain. Model response bodies are forbidden."""

from __future__ import annotations

import json
from typing import Any, Iterable

# Exact names plus substrings that would leak a completion.
FORBIDDEN_KEYS = {
    "response",
    "content",
    "text",
    "output",
    "completion",
    "message",
    "body",
    "raw",
    "generation",
    "answer_text",
    "raw_output",
    "model_output",
    "completion_text",
    "choices",
    "messages",
}

ALLOWED_KEYS = {
    "key",
    "qid",
    "lang",
    "bucket",
    "scorer",
    "model_key",
    "model_id",
    "status",
    "parse_ok",
    "correct",
    "prompt_tokens",
    "completion_tokens",
    "cost_usd",
    "latency_ms",
    "error_class",
    "sandbox",
    "infra_attempt",
    "finish_reason",
    "native_finish_reason",
    "reasoning_tokens",
    "max_tokens",
}

STATUSES = {
    "ok",
    "parse_failed",
    "cap_hit",
    "http_error",
    "timeout",
    "sandbox_timeout",
    "sandbox_network_blocked",
    "sandbox_error",
}


def label_key(model_key: str, qid: str, lang: str) -> str:
    return f"{model_key}|{qid}|{lang}"


def forbidden_key_hits(record: dict) -> list[str]:
    hits = []
    for key in record:
        low = str(key).lower()
        if low in FORBIDDEN_KEYS:
            hits.append(key)
            continue
        if low not in ALLOWED_KEYS and any(part in low for part in FORBIDDEN_KEYS):
            hits.append(key)
    return hits


def audit_labels(rows: Iterable[dict]) -> dict[str, Any]:
    rows = list(rows)
    hits = []
    extra_keys = set()
    for i, row in enumerate(rows):
        bad = forbidden_key_hits(row)
        if bad:
            hits.append({"line": i, "keys": bad})
        extra_keys.update(k for k in row if k not in ALLOWED_KEYS)
    return {
        "n": len(rows),
        "forbidden_hits": hits,
        "extra_keys": sorted(extra_keys),
        "ok": not hits,
    }


def dump_label(record: dict) -> str:
    bad = forbidden_key_hits(record)
    if bad:
        raise ValueError(f"labels must not store response bodies; keys={bad}")
    extra = [k for k in record if k not in ALLOWED_KEYS]
    if extra:
        raise ValueError(f"unknown label keys: {extra}")
    return json.dumps(record, ensure_ascii=False, sort_keys=True)
