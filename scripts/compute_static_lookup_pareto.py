#!/usr/bin/env python3
"""Build the stable task×language lookup and billed-cost Pareto frontier."""

from __future__ import annotations

import csv
import hashlib
import json
import math
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN_A = ROOT / "results/phase2"
RUN_B = ROOT / "results/replicate1"
OUT_JSON = ROOT / "reports/static_lookup_pareto.json"
OUT_CSV = ROOT / "reports/static_lookup_21.csv"
OUT_SVG = ROOT / "reports/stable_billed_pareto.svg"
OUT_QIDS = ROOT / "reports/final_qid_98.txt"
PRODUCT_PARETO_NAMES = [
    "deepseek_v4_flash",
    "gpt_5_6_luna",
    "gemini_3_7_flash",
    "static_lookup_all_coding_grok_4_3",
    "static_task_lang_lookup",
]
# Human 2026-08-23T03:33Z: jitter-floor override. Not a cost cut.
HUMAN_CELL_OVERRIDE = {
    ("coding", "hi"): {
        "model": "grok_4_3",
        "rule": (
            "Post-hold human lock 2026-08-23T03:33Z: do not buy a unique 1-cell "
            "coding edge whose A/B sign fails (stable +1, A +1, B +0)."
        ),
        "source": "2026-08-23T03:33Z",
        "argmax_would_have_been": "claude_fable_5",
    }
}
HUMAN_UNSIGNED_TIE = {
    ("toolcall", "hi"): {
        "model": "gemini_3_7_flash",
        "rule": (
            "Human 2026-08-23T04:01Z rule (b): a unique stable winner with "
            "exactly +1 whose A/B margin is unsigned is treated as tied with "
            "the one-behind candidates; min billed breaks the tie. The winner "
            "is already min billed here, so the rule intentionally does not change it."
        ),
        "source": "2026-08-23T04:01Z",
        "evidence_grade": "tie-break selection; no signed accuracy premium",
    }
}
BUCKETS = [
    "knowledge",
    "math",
    "instruction",
    "extraction",
    "toolcall",
    "abstention",
    "coding",
]
LANGS = ["ko", "en", "hi"]
INFRA = {
    "http_error",
    "timeout",
    "sandbox_error",
    "sandbox_timeout",
    "sandbox_network_blocked",
}


def load_run(root: Path) -> dict[str, dict[str, dict]]:
    result = {}
    for model_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        path = model_dir / "labels.jsonl"
        if not path.exists():
            continue
        last = {}
        for line in path.read_text().splitlines():
            if line.strip():
                row = json.loads(line)
                last[row["key"]] = row
        result[model_dir.name] = last
    return result


def cell(run: dict[str, dict[str, dict]], model: str, qid: str, lang: str) -> dict:
    return run[model][f"{model}|{qid}|{lang}"]


def usable(row: dict) -> bool:
    return row.get("status") not in INFRA


def correct(row: dict) -> bool:
    return usable(row) and row.get("correct") == 1


def stable_correct(a: dict, b: dict) -> bool:
    return usable(a) and usable(b) and correct(a) and correct(b)


def billed(rows: list[dict]) -> dict:
    known = [float(row["cost_usd"]) for row in rows if row.get("cost_usd") is not None]
    return {
        "cost": sum(known),
        "n_billed": len(known),
        "n_total": len(rows),
        "n_missing": len(rows) - len(known),
    }


def pareto_frontier(points: list[dict]) -> list[dict]:
    frontier = []
    for point in points:
        dominated = any(
            other["mean_billed_cost"] <= point["mean_billed_cost"]
            and other["stable_accuracy_matrix"] >= point["stable_accuracy_matrix"]
            and (
                other["mean_billed_cost"] < point["mean_billed_cost"]
                or other["stable_accuracy_matrix"] > point["stable_accuracy_matrix"]
            )
            for other in points
            if other["name"] != point["name"]
        )
        if not dominated:
            frontier.append(point)
    return sorted(frontier, key=lambda row: row["mean_billed_cost"])


