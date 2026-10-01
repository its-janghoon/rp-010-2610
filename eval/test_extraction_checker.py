#!/usr/bin/env python3
from eval.extraction_checker import (
    extraction_invariants,
    protected_gold_literals,
    query_schema,
)


def main():
    en = "Invoice from Orbit Labs dated 2026-03-12. Total due: 1840 USD. Status: unpaid."
    gold = {
        "vendor": "Orbit Labs",
        "date": "2026-03-12",
        "total": 1840,
        "currency": "USD",
        "paid": False,
    }
    assert protected_gold_literals(en, gold) == [
        "2026-03-12",
        "Orbit Labs",
        "1840",
        "USD",
    ]
    schema = query_schema(gold, None)
    good = extraction_invariants(en, "Orbit Labs 청구서 날짜 2026-03-12. 합계: 1840 USD.", gold, gold, schema)
    assert good["ok"], good

    transliterated = extraction_invariants(
        en,
        "오르빗 랩스 청구서 날짜 2026-03-12. 합계: 1840 USD.",
        gold,
        gold,
        schema,
    )
    assert transliterated["invalidates_item"], transliterated
    assert transliterated["missing_gold_literals"] == ["Orbit Labs"], transliterated

    appt_en = "Appointment for A. Novak on 2026-09-02 at 14:30 in cardiology."
    appt_gold = {
        "patient": "A. Novak",
        "date": "2026-09-02",
        "time": "14:30",
        "dept": "cardiology",
    }
    enums = {"dept": ["cardiology", "dentistry", "oncology"]}
    assert "cardiology" not in protected_gold_literals(appt_en, appt_gold, enums)
    assert "A. Novak" in protected_gold_literals(appt_en, appt_gold, enums)
    translated_ok = extraction_invariants(
        appt_en,
        "A. Novak 예약 날짜 2026-09-02 시각 14:30, 심장내과.",
        appt_gold,
        appt_gold,
        query_schema(appt_gold, enums),
        enums,
    )
    assert translated_ok["ok"], translated_ok

    unit_en = "SKU NB-4401, weight 1280 g."
    unit_gold = {"sku": "NB-4401", "weight_g": 1280}
    unit_bad = extraction_invariants(
        unit_en,
        "SKU NB-4401, 무게 1280그램.",
        unit_gold,
        unit_gold,
        query_schema(unit_gold),
    )
    assert "unit" in unit_bad["reasons"] and unit_bad["missing_units"] == ["1280 g"], unit_bad

    key_bad = extraction_invariants(
        unit_en,
        "SKU NB-4401, 무게 1280 g.",
        unit_gold,
        unit_gold,
        '{"sku": ..., "무게": ...}',
    )
    assert key_bad["missing_schema_keys"] == ["weight_g"], key_bad
    print("ok")


if __name__ == "__main__":
    main()
