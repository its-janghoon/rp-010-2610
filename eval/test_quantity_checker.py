#!/usr/bin/env python3
from eval.quantity_checker import extract_v2, compare, CHECKER_V1, CHECKER_V2


def vals(text):
    return sorted((str(k), v) for k, v in extract_v2(text).items())


def main():
    # Ordinals must not inject 1/2.
    t = "In the first 20 minutes, in the second 20 minutes, he scores 4 points."
    assert ("1", 1) not in vals(t), vals(t)
    assert ("2", 1) not in vals(t), vals(t)
    assert ("20", 2) in vals(t)

    t2 = "He first stopped after 20 miles. His second stop was 15 miles."
    d = dict(vals(t2))
    assert "1" not in d, d
    assert d.get("20") == 1
    assert d.get("15") == 1

    # twice / 4 / 20  vs 두 배 / 네 배 / 20
    en = "twice as many. Charleston has 4 times. Seattle has 20 sheep."
    ko = "두 배 더 많습니다. 네 배 더 많습니다. 20마리"
    assert compare(en, ko, CHECKER_V2)["ok"], compare(en, ko, CHECKER_V2)

    # Charleston must not yield 4 from चार substring
    hi = "चार्ल्सटन की तुलना में 4 गुना. 20 भेड़ें. दोगुनी"
    assert compare(en, hi, CHECKER_V2)["ok"], (extract_v2(en), extract_v2(hi), compare(en, hi, CHECKER_V2))

    # 두 번째 must not count as 두+번
    d = dict(vals("두 번째 정차 두 번"))
    assert d.get("2") == 1, d

    # 일/이/삼 as ordinary hangul must not fire; 이 is not in the table
    assert extract_v2("이것은 일상이다").total() == 0

    # masking identical
    en_m = extract_v2("Meet on 2026-08-21 use v1.2.3 SKU-ABC-19 qty 3")
    ko_m = extract_v2("2026-08-21에 v1.2.3 과 SKU-ABC-19 수량 3")
    hi_m = extract_v2("2026-08-21 को v1.2.3 और SKU-ABC-19 मात्रा 3")
    assert en_m == ko_m == hi_m == extract_v2("qty 3")

    # v1 still surface-only
    assert not compare("4 times and 20", "네 배 그리고 20", CHECKER_V1)["ok"]

    from decimal import Decimal
    from eval.bucket_check import assert_quantity_version_allowed
    from eval.quantity_checker import CHECKER_V3

    try:
        assert_quantity_version_allowed("coding", CHECKER_V3)
        raise AssertionError("coding must reject v3")
    except ValueError:
        pass
    try:
        compare("one DVD", "1개", CHECKER_V3)
        raise AssertionError("v3 requires calc_values")
    except ValueError:
        pass

    en022 = (
        "Billy sells DVDs. He has 8 customers on Tuesday. His first 3 customers "
        "buy one DVD each.  His next 2 customers buy 2 DVDs each.  His last 3 "
        "customers don't buy any DVDs. How many DVDs did Billy sell on Tuesday?"
    )
    ko022 = (
        "Billy는 DVD를 판매합니다. 그는 화요일에 8명의 고객이 있습니다. 그의 첫 번째 3명의 "
        "고객은 각각 DVD를 1개씩 구매합니다. 그의 다음 2명의 고객은 각각 DVD를 2개씩 구매합니다. "
        "그의 마지막 3명의 고객은 DVD를 전혀 구매하지 않습니다. Billy는 화요일에 DVD를 몇 개 팔았습니까?"
    )
    calc022 = {Decimal(x) for x in ("0", "1", "2", "3", "4", "7")}
    c022 = compare(en022, ko022, CHECKER_V3, calc_values=calc022)
    assert c022["ok"], c022
    assert "1" in c022["source_essential"]

    en163 = (
        "In a room, there are various toys: 5 red cars, 3 action figures, and a doll. "
        "The doll cost as much as 3 action figures and one red car cost $4. How much "
        "are all toys worth, of an action figure costs $5?"
    )
    ko163 = (
        "방 안에는 다양한 장난감들이 있습니다: 5개의 빨간 자동차, 3개의 액션 피규어, 그리고 인형 하나. "
        "인형의 가격은 3개의 액션 피규어와 같고, 빨간 자동차 하나의 가격은 $4입니다. "
        "액션 피규어 하나의 가격이 $5일 때, 모든 장난감의 총 가치는 얼마입니까?"
    )
    hi163 = (
        "एक कमरे में, विभिन्न खिलौने हैं: 5 लाल कारें, 3 एक्शन फिगर्स, और एक गुड़िया। "
        "गुड़िया की कीमत 3 एक्शन फिगर्स के बराबर है और एक लाल कार की कीमत $4 है। "
        "यदि एक एक्शन फिगर की कीमत $5 है, तो सभी खिलौनों की कुल कीमत कितनी है?"
    )
    calc163 = {Decimal(x) for x in ("15", "20", "3", "4", "5", "50")}
    assert not compare(en163, ko163, CHECKER_V2)["ok"]
    assert not compare(en163, hi163, CHECKER_V2)["ok"]
    c163k = compare(en163, ko163, CHECKER_V3, calc_values=calc163)
    c163h = compare(en163, hi163, CHECKER_V3, calc_values=calc163)
    assert c163k["ok"], c163k
    assert c163h["ok"], c163h
    assert "1" not in c163k["source_essential"]

    print("ok")


if __name__ == "__main__":
    main()
