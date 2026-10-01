#!/usr/bin/env python3
"""Item-level coding-cell hold: fable vs grok43, all-model ranks, top-3 swaps."""

from __future__ import annotations

import csv
import hashlib
import json
from itertools import product
from pathlib import Path

from compute_static_lookup_pareto import (
    LANGS,
    RUN_A,
    RUN_B,
    billed,
    cell,
    correct,
    load_run,
    stable_correct,
    usable,
)

ROOT = Path(__file__).resolve().parents[1]
OUT_JSON = ROOT / "reports/coding_cell_hold.json"
OUT_MD = ROOT / "reports/coding_cell_hold.md"
CODING14 = ROOT / "data/coding14_translated.jsonl"
LOOKUP_CSV = ROOT / "reports/static_lookup_21.csv"
FROZEN_BUCKETS = {
    "knowledge",
    "math",
    "instruction",
    "extraction",
    "toolcall",
    "abstention",
}
FABLE = "claude_fable_5"
GROK43 = "grok_4_3"


def load_difficulty() -> dict[str, dict[str, str]]:
    out = {}
    for line in CODING14.read_text().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        out[row["qid"]] = {
            "difficulty": row["difficulty"],
            "platform": row["platform"],
        }
    return out


def frozen_from_csv() -> dict[tuple[str, str], str]:
    selected = {}
    with LOOKUP_CSV.open() as handle:
        for row in csv.DictReader(handle):
            if row["bucket"] in FROZEN_BUCKETS:
                selected[(row["bucket"], row["lang"])] = row["selected_model"]
    assert len(selected) == 18
    return selected


def item_row(run_a, run_b, model: str, qid: str, lang: str) -> dict:
    a = cell(run_a, model, qid, lang)
    b = cell(run_b, model, qid, lang)
    return {
        "qid": qid,
        "lang": lang,
        "model": model,
        "a_correct": bool(correct(a)),
        "b_correct": bool(correct(b)),
        "stable": bool(stable_correct(a, b)),
        "a_usable": bool(usable(a)),
        "b_usable": bool(usable(b)),
        "a_status": a.get("status"),
        "b_status": b.get("status"),
        "cost_a": a.get("cost_usd"),
        "cost_b": b.get("cost_usd"),
    }


def model_cell_stats(run_a, run_b, model: str, qids: list[str], lang: str) -> dict:
    pairs = [(cell(run_a, model, qid, lang), cell(run_b, model, qid, lang)) for qid in qids]
    cost_a = billed([a for a, _ in pairs])
    cost_b = billed([b for _, b in pairs])
    combined = cost_a["n_billed"] + cost_b["n_billed"]
    return {
        "model": model,
        "stable_correct": sum(stable_correct(a, b) for a, b in pairs),
        "a_correct": sum(correct(a) for a, _ in pairs),
        "b_correct": sum(correct(b) for _, b in pairs),
        "stable_n": sum(usable(a) and usable(b) for a, b in pairs),
        "cost_a": cost_a,
        "cost_b": cost_b,
        "mean_billed_cost": (cost_a["cost"] + cost_b["cost"]) / 2,
        "mean_billed_per_request": (
            (cost_a["cost"] + cost_b["cost"]) / combined if combined else None
        ),
        "infra_qids": [
            qid
            for qid, (a, b) in zip(qids, pairs)
            if (not usable(a)) or (not usable(b))
        ],
    }


