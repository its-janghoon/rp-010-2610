#!/usr/bin/env python3
from eval.labels_schema import audit_labels, dump_label, forbidden_key_hits
from eval.outcome import classify_outcome, hit_cap
from eval.s_exec import extract_code, run_tests
from eval.scorers import SCORERS, score_abstain, score_exact, score_json_match, score_mcq
from eval.toolcall_score import parse_calls, score_toolcall
from eval.ifeval_score import score as ifeval_score


def test_s_exec():
    stdin = [{"input": "3x8\n", "output": "24", "testtype": "stdin"}]
    code = "s=input().strip()\nprint(int(s[0])*int(s[2]))\n"
    r = run_tests(code, stdin, timeout_s=2)
    assert r["ok"] and r["kind"] == "ok", r

    r_to = run_tests("while True:\n    pass\n", stdin, timeout_s=1)
    assert r_to["kind"] == "timeout", r_to

    net = "import urllib.request\nurllib.request.urlopen('http://example.com')\nprint(1)\n"
    r_net = run_tests(net, [{"input": "x\n", "output": "1", "testtype": "stdin"}], timeout_s=3)
    assert r_net["kind"] in {"network_blocked", "runtime", "fail"}, r_net

    fn = '''
class Solution:
    def findValidPair(self, s: str) -> str:
        from collections import Counter
        c = Counter(s)
        for i in range(len(s)-1):
            a,b = s[i], s[i+1]
            if a!=b and c[a]==int(a) and c[b]==int(b):
                return a+b
        return ""
'''
    tests = [
        {"input": '"2523533"', "output": '"23"', "testtype": "functional"},
        {"input": '"221"', "output": '"21"', "testtype": "functional"},
        {"input": '"22"', "output": '""', "testtype": "functional"},
    ]
    r_fn = run_tests(fn, tests, fn_name="findValidPair", timeout_s=2)
    assert r_fn["ok"], r_fn


def test_extract_code():
    assert "print(1)" in (extract_code("```python\nprint(1)\n```") or "")
    assert extract_code("") is None


def test_scorers():
    assert score_mcq("The answer is C.", {"answer": "C", "answer_index": 2, "options": ["a", "b", "c"]})["correct"] == 1
    assert score_mcq("", {"answer": "C", "answer_index": 2})["parse_ok"] is False
    assert score_exact("work\n#### 260", {"answer_number": 260})["correct"] == 1
    assert score_exact("no number", {"answer_number": 1})["parse_ok"] is False
    gold = {"gold": {"vendor": "Orbit Labs", "total": 1840, "paid": False}}
    assert score_json_match('{"vendor":"Orbit Labs","total":1840,"paid":false}', gold)["correct"] == 1
    assert score_json_match("not json", gold)["parse_ok"] is False
    gt = [{"geometry.circumference": {"radius": [3], "units": ["cm", ""]}}]
    assert score_toolcall("geometry.circumference(radius=3)", gt)["correct"] == 1
    assert parse_calls("[foo(a=1), bar(b='x')]") == [
        {"name": "foo", "arguments": {"a": 1}},
        {"name": "bar", "arguments": {"b": "x"}},
    ]
    assert score_toolcall("hello", gt)["parse_ok"] is False
    assert score_toolcall("foo(bar=unquoted)", gt)["parse_ok"] is False
    assert score_abstain("I cannot help with that.")["correct"] == 1
    assert score_abstain("draw_circle(radius=1.0, unit='m')")["correct"] == 0
    assert ifeval_score("<<Hello>>\nbody", ["detectable_format:title"], [{}])["correct"] == 1
    assert set(SCORERS) == {"mcq", "exact", "ast", "abstain", "exec", "ifeval", "json_match"}


def test_labels_forbid_bodies():
    rec = {
        "key": "m|q|en",
        "qid": "q",
        "lang": "en",
        "bucket": "math",
        "scorer": "exact",
        "model_key": "m",
        "model_id": "x",
        "status": "ok",
        "parse_ok": True,
        "correct": 1,
        "prompt_tokens": 1,
        "completion_tokens": 1,
        "cost_usd": 0.0,
        "latency_ms": 1,
        "error_class": None,
        "sandbox": None,
    }
    dump_label(rec)
    bad = dict(rec)
    bad["response"] = "secret"
    assert forbidden_key_hits(bad) == ["response"]
    assert audit_labels([rec])["ok"]


def test_cap_hit_status():
    assert hit_cap("length", 100, 8192) is True
    assert hit_cap("stop", 8192, 8192) is True
    assert hit_cap("stop", 8191, 8192) is False
    st, corr = classify_outcome(
        sandbox_status=None,
        parse_ok=True,
        finish_reason="length",
        completion_tokens=100,
        cap=8192,
    )
    assert st == "cap_hit" and corr == 0
    st, corr = classify_outcome(
        sandbox_status="sandbox_error",
        parse_ok=True,
        finish_reason="length",
        completion_tokens=4096,
        cap=32768,
    )
    assert st == "cap_hit" and corr == 0
    st, corr = classify_outcome(
        sandbox_status="sandbox_error",
        parse_ok=True,
        finish_reason="stop",
        completion_tokens=100,
        cap=8192,
    )
    assert st == "sandbox_error" and corr is None
    st, corr = classify_outcome(
        sandbox_status=None,
        parse_ok=False,
        finish_reason="stop",
        completion_tokens=12,
        cap=8192,
    )
    assert st == "parse_failed" and corr == 0


def main():
    test_s_exec()
    test_extract_code()
    test_scorers()
    test_labels_forbid_bodies()
    test_cap_hit_status()
    print("ok")


if __name__ == "__main__":
    main()
