#!/usr/bin/env python3
"""Assemble 294 (qid, lang) queries. Prompts are data; model outputs are not stored here."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import yaml
from huggingface_hub import hf_hub_download

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from eval.extraction_checker import query_schema  # noqa: E402

CFG = yaml.safe_load((ROOT / "config.yaml").read_text())
LANGS = list(CFG["languages"])
TRANSLATOR = "openai/gpt-4.1"


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]


def cache_best() -> dict[tuple[str, str], str]:
    """qid, lang -> gpt-4.1 translation text."""
    out: dict[tuple[str, str], str] = {}
    for row in read_jsonl(ROOT / "data" / "translation_cache.jsonl"):
        if row.get("model_used") != TRANSLATOR:
            continue
        qid = row["qid"]
        lang = row.get("target_lang")
        if lang not in ("ko", "hi"):
            continue
        out[(qid, lang)] = row["text"]
    return out


def load_mgsm_en() -> dict[int, dict]:
    src = CFG["sources"]["mgsm"]
    path = hf_hub_download(
        src["hub"],
        "en/test-00000-of-00001.parquet",
        repo_type="dataset",
        revision=src["revision"],
    )
    df = pd.read_parquet(path)
    items = {}
    for i, row in df.iterrows():
        items[int(i)] = {
            "question": str(row["question"]),
            "answer_number": row["answer_number"] if "answer_number" in row else row.get("answer"),
        }
    return items


def load_mmlu(lang: str) -> pd.DataFrame:
    src = CFG["sources"]["mmlu_prox"]
    path = hf_hub_download(
        src["hub"],
        f"{lang}/test-00000-of-00001.parquet",
        repo_type="dataset",
        revision=src["revision"],
    )
    return pd.read_parquet(path)


def options(row) -> list[str | None]:
    out = []
    for i in range(10):
        val = row[f"option_{i}"]
        if val is None or (isinstance(val, float) and pd.isna(val)):
            out.append(None)
        else:
            out.append(str(val))
    return out


def mcq_prompt(question: str, opts: list[str | None]) -> str:
    letters = "ABCDEFGHIJ"
    lines = [question.strip(), "", "Options:"]
    for i, opt in enumerate(opts):
        if opt is None:
            continue
        lines.append(f"{letters[i]}. {opt}")
    lines.append("")
    lines.append("Reply with the single option letter.")
    return "\n".join(lines)


def math_prompt(q: str) -> str:
    return q.strip() + "\n\nPut the final numeric answer after ####"


def extraction_prompt(doc: str, schema: str) -> str:
    return schema.strip() + "\n\nDocument:\n" + doc.strip() + "\n\nReturn only the JSON object."


def tool_prompt(utterance: str, functions) -> str:
    schema = json.dumps(functions, ensure_ascii=False)
    return (
        utterance.strip()
        + "\n\nAvailable functions (English, do not translate names):\n"
        + schema
        + "\n\nIf you call a function, write it as name(arg=value, ...). "
        "You may write several calls. Do not wrap in prose."
    )


def abstain_prompt(utterance: str, functions) -> str:
    schema = json.dumps(functions, ensure_ascii=False)
    return (
        utterance.strip()
        + "\n\nAvailable functions (English, do not translate names):\n"
        + schema
        + "\n\nIf none of the functions apply, do not call a function. Reply in natural language."
    )


def coding_prompt(question: str, starter: str) -> str:
    parts = [question.strip(), "", "Write a Python solution."]
    if starter.strip():
        parts.append("Use this starter:")
        parts.append("```python")
        parts.append(starter.rstrip())
        parts.append("```")
    return "\n".join(parts)


def fn_name_of(item: dict) -> str:
    meta = item.get("metadata") or "{}"
    if isinstance(meta, str):
        meta = json.loads(meta)
    return str(meta.get("func_name") or "")


def main() -> int:
    cache = cache_best()
    queries: list[dict] = []

    # knowledge
    pin = json.loads((ROOT / "data" / "knowledge_mmluprox14.json").read_text())
    frames = {lang: load_mmlu(lang) for lang in LANGS}
    by_id = {lang: frames[lang].set_index("question_id") for lang in LANGS}
    for item in pin["items"]:
        qid_num = item["question_id"]
        for lang in LANGS:
            row = by_id[lang].loc[qid_num]
            opts = options(row)
            gold_row = by_id["en"].loc[qid_num]
            queries.append(
                {
                    "qid": item["qid"],
                    "lang": lang,
                    "bucket": "knowledge",
                    "scorer": "mcq",
                    "prompt": mcq_prompt(str(row["question"]), opts),
                    "gold": {
                        "answer": str(gold_row["answer"]),
                        "answer_index": int(gold_row["answer_index"]),
                        "options": [o for o in options(gold_row) if o is not None],
                    },
                }
            )

    # math
    math_pin = json.loads((ROOT / "data" / "math_mgsm14_gsm8k_equations.json").read_text())
    mgsm = load_mgsm_en()
    for item in math_pin["items"]:
        idx = int(item["mgsm_index"])
        en_q = mgsm[idx]["question"]
        ans = item["answer_number"]
        for lang in LANGS:
            q = en_q if lang == "en" else cache[(item["qid"], lang)]
            queries.append(
                {
                    "qid": item["qid"],
                    "lang": lang,
                    "bucket": "math",
                    "scorer": "exact",
                    "prompt": math_prompt(q),
                    "gold": {"answer_number": ans},
                }
            )

    # instruction
    inst_pin = json.loads((ROOT / "data" / "instruction_ifeval14.json").read_text())
    for item in inst_pin["items"]:
        for lang in LANGS:
            prompt = item["prompt"] if lang == "en" else cache[(item["qid"], lang)]
            queries.append(
                {
                    "qid": item["qid"],
                    "lang": lang,
                    "bucket": "instruction",
                    "scorer": "ifeval",
                    "prompt": prompt,
                    "gold": {
                        "instruction_id_list": item["instruction_id_list"],
                        "kwargs": item["kwargs"],
                    },
                }
            )

    # extraction
    for row in read_jsonl(ROOT / "data" / "extraction14_translated.jsonl"):
        schema = row.get("query_schema_en") or query_schema(row["field_types"], row.get("schema_enums"))
        for lang in LANGS:
            doc = row["document_en"] if lang == "en" else row[f"document_{lang}"]
            queries.append(
                {
                    "qid": row["qid"],
                    "lang": lang,
                    "bucket": "extraction",
                    "scorer": "json_match",
                    "prompt": extraction_prompt(doc, schema),
                    "gold": {"gold": row["gold"]},
                }
            )

    # toolcall
    for row in read_jsonl(ROOT / "data" / "toolcall14_translated.jsonl"):
        for lang in LANGS:
            utt = row["utterance_en"] if lang == "en" else row[f"utterance_{lang}"]
            queries.append(
                {
                    "qid": row["qid"],
                    "lang": lang,
                    "bucket": "toolcall",
                    "scorer": "ast",
                    "prompt": tool_prompt(utt, row["function"]),
                    "gold": {"ground_truth": row["ground_truth"]},
                }
            )

    # abstention
    for row in read_jsonl(ROOT / "data" / "abstention14_translated.jsonl"):
        for lang in LANGS:
            utt = row["utterance_en"] if lang == "en" else row[f"utterance_{lang}"]
            queries.append(
                {
                    "qid": row["qid"],
                    "lang": lang,
                    "bucket": "abstention",
                    "scorer": "abstain",
                    "prompt": abstain_prompt(utt, row["function"]),
                    "gold": {"ground_truth": "no_tool"},
                }
            )

    # coding: public tests in gold; private tests attached at run time from the hub.
    coding_pin = json.loads((ROOT / "data" / "coding_lcb14.json").read_text())
    translated = {r["qid"]: r for r in read_jsonl(ROOT / "data" / "coding14_translated.jsonl")}
    for item in coding_pin["items"]:
        tr = translated[item["qid"]]
        starter = item.get("starter_code") or ""
        gold = {
            "question_id": str(item["question_id"]),
            "starter": starter,
            "fn_name": fn_name_of(item),
            "public_test_cases": item["public_test_cases"],
        }
        for lang in LANGS:
            q = tr["question_content_en"] if lang == "en" else tr[f"question_content_{lang}"]
            queries.append(
                {
                    "qid": item["qid"],
                    "lang": lang,
                    "bucket": "coding",
                    "scorer": "exec",
                    "prompt": coding_prompt(q, starter),
                    "gold": gold,
                }
            )

    if len(queries) != 294:
        raise SystemExit(f"expected 294, got {len(queries)}")
    by_qid: dict[str, set[str]] = {}
    for q in queries:
        by_qid.setdefault(q["qid"], set()).add(q["lang"])
    bad = {qid: sorted(langs) for qid, langs in by_qid.items() if langs != set(LANGS)}
    if bad:
        raise SystemExit(f"qid lang invariant failed: {list(bad)[:5]}")
    if len(by_qid) != 98:
        raise SystemExit(f"expected 98 qids, got {len(by_qid)}")

    out = ROOT / "data" / "queries_294.jsonl"
    with out.open("w") as fh:
        for q in queries:
            fh.write(json.dumps(q, ensure_ascii=False) + "\n")
    buckets = {}
    for q in queries:
        buckets[q["bucket"]] = buckets.get(q["bucket"], 0) + 1
    print(json.dumps({"wrote": str(out), "n": len(queries), "qids": len(by_qid), "buckets": buckets}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