def pair_compare(run_a, run_b, left: str, right: str, qids: list[str], lang: str, meta: dict) -> dict:
    items = []
    for qid in qids:
        l = item_row(run_a, run_b, left, qid, lang)
        r = item_row(run_a, run_b, right, qid, lang)
        items.append(
            {
                "qid": qid,
                "difficulty": meta[qid]["difficulty"],
                "platform": meta[qid]["platform"],
                left: l,
                right: r,
                "stable_left_only": l["stable"] and not r["stable"],
                "stable_right_only": r["stable"] and not l["stable"],
                "stable_both": l["stable"] and r["stable"],
                "stable_neither": (not l["stable"]) and (not r["stable"]),
                "a_left_only": l["a_correct"] and not r["a_correct"],
                "a_right_only": r["a_correct"] and not l["a_correct"],
                "b_left_only": l["b_correct"] and not r["b_correct"],
                "b_right_only": r["b_correct"] and not l["b_correct"],
            }
        )
    left_only = [row["qid"] for row in items if row["stable_left_only"]]
    right_only = [row["qid"] for row in items if row["stable_right_only"]]
    both = [row["qid"] for row in items if row["stable_both"]]
    neither = [row["qid"] for row in items if row["stable_neither"]]
    left_only_hard = [row["qid"] for row in items if row["stable_left_only"] and row["difficulty"] == "hard"]
    return {
        "lang": lang,
        "left": left,
        "right": right,
        "stable_left": sum(row[left]["stable"] for row in items),
        "stable_right": sum(row[right]["stable"] for row in items),
        "stable_delta_left_minus_right": sum(row[left]["stable"] for row in items)
        - sum(row[right]["stable"] for row in items),
        "a_left": sum(row[left]["a_correct"] for row in items),
        "a_right": sum(row[right]["a_correct"] for row in items),
        "b_left": sum(row[left]["b_correct"] for row in items),
        "b_right": sum(row[right]["b_correct"] for row in items),
        "a_delta": sum(row[left]["a_correct"] for row in items)
        - sum(row[right]["a_correct"] for row in items),
        "b_delta": sum(row[left]["b_correct"] for row in items)
        - sum(row[right]["b_correct"] for row in items),
        "stable_left_only_qids": left_only,
        "stable_right_only_qids": right_only,
        "stable_both_qids": both,
        "stable_neither_qids": neither,
        "stable_left_only_hard_qids": left_only_hard,
        "items": items,
    }


def policy_score(run_a, run_b, frozen: dict, coding_models: dict[str, str], qids_by_bucket: dict) -> dict:
    hits = 0
    cost_a = 0.0
    cost_b = 0.0
    n_billed_a = 0
    n_billed_b = 0
    coding_hits = 0
    coding_cost_mean = 0.0
    for bucket, lang_qids in qids_by_bucket.items():
        qids = sorted(lang_qids)
        for lang in LANGS:
            model = frozen[(bucket, lang)] if bucket != "coding" else coding_models[lang]
            pairs = [(cell(run_a, model, qid, lang), cell(run_b, model, qid, lang)) for qid in qids]
            cell_hits = sum(stable_correct(a, b) for a, b in pairs)
            hits += cell_hits
            ca = billed([a for a, _ in pairs])
            cb = billed([b for _, b in pairs])
            cost_a += ca["cost"]
            cost_b += cb["cost"]
            n_billed_a += ca["n_billed"]
            n_billed_b += cb["n_billed"]
            if bucket == "coding":
                coding_hits += cell_hits
                coding_cost_mean += (ca["cost"] + cb["cost"]) / 2
    return {
        "coding_models": coding_models,
        "stable_correct": hits,
        "stable_accuracy_matrix": hits / 294,
        "coding_stable_correct": coding_hits,
        "noncoding_stable_correct": hits - coding_hits,
        "cost_a": cost_a,
        "cost_b": cost_b,
        "mean_billed_cost": (cost_a + cost_b) / 2,
        "n_billed_a": n_billed_a,
        "n_billed_b": n_billed_b,
        "coding_mean_billed_cost": coding_cost_mean,
    }


def fmt_usd(value: float) -> str:
    return f"${value:.6f}"


