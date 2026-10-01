"""Parse Python-like tool calls and match BFCL possible_answer lists."""

from __future__ import annotations

import ast
import json
import re

CHECKER_ID = "010.toolcall_score"

_CALL = re.compile(
    r"([A-Za-z_][\w.]*)\s*\((.*)\)\s*$",
    re.DOTALL,
)


def _split_top_calls(text: str) -> list[str]:
    s = text.strip()
    if s.startswith("```"):
        s = re.sub(r"^```(?:python|json)?\s*", "", s)
        s = re.sub(r"\s*```$", "", s)
    if s.startswith("["):
        depth = 0
        start = None
        parts = []
        for i, ch in enumerate(s):
            if ch == "[":
                depth += 1
            elif ch == "]":
                depth -= 1
            elif ch == "(" and depth == 1:
                # find matching name start
                pass
        # fallback: find name(...) spans
    spans = []
    i = 0
    n = len(s)
    while i < n:
        if s[i].isalpha() or s[i] == "_":
            j = i
            while j < n and (s[j].isalnum() or s[j] in "._"):
                j += 1
            if j < n and s[j] == "(":
                depth = 0
                k = j
                while k < n:
                    if s[k] == "(":
                        depth += 1
                    elif s[k] == ")":
                        depth -= 1
                        if depth == 0:
                            spans.append(s[i : k + 1])
                            i = k + 1
                            break
                    k += 1
                else:
                    break
                continue
        i += 1
    return spans


def _parse_call(expr: str) -> dict | None:
    expr = expr.strip().rstrip(",")
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError:
        return None
    node = tree.body
    if not isinstance(node, ast.Call):
        return None
    name = _dotted(node.func)
    if not name:
        return None
    args = {}
    for kw in node.keywords:
        if kw.arg is None:
            return None
        try:
            args[kw.arg] = ast.literal_eval(kw.value)
        except (ValueError, TypeError, SyntaxError):
            return None
    if node.args:
        return None
    return {"name": name, "arguments": args}


def _dotted(node) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted(node.value)
        if not base:
            return None
        return f"{base}.{node.attr}"
    return None


def parse_calls(text: str) -> list[dict] | None:
    if not (text or "").strip():
        return None
    raw = text.strip()
    try:
        obj = json.loads(raw)
        if isinstance(obj, dict) and "name" in obj:
            return [{"name": obj["name"], "arguments": obj.get("arguments") or obj.get("parameters") or {}}]
        if isinstance(obj, list) and obj and isinstance(obj[0], dict) and "name" in obj[0]:
            out = []
            for item in obj:
                out.append(
                    {
                        "name": item["name"],
                        "arguments": item.get("arguments") or item.get("parameters") or {},
                    }
                )
            return out
    except json.JSONDecodeError:
        pass
    spans = _split_top_calls(raw)
    if not spans:
        return []
    parsed = []
    for span in spans:
        call = _parse_call(span)
        if call is None:
            return None
        parsed.append(call)
    return parsed


def _value_ok(got, allowed: list) -> bool:
    if got is None:
        return "" in allowed or None in allowed
    for opt in allowed:
        if opt == "":
            continue
        if got == opt:
            return True
        if isinstance(opt, (int, float)) and isinstance(got, (int, float)) and got == opt:
            return True
        if str(got) == str(opt):
            return True
        if isinstance(got, str) and isinstance(opt, str) and got.lower() == opt.lower():
            return True
    return False


def match_possible(calls: list[dict], ground_truth: list) -> bool:
    if not isinstance(ground_truth, list):
        return False
    if len(calls) != len(ground_truth):
        return False
    used = set()
    for call in calls:
        hit = False
        for i, gold in enumerate(ground_truth):
            if i in used or not isinstance(gold, dict) or len(gold) != 1:
                continue
            name, params = next(iter(gold.items()))
            if call["name"] != name:
                continue
            args = call.get("arguments") or {}
            ok = True
            for key, allowed in (params or {}).items():
                if key not in args:
                    if "" in (allowed or []) or None in (allowed or []):
                        continue
                    ok = False
                    break
                if not _value_ok(args[key], list(allowed or [])):
                    ok = False
                    break
            if ok:
                used.add(i)
                hit = True
                break
        if not hit:
            return False
    return len(used) == len(ground_truth)


def score_toolcall(text: str, ground_truth: list) -> dict:
    parsed = parse_calls(text)
    if parsed is None:
        return {"parse_ok": False, "correct": None, "checker_id": CHECKER_ID}
    if parsed == []:
        return {"parse_ok": False, "correct": None, "checker_id": CHECKER_ID}
    return {
        "parse_ok": True,
        "correct": int(match_possible(parsed, ground_truth)),
        "checker_id": CHECKER_ID,
    }


def looks_like_call(text: str) -> bool:
    parsed = parse_calls(text or "")
    return bool(parsed)
