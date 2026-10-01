#!/usr/bin/env python3
"""Pilot runner. Resume by labels.jsonl key. Does not persist model bodies."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import yaml
from huggingface_hub import hf_hub_download

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from eval.labels_schema import dump_label, label_key  # noqa: E402
from eval.outcome import classify_outcome  # noqa: E402
from eval.s_exec import decode_private_tests, run_tests  # noqa: E402
from eval.scorers import SCORERS, score  # noqa: E402

OPENROUTER = "https://openrouter.ai/api/v1/chat/completions"
KEY_PATH = Path("$OPENROUTER_KEY_FILE")
CFG = yaml.safe_load((ROOT / "config.yaml").read_text())
HTTP_TIMEOUT_S = 900

COMPLETED_STATUSES = set(CFG["scoring"]["completed_statuses"])
RETRY_STATUSES = set(CFG["scoring"]["retry_statuses"])
INFRA_BUDGET = int(CFG["scoring"]["infra_retry_budget"])


def api_key() -> str:
    return os.environ.get("OPENROUTER_API_KEY", "").strip() or KEY_PATH.read_text().strip()


def models_by_key() -> dict:
    return {m["key"]: m for m in CFG["models"]}


def max_tokens_for(bucket: str) -> int:
    mt = CFG["max_tokens"]
    if bucket == "coding":
        return int(mt["coding"])
    if bucket == "instruction":
        return int(mt["instruction"])
    return int(mt["default"])


def compact_labels(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    last: dict[str, dict] = {}
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("key"):
            last[row["key"]] = row
    for row in last.values():
        # One diagnostic revision temporarily used provider_error. Human criteria
        # classify MALFORMED_FUNCTION_CALL as a model format failure instead.
        if row.get("status") == "provider_error":
            row["status"] = "parse_failed"
            row["parse_ok"] = False
            row["correct"] = 0
            row["error_class"] = None
            row["infra_attempt"] = None
        if row.get("status") in {"parse_failed", "cap_hit"}:
            row["correct"] = 0
    with path.open("w") as fh:
        for row in last.values():
            fh.write(dump_label(row) + "\n")
    return last


def chat(model_id: str, prompt: str, max_tokens: int, title: str = "010-pilot") -> dict:
    body = json.dumps(
        {
            "model": model_id,
            "temperature": CFG["temperature"],
            "seed": CFG["seed"],
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }
    ).encode()
    last_exc: BaseException | None = None
    for trial in range(4):
        req = urllib.request.Request(
            OPENROUTER,
            data=body,
            headers={
                "Authorization": f"Bearer {api_key()}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://example.invalid/anonymous-replication",
                "X-Title": title,
            },
            method="POST",
        )
        t0 = time.time()
        try:
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_S) as resp:
                payload = json.loads(resp.read().decode())
            break
        except urllib.error.HTTPError as exc:
            last_exc = exc
            if exc.code in {429, 500, 502, 503} and trial < 3:
                time.sleep(2 ** trial)
                continue
            raise
        except TimeoutError as exc:
            last_exc = exc
            if trial < 3:
                time.sleep(2 ** trial)
                continue
            raise
    else:
        raise last_exc or RuntimeError("chat failed")
    latency = int((time.time() - t0) * 1000)
    choice = (payload.get("choices") or [{}])[0]
    msg = choice.get("message") or {}
    content = msg.get("content")
    if isinstance(content, list):
        text = "".join(
            (b.get("text") or "") if isinstance(b, dict) else str(b) for b in content
        )
    else:
        text = content or ""
    usage = payload.get("usage") or {}
    cost = usage.get("cost")
    if cost is None:
        details = usage.get("cost_details") or {}
        cost = details.get("upstream_inference_cost")
    details_c = usage.get("completion_tokens_details") or {}
    return {
        "text": text,
        "prompt_tokens": usage.get("prompt_tokens"),
        "completion_tokens": usage.get("completion_tokens"),
        "reasoning_tokens": details_c.get("reasoning_tokens"),
        "cost_usd": cost,
        "latency_ms": latency,
        "routed_model": payload.get("model"),
        "finish_reason": choice.get("finish_reason") or choice.get("native_finish_reason"),
        "native_finish_reason": choice.get("native_finish_reason"),
    }


def classify_http(exc: BaseException) -> str:
    name = type(exc).__name__.lower()
    text = str(exc).lower()
    if "timeout" in name or "timeout" in text:
        return "timeout"
    return "http_error"


def attach_coding_tests(queries: list[dict]) -> None:
    src = CFG["sources"]["livecodebench"]
    want = {
        str(q["gold"].get("question_id"))
        for q in queries
        if q["bucket"] == "coding"
    }
    found = {}
    for name in ["test.jsonl", "test2.jsonl", "test3.jsonl", "test4.jsonl", "test5.jsonl", "test6.jsonl"]:
        path = hf_hub_download(src["hub"], name, repo_type="dataset", revision=src["revision"])
        for line in Path(path).read_text().splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            qid = str(row.get("question_id"))
            if qid in want:
                found[qid] = row.get("private_test_cases") or ""
    for q in queries:
        if q["bucket"] != "coding":
            continue
        pub = json.loads(q["gold"]["public_test_cases"])
        priv = decode_private_tests(found.get(str(q["gold"]["question_id"])) or "")
        q["gold"] = {
            "tests": list(pub) + list(priv),
            "starter": q["gold"].get("starter") or "",
            "fn_name": q["gold"].get("fn_name") or "",
        }


def one_call(model: dict, query: dict, title: str) -> dict:
    key = label_key(model["key"], query["qid"], query["lang"])
    cap = max_tokens_for(query["bucket"])
    rec = {
        "key": key,
        "qid": query["qid"],
        "lang": query["lang"],
        "bucket": query["bucket"],
        "scorer": query["scorer"],
        "model_key": model["key"],
        "model_id": model["model_id"],
        "status": "ok",
        "parse_ok": False,
        "correct": None,
        "prompt_tokens": None,
        "completion_tokens": None,
        "reasoning_tokens": None,
        "finish_reason": None,
        "native_finish_reason": None,
        "max_tokens": cap,
        "cost_usd": None,
        "latency_ms": None,
        "error_class": None,
        "sandbox": None,
        "infra_attempt": None,
    }
    try:
        got = chat(model["model_id"], query["prompt"], cap, title=title)
    except Exception as exc:  # noqa: BLE001
        rec["status"] = classify_http(exc)
        rec["error_class"] = type(exc).__name__
        rec["parse_ok"] = False
        rec["correct"] = None
        return rec
    rec["prompt_tokens"] = got["prompt_tokens"]
    rec["completion_tokens"] = got["completion_tokens"]
    rec["reasoning_tokens"] = got["reasoning_tokens"]
    rec["finish_reason"] = got["finish_reason"]
    rec["native_finish_reason"] = got["native_finish_reason"]
    rec["cost_usd"] = got["cost_usd"]
    rec["latency_ms"] = got["latency_ms"]
    scored = score(query["scorer"], got["text"], query["gold"])
    rec["parse_ok"] = bool(scored.get("parse_ok"))
    rec["correct"] = scored.get("correct")
    if scored.get("sandbox") is not None:
        rec["sandbox"] = scored.get("sandbox")
    sandbox_status = scored.get("status") if scored.get("status") == "sandbox_error" else None
    status, override = classify_outcome(
        sandbox_status=sandbox_status,
        parse_ok=rec["parse_ok"],
        finish_reason=rec["finish_reason"],
        completion_tokens=rec["completion_tokens"],
        cap=cap,
    )
    rec["status"] = status
    if override is not None:
        rec["correct"] = override
    elif status == "ok":
        rec["correct"] = scored.get("correct")
    # got["text"] dropped. never copied into rec.
    return rec


def sandbox_probe() -> dict:
    ok_code = "print(input())\n"
    timeout_code = "while True:\n    pass\n"
    net_code = (
        "import urllib.request\n"
        "urllib.request.urlopen('http://example.com', timeout=2)\n"
        "print('net')\n"
    )
    stdin = [{"input": "hi\n", "output": "hi", "testtype": "stdin"}]
    r_ok = run_tests(ok_code, stdin, timeout_s=2)
    r_to = run_tests(timeout_code, stdin, timeout_s=1)
    r_net = run_tests(net_code, stdin, timeout_s=3)
    return {
        "correct_stdin": bool(r_ok.get("ok")),
        "timeout_fires": r_to.get("kind") == "timeout",
        "network_blocked": r_net.get("kind") in {"network_blocked", "runtime", "fail"},
        "timeout_kind": r_to.get("kind"),
        "network_kind": r_net.get("kind"),
    }


def summarize(rows: list[dict], model: dict | None = None) -> dict:
    last: dict[str, dict] = {}
    for r in rows:
        last[r["key"]] = r
    rows = list(last.values())
    n = len(rows)
    status = Counter(r["status"] for r in rows)
    n_cap_hit = sum(1 for r in rows if r.get("status") == "cap_hit")
    n_parse_failed = sum(1 for r in rows if r.get("status") == "parse_failed")
    infra = [r for r in rows if r.get("status") in RETRY_STATUSES]
    n_correct = sum(1 for r in rows if r.get("correct") == 1)
    parse_ok_not_infra_not_caphit = [
        r
        for r in rows
        if r.get("parse_ok")
        and r.get("status") not in RETRY_STATUSES
        and r.get("status") != "cap_hit"
    ]
    n_correct_diag = sum(1 for r in parse_ok_not_infra_not_caphit if r.get("correct") == 1)
    by_bucket: dict = {}
    by_lang: dict = {}
    by_scorer = Counter(r["scorer"] for r in rows)
    cap_hit_lang_bucket: dict = defaultdict(lambda: {"ko": 0, "en": 0, "hi": 0})
    parse_fail_lang_bucket: dict = defaultdict(lambda: {"ko": 0, "en": 0, "hi": 0})
    for r in rows:
        by_bucket.setdefault(
            r["bucket"],
            {
                "n": 0,
                "parse_failed": 0,
                "cap_hit": 0,
                "correct": 0,
                "parse_ok_not_infra_not_caphit": 0,
                "infra": 0,
            },
        )
        b = by_bucket[r["bucket"]]
        b["n"] += 1
        if r.get("status") == "parse_failed":
            b["parse_failed"] += 1
            parse_fail_lang_bucket[r["bucket"]][r["lang"]] += 1
        if r.get("status") == "cap_hit":
            b["cap_hit"] += 1
            cap_hit_lang_bucket[r["bucket"]][r["lang"]] += 1
        if r.get("status") in RETRY_STATUSES:
            b["infra"] += 1
        if (
            r.get("parse_ok")
            and r.get("status") not in RETRY_STATUSES
            and r.get("status") != "cap_hit"
        ):
            b["parse_ok_not_infra_not_caphit"] += 1
            b["correct"] += int(r.get("correct") == 1)
        by_lang.setdefault(
            r["lang"],
            {
                "n": 0,
                "parse_failed": 0,
                "cap_hit": 0,
                "correct": 0,
                "parse_ok_not_infra_not_caphit": 0,
            },
        )
        L = by_lang[r["lang"]]
        L["n"] += 1
        if r.get("status") == "parse_failed":
            L["parse_failed"] += 1
        if r.get("status") == "cap_hit":
            L["cap_hit"] += 1
        if (
            r.get("parse_ok")
            and r.get("status") not in RETRY_STATUSES
            and r.get("status") != "cap_hit"
        ):
            L["parse_ok_not_infra_not_caphit"] += 1
            L["correct"] += int(r.get("correct") == 1)
    qids = {}
    for r in rows:
        qids.setdefault(r["qid"], set()).add(r["lang"])
    invariant = all(v == {"ko", "en", "hi"} for v in qids.values()) and len(qids) == 98
    billed = sum(float(r["cost_usd"] or 0) for r in rows)
    pt = sum(int(r["prompt_tokens"] or 0) for r in rows)
    ct = sum(int(r["completion_tokens"] or 0) for r in rows)
    catalog = None
    if model:
        catalog = (pt * float(model["price_in"]) + ct * float(model["price_out"])) / 1e6
    or_list = (pt * 0.0679 + ct * 0.168) / 1e6
    return {
        "n": n,
        "status": dict(status),
        "n_parse_failed": n_parse_failed,
        "n_cap_hit": n_cap_hit,
        "n_infra_unscored": len(infra),
        "n_correct": n_correct,
        "denom_matrix_294": 294,
        "accuracy_matrix_parse_as_0": n_correct / 294 if n else None,
        "denom_parse_ok_not_infra_not_caphit": len(parse_ok_not_infra_not_caphit),
        "n_correct_parse_ok_not_infra_not_caphit": n_correct_diag,
        "scoring_pin": CFG.get("scoring"),
        "max_tokens": CFG.get("max_tokens"),
        "by_bucket": by_bucket,
        "by_lang": by_lang,
        "parse_fail_lang_bucket": {k: dict(v) for k, v in parse_fail_lang_bucket.items()},
        "cap_hit_lang_bucket": {k: dict(v) for k, v in cap_hit_lang_bucket.items()},
        "by_scorer": dict(by_scorer),
        "scorers_seen": sorted(by_scorer),
        "scorers_expected": list(SCORERS),
        "qid_three_langs": invariant,
        "n_qid": len(qids),
        "prompt_tokens": pt,
        "completion_tokens": ct,
        "cost_usd_billed": round(billed, 6),
        "cost_usd_catalog_config": None if catalog is None else round(catalog, 6),
        "cost_usd_openrouter_list_0.0679_0.168": round(or_list, 6),
    }


def load_queries(path: Path, limit: int) -> list[dict]:
    queries = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
    if limit:
        queries = queries[:limit]
    attach_coding_tests(queries)
    return queries


def run_model(model: dict, queries: list[dict], out_dir: Path, title: str) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    labels_path = out_dir / "labels.jsonl"
    probe = sandbox_probe()
    (out_dir / "sandbox_probe.json").write_text(json.dumps(probe, indent=2) + "\n")
    conc = int(CFG["max_concurrency"])
    while True:
        last = compact_labels(labels_path)
        done = {k for k, r in last.items() if r.get("status") in COMPLETED_STATUSES}
        todo = []
        for q in queries:
            key = label_key(model["key"], q["qid"], q["lang"])
            if key in done:
                continue
            prev = last.get(key)
            n_try = int((prev or {}).get("infra_attempt") or 0)
            if prev and prev.get("status") in RETRY_STATUSES and n_try >= INFRA_BUDGET:
                continue
            todo.append(q)
        print(
            json.dumps(
                {
                    "model": model["model_id"],
                    "resume_existing": len(done),
                    "todo": len(todo),
                    "total": len(queries),
                    "infra_exhausted": sum(
                        1
                        for q in queries
                        if label_key(model["key"], q["qid"], q["lang"]) not in done
                        and int((last.get(label_key(model["key"], q["qid"], q["lang"])) or {}).get("infra_attempt") or 0)
                        >= INFRA_BUDGET
                    ),
                }
            ),
            flush=True,
        )
        if not todo:
            break
        with labels_path.open("a") as fh:
            with ThreadPoolExecutor(max_workers=conc) as pool:
                futs = [pool.submit(one_call, model, q, title) for q in todo]
                n = 0
                for fut in as_completed(futs):
                    rec = fut.result()
                    key = rec["key"]
                    prev = last.get(key)
                    if rec["status"] in RETRY_STATUSES:
                        rec["infra_attempt"] = int((prev or {}).get("infra_attempt") or 0) + 1
                    line = dump_label(rec)
                    fh.write(line + "\n")
                    fh.flush()
                    n += 1
                    if n % 20 == 0:
                        print(
                            f"{model['key']} wrote {n}/{len(todo)} last={rec['status']} {rec['qid']} {rec['lang']}",
                            flush=True,
                        )
    rows = [json.loads(l) for l in labels_path.read_text().splitlines() if l.strip()]
    summary = summarize(rows, model)
    summary["sandbox_probe"] = probe
    summary["model_key"] = model["key"]
    summary["labels_path"] = str(labels_path.relative_to(ROOT))
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))
    return summary


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--model-key", default="deepseek_v4_flash")
    p.add_argument("--all-models", action="store_true")
    p.add_argument("--queries", default=str(ROOT / "data" / "queries_294.jsonl"))
    p.add_argument("--out-dir", default="")
    p.add_argument("--out-root", default="")
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--title", default="010-pilot")
    args = p.parse_args()
    queries = load_queries(Path(args.queries), args.limit)
    if args.all_models:
        root = Path(args.out_root) if args.out_root else ROOT / "results" / "phase2"
        for model in CFG["models"]:
            out_dir = root / model["key"]
            run_model(model, queries, out_dir, title=args.title)
        return 0
    model = models_by_key()[args.model_key]
    out_dir = Path(args.out_dir) if args.out_dir else ROOT / "results" / f"smoke_{args.model_key}"
    run_model(model, queries, out_dir, title=args.title)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
