#!/usr/bin/env python3
from eval.coding_checker import (
    assemble,
    coding_invariants,
    freeze_spans,
    mask_head,
    public_output_tokens,
    realized_execution_literals,
    split_question_content,
    starter_identifiers,
    unmask_head,
)


def main():
    lc = (
        "You are given an array of positive integers nums.\n"
        "Return the length of the longest subarray.\n"
        "\n"
        "Example 1:\n"
        "\n"
        "Input: nums = [1,2,1]\n"
        "Output: 5\n"
        "Explanation:\n"
        "The subarray is [1, 2, 1].\n"
        "\n"
        "Constraints:\n"
        "\n"
        "2 <= nums.length <= 100\n"
        "1 <= nums[i] <= 10\n"
    )
    head, tail = split_question_content(lc)
    assert head.startswith("You are given")
    assert "Example 1:" in tail
    assert "Constraints:" in tail
    assert "nums = [1,2,1]" in tail
    assert "Example 1:" not in head

    at = (
        "Each cell contains i \\times j.\n"
        "You are given an integer X. Print Yes if it exists.\n"
        "\n"
        "Input\n"
        "\n"
        "The input is given from Standard Input in the following format:\n"
        "X\n"
        "\n"
        "Constraints\n"
        "\n"
        "- 1 \\leq N \\leq 10^5\n"
        "\n"
        "Sample Input 1\n"
        "\n"
        "1\n"
        "\n"
        "Sample Output 1\n"
        "\n"
        "Yes\n"
    )
    # AtCoder constraints header is "Constraints" without colon sometimes.
    # Our split is first Input, so Constraints stay in tail. Good.
    h2, t2 = split_question_content(at)
    assert "\\times" in h2
    assert t2.lstrip("\n").startswith("Input")
    assert "Sample Input 1" in t2
    assert "Print Yes" in h2

    starter = "class Solution:\n    def maxLength(self, nums: List[int]) -> int:\n"
    idents = starter_identifiers(starter, '{"func_name": "maxLength"}')
    assert "maxLength" in idents
    assert "nums" in idents
    assert "self" not in idents
    assert "List" not in idents

    tests = '[{"input": "[1]", "output": "Yes"}, {"input": "[0]", "output": "No"}]'
    assert public_output_tokens(tests) == ["Yes", "No"]
    realized = realized_execution_literals(h2, tests)
    assert {row["value"] for row in realized} == {"Yes"}
    assert realized[0]["class"] == "print_token"

    spans = freeze_spans(h2, [], ["Yes"])
    masked, frozen = mask_head(h2, spans)
    assert "\\times" not in masked
    assert "⟦" in masked
    assert "Yes" not in masked
    restored, missing = unmask_head(masked, frozen)
    assert missing == []
    assert restored == h2

    # Inequalities freeze operands only, not the English to their left.
    formula_head = (
        "A string word is generated if it satisfies the following conditions "
        "for each index 0 <= i <= n - 1:\n"
        "If str1[i] == 'T', use str2.\n"
    )
    spans_f = freeze_spans(formula_head, ["str1", "str2"], [])
    masked_f, frozen_f = mask_head(formula_head, spans_f)
    assert "following conditions" in masked_f
    assert any("0 <= i <= n" in tok for tok in frozen_f), frozen_f
    assert not any("following" in tok for tok in frozen_f), frozen_f

    # Translator drops a placeholder -> invalid.
    dropped, missing2 = unmask_head("각 칸은 ⟦0⟧.\n정수 X. Print  if it exists.", frozen)
    assert missing2

    ko_head = restored.replace("You are given", "정수").replace("Print Yes if it exists.", "존재하면 Yes.")
    # keep latex and Yes via restore path
    full = assemble(h2.replace("You are given an integer X. Print Yes if it exists.", "정수 X. 존재하면 Yes."), t2)
    inv = coding_invariants(at, full, starter, starter, True, [], realized)
    assert inv["tail_ok"]
    assert inv["starter_ok"]
    assert inv["structure_ok"]

    mutated_tail = full.replace("Sample Output 1", "샘플 출력 1")
    bad = coding_invariants(at, mutated_tail, starter, starter, True, [], realized)
    assert "frozen_tail" in bad["reasons"] or "example_structure" in bad["reasons"]

    starter_bad = coding_invariants(at, full, starter, "def other():\n", True, [], realized)
    assert "starter_bytes" in starter_bad["reasons"]

    # Gold is execution: ordinary print tokens live in tests, not toolcall string match.
    assert realized[0]["class"] == "print_token"

    print("ok")


if __name__ == "__main__":
    main()