def render_svg(points: list[dict], product_frontier: list[dict]) -> None:
    width, height = 1000, 620
    left, right, top, bottom = 100, 40, 50, 90
    plot_w, plot_h = width - left - right, height - top - bottom
    xs = [math.log10(p["mean_billed_cost"]) for p in points]
    ys = [p["stable_accuracy_matrix"] for p in points]
    xmin, xmax = min(xs) - 0.08, max(xs) + 0.08
    ymin, ymax = min(ys) - 0.02, max(ys) + 0.02

    def xy(point: dict) -> tuple[float, float]:
        x = left + (math.log10(point["mean_billed_cost"]) - xmin) / (xmax - xmin) * plot_w
        y = top + (ymax - point["stable_accuracy_matrix"]) / (ymax - ymin) * plot_h
        return x, y

    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        '<text x="500" y="28" text-anchor="middle" font-family="sans-serif" font-size="18">Product comparison: dsflash / luna / g37flash / all-grok / lookup</text>',
        f'<line x1="{left}" y1="{top + plot_h}" x2="{left + plot_w}" y2="{top + plot_h}" stroke="#333"/>',
        f'<line x1="{left}" y1="{top}" x2="{left}" y2="{top + plot_h}" stroke="#333"/>',
        f'<text x="{left + plot_w / 2}" y="{height - 25}" text-anchor="middle" font-family="sans-serif" font-size="14">Mean billed USD for 294-query workload (log scale)</text>',
        f'<text x="22" y="{top + plot_h / 2}" text-anchor="middle" transform="rotate(-90 22 {top + plot_h / 2})" font-family="sans-serif" font-size="14">Stable accuracy</text>',
    ]
    for i in range(6):
        value = ymin + (ymax - ymin) * i / 5
        y = top + plot_h - plot_h * i / 5
        lines.extend(
            [
                f'<line x1="{left}" y1="{y:.1f}" x2="{left + plot_w}" y2="{y:.1f}" stroke="#ddd"/>',
                f'<text x="{left - 10}" y="{y + 4:.1f}" text-anchor="end" font-family="sans-serif" font-size="11">{value:.2f}</text>',
            ]
        )
    polyline = " ".join(f"{xy(p)[0]:.1f},{xy(p)[1]:.1f}" for p in product_frontier)
    lines.append(f'<polyline points="{polyline}" fill="none" stroke="#d62728" stroke-width="2.5"/>')
    frontier_names = {p["name"] for p in product_frontier}
    for point in points:
        x, y = xy(point)
        is_lookup = point["name"] == "static_task_lang_lookup"
        color = "#2ca02c" if is_lookup else ("#d62728" if point["name"] in frontier_names else "#777")
        radius = 7 if is_lookup else 4
        label = point["short_name"]
        lines.extend(
            [
                f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{radius}" fill="{color}"/>',
                f'<text x="{x + 7:.1f}" y="{y - 7:.1f}" font-family="sans-serif" font-size="10">{label}</text>',
            ]
        )
    lines.append(
        '<text x="980" y="600" text-anchor="end" font-family="sans-serif" font-size="10">'
        'Opus cost: 293 billed cells; no catalog imputation</text>'
    )
    lines.append("</svg>")
    OUT_SVG.write_text("\n".join(lines) + "\n")