def main() -> int:
    run_a = load_run(RUN_A)
    run_b = load_run(RUN_B)
    models = sorted(run_a)
    meta = load_difficulty()
    frozen = frozen_from_csv()
    exemplar = next(iter(run_a.values()))
    qids_by_bucket = {}
    for row in exemplar.values():
        qids_by_bucket.setdefault(row["bucket"], set()).add(row["qid"])
    coding_qids = sorted(qids_by_bucket["coding"])
    assert len(coding_qids) == 14
    hard_qids = [qid for qid in coding_qids if meta[qid]["difficulty"] == "hard"]
    assert len(hard_qids) == 6

    ranks = {}
    top3 = {}
    for lang in LANGS:
        stats = [model_cell_stats(run_a, run_b, model, coding_qids, lang) for model in models]
        stats.sort(
            key=lambda row: (
                -row["stable_correct"],
                row["mean_billed_per_request"],
                row["model"],
            )
        )
        ranks[lang] = stats
        top3[lang] = stats[:3]

    compares = {
        lang: pair_compare(run_a, run_b, FABLE, GROK43, coding_qids, lang, meta)
        for lang in ("ko", "hi")
    }
    en_compare = pair_compare(run_a, run_b, GROK43, FABLE, coding_qids, "en", meta)

    current_coding = {"ko": FABLE, "en": GROK43, "hi": FABLE}
    current = policy_score(run_a, run_b, frozen, current_coding, qids_by_bucket)

    combos = []
    for ko_m, en_m, hi_m in product(
        [row["model"] for row in top3["ko"]],
        [row["model"] for row in top3["en"]],
        [row["model"] for row in top3["hi"]],
    ):
        coding_models = {"ko": ko_m, "en": en_m, "hi": hi_m}
        scored = policy_score(run_a, run_b, frozen, coding_models, qids_by_bucket)
        combos.append(scored)
    combos.sort(key=lambda row: (-row["stable_correct"], row["mean_billed_cost"]))

    named = {
        "current_hold_argmax": current,
        "coding_all_grok_4_3": policy_score(
            run_a, run_b, frozen, {"ko": GROK43, "en": GROK43, "hi": GROK43}, qids_by_bucket
        ),
        "coding_all_fable": policy_score(
            run_a, run_b, frozen, {"ko": FABLE, "en": FABLE, "hi": FABLE}, qids_by_bucket
        ),
        "coding_top3_cheapest": policy_score(
            run_a,
            run_b,
            frozen,
            {lang: min(top3[lang], key=lambda row: row["mean_billed_cost"])["model"] for lang in LANGS},
            qids_by_bucket,
        ),
        "coding_rank2_each_lang": policy_score(
            run_a,
            run_b,
            frozen,
            {lang: top3[lang][1]["model"] for lang in LANGS},
            qids_by_bucket,
        ),
    }

    run_solo = {}
    for lang in LANGS:
        a_best = max(row["a_correct"] for row in ranks[lang])
        b_best = max(row["b_correct"] for row in ranks[lang])
        run_solo[lang] = {
            "a_best": a_best,
            "b_best": b_best,
            "a_tied_models": [row["model"] for row in ranks[lang] if row["a_correct"] == a_best],
            "b_tied_models": [row["model"] for row in ranks[lang] if row["b_correct"] == b_best],
            "stable_best_model": ranks[lang][0]["model"],
            "stable_best": ranks[lang][0]["stable_correct"],
        }

    infra_rows = []
    for lang in LANGS:
        for row in ranks[lang]:
            if row["infra_qids"]:
                infra_rows.append(
                    {
                        "lang": lang,
                        "model": row["model"],
                        "infra_qids": row["infra_qids"],
                        "stable_correct": row["stable_correct"],
                        "stable_n": row["stable_n"],
                        "matrix_denom": 14,
                    }
                )

    opus = {
        "stable_correct": 245,
        "mean_billed_cost": 7.6888975,
        "source": "reports/static_lookup_pareto.json model_points claude_opus_5",
    }
    hi_to_grok = next(
        row
        for row in combos
        if row["coding_models"] == {"ko": FABLE, "en": GROK43, "hi": GROK43}
    )

    within_one_of_best = {}
    for lang in LANGS:
        best = ranks[lang][0]["stable_correct"]
        within_one_of_best[lang] = [
            {
                "model": row["model"],
                "stable_correct": row["stable_correct"],
                "delta_from_best": row["stable_correct"] - best,
                "mean_billed_cost": row["mean_billed_cost"],
                "cost_ratio_vs_best": (
                    row["mean_billed_cost"] / ranks[lang][0]["mean_billed_cost"]
                    if ranks[lang][0]["mean_billed_cost"]
                    else None
                ),
            }
            for row in ranks[lang]
            if row["stable_correct"] >= best - 1
        ]

    payload = {
        "scope": {
            "frozen_noncoding_cells": 18,
            "coding_cells_on_hold": 3,
            "n_per_cell": 14,
            "hard_n": 6,
            "hard_qids": hard_qids,
            "selection_rule_for_ranks": (
                "max stable_correct, then min A/B mean billed for the 14-item cell "
                "(same order as per-request mean; table shows 14-item totals)"
            ),
            "winners_curse": (
                "Lookup performance is an in-sample upper-bound estimate. "
                "Do not numerically correct 268/294 or residual 6."
            ),
        },
        "frozen_lookup": {f"{bucket}:{lang}": model for (bucket, lang), model in frozen.items()},
        "coding_ranks": ranks,
        "coding_top3": {lang: [row["model"] for row in rows] for lang, rows in top3.items()},
        "within_one_cell_of_best": within_one_of_best,
        "fable_vs_grok43": compares,
        "en_grok43_vs_fable": en_compare,
        "named_policies": named,
        "top3_combinations": combos,
        "run_solo_argmax": run_solo,
        "infra_in_coding_tables": infra_rows,
        "pareto_neighbors": {
            "opus": opus,
            "current_dominates_opus": (
                current["stable_correct"] > opus["stable_correct"]
                and current["mean_billed_cost"] < opus["mean_billed_cost"]
            ),
            "hi_grok_swap": {
                "stable_correct": hi_to_grok["stable_correct"],
                "mean_billed_cost": hi_to_grok["mean_billed_cost"],
                "dominates_opus": (
                    hi_to_grok["stable_correct"] > opus["stable_correct"]
                    and hi_to_grok["mean_billed_cost"] < opus["mean_billed_cost"]
                ),
            },
        },
        "noncoding_residual_by_lang": {"ko": 1, "en": 0, "hi": 0, "note": "instruction-ko only"},
    }
    OUT_JSON.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str) + "\n")
    OUT_MD.write_text(render_md(payload) + "\n")
    print(
        json.dumps(
            {
                "sha256_md": hashlib.sha256(OUT_MD.read_bytes()).hexdigest(),
                "current": {
                    "stable": current["stable_correct"],
                    "cost": current["mean_billed_cost"],
                },
                "top3": payload["coding_top3"],
                "ko_delta": compares["ko"]["stable_delta_left_minus_right"],
                "hi_delta": compares["hi"]["stable_delta_left_minus_right"],
            },
            indent=2,
        )
    )
    return 0


