#!/usr/bin/env python3
from eval.marker_checker import extract_markers, compare_markers


def main():
    six = "Separate with 6 asterisk symbols: ******."
    assert extract_markers(six)["******"] == 1
    assert extract_markers(six).get("*", 0) == 0

    seven = "exactly 6 asterisks symbols: *******"
    d = extract_markers(seven)
    assert d["******"] == 1 and d["*"] == 1, d

    para = "Separate the paragraphs with the markdown divider: ***"
    assert extract_markers(para)["***"] == 1
    assert extract_markers(para).get("*", 0) == 0

    hl = "Highlight like *highlighted text*."
    assert extract_markers(hl)["*"] == 2

    ph = "placeholders such as [address], [name]"
    d = extract_markers(ph)
    assert d["["] == 2 and d["]"] == 2

    title = "wrapped in double angular brackets, i.e. <<title>>."
    d = extract_markers(title)
    assert d["<<"] == 1 and d[">>"] == 1

    bullets = "* Bullet point one.\n* Bullet point two."
    assert extract_markers(bullets)["*"] == 2

    fence = "markdown ticks such as ```."
    assert extract_markers(fence)["```"] == 1

    # 7-day must not count as a markdown hyphen.
    assert extract_markers("a 7-day trip")["-"] == 0
    assert extract_markers("use * or - for bullets")["-"] == 1
    assert extract_markers("दो अलग-अलग उत्तर")["-"] == 0

    ko = "6개의 별표로 구분: ******."
    assert compare_markers(six, ko)["ok"]

    broken = "6개의 별표로 구분."
    c = compare_markers(six, broken)
    assert not c["ok"] and c["missing"].get("******") == 1

    print("ok")


if __name__ == "__main__":
    main()
