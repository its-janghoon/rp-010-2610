#!/usr/bin/env python3
"""Confirm labels.jsonl stores no model bodies."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from eval.labels_schema import audit_labels  # noqa: E402


def main() -> int:
    path = Path(sys.argv[1] if len(sys.argv) > 1 else ROOT / "results/smoke_deepseek_v4_flash/labels.jsonl")
    rows = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
    report = audit_labels(rows)
    print(json.dumps(report, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
