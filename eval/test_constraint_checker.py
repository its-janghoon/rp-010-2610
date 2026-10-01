#!/usr/bin/env python3
from eval.constraint_checker import compare_constraints, kwargs_constraint_values


def main():
    ids = ["length_constraints:number_paragraphs"]
    kw = [{"num_paragraphs": 2}]
    assert [str(x) for x in kwargs_constraint_values(ids, kw)] == ["2"]

    en = (
        "Write a story of exactly 2 paragraphs about a man who wakes up one day. "
        "Separate the paragraphs with the markdown divider: ***"
    )
    hi_drop = (
        "एक ऐसी कहानी लिखिए जिसमें एक आदमी एक दिन जागता है। "
        "पैराग्राफ़ को निम्नलिखित मार्कडाउन डिवाइडर से अलग करें: ***"
    )
    hi_ok = (
        "एक आदमी के बारे में ठीक 2 पैराग्राफ की कहानी लिखें। "
        "पैराग्राफ़ को मार्कडाउन डिवाइडर से अलग करें: ***"
    )
    ko_ok = "정확히 2단락으로 작성하세요. 구분선: ***"
    drop = compare_constraints(en, hi_drop, ids, kw)
    assert not drop["ok"] and drop["invalidates_item"] and "2" in drop["missing_in_target"], drop
    assert compare_constraints(en, hi_ok, ids, kw)["ok"]
    assert compare_constraints(en, ko_ok, ids, kw)["ok"]

    # kwargs 1 is the contract but the English prompt never states 1.
    # Survival does not invent a number that was not in the source.
    ids_h = ["detectable_format:number_highlighted_sections"]
    kw_h = [{"num_highlights": 1}]
    en_h = 'Highlight some key parts with "*", like *highlighted text*.'
    c = compare_constraints(en_h, en_h, ids_h, kw_h)
    assert c["ok"]
    assert c["kwargs_not_in_english_prompt"] == ["1"]

    # placeholder "one" is in English and in kwargs.
    ids_p = ["detectable_content:number_placeholders"]
    kw_p = [{"num_placeholders": 1}]
    en_p = "Include at least one placeholder represented by square brackets."
    hi_p = "कम से कम एक प्लेसहोल्डर शामिल करें"
    c = compare_constraints(en_p, hi_p, ids_p, kw_p)
    assert not c["ok"] and "1" in c["missing_in_target"]

    print("ok")


if __name__ == "__main__":
    main()