def render_md(payload: dict) -> str:
    ranks = payload["coding_ranks"]
    compares = payload["fable_vs_grok43"]
    named = payload["named_policies"]
    combos = payload["top3_combinations"]
    within = payload["within_one_cell_of_best"]
    top3 = payload["coding_top3"]
    run_solo = payload["run_solo_argmax"]
    infra = payload["infra_in_coding_tables"]
    neighbors = payload["pareto_neighbors"]
    hi_swap = neighbors["hi_grok_swap"]
    current = named["current_hold_argmax"]
    ko = compares["ko"]
    hi = compares["hi"]
    ko_extra_cost = ranks["ko"][0]["mean_billed_cost"] - next(
        row["mean_billed_cost"] for row in ranks["ko"] if row["model"] == GROK43
    )
    hi_extra_cost = ranks["hi"][0]["mean_billed_cost"] - next(
        row["mean_billed_cost"] for row in ranks["hi"] if row["model"] == GROK43
    )
    en_cost = next(row["mean_billed_cost"] for row in ranks["en"] if row["model"] == GROK43)
    ko_fable_cost = next(row["mean_billed_cost"] for row in ranks["ko"] if row["model"] == FABLE)
    hi_fable_cost = next(row["mean_billed_cost"] for row in ranks["hi"] if row["model"] == FABLE)
    lines = [
        "# Coding-cell hold: n=14 instability check",
        "",
        "Status: **coding 3 cells HOLD**. Non-coding 18 cells remain locked.",
        "No learned router. Gate 5pp PASS record is unchanged.",
        "This report does not confirm coding cells and does not rewrite the lookup.",
        "",
        "## Answers to the three hold checks",
        "",
        "1. Extra stable cells, fable minus grok_4_3, coding ko/hi (14 items).",
        f"   - ko: **+{ko['stable_delta_left_minus_right']}** stable ({ko['stable_left']} vs {ko['stable_right']}). "
        f"Fable-only `{','.join(q.split(':')[1] for q in ko['stable_left_only_qids'])}`; "
        f"grok-only `{','.join(q.split(':')[1] for q in ko['stable_right_only_qids'])}`. "
        f"Net {len(ko['stable_left_only_qids'])}−{len(ko['stable_right_only_qids'])}={ko['stable_delta_left_minus_right']}. "
        f"{len(ko['stable_left_only_hard_qids'])} of the fable-only qids are hard.",
        f"   - ko A/B: A **+{ko['a_delta']}** ({ko['a_left']} vs {ko['a_right']}), "
        f"B **+{ko['b_delta']}** ({ko['b_left']} vs {ko['b_right']}). Same sign, not the same size.",
        f"   - hi: **+{hi['stable_delta_left_minus_right']}** stable ({hi['stable_left']} vs {hi['stable_right']}). "
        f"Fable-only `{','.join(q.split(':')[1] for q in hi['stable_left_only_qids'])}`; "
        f"grok-only `{','.join(q.split(':')[1] for q in hi['stable_right_only_qids'])}`. "
        f"Net {len(hi['stable_left_only_qids'])}−{len(hi['stable_right_only_qids'])}={hi['stable_delta_left_minus_right']}. "
        f"Fable-only that are hard: {len(hi['stable_left_only_hard_qids'])}/{len(hi['stable_left_only_qids'])}.",
        f"   - hi A/B: A **+{hi['a_delta']}** ({hi['a_left']} vs {hi['a_right']}), "
        f"B **+{hi['b_delta']}** ({hi['b_left']} vs {hi['b_right']}). The one-cell edge **disappears on B**.",
        f"   - Cost of that edge vs grok_4_3 on the same 14 items: ko extra **{fmt_usd(ko_extra_cost)}** for "
        f"{ko['stable_delta_left_minus_right']} cells (**{fmt_usd(ko_extra_cost / ko['stable_delta_left_minus_right'])}/cell**); "
        f"hi extra **{fmt_usd(hi_extra_cost)}** for {hi['stable_delta_left_minus_right']} cell. "
        "hi is the “1 cell for ~$3” case. ko is not 1–2 cells; it is 3, but the A/B magnitude moves 2↔4.",
        "",
        "2. Unique optimum vs 1-cell cheaper near-miss, all 14 models.",
        "   - ko: fable **unique** at 9/14. Next is opus 7/14 (−2). No model is 1 cell behind.",
        "   - en: grok_4_3 **unique** at 9/14. Next are kimi and fable at 7/14 (−2). grok A=11 / B=9: the winning count jitters by 2.",
        "   - hi: fable 9/14 is **not unique-optimal**. grok_4_3 is **1 cell behind** (8/14) at 0.03× fable cost.",
        "",
        "3. Coding cells only swapped to each language’s top-3; 18 non-coding cells frozen (241/252).",
        f"   - Current argmax: **{current['stable_correct']}/294 @ {fmt_usd(current['mean_billed_cost'])}** "
        f"(coding {current['coding_stable_correct']}/42). This is **1 of 27** top-3 combinations.",
        f"   - Next: hi → grok_4_3: **{hi_swap['stable_correct']}/294 @ {fmt_usd(hi_swap['mean_billed_cost'])}** "
        f"(−1 cell). That −1 is the hi check-1 cell.",
        f"   - All 27: matrix {min(row['stable_correct'] for row in combos)}–"
        f"{max(row['stable_correct'] for row in combos)}; billed "
        f"{fmt_usd(min(row['mean_billed_cost'] for row in combos))}–"
        f"{fmt_usd(max(row['mean_billed_cost'] for row in combos))}. The argmax is a point, not a plateau.",
        "",
        f"Language cost ratio vs coding-en grok_4_3 {fmt_usd(en_cost)}: "
        f"ko fable {fmt_usd(ko_fable_cost)} = **{ko_fable_cost / en_cost:.1f}×**; "
        f"hi fable {fmt_usd(hi_fable_cost)} = **{hi_fable_cost / en_cost:.1f}×**. "
        "The hi ratio is the 1-cell, B-unstable edge.",
        "",
        f"Pareto headline without confirming hi-fable: {hi_swap['stable_correct']}/294 @ "
        f"{fmt_usd(hi_swap['mean_billed_cost'])} still strictly dominates opus "
        f"{neighbors['opus']['stable_correct']}/294 @ {fmt_usd(neighbors['opus']['mean_billed_cost'])} "
        f"(dominates={hi_swap['dominates_opus']}). HOLD on coding-hi does not carry the Pareto claim.",
        "",
        "## Winner's curse (paper language; no numerical correction)",
        "",
        "The 21-cell lookup was selected and scored on the same A/B cells.",
        "Residual 6/294 is an optimistic lower bound (winner's curse).",
        "Holdout split is not possible at n=14 per bucket×language.",
        "State lookup performance as an **upper-bound estimate**.",
        "Do not adjust 268/294, residual 6, or billed $6.723015.",
        "",
        "## 1. fable vs grok_4_3 on coding ko/hi",
        "",
        "Question: how many extra stable cells does fable buy, and is that delta the same on A and on B?",
        "",
    ]
    for lang in ("ko", "hi"):
        cmp_ = compares[lang]
        lines.extend(
            [
                f"### coding {lang}",
                "",
                f"- stable: fable {cmp_['stable_left']}/14, grok_4_3 {cmp_['stable_right']}/14, **Δ {cmp_['stable_delta_left_minus_right']} cells**",
                f"- run A: fable {cmp_['a_left']}/14, grok_4_3 {cmp_['a_right']}/14, Δ {cmp_['a_delta']}",
                f"- run B: fable {cmp_['b_left']}/14, grok_4_3 {cmp_['b_right']}/14, Δ {cmp_['b_delta']}",
                f"- fable-only stable qids: {', '.join(cmp_['stable_left_only_qids']) or '(none)'}",
                f"- grok_4_3-only stable qids: {', '.join(cmp_['stable_right_only_qids']) or '(none)'}",
                f"- both stable: {len(cmp_['stable_both_qids'])} ; neither: {len(cmp_['stable_neither_qids'])}",
                f"- fable-only that are hard: {', '.join(cmp_['stable_left_only_hard_qids']) or '(none)'}",
                "",
                "| qid | difficulty | fable A | fable B | fable stable | grok43 A | grok43 B | grok43 stable |",
                "|---|---|---|---|---|---|---|---|",
            ]
        )
        for item in cmp_["items"]:
            fable = item[FABLE]
            grok = item[GROK43]
            lines.append(
                "| {qid} | {diff} | {fa} | {fb} | {fs} | {ga} | {gb} | {gs} |".format(
                    qid=item["qid"],
                    diff=item["difficulty"],
                    fa=int(fable["a_correct"]),
                    fb=int(fable["b_correct"]),
                    fs=int(fable["stable"]),
                    ga=int(grok["a_correct"]),
                    gb=int(grok["b_correct"]),
                    gs=int(grok["stable"]),
                )
            )
        lines.append("")

    en = payload["en_grok43_vs_fable"]
    lines.extend(
        [
            "### coding en (reference; current pick is grok_4_3)",
            "",
            f"- stable: grok_4_3 {en['stable_left']}/14, fable {en['stable_right']}/14, Δ grok−fable {en['stable_delta_left_minus_right']}",
            f"- grok_4_3-only stable: {', '.join(en['stable_left_only_qids']) or '(none)'}",
            f"- fable-only stable: {', '.join(en['stable_right_only_qids']) or '(none)'}",
            "",
        ]
    )

    lines.extend(
        [
            "## 2. All 14 models per coding language cell",
            "",
            "Rank = max stable_correct, then min A/B mean billed for the 14-item cell "
            "(same order as per-request mean; the table shows 14-item totals, not per-request).",
            "Matrix column is /14 including cap_hit as scored 0. Diagnostic column is /stable_n "
            "(both runs usable).",
            "",
        ]
    )
    if infra:
        lines.append("Infra leftovers inside these 14×3×14 cells:")
        for row in infra:
            lines.append(
                f"- `{row['model']}` coding {row['lang']} {', '.join(row['infra_qids'])}: "
                f"matrix {row['stable_correct']}/14, diagnostic {row['stable_correct']}/{row['stable_n']}."
            )
        lines.append("")
    else:
        lines.append("Infra leftovers in these tables: none.")
        lines.append("")

    for lang in LANGS:
        best = ranks[lang][0]["stable_correct"]
        lines.extend(
            [
                f"### coding {lang}",
                "",
                "| rank | model | stable /14 | stable /n | A /14 | B /14 | mean billed | vs best cells | vs best $ |",
                "|---|---|---|---|---|---|---|---|---|",
            ]
        )
        for i, row in enumerate(ranks[lang], start=1):
            lines.append(
                "| {rank} | `{model}` | {st} | {stn} | {a} | {b} | {cost} | {dcells} | {dratio} |".format(
                    rank=i,
                    model=row["model"],
                    st=row["stable_correct"],
                    stn=f"{row['stable_correct']}/{row['stable_n']}",
                    a=row["a_correct"],
                    b=row["b_correct"],
                    cost=fmt_usd(row["mean_billed_cost"]),
                    dcells=row["stable_correct"] - best,
                    dratio=(
                        f"{row['mean_billed_cost'] / ranks[lang][0]['mean_billed_cost']:.2f}×"
                        if ranks[lang][0]["mean_billed_cost"]
                        else "—"
                    ),
                )
            )
        lines.append("")
        near = within[lang]
        lines.append(
            "Models within 1 stable cell of the cell-best: "
            + ", ".join(f"`{row['model']}` ({row['stable_correct']}/14, {fmt_usd(row['mean_billed_cost'])})" for row in near)
        )
        lines.append("")

    lines.extend(
        [
            "### Run-solo argmax (A only / B only vs stable)",
            "",
            "Stable argmax can hide run-solo ties. These ties are part of the n=14 instability, not a new product rule.",
            "",
            "| lang | stable winner (count) | A-only max (models) | B-only max (models) |",
            "|---|---|---|---|",
        ]
    )
    for lang in LANGS:
        solo = run_solo[lang]
        lines.append(
            "| {lang} | `{win}` ({n}) | {a} ({am}) | {b} ({bm}) |".format(
                lang=lang,
                win=solo["stable_best_model"],
                n=solo["stable_best"],
                a=solo["a_best"],
                am=", ".join(f"`{m}`" for m in solo["a_tied_models"]),
                b=solo["b_best"],
                bm=", ".join(f"`{m}`" for m in solo["b_tied_models"]),
            )
        )
    lines.extend(
        [
            "",
            "Pinned observations from the rank table: coding-en B is grok_4_3 9 = fable 9. "
            "coding-hi B is fable 9 = grok_4_3 9 = sonnet 9 (sonnet hi stable is 3; A6→B9). "
            "sonnet en A9→B4 is the largest A/B swing in these tables.",
            "",
            "Language residual on the current (held) lookup: non-coding residual is ko 1 / en 0 / hi 0 "
            "(instruction-ko). Coding residual is ko 2 / en 2 / hi 1. Total residual 6. "
            "A/B fable−grok Δ on coding is ko 2↔4, hi 1↔0.",
            "",
        ]
    )

    current = named["current_hold_argmax"]
    lines.extend(
        [
            "## 3. Top-3 coding swaps; 18 non-coding cells frozen",
            "",
            f"Frozen 18 contribute {current['noncoding_stable_correct']}/252 stable cells.",
            "Coding 3 cells currently contribute "
            f"{current['coding_stable_correct']}/42. Matrix total {current['stable_correct']}/294 @ "
            f"{fmt_usd(current['mean_billed_cost'])}.",
            "",
            f"Top-3 by the same rank rule: ko={top3['ko']}, en={top3['en']}, hi={top3['hi']}.",
            "27 combinations (3³). Goal is n=14 instability, not a cost cut.",
            "",
            "### Named policies",
            "",
            "| policy | ko | en | hi | matrix stable /294 | coding /42 | mean billed | Δ cells vs current | Δ $ vs current |",
            "|---|---|---|---|---|---|---|---|---|",
        ]
    )
    policy_labels = [
        ("current_hold_argmax", "current (fable / grok43 / fable)"),
        ("coding_rank2_each_lang", "rank-2 on each coding lang"),
        ("coding_top3_cheapest", "cheapest of each lang's top-3"),
        ("coding_all_grok_4_3", "all coding → grok_4_3"),
        ("coding_all_fable", "all coding → fable"),
    ]
    for key, label in policy_labels:
        row = named[key]
        cm = row["coding_models"]
        lines.append(
            "| {label} | `{ko}` | `{en}` | `{hi}` | {st} | {cod} | {cost} | {dc} | {dd} |".format(
                label=label,
                ko=cm["ko"],
                en=cm["en"],
                hi=cm["hi"],
                st=row["stable_correct"],
                cod=row["coding_stable_correct"],
                cost=fmt_usd(row["mean_billed_cost"]),
                dc=row["stable_correct"] - current["stable_correct"],
                dd=fmt_usd(row["mean_billed_cost"] - current["mean_billed_cost"]),
            )
        )
    lines.extend(
        [
            "",
            "### All 27 top-3 combinations, sorted by stable then cost",
            "",
            "| ko | en | hi | matrix /294 | coding /42 | mean billed | Δ cells | Δ $ |",
            "|---|---|---|---|---|---|---|---|",
        ]
    )
    for row in combos:
        cm = row["coding_models"]
        lines.append(
            "| `{ko}` | `{en}` | `{hi}` | {st} | {cod} | {cost} | {dc} | {dd} |".format(
                ko=cm["ko"],
                en=cm["en"],
                hi=cm["hi"],
                st=row["stable_correct"],
                cod=row["coding_stable_correct"],
                cost=fmt_usd(row["mean_billed_cost"]),
                dc=row["stable_correct"] - current["stable_correct"],
                dd=fmt_usd(row["mean_billed_cost"] - current["mean_billed_cost"]),
            )
        )
    unique_acc = sorted({row["stable_correct"] for row in combos}, reverse=True)
    lines.extend(
        [
            "",
            f"Distinct matrix totals among the 27: {unique_acc}.",
            f"Range: {min(row['stable_correct'] for row in combos)}–{max(row['stable_correct'] for row in combos)} /294; "
            f"cost {fmt_usd(min(row['mean_billed_cost'] for row in combos))}–"
            f"{fmt_usd(max(row['mean_billed_cost'] for row in combos))}.",
            "",
            "## Reading (not a coding confirmation)",
            "",
            "- hi matches the overfitting test: 1 extra stable cell, ~$3.35, and Δ=0 on B.",
            "- ko is a larger edge (+3 stable, unique 9/14) but A/B Δ moves 2↔4, and most fable-only qids are hard.",
            "- en grok_4_3 is unique-best and cheap; it is not the 40× problem. Run-solo still ties fable on B.",
            "- Swapping only coding-hi to grok_4_3 (267/294) still dominates opus. Pareto vs opus does not require confirming fable on hi.",
            "- The 27-combo spread is the instability diagnostic. Do not pick the cheapest combo as the product rule from this table.",
            "- Paper: lookup accuracy is an upper bound; no shrinkage of 268/294.",
            "",
            "Unchanged: no learned router; static task×language lookup adopted for the 18 non-coding cells; gate 5pp PASS recorded with the decomposition.",
        ]
    )
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
