"""Instruction constraint-number survival.

For the four IFEval types whose kwargs carry a count, that count is the
scoring contract. If the English prompt states it and the translation
drops it, the item is invalid: the scorer still demands N, the prompt
does not.

Not the same as math quantities. A dropped math number is a solvable
wrong answer. A dropped instruction constraint means no correct output
exists.

kwargs themselves are not translated. This checker only asks whether
values that already appear in the English prompt still appear in the
target (quantity v2 extract).
"""

from __future__ import annotations

from decimal import Decimal

from eval.quantity_checker import extract_v2

CHECKER_ID = "010.constraint_checker"

CONSTRAINT_TYPES = {
    "detectable_content:number_placeholders": ("num_placeholders",),
    "detectable_format:number_bullet_lists": ("num_bullets",),
    "detectable_format:number_highlighted_sections": ("num_highlights",),
    "length_constraints:number_paragraphs": ("num_paragraphs",),
}


def kwargs_constraint_values(instruction_ids: list, kwargs_list: list) -> list[Decimal]:
    vals: list[Decimal] = []
    for iid, kw in zip(instruction_ids or [], kwargs_list or []):
        keys = CONSTRAINT_TYPES.get(iid, ())
        if not kw:
            continue
        for k in keys:
            if k in kw and kw[k] is not None:
                vals.append(Decimal(str(kw[k])))
    return vals


def compare_constraints(
    source: str,
    target: str,
    instruction_ids: list,
    kwargs_list: list,
) -> dict:
    """Fail only when a kwargs count is in the English prompt and missing in target."""
    src_q = extract_v2(source)
    tgt_q = extract_v2(target)
    raw = kwargs_constraint_values(instruction_ids, kwargs_list)
    required = []
    missing = []
    not_in_source = []
    for v in raw:
        if v in src_q:
            required.append(str(v))
            if v not in tgt_q:
                missing.append(str(v))
        else:
            not_in_source.append(str(v))
    return {
        "checker_id": CHECKER_ID,
        "ok": not missing,
        "invalidates_item": bool(missing),
        "kwargs_values": [str(v) for v in raw],
        "required_present_in_english": required,
        "missing_in_target": missing,
        "kwargs_not_in_english_prompt": not_in_source,
    }
