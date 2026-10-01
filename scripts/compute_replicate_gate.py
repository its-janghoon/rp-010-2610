#!/usr/bin/env python3
"""A/B flips, seven gate variants, and language decompositions. No bodies."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PHASE2 = ROOT / "results/phase2"
REP1 = ROOT / "results/replicate1"
COMPLETED = {"ok", "parse_failed", "cap_hit"}
RETRY = {"http_error", "timeout", "sandbox_error", "sandbox_timeout", "sandbox_network_blocked"}
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


def last_per_key(path: Path) -> dict[str, dict]:
    last: dict[str, dict] = {}
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        last[row["key"]] = row
    return last


def load_run(root: Path) -> dict[str, dict[str, dict]]:
    out = {}
    for d in sorted(p for p in root.iterdir() if p.is_dir() and (p / "labels.jsonl").exists()):
        out[d.name] = last_per_key(d / "labels.jsonl")
    return out


def item_id(row: dict) -> tuple[str, str]:
    return (row["qid"], row["lang"])


def is_infra(row: dict) -> bool:
    return (row.get("status") or "") in RETRY


def is_cap(row: dict) -> bool:
    return row.get("status") == "cap_hit"


def is_correct(row: dict) -> bool:
    return row.get("status") in COMPLETED and row.get("correct") == 1


def usable(row: dict, *, drop_cap: bool) -> bool:
    if is_infra(row):
        return False
    if drop_cap and is_cap(row):
        return False
    return True


def main() -> int:
    from eval.labels_schema import audit_labels

    a_run = load_run(PHASE2)
    b_run = load_run(REP1)
    models = sorted(set(a_run) | set(b_run))
    audits = {}
    for name, run in (("phase2", a_run), ("replicate1", b_run)):
        audits[name] = {}
        for mk, last in run.items():
            audits[name][mk] = audit_labels(last.values())

    items = sorted({item_id(r) for last in a_run.values() for r in last.values()})
    assert len(items) == 294, len(items)

    def cell(run, mk, qid, lang):
        key = f"{mk}|{qid}|{lang}"
        return run[mk][key]

    infra_a = []
    infra_b = []
    for mk in models:
        for r in a_run[mk].values():
            if is_infra(r):
                infra_a.append({"model": mk, "qid": r["qid"], "lang": r["lang"], "status": r["status"], "infra_attempt": r.get("infra_attempt")})
        for r in b_run[mk].values():
            if is_infra(r):
                infra_b.append({"model": mk, "qid": r["qid"], "lang": r["lang"], "status": r["status"], "infra_attempt": r.get("infra_attempt")})

    status_a = {mk: dict(Counter(r.get("status") for r in a_run[mk].values())) for mk in models}
    status_b = {mk: dict(Counter(r.get("status") for r in b_run[mk].values())) for mk in models}
    n_a = {mk: len(a_run[mk]) for mk in models}
    n_b = {mk: len(b_run[mk]) for mk in models}

    billed_a = {}
    billed_b = {}
    cost_null_a = []
    cost_null_b = []
    for mk in models:
        sa = sum(r.get("cost_usd") or 0 for r in a_run[mk].values())
        sb = sum(r.get("cost_usd") or 0 for r in b_run[mk].values())
        billed_a[mk] = round(sa, 6)
        billed_b[mk] = round(sb, 6)
        for r in a_run[mk].values():
            if r.get("cost_usd") is None:
                cost_null_a.append(r["key"])
        for r in b_run[mk].values():
            if r.get("cost_usd") is None:
                cost_null_b.append(r["key"])

    # flips on scored-correct bit among paired completed-or-not cells
    flips = []
    status_trans = Counter()
    for mk in models:
        for qid, lang in items:
            ra = cell(a_run, mk, qid, lang)
            rb = cell(b_run, mk, qid, lang)
            ca, cb = is_correct(ra), is_correct(rb)
            sa, sb = ra.get("status") or "null", rb.get("status") or "null"
            status_trans[f"{sa}->{sb}"] += 1
            if ca != cb:
                flips.append(
                    {
                        "model": mk,
                        "qid": qid,
                        "lang": lang,
                        "bucket": ra["bucket"],
                        "a_status": sa,
                        "b_status": sb,
                        "a_correct": ra.get("correct"),
                        "b_correct": rb.get("correct"),
                        "direction": "1->0" if ca and not cb else "0->1",
                    }
                )

    flip_by_model = Counter()
    flip_10 = Counter()
    flip_01 = Counter()
    flip_by_bucket = Counter()
    flip_by_lang = Counter()
    for f in flips:
        flip_by_model[f["model"]] += 1
        flip_by_bucket[f["bucket"]] += 1
        flip_by_lang[f["lang"]] += 1
        if f["direction"] == "1->0":
            flip_10[f["model"]] += 1
        else:
            flip_01[f["model"]] += 1

    def acc_model(run, mk, *, drop_cap: bool) -> dict:
        rows = list(run[mk].values())
        scored = [r for r in rows if usable(r, drop_cap=drop_cap)]
        n_corr = sum(1 for r in scored if is_correct(r))
        n = len(scored)
        return {"n": n, "correct": n_corr, "acc": (n_corr / n) if n else None}

    def oracle_items(a_src, b_src, *, stable: bool, drop_cap: bool, drop_items: set[tuple[str, str]] | None):
        drop_items = drop_items or set()
        wins = []
        for qid, lang in items:
            if (qid, lang) in drop_items:
                continue
            hit = False
            for mk in models:
                ra = cell(a_src, mk, qid, lang)
                if not usable(ra, drop_cap=drop_cap):
                    continue
                if stable:
                    rb = cell(b_src, mk, qid, lang)
                    if not usable(rb, drop_cap=drop_cap):
                        continue
                    if is_correct(ra) and is_correct(rb):
                        hit = True
                        break
                else:
                    if is_correct(ra):
                        hit = True
                        break
            wins.append(hit)
        n = len(wins)
        c = sum(wins)
        return {"n": n, "correct": c, "acc": (c / n) if n else None}

    def best_single(a_src, b_src, *, stable: bool, drop_cap: bool, drop_items: set[tuple[str, str]] | None):
        drop_items = drop_items or set()
        rows = []
        for mk in models:
            n = 0
            c = 0
            for qid, lang in items:
                if (qid, lang) in drop_items:
                    continue
                ra = cell(a_src, mk, qid, lang)
                if not usable(ra, drop_cap=drop_cap):
                    continue
                if stable:
                    rb = cell(b_src, mk, qid, lang)
                    if not usable(rb, drop_cap=drop_cap):
                        continue
                    n += 1
                    if is_correct(ra) and is_correct(rb):
                        c += 1
                else:
                    n += 1
                    if is_correct(ra):
                        c += 1
            acc = (c / n) if n else None
            rows.append({"model": mk, "n": n, "correct": c, "acc": acc})
        rows.sort(key=lambda x: (-(x["acc"] or -1), x["model"]))
        return rows

    infra_items_a = {(x["qid"], x["lang"]) for x in infra_a}

    def usable_parse(row, *, drop_parse: bool) -> bool:
        if is_infra(row):
            return False
        if drop_parse and row.get("status") == "parse_failed":
            return False
        return True

    def oracle_items_parse(a_src, b_src, *, stable: bool, drop_parse: bool):
        wins = []
        for qid, lang in items:
            hit = False
            for mk in models:
                ra = cell(a_src, mk, qid, lang)
                if not usable_parse(ra, drop_parse=drop_parse):
                    continue
                if stable:
                    rb = cell(b_src, mk, qid, lang)
                    if not usable_parse(rb, drop_parse=drop_parse):
                        continue
                    if is_correct(ra) and is_correct(rb):
                        hit = True
                        break
                elif is_correct(ra):
                    hit = True
                    break
            wins.append(hit)
        n = len(wins)
        c = sum(wins)
        return {"n": n, "correct": c, "acc": (c / n) if n else None}

    def best_single_parse(a_src, b_src, *, stable: bool, drop_parse: bool):
        rows = []
        for mk in models:
            n = 0
            c = 0
            for qid, lang in items:
                ra = cell(a_src, mk, qid, lang)
                if not usable_parse(ra, drop_parse=drop_parse):
                    continue
                if stable:
                    rb = cell(b_src, mk, qid, lang)
                    if not usable_parse(rb, drop_parse=drop_parse):
                        continue
                    n += 1
                    if is_correct(ra) and is_correct(rb):
                        c += 1
                else:
                    n += 1
                    if is_correct(ra):
                        c += 1
            acc = (c / n) if n else None
            rows.append({"model": mk, "n": n, "correct": c, "acc": acc})
        rows.sort(key=lambda x: (-(x["acc"] or -1), x["model"]))
        return rows

    variants = {}
    for vname, stable, drop_cap in (
        ("naive_all", False, False),
        ("stable_all", True, False),
        ("naive_cap_excluded", False, True),
        ("stable_cap_excluded", True, True),
    ):
        oracle = oracle_items(a_run, b_run, stable=stable, drop_cap=drop_cap, drop_items=None)
        ranking = best_single(a_run, b_run, stable=stable, drop_cap=drop_cap, drop_items=None)
        best = ranking[0]
        gap = (oracle["acc"] - best["acc"]) if oracle["acc"] is not None and best["acc"] is not None else None
        variants[vname] = {
            "oracle": oracle,
            "best_single": best,
            "gap": gap,
            "ranking": ranking,
        }

    # naive on run B only (direct replicate of naive A)
    oracle_b = oracle_items(b_run, a_run, stable=False, drop_cap=False, drop_items=None)
    ranking_b = best_single(b_run, a_run, stable=False, drop_cap=False, drop_items=None)
    variants["naive_b_all"] = {
        "oracle": oracle_b,
        "best_single": ranking_b[0],
        "gap": (oracle_b["acc"] - ranking_b[0]["acc"]) if oracle_b["acc"] is not None else None,
        "ranking": ranking_b,
    }

    for vname, stable in (("naive_parse_excluded", False), ("stable_parse_excluded", True)):
        o = oracle_items_parse(a_run, b_run, stable=stable, drop_parse=True)
        rnk = best_single_parse(a_run, b_run, stable=stable, drop_parse=True)
        variants[vname] = {
            "oracle": o,
            "best_single": rnk[0],
            "gap": (o["acc"] - rnk[0]["acc"]) if o["acc"] is not None else None,
            "ranking": rnk,
        }

    # infra-2 sensitivity: drop the two items that had A-run infra leftovers
    sens = {}
    for vname, stable, drop_cap in (
        ("naive_all_drop_infra_items", False, False),
        ("stable_all_drop_infra_items", True, False),
    ):
        oracle = oracle_items(a_run, b_run, stable=stable, drop_cap=drop_cap, drop_items=infra_items_a)
        ranking = best_single(a_run, b_run, stable=stable, drop_cap=drop_cap, drop_items=infra_items_a)
        best = ranking[0]
        gap = (oracle["acc"] - best["acc"]) if oracle["acc"] is not None and best["acc"] is not None else None
        sens[vname] = {"oracle": oracle, "best_single": best, "gap": gap, "dropped_items": sorted(infra_items_a)}

    # by bucket / lang for stable_all and naive_all
    def slice_gate(item_filter, *, stable, drop_cap):
        sub = [it for it in items if item_filter(it)]
        # temporary: reuse oracle_items by dropping the complement
        drop = set(items) - set(sub)
        o = oracle_items(a_run, b_run, stable=stable, drop_cap=drop_cap, drop_items=drop)
        r = best_single(a_run, b_run, stable=stable, drop_cap=drop_cap, drop_items=drop)
        b0 = r[0]
        return {
            "n": o["n"],
            "oracle": o,
            "best_single": b0,
            "gap": (o["acc"] - b0["acc"]) if o["acc"] is not None and b0["acc"] is not None else None,
        }

    qid_bucket = {}
    for r in next(iter(a_run.values())).values():
        qid_bucket[r["qid"]] = r["bucket"]

    by_bucket = {}
    by_lang = {}
    by_bucket_lang = {}
    lang_decomposition = {}
    for lab, stable in (("naive", False), ("stable", True)):
        by_bucket[lab] = {}
        by_lang[lab] = {}
        by_bucket_lang[lab] = {}
        for bkt in BUCKETS:
            by_bucket[lab][bkt] = slice_gate(lambda it, b=bkt: qid_bucket[it[0]] == b, stable=stable, drop_cap=False)
        for lang in LANGS:
            by_lang[lab][lang] = slice_gate(lambda it, L=lang: it[1] == L, stable=stable, drop_cap=False)
            by_bucket_lang[lab][lang] = {}
            for bkt in BUCKETS:
                by_bucket_lang[lab][lang][bkt] = slice_gate(
                    lambda it, L=lang, b=bkt: it[1] == L and qid_bucket[it[0]] == b,
                    stable=stable,
                    drop_cap=False,
                )
            overall_gap_cells = (
                by_lang[lab][lang]["oracle"]["correct"]
                - by_lang[lab][lang]["best_single"]["correct"]
            )
            within_bucket_gap_cells = sum(
                row["oracle"]["correct"] - row["best_single"]["correct"]
                for row in by_bucket_lang[lab][lang].values()
            )
            lang_decomposition.setdefault(lab, {})[lang] = {
                "overall_gap_cells": overall_gap_cells,
                "within_bucket_gap_cells": within_bucket_gap_cells,
                "between_bucket_gap_cells": overall_gap_cells - within_bucket_gap_cells,
            }

    overall_decomposition = {}
    for lab, variant_name in (("naive", "naive_all"), ("stable", "stable_all")):
        overall_gap_cells = (
            variants[variant_name]["oracle"]["correct"]
            - variants[variant_name]["best_single"]["correct"]
        )
        within_bucket_gap_cells = sum(
            row["oracle"]["correct"] - row["best_single"]["correct"]
            for row in by_bucket[lab].values()
        )
        coding_gap_cells = (
            by_bucket[lab]["coding"]["oracle"]["correct"]
            - by_bucket[lab]["coding"]["best_single"]["correct"]
        )
        language_best_correct = sum(
            row["best_single"]["correct"] for row in by_lang[lab].values()
        )
        overall_decomposition[lab] = {
            "overall_gap_cells": overall_gap_cells,
            "within_bucket_gap_cells": within_bucket_gap_cells,
            "between_bucket_gap_cells": overall_gap_cells - within_bucket_gap_cells,
            "coding_within_gap_cells": coding_gap_cells,
            "other_six_within_gap_cells": within_bucket_gap_cells - coding_gap_cells,
            "language_selector_gain_cells": (
                language_best_correct - variants[variant_name]["best_single"]["correct"]
            ),
        }

    assert overall_decomposition["naive"] == {
        "overall_gap_cells": 31,
        "within_bucket_gap_cells": 12,
        "between_bucket_gap_cells": 19,
        "coding_within_gap_cells": 9,
        "other_six_within_gap_cells": 3,
        "language_selector_gain_cells": 5,
    }
    assert overall_decomposition["stable"] == {
        "overall_gap_cells": 29,
        "within_bucket_gap_cells": 8,
        "between_bucket_gap_cells": 21,
        "coding_within_gap_cells": 7,
        "other_six_within_gap_cells": 1,
        "language_selector_gain_cells": 3,
    }

    acc_a = {mk: acc_model(a_run, mk, drop_cap=False) for mk in models}
    acc_b = {mk: acc_model(b_run, mk, drop_cap=False) for mk in models}

    both1 = Counter()
    a1b0 = Counter()
    a0b1 = Counter()
    for mk in models:
        for qid, lang in items:
            ra = cell(a_run, mk, qid, lang)
            rb = cell(b_run, mk, qid, lang)
            ca, cb = is_correct(ra), is_correct(rb)
            if ca and cb:
                both1[mk] += 1
            elif ca and not cb:
                a1b0[mk] += 1
            elif (not ca) and cb:
                a0b1[mk] += 1

    report = {
        "n_items": 294,
        "n_models": len(models),
        "models": models,
        "n_a": n_a,
        "n_b": n_b,
        "audits": {
            name: {mk: {"n": v["n"], "ok": v["ok"], "forbidden": v["forbidden_hits"], "extra_keys": v["extra_keys"]} for mk, v in block.items()}
            for name, block in audits.items()
        },
        "status_a": status_a,
        "status_b": status_b,
        "infra_a": infra_a,
        "infra_b": infra_b,
        "billed_a": billed_a,
        "billed_b": billed_b,
        "billed_a_sum": round(sum(billed_a.values()), 6),
        "billed_b_sum": round(sum(billed_b.values()), 6),
        "cost_null_a": cost_null_a,
        "cost_null_b": cost_null_b,
        "acc_a": acc_a,
        "acc_b": acc_b,
        "n_flips": len(flips),
        "n_1to0": sum(1 for f in flips if f["direction"] == "1->0"),
        "n_0to1": sum(1 for f in flips if f["direction"] == "0->1"),
        "flip_by_model": dict(flip_by_model),
        "flip_1to0_by_model": dict(flip_10),
        "flip_0to1_by_model": dict(flip_01),
        "flip_by_bucket": dict(flip_by_bucket),
        "flip_by_lang": dict(flip_by_lang),
        "status_transitions": dict(status_trans.most_common()),
        "both_correct": dict(both1),
        "a1_b0": dict(a1b0),
        "a0_b1": dict(a0b1),
        "variants": {
            k: {
                "oracle": v["oracle"],
                "best_single": v["best_single"],
                "gap": v["gap"],
                "ranking": v["ranking"],
            }
            for k, v in variants.items()
        },
        "infra_item_sensitivity": sens,
        "by_bucket": by_bucket,
        "by_lang": by_lang,
        "by_bucket_lang": by_bucket_lang,
        "lang_decomposition": lang_decomposition,
        "overall_decomposition": overall_decomposition,
        "final_decision": {
            "main_variant": "stable_all",
            "keep_all_seven_variants": True,
            "router_claim": (
                "Task type captures about 61% of naive A gap for free; "
                "material learned-routing residual is coding, not a generic router claim."
            ),
            "jitter_floor_cell_flip_rate": 221 / 4116,
            "cost_axis_ab_delta_rate": (49.591932 / 51.557488) - 1,
            "cost_null_policy": {
                "policy": "exclude_cell_keep_model",
                "model": "claude_opus_5",
                "billed_cell_denominator": 293,
                "catalog_imputation": False,
            },
        },
        "jitter_floor_note": "temp 0 / seed 42 is not bit-identical. Recap smoke had >=9/294 1->0 vs old-cap. Grok 33 replay accepted ~11/66. Gaps smaller than that jitter are not a router signal.",
    }
    out = ROOT / "reports/replicate1_gate.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({k: report[k] for k in ["n_flips", "n_1to0", "n_0to1", "infra_a", "infra_b", "billed_a_sum", "billed_b_sum"]}, indent=2))
    for k, v in report["variants"].items():
        print(k, "oracle", v["oracle"], "best", v["best_single"], "gap", round(v["gap"], 6) if v["gap"] is not None else None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
