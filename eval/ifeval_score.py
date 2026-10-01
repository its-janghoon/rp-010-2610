"""IFEval scoring for the 7 adopted instruction types."""

from __future__ import annotations

import json
import re

CHECKER_ID = "010.ifeval_score"

_PLACEHOLDER = re.compile(r"\[[^\]]+\]")
_HIGHLIGHT = re.compile(r"\*[^*]+\*")
_TITLE = re.compile(r"<<([^>]+)>>")
_BULLET = re.compile(r"(?m)^\s*\*\s+\S")


def two_responses(text: str) -> bool:
    if text.count("******") != 1:
        return False
    left, right = text.split("******", 1)
    return bool(left.strip()) and bool(right.strip())


def n_placeholders(text: str, n: int) -> bool:
    return len(_PLACEHOLDER.findall(text)) >= n


def json_format(text: str) -> bool:
    blob = text.strip()
    if blob.startswith("```"):
        blob = re.sub(r"^```(?:json)?\s*", "", blob)
        blob = re.sub(r"\s*```$", "", blob)
    try:
        json.loads(blob)
        return True
    except json.JSONDecodeError:
        start = blob.find("{")
        end = blob.rfind("}")
        if start >= 0 and end > start:
            try:
                json.loads(blob[start : end + 1])
                return True
            except json.JSONDecodeError:
                return False
        return False


def n_bullets(text: str, n: int) -> bool:
    return len(_BULLET.findall(text)) >= n


def n_highlights(text: str, n: int) -> bool:
    return len(_HIGHLIGHT.findall(text)) >= n


def has_title(text: str) -> bool:
    return bool(_TITLE.search(text))


def n_paragraphs(text: str, n: int) -> bool:
    parts = [p.strip() for p in re.split(r"\n\s*\n", text.strip()) if p.strip()]
    return len(parts) == n


def score(text: str, instruction_ids: list[str], kwargs_list: list[dict]) -> dict:
    if not (text or "").strip():
        return {"parse_ok": False, "correct": None, "checker_id": CHECKER_ID}
    ok = True
    for iid, kw in zip(instruction_ids, kwargs_list or [{}] * len(instruction_ids)):
        kw = kw or {}
        if iid == "combination:two_responses":
            ok = ok and two_responses(text)
        elif iid == "detectable_content:number_placeholders":
            ok = ok and n_placeholders(text, int(kw.get("num_placeholders") or 0))
        elif iid == "detectable_format:json_format":
            ok = ok and json_format(text)
        elif iid == "detectable_format:number_bullet_lists":
            ok = ok and n_bullets(text, int(kw.get("num_bullets") or 0))
        elif iid == "detectable_format:number_highlighted_sections":
            ok = ok and n_highlights(text, int(kw.get("num_highlights") or 0))
        elif iid == "detectable_format:title":
            ok = ok and has_title(text)
        elif iid == "length_constraints:number_paragraphs":
            ok = ok and n_paragraphs(text, int(kw.get("num_paragraphs") or 0))
        else:
            raise ValueError(iid)
    return {"parse_ok": True, "correct": int(ok), "checker_id": CHECKER_ID}
