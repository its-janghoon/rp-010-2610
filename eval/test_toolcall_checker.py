#!/usr/bin/env python3
from eval.toolcall_checker import (
    classify_literal,
    identifier_digit_leak,
    realized_answer_literals,
    schema_canonical,
    toolcall_invariants,
)


def main():
    assert classify_literal(10) == "number"
    assert classify_literal("INV-8841") == "opaque_identifier"
    assert classify_literal("Taylor Swift") == "proper_name"
    assert classify_literal("units") == "ordinary_word"
    assert classify_literal("cm") == "opaque_identifier"
    assert classify_literal("") is None

    utt = "Play songs from Taylor Swift for 20 minutes."
    gt = [{"spotify.play": {"artist": ["Taylor Swift"], "duration": [20]}}]
    realized = realized_answer_literals(utt, gt)
    assert {row["value"] for row in realized} == {"Taylor Swift", "20"}, realized

    fn = [{"name": "spotify.play", "parameters": {"a": 1}}]
    good = toolcall_invariants(utt, "Taylor Swift의 곡을 20분 재생.", fn, fn, gt)
    assert good["ok"], good

    dropped = toolcall_invariants(utt, "테일러 스위프트의 곡을 20분 재생.", fn, fn, gt)
    assert dropped["invalidates_item"]
    assert dropped["missing_literals"] == ["Taylor Swift"]
    assert not dropped["ordinary_gold_only"]

    ordinary_utt = "Use units of inches."
    ordinary_gt = [{"f": {"unit": ["inches"]}}]
    miss = toolcall_invariants(
        ordinary_utt, "인치 단위를 사용하세요.", fn, fn, ordinary_gt
    )
    assert miss["ordinary_gold_only"], miss

    mutated = [{"name": "translated.play"}]
    schema_bad = toolcall_invariants(utt, utt, fn, mutated, gt)
    assert "schema_bytes" in schema_bad["reasons"]
    assert schema_canonical(fn) != schema_canonical(mutated)

    assert identifier_digit_leak("North Arc issued INV-8841.", {"8841": 1}) == ["8841"]
    print("ok")


if __name__ == "__main__":
    main()
