"""Seven run scorers. Translation checkers are not run scorers."""

from __future__ import annotations

import json
import re
from typing import Any

from eval.ifeval_score import score as ifeval_score
from eval.s_exec import extract_code, run_tests
from eval.toolcall_score import looks_like_call, parse_calls, score_toolcall

SCORERS = ("mcq", "exact", "ast", "abstain", "exec", "ifeval", "json_match")
# translation was the 8th task scorer; it is not a run scorer.

_LETTER = re.compile(r"\b([A-J])\b")
_NUM = re.compile(r"-?\d+(?:\.\d+)?")


def score_mcq(text: str, gold: dict) -> dict:
    if not (text or "").strip():
        return {"parse_ok": False, "correct": None}
    t = text.strip().upper()
    ans = str(gold["answer"]).strip().upper()
    idx = int(gold["answer_index"])
    # last standalone letter
    letters = _LETTER.findall(t)
    if letters:
        got = letters[-1]
        return {"parse_ok": True, "correct": int(got == ans)}
    options = gold.get("options") or []
    if idx < len(options) and options[idx] and options[idx] in text:
        return {"parse_ok": True, "correct": 1}
    return {"parse_ok": False, "correct": None}


def score_exact(text: str, gold: dict) -> dict:
    if not (text or "").strip():
        return {"parse_ok": False, "correct": None}
    nums = _NUM.findall(text.replace(",", ""))
    if not nums:
        return {"parse_ok": False, "correct": None}
    got = float(nums[-1])
    exp = float(gold["answer_number"])
    return {"parse_ok": True, "correct": int(got == exp)}


def _json_obj(text: str) -> dict | None:
    s = (text or "").strip()
    if not s:
        return None
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?\s*", "", s)
        s = re.sub(r"\s*```$", "", s)
    try:
        obj = json.loads(s)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        a, b = s.find("{"), s.rfind("}")
        if a >= 0 and b > a:
            try:
                obj = json.loads(s[a : b + 1])
                return obj if isinstance(obj, dict) else None
            except json.JSONDecodeError:
                return None
        return None


def _norm(v):
    if isinstance(v, list):
        return [_norm(x) for x in v]
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return v
    if isinstance(v, str) and v.lower() in {"true", "false"}:
        return v.lower() == "true"
    return v


def score_json_match(text: str, gold: dict) -> dict:
    obj = _json_obj(text)
    if obj is None:
        return {"parse_ok": False, "correct": None}
    g = gold["gold"]
    ok = True
    for k, exp in g.items():
        if k not in obj:
            ok = False
            break
        if _norm(obj[k]) != _norm(exp):
            ok = False
            break
    if ok and set(obj) != set(g):
        # extra keys still fail exact match
        ok = False
    return {"parse_ok": True, "correct": int(ok)}


def score_abstain(text: str) -> dict:
    if not (text or "").strip():
        return {"parse_ok": False, "correct": None}
    parsed = parse_calls(text)
    if parsed is None:
        return {"parse_ok": True, "correct": 1}  # prose, not a call
    if parsed:
        return {"parse_ok": True, "correct": 0}
    return {"parse_ok": True, "correct": 1}


def score_exec(text: str, gold: dict) -> dict:
    code = extract_code(text)
    if not code:
        return {"parse_ok": False, "correct": None, "sandbox": None}
    result = run_tests(
        code,
        gold["tests"],
        starter=gold.get("starter") or "",
        fn_name=gold.get("fn_name") or "",
    )
    kind = result.get("kind")
    if kind == "timeout":
        return {"parse_ok": True, "correct": 0, "sandbox": "timeout", "status": "sandbox_timeout"}
    if kind == "network_blocked":
        return {
            "parse_ok": True,
            "correct": 0,
            "sandbox": "network_blocked",
            "status": "sandbox_network_blocked",
        }
    if kind == "error":
        return {"parse_ok": True, "correct": 0, "sandbox": "error", "status": "sandbox_error"}
    return {
        "parse_ok": True,
        "correct": int(bool(result.get("ok"))),
        "sandbox": kind,
    }


def score(scorer: str, text: str, gold: dict) -> dict:
    if scorer == "mcq":
        return score_mcq(text, gold)
    if scorer == "exact":
        return score_exact(text, gold)
    if scorer == "ast":
        return score_toolcall(text, gold["ground_truth"])
    if scorer == "abstain":
        return score_abstain(text)
    if scorer == "exec":
        return score_exec(text, gold)
    if scorer == "ifeval":
        return ifeval_score(text, gold["instruction_id_list"], gold.get("kwargs") or [])
    if scorer == "json_match":
        return score_json_match(text, gold)
    raise KeyError(scorer)