def main() -> int:
    run_a = load_run(RUN_A)
    run_b = load_run(RUN_B)
    models = sorted(run_a)
    assert models == sorted(run_b)

    exemplar = next(iter(run_a.values()))
    qids_by_bucket = {bucket: set() for bucket in BUCKETS}
    for row in exemplar.values():
        qids_by_bucket[row["bucket"]].add(row["qid"])
    assert all(len(qids) == 14 for qids in qids_by_bucket.values())
    qid_ledger = "\n".join(
        f"{bucket}\t{qid}"
        for bucket in BUCKETS
        for qid in sorted(qids_by_bucket[bucket])
    ) + "\n"
    OUT_QIDS.write_text(qid_ledger)
    qid_ledger_sha256 = hashlib.sha256(qid_ledger.encode()).hexdigest()

    lookup = []
    for bucket in BUCKETS:
        for lang in LANGS:
            candidates = []
            qids = sorted(qids_by_bucket[bucket])
            for model in models:
                pairs = [(cell(run_a, model, qid, lang), cell(run_b, model, qid, lang)) for qid in qids]
                n_usable = sum(usable(a) and usable(b) for a, b in pairs)
                n_correct = sum(stable_correct(a, b) for a, b in pairs)
                cost_a = billed([a for a, _ in pairs])
                cost_b = billed([b for _, b in pairs])
                combined_billed = cost_a["n_billed"] + cost_b["n_billed"]
                mean_per_request = (
                    (cost_a["cost"] + cost_b["cost"]) / combined_billed
                    if combined_billed
                    else None
                )
                candidates.append(
                    {
                        "model": model,
                        "stable_correct": n_correct,
                        "correct_a": sum(correct(a) for a, _ in pairs),
                        "correct_b": sum(correct(b) for _, b in pairs),
                        "stable_n": n_usable,
                        "stable_accuracy": n_correct / n_usable if n_usable else None,
                        "cost_a": cost_a,
                        "cost_b": cost_b,
                        "mean_billed_cost": (cost_a["cost"] + cost_b["cost"]) / 2,
                        "mean_billed_per_request": mean_per_request,
                    }
                )
            best_accuracy = max(row["stable_accuracy"] for row in candidates)
            accuracy_ties = [row for row in candidates if row["stable_accuracy"] == best_accuracy]
            pre_rule_selected = min(
                accuracy_ties,
                key=lambda row: (
                    row["mean_billed_per_request"],
                    row["model"],
                ),
            )
            selected = pre_rule_selected
            one_behind = [
                row
                for row in candidates
                if row["stable_correct"] == pre_rule_selected["stable_correct"] - 1
            ]
            cheapest_one_behind = (
                min(one_behind, key=lambda row: (row["mean_billed_cost"], row["model"]))
                if one_behind
                else None
            )
            if cheapest_one_behind:
                margin_a = pre_rule_selected["correct_a"] - cheapest_one_behind["correct_a"]
                margin_b = pre_rule_selected["correct_b"] - cheapest_one_behind["correct_b"]
                unsigned_margin = not (
                    (margin_a > 0 and margin_b > 0)
                    or (margin_a < 0 and margin_b < 0)
                )
                has_premium = (
                    pre_rule_selected["mean_billed_cost"]
                    > cheapest_one_behind["mean_billed_cost"]
                )
            else:
                margin_a = margin_b = None
                unsigned_margin = False
                has_premium = False
            uniform_rule_b = bool(cheapest_one_behind and unsigned_margin and has_premium)
            override = HUMAN_CELL_OVERRIDE.get((bucket, lang))
            unsigned_tie = HUMAN_UNSIGNED_TIE.get((bucket, lang))
            selection_rule = "max stable accuracy, then min A/B mean billed per request"
            if uniform_rule_b:
                selected = cheapest_one_behind
                selection_rule = (
                    "Human 2026-08-23T04:44Z rule (b), option B: treat every "
                    "premium=yes unsigned margin vs the cheapest one-behind as a tie; "
                    "min billed selects the one-behind model."
                )
            elif override:
                forced = next(row for row in candidates if row["model"] == override["model"])
                selected = forced
                selection_rule = override["rule"]
            elif unsigned_tie:
                forced = next(row for row in candidates if row["model"] == unsigned_tie["model"])
                selected = forced
                selection_rule = unsigned_tie["rule"]
            second_one_behind = [
                row
                for row in candidates
                if row["stable_correct"] == selected["stable_correct"] - 1
            ]
            second_cheapest = (
                min(
                    second_one_behind,
                    key=lambda row: (row["mean_billed_cost"], row["model"]),
                )
                if second_one_behind
                else None
            )
            if second_cheapest:
                second_margin_a = selected["correct_a"] - second_cheapest["correct_a"]
                second_margin_b = selected["correct_b"] - second_cheapest["correct_b"]
                second_unsigned = not (
                    (second_margin_a > 0 and second_margin_b > 0)
                    or (second_margin_a < 0 and second_margin_b < 0)
                )
                second_premium = (
                    selected["mean_billed_cost"] > second_cheapest["mean_billed_cost"]
                )
            else:
                second_unsigned = second_premium = False
            second_pass_would_apply = bool(
                second_cheapest and second_unsigned and second_premium
            )
            stable_oracle = sum(
                any(
                    stable_correct(
                        cell(run_a, model, qid, lang),
                        cell(run_b, model, qid, lang),
                    )
                    for model in models
                )
                for qid in qids
            )
            lookup.append(
                {
                    "bucket": bucket,
                    "lang": lang,
                    "selected_model": selected["model"],
                    "stable_correct": selected["stable_correct"],
                    "stable_n": selected["stable_n"],
                    "stable_accuracy": selected["stable_accuracy"],
                    "stable_oracle": stable_oracle,
                    "residual_to_oracle": stable_oracle - selected["stable_correct"],
                    "cost_a": selected["cost_a"],
                    "cost_b": selected["cost_b"],
                    "mean_billed_cost": selected["mean_billed_cost"],
                    "mean_billed_per_request": selected["mean_billed_per_request"],
                    "accuracy_tie_models": sorted(row["model"] for row in accuracy_ties),
                    "tie_break": selection_rule,
                    "argmax_model": pre_rule_selected["model"],
                    "pre_rule_model": pre_rule_selected["model"],
                    "rule_b_applied": uniform_rule_b,
                    "rule_b_one_behind_model": (
                        cheapest_one_behind["model"] if cheapest_one_behind else None
                    ),
                    "rule_b_margin_a": margin_a,
                    "rule_b_margin_b": margin_b,
                    "rule_b_has_premium": has_premium,
                    "rule_b_second_pass_would_apply": second_pass_would_apply,
                    "rule_b_second_pass_candidate": (
                        second_cheapest["model"] if second_cheapest else None
                    ),
                    "human_override": override["model"] if override else None,
                    "unsigned_tie_rule": (
                        selected["model"]
                        if uniform_rule_b
                        else (unsigned_tie["model"] if unsigned_tie else None)
                    ),
                    "evidence_grade": (
                        "rule-b uniform premium tie-break; no signed accuracy premium"
                        if uniform_rule_b
                        else (
                            unsigned_tie["evidence_grade"]
                            if unsigned_tie
                            else (
                                "post-hold unsigned-premium override"
                                if override
                                else "signed accuracy or ordinary tie-break"
                            )
                        )
                    ),
                }
            )

    assert not any(row["rule_b_second_pass_would_apply"] for row in lookup)

    model_points = []
    short = {
        "gpt_5_6_sol": "sol",
        "gpt_5_6_terra": "terra",
        "gpt_5_6_luna": "luna",
        "claude_fable_5": "fable",
        "claude_opus_5": "opus",
        "claude_sonnet_5": "sonnet",
        "gemini_3_1_pro": "g31",
        "gemini_3_7_flash": "g37f",
        "grok_4_6": "grok46",
        "grok_4_3": "grok43",
        "deepseek_v4_pro": "dspro",
        "deepseek_v4_flash": "dsflash",
        "kimi_k3": "kimi",
        "qwen3_7_plus": "qwen",
    }
    for model in models:
        pairs = []
        for row in run_a[model].values():
            pairs.append((row, run_b[model][row["key"]]))
        stable_n = sum(usable(a) and usable(b) for a, b in pairs)
        stable_hits = sum(stable_correct(a, b) for a, b in pairs)
        cost_a = billed([a for a, _ in pairs])
        cost_b = billed([b for _, b in pairs])
        model_points.append(
            {
                "name": model,
                "short_name": short[model],
                "type": "single_model",
                "stable_correct": stable_hits,
                "stable_n": stable_n,
                "stable_accuracy_matrix": stable_hits / 294,
                "stable_accuracy_diagnostic": stable_hits / stable_n,
                "cost_a": cost_a,
                "cost_b": cost_b,
                "mean_billed_cost": (cost_a["cost"] + cost_b["cost"]) / 2,
                "status_a": dict(Counter(row.get("status") for row, _ in pairs)),
                "status_b": dict(Counter(row.get("status") for _, row in pairs)),
            }
        )

    lookup_cost_a = sum(row["cost_a"]["cost"] for row in lookup)
    lookup_cost_b = sum(row["cost_b"]["cost"] for row in lookup)
    lookup_n_billed_a = sum(row["cost_a"]["n_billed"] for row in lookup)
    lookup_n_billed_b = sum(row["cost_b"]["n_billed"] for row in lookup)
    lookup_point = {
        "name": "static_task_lang_lookup",
        "short_name": "lookup",
        "type": "static_lookup",
        "stable_correct": sum(row["stable_correct"] for row in lookup),
        "stable_n": sum(row["stable_n"] for row in lookup),
        "stable_accuracy_matrix": (
            sum(row["stable_correct"] for row in lookup) / 294
        ),
        "stable_accuracy_diagnostic": (
            sum(row["stable_correct"] for row in lookup)
            / sum(row["stable_n"] for row in lookup)
        ),
        "stable_oracle": sum(row["stable_oracle"] for row in lookup),
        "residual_to_oracle": sum(row["residual_to_oracle"] for row in lookup),
        "cost_a": {"cost": lookup_cost_a, "n_billed": lookup_n_billed_a, "n_total": 294},
        "cost_b": {"cost": lookup_cost_b, "n_billed": lookup_n_billed_b, "n_total": 294},
        "mean_billed_cost": (lookup_cost_a + lookup_cost_b) / 2,
    }

    all_grok_hits = 0
    all_grok_n = 0
    all_grok_cost_a = 0.0
    all_grok_cost_b = 0.0
    all_grok_n_billed_a = 0
    all_grok_n_billed_b = 0
    for row in lookup:
        bucket = row["bucket"]
        lang = row["lang"]
        # Keep the human-specified 04:01Z all-grok comparison point frozen:
        # pre-rule 18 non-coding cells + grok_4_3 in all three coding cells.
        model = "grok_4_3" if bucket == "coding" else row["pre_rule_model"]
        pairs = [
            (cell(run_a, model, qid, lang), cell(run_b, model, qid, lang))
            for qid in sorted(qids_by_bucket[bucket])
        ]
        all_grok_hits += sum(stable_correct(a, b) for a, b in pairs)
        all_grok_n += sum(usable(a) and usable(b) for a, b in pairs)
        cost_a = billed([a for a, _ in pairs])
        cost_b = billed([b for _, b in pairs])
        all_grok_cost_a += cost_a["cost"]
        all_grok_cost_b += cost_b["cost"]
        all_grok_n_billed_a += cost_a["n_billed"]
        all_grok_n_billed_b += cost_b["n_billed"]
    all_coding_grok_point = {
        "name": "static_lookup_all_coding_grok_4_3",
        "short_name": "all-grok",
        "type": "coding_sensitivity_policy",
        "policy": "locked 18 non-coding cells; all three coding cells use grok_4_3",
        "rule_version": (
            "frozen pre-rule-b 04:01Z policy; uniform option B is not applied "
            "to its 18 non-coding cells"
        ),
        "stable_correct": all_grok_hits,
        "stable_n": all_grok_n,
        "stable_accuracy_matrix": all_grok_hits / 294,
        "stable_accuracy_diagnostic": all_grok_hits / all_grok_n,
        "cost_a": {
            "cost": all_grok_cost_a,
            "n_billed": all_grok_n_billed_a,
            "n_total": 294,
        },
        "cost_b": {
            "cost": all_grok_cost_b,
            "n_billed": all_grok_n_billed_b,
            "n_total": 294,
        },
        "mean_billed_cost": (all_grok_cost_a + all_grok_cost_b) / 2,
    }
    assert all_coding_grok_point["stable_correct"] == 264
    assert all_coding_grok_point["stable_n"] == 294
    assert abs(all_coding_grok_point["mean_billed_cost"] - 0.542932) < 1e-6

    symmetric_b_all_grok_hits = 0
    symmetric_b_all_grok_cost_a = 0.0
    symmetric_b_all_grok_cost_b = 0.0
    for row in lookup:
        bucket = row["bucket"]
        lang = row["lang"]
        model = "grok_4_3" if bucket == "coding" else row["selected_model"]
        pairs = [
            (cell(run_a, model, qid, lang), cell(run_b, model, qid, lang))
            for qid in sorted(qids_by_bucket[bucket])
        ]
        symmetric_b_all_grok_hits += sum(stable_correct(a, b) for a, b in pairs)
        symmetric_b_all_grok_cost_a += billed([a for a, _ in pairs])["cost"]
        symmetric_b_all_grok_cost_b += billed([b for _, b in pairs])["cost"]
    symmetric_b_all_grok_audit = {
        "name": "static_lookup_all_coding_grok_4_3_symmetric_rule_b_audit",
        "type": "audit_only_not_in_five_named_points",
        "policy": "post-rule-b 18 non-coding cells; all coding cells use grok_4_3",
        "stable_correct": symmetric_b_all_grok_hits,
        "stable_n": 294,
        "cost_a": symmetric_b_all_grok_cost_a,
        "cost_b": symmetric_b_all_grok_cost_b,
        "mean_billed_cost": (
            symmetric_b_all_grok_cost_a + symmetric_b_all_grok_cost_b
        )
        / 2,
    }
    assert symmetric_b_all_grok_hits == 259
    assert math.isclose(
        symmetric_b_all_grok_audit["mean_billed_cost"],
        0.507668613162,
        rel_tol=0,
        abs_tol=1e-12,
    )

    all_points = model_points + [all_coding_grok_point, lookup_point]
    unrestricted_frontier = pareto_frontier(all_points)
    by_name = {point["name"]: point for point in all_points}
    product_comparison_points = [by_name[name] for name in PRODUCT_PARETO_NAMES]
    for left, right in zip(product_comparison_points, product_comparison_points[1:]):
        assert left["mean_billed_cost"] < right["mean_billed_cost"]

    coding_hi = next(row for row in lookup if row["bucket"] == "coding" and row["lang"] == "hi")
    coding_ko = next(row for row in lookup if row["bucket"] == "coding" and row["lang"] == "ko")
    coding_en = next(row for row in lookup if row["bucket"] == "coding" and row["lang"] == "en")
    assert coding_hi["selected_model"] == "grok_4_3"
    assert coding_ko["selected_model"] == "claude_fable_5"
    assert coding_en["selected_model"] == "grok_4_3"
    assert lookup_point["stable_correct"] == 262
    assert lookup_point["stable_oracle"] == 274
    assert lookup_point["residual_to_oracle"] == 12
    assert lookup_point["stable_n"] == 294
    assert abs(lookup_point["mean_billed_cost"] - 3.332910) < 1e-6
    opus = by_name["claude_opus_5"]
    assert lookup_point["stable_correct"] > opus["stable_correct"]
    assert lookup_point["mean_billed_cost"] < opus["mean_billed_cost"]
    # The frozen 04:01Z all-grok sensitivity point dominates the lookup after
    # uniform rule (b). Keep the five requested comparison points, but do not
    # mislabel the dominated lookup as Pareto-optimal.
    assert all_coding_grok_point["stable_correct"] > lookup_point["stable_correct"]
    assert all_coding_grok_point["mean_billed_cost"] < lookup_point["mean_billed_cost"]

    opus_null = {
        "A": [
            key
            for key, row in run_a["claude_opus_5"].items()
            if row.get("cost_usd") is None
        ],
        "B": [
            key
            for key, row in run_b["claude_opus_5"].items()
            if row.get("cost_usd") is None
        ],
    }
    assert opus_null["A"] == ["claude_opus_5|toolcall:parallel_multiple_139|en"]
    assert opus_null["B"] == opus_null["A"]

    margin_audit = []
    unsigned_unique_one_cell = []
    for bucket in BUCKETS:
        qids = sorted(qids_by_bucket[bucket])
        for lang in LANGS:
            stats = []
            for model in models:
                pairs = [
                    (cell(run_a, model, qid, lang), cell(run_b, model, qid, lang))
                    for qid in qids
                ]
                cost_a = billed([a for a, _ in pairs])
                cost_b = billed([b for _, b in pairs])
                combined = cost_a["n_billed"] + cost_b["n_billed"]
                stats.append(
                    {
                        "model": model,
                        "stable": sum(stable_correct(a, b) for a, b in pairs),
                        "a": sum(correct(a) for a, _ in pairs),
                        "b": sum(correct(b) for _, b in pairs),
                        "mean_billed_cost": (cost_a["cost"] + cost_b["cost"]) / 2,
                        "mean_billed_per_request": (
                            (cost_a["cost"] + cost_b["cost"]) / combined if combined else None
                        ),
                    }
                )
            stats.sort(
                key=lambda row: (
                    -row["stable"],
                    row["mean_billed_per_request"],
                    row["model"],
                )
            )
            best, rank2 = stats[0], stats[1]
            one_behind = [row for row in stats[1:] if row["stable"] == best["stable"] - 1]
            cheapest_one = (
                min(one_behind, key=lambda row: row["mean_billed_cost"]) if one_behind else None
            )
            unique = best["stable"] > rank2["stable"]
            if cheapest_one:
                a_m = best["a"] - cheapest_one["a"]
                b_m = best["b"] - cheapest_one["b"]
                sign_hold = (a_m > 0 and b_m > 0) or (a_m < 0 and b_m < 0)
                has_premium = best["mean_billed_cost"] > cheapest_one["mean_billed_cost"]
            else:
                a_m = b_m = None
                sign_hold = None
                has_premium = None
            rec = {
                "bucket": bucket,
                "lang": lang,
                "argmax": best["model"],
                "argmax_stable": best["stable"],
                "argmax_a": best["a"],
                "argmax_b": best["b"],
                "rank2": rank2["model"],
                "rank2_stable": rank2["stable"],
                "argmax_mean_billed_cost": best["mean_billed_cost"],
                "unique_best": unique,
                "stable_gap_to_rank2": best["stable"] - rank2["stable"],
                "cheapest_one_behind": cheapest_one["model"] if cheapest_one else None,
                "one_behind_stable": cheapest_one["stable"] if cheapest_one else None,
                "cheapest_one_behind_mean_billed_cost": (
                    cheapest_one["mean_billed_cost"] if cheapest_one else None
                ),
                "one_behind_absent_reason": (
                    None
                    if cheapest_one
                    else (
                        "no model one stable below argmax"
                        if best["stable"] - rank2["stable"] >= 2
                        else "argmax stable not reproduced by any lower model"
                    )
                ),
                "a_margin_vs_one_behind": a_m,
                "b_margin_vs_one_behind": b_m,
                "sign_holds_vs_one_behind": sign_hold,
                "has_premium_vs_one_behind": has_premium,
                "rule_b_domain": (
                    unique
                    and best["stable"] - rank2["stable"] == 1
                    and sign_hold is False
                ),
                "rule_b_result": (
                    min(
                        [best, cheapest_one],
                        key=lambda row: (row["mean_billed_cost"], row["model"]),
                    )["model"]
                    if (
                        unique
                        and best["stable"] - rank2["stable"] == 1
                        and sign_hold is False
                        and cheapest_one
                    )
                    else best["model"]
                ),
                "adopted_rule_b_result": (
                    min(
                        [best, cheapest_one],
                        key=lambda row: (row["mean_billed_cost"], row["model"]),
                    )["model"]
                    if sign_hold is False
                    and has_premium is True
                    and cheapest_one
                    else best["model"]
                ),
                "rule_b_cheapest_boundary_result": (
                    min(
                        [best, cheapest_one],
                        key=lambda row: (row["mean_billed_cost"], row["model"]),
                    )["model"]
                    if sign_hold is False and cheapest_one
                    else best["model"]
                ),
                "rule_b_all_unsigned_result": (
                    min(
                        [best]
                        + [
                            row
                            for row in one_behind
                            if not (
                                (best["a"] - row["a"] > 0 and best["b"] - row["b"] > 0)
                                or (best["a"] - row["a"] < 0 and best["b"] - row["b"] < 0)
                            )
                        ],
                        key=lambda row: (row["mean_billed_cost"], row["model"]),
                    )["model"]
                    if one_behind
                    and any(
                        not (
                            (best["a"] - row["a"] > 0 and best["b"] - row["b"] > 0)
                            or (best["a"] - row["a"] < 0 and best["b"] - row["b"] < 0)
                        )
                        for row in one_behind
                    )
                    else best["model"]
                ),
            }
            margin_audit.append(rec)
            if unique and best["stable"] - rank2["stable"] == 1 and sign_hold is False:
                unsigned_unique_one_cell.append(f"{bucket}:{lang}")
    assert unsigned_unique_one_cell == ["toolcall:hi", "coding:hi"]

    policy_fields = {
        "unique_plus_one": "rule_b_result",
        "cheapest_boundary": "rule_b_cheapest_boundary_result",
        "all_unsigned_one_behind": "rule_b_all_unsigned_result",
    }
    rule_b_sensitivity = {}
    for policy_name, field in policy_fields.items():
        policy_lookup = []
        for rec in margin_audit:
            bucket = rec["bucket"]
            lang = rec["lang"]
            qids = sorted(qids_by_bucket[bucket])
            model = rec[field]
            if (bucket, lang) == ("coding", "hi"):
                model = HUMAN_CELL_OVERRIDE[("coding", "hi")]["model"]
            pairs = [
                (cell(run_a, model, qid, lang), cell(run_b, model, qid, lang))
                for qid in qids
            ]
            cost_a = billed([a for a, _ in pairs])
            cost_b = billed([b for _, b in pairs])
            policy_lookup.append(
                {
                    "bucket": bucket,
                    "lang": lang,
                    "selected_model": model,
                    "stable_correct": sum(stable_correct(a, b) for a, b in pairs),
                    "mean_billed_cost": (cost_a["cost"] + cost_b["cost"]) / 2,
                }
            )
        stable_total = sum(row["stable_correct"] for row in policy_lookup)
        cost_a_total = sum(
            billed(
                [
                    cell(run_a, row["selected_model"], qid, row["lang"])
                    for qid in sorted(qids_by_bucket[row["bucket"]])
                ]
            )["cost"]
            for row in policy_lookup
        )
        cost_b_total = sum(
            billed(
                [
                    cell(run_b, row["selected_model"], qid, row["lang"])
                    for qid in sorted(qids_by_bucket[row["bucket"]])
                ]
            )["cost"]
            for row in policy_lookup
        )
        adopted_lookup = {
            (row["bucket"], row["lang"]): row["selected_model"] for row in lookup
        }
        policy_lookup_map = {
            (row["bucket"], row["lang"]): row["selected_model"] for row in policy_lookup
        }
        rule_b_sensitivity[policy_name] = {
            "stable_correct": stable_total,
            "stable_accuracy": stable_total / 294,
            "cost_a": cost_a_total,
            "cost_b": cost_b_total,
            "mean_billed_cost": (cost_a_total + cost_b_total) / 2,
            "cells_changed_vs_adopted": [
                f"{bucket}:{lang}"
                for bucket, lang in adopted_lookup
                if adopted_lookup[(bucket, lang)] != policy_lookup_map[(bucket, lang)]
            ],
            "adopted": policy_name == "cheapest_boundary",
        }
    assert rule_b_sensitivity["unique_plus_one"]["stable_correct"] == 267
    assert math.isclose(
        rule_b_sensitivity["unique_plus_one"]["mean_billed_cost"], 3.368173337, rel_tol=0, abs_tol=1e-6
    )
    assert rule_b_sensitivity["cheapest_boundary"]["stable_correct"] == 262
    assert math.isclose(
        rule_b_sensitivity["cheapest_boundary"]["mean_billed_cost"],
        lookup_point["mean_billed_cost"],
        rel_tol=0,
        abs_tol=1e-12,
    )
    assert rule_b_sensitivity["all_unsigned_one_behind"]["stable_correct"] == 261

    payload = {
        "cost_rule": {
            "primary": "billed usage.cost",
            "run_combination": "arithmetic mean of A and B observed billed totals",
            "tie_break": (
                "max stable accuracy, then min A/B mean billed for the 14-item cell "
                "(same order as per-request mean)"
            ),
            "coding_hi_override": HUMAN_CELL_OVERRIDE[("coding", "hi")],
            "toolcall_hi_unsigned_tie": HUMAN_UNSIGNED_TIE[("toolcall", "hi")],
            "unsigned_rule": (
                "Human 2026-08-23T04:44Z option B: uniformly apply to every "
                "premium=yes unsigned margin against the cheapest one-behind. "
                "Treat the margin as a tie and select min billed. Option C "
                "(expanding the tie pool to every unsigned one-behind) is rejected."
            ),
            "override_scope": (
                "Human 2026-08-23T04:44Z explicitly superseded the narrow scope "
                "and required uniform application across all 21 cells."
            ),
            "missing_cost": "exclude cell, keep model; no catalog imputation",
            "opus_note": (
                "A and B each have 293 billed cells. The missing cell is the same "
                "key in both runs: claude_opus_5|toolcall:parallel_multiple_139|en"
            ),
            "opus_cost_null_keys": opus_null,
            "cost_noise_floor": "A/B full-matrix billed totals differ by 3.81%",
            "lookup_ab_cost_spread": (
                "locked lookup billed A $3.598971 vs B $3.066849; "
                "mean $3.332910; driven by coding-ko fable"
            ),
            "winners_curse": (
                "262/294 is an in-sample upper-bound estimate. Do not numerically correct."
            ),
        },
        "final_qid_ledger": {
            "path": "reports/final_qid_98.txt",
            "n": 98,
            "sha256": qid_ledger_sha256,
        },
        "lookup": lookup,
        "lookup_point": lookup_point,
        "all_coding_grok_point": all_coding_grok_point,
        "symmetric_b_all_coding_grok_audit": symmetric_b_all_grok_audit,
        "margin_audit": margin_audit,
        "unsigned_unique_one_cell_edges": unsigned_unique_one_cell,
        "rule_b_sensitivity": rule_b_sensitivity,
        "model_points": model_points,
        "unrestricted_pareto_frontier": unrestricted_frontier,
        "product_comparison_points": product_comparison_points,
        "product_coordinate_frontier_mixed_rule_versions": pareto_frontier(
            product_comparison_points
        ),
        "product_pareto_frontier": None,
        "pareto_frontier": None,
        "pareto_note": (
            "No product frontier is asserted across mixed rule versions. "
            "The five human-specified points include frozen pre-B all-grok and "
            "post-B lookup. See symmetric_b_all_coding_grok_audit."
        ),
    }
    OUT_JSON.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")

    with OUT_CSV.open("w", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            lineterminator="\n",
            fieldnames=[
                "bucket",
                "lang",
                "selected_model",
                "stable_correct",
                "stable_n",
                "stable_oracle",
                "residual_to_oracle",
                "cost_a_usd",
                "cost_a_n_billed",
                "cost_b_usd",
                "cost_b_n_billed",
                "mean_billed_cost_usd",
                "accuracy_tie_models",
                "argmax_model",
                "pre_rule_model",
                "rule_b_applied",
                "rule_b_one_behind_model",
                "rule_b_margin_a",
                "rule_b_margin_b",
                "rule_b_has_premium",
                "human_override",
                "unsigned_tie_rule",
                "evidence_grade",
            ],
        )
        writer.writeheader()
        for row in lookup:
            writer.writerow(
                {
                    "bucket": row["bucket"],
                    "lang": row["lang"],
                    "selected_model": row["selected_model"],
                    "stable_correct": row["stable_correct"],
                    "stable_n": row["stable_n"],
                    "stable_oracle": row["stable_oracle"],
                    "residual_to_oracle": row["residual_to_oracle"],
                    "cost_a_usd": f'{row["cost_a"]["cost"]:.9f}',
                    "cost_a_n_billed": row["cost_a"]["n_billed"],
                    "cost_b_usd": f'{row["cost_b"]["cost"]:.9f}',
                    "cost_b_n_billed": row["cost_b"]["n_billed"],
                    "mean_billed_cost_usd": f'{row["mean_billed_cost"]:.9f}',
                    "accuracy_tie_models": "|".join(row["accuracy_tie_models"]),
                    "argmax_model": row["argmax_model"],
                    "pre_rule_model": row["pre_rule_model"],
                    "rule_b_applied": row["rule_b_applied"],
                    "rule_b_one_behind_model": row["rule_b_one_behind_model"] or "",
                    "rule_b_margin_a": (
                        "" if row["rule_b_margin_a"] is None else row["rule_b_margin_a"]
                    ),
                    "rule_b_margin_b": (
                        "" if row["rule_b_margin_b"] is None else row["rule_b_margin_b"]
                    ),
                    "rule_b_has_premium": row["rule_b_has_premium"],
                    "human_override": row["human_override"] or "",
                    "unsigned_tie_rule": row["unsigned_tie_rule"] or "",
                    "evidence_grade": row["evidence_grade"],
                }
            )

    render_svg(all_points, product_comparison_points)
    print(
        json.dumps(
            {
                "lookup": {
                    "stable_correct": lookup_point["stable_correct"],
                    "residual": lookup_point["residual_to_oracle"],
                    "mean_billed_cost": lookup_point["mean_billed_cost"],
                },
                "product_comparison_points": [
                    point["name"] for point in product_comparison_points
                ],
                "coordinate_frontier_mixed_rule_versions": [
                    point["name"]
                    for point in pareto_frontier(product_comparison_points)
                ],
                "unrestricted_frontier": [point["name"] for point in unrestricted_frontier],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
