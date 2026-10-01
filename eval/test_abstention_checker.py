#!/usr/bin/env python3
from eval.abstention_checker import (
    abstention_invariants,
    classify_quantity_residual,
    en_schema_overlap,
    new_schema_leaks,
    schema_tokens,
    token_in_text,
)


def main():
    fn = [
        {
            "name": "determine_body_mass_index",
            "parameters": {
                "type": "dict",
                "properties": {
                    "weight": {"type": "float"},
                    "height": {"type": "float"},
                    "unit": {"type": "string", "enum": ["kg", "lb"]},
                    "a": {"type": "float"},
                },
            },
        }
    ]
    tokens = {(row["kind"], row["token"]) for row in schema_tokens(fn)}
    assert ("fn", "determine_body_mass_index") in tokens
    assert ("param", "weight") in tokens
    assert ("enum", "kg") in tokens
    assert ("param", "a") in tokens

    en = "Calculate the area of a triangle. height is 5 meters."
    # EN already has height; Korean inserting the function name is a new leak.
    ko_leak = "삼각형 넓이를 구하세요. determine_body_mass_index 사용."
    leaks = new_schema_leaks(en, ko_leak, fn)
    assert any(row["token"] == "determine_body_mass_index" for row in leaks), leaks
    assert not any(row["token"] == "height" for row in leaks), leaks

    ko_clean = "밑변 10미터, 높이 5미터인 삼각형의 넓이를 구하세요."
    assert new_schema_leaks(en, ko_clean, fn) == []

    # Param already in EN is overlap, not a new leak, even if kept.
    overlap = en_schema_overlap(en, fn)
    assert any(row["token"] == "height" for row in overlap)
    assert not any(row["token"] == "weight" for row in overlap)

    # New param name that EN did not contain.
    ko_weight = "weight를 넣어서 삼각형 넓이를 구하세요."
    leaks2 = new_schema_leaks(en, ko_weight, fn)
    assert [row["token"] for row in leaks2] == ["weight"], leaks2

    # Short param `a` is not eligible.
    assert not any(row["token"] == "a" for row in new_schema_leaks(en, "a 값을 쓰세요.", fn))

    # Enum newly introduced.
    leaks3 = new_schema_leaks(en, "단위는 kg 로.", fn)
    assert [row["token"] for row in leaks3] == ["kg"], leaks3

    dotted = [{"name": "math.sum", "parameters": {"type": "dict", "properties": {}}}]
    leaks4 = new_schema_leaks("Add these numbers.", "Please use math.sum here.", dotted)
    assert {row["token"] for row in leaks4} >= {"math.sum", "math", "sum"}

    # Boundary: "summer" must not match token "sum".
    assert not token_in_text("sum", "A summer day.")
    assert token_in_text("sum", "the sum is 3")

    held = [{"name": "other"}]
    bad = abstention_invariants(en, ko_clean, fn, held)
    assert bad["invalidates_item"]
    assert "schema_bytes" in bad["reasons"]
    assert not bad["schema_proximity_leak"]

    good = abstention_invariants(en, ko_clean, fn, fn)
    assert good["ok"]
    assert good["schema_ok"]

    leak_row = abstention_invariants(en, ko_leak, fn, fn)
    assert leak_row["schema_proximity_leak"]
    assert not leak_row["invalidates_item"]  # report, do not invalidate

    date_en = "Meet on 2024-03-15 at the park."
    date_drop = abstention_invariants(date_en, "공원에서 만나자.", fn, fn)
    assert "date_or_iso" in date_drop["reasons"]

    assert (
        classify_quantity_residual("18th century France", "18세기 프랑스", {"18": 1}, [])
        == "ordinal_quantity_promotion"
    )
    assert (
        classify_quantity_residual("two different funds", "두 개의 펀드", {"2": 1}, [])
        == "count_word_promotion"
    )
    assert (
        classify_quantity_residual("a deck of cards", "카드 한 벌", {"1": 1}, [])
        == "grammatical_one"
    )
    assert (
        classify_quantity_residual("INV-8841 issued", "INV-8841 발행", {"8841": 1}, ["8841"])
        == "identifier_digit_leak"
    )
    print("ok")


if __name__ == "__main__":
    main()
