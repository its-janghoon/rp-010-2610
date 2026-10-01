#!/usr/bin/env python3
"""Live-check pinned OpenRouter model ids. No bodies stored.

Checks: catalog membership, HTTP, routed slug vs requested, usage.cost.
Gemini Flash extra: short vs longer max_tokens, usage.include, generation lookup.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
KEY_PATH = Path("$OPENROUTER_KEY_FILE")
CFG = yaml.safe_load((ROOT / "config.yaml").read_text())
CHAT = "https://openrouter.ai/api/v1/chat/completions"
MODELS = "https://openrouter.ai/api/v1/models"
GENERATION = "https://openrouter.ai/api/v1/generation"


def api_key() -> str:
    return os.environ.get("OPENROUTER_API_KEY", "").strip() or KEY_PATH.read_text().strip()


def headers() -> dict:
    return {
        "Authorization": f"Bearer {api_key()}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://example.invalid/anonymous-replication",
        "X-Title": "010-model-id-verify",
    }


def catalog_ids() -> set[str]:
    req = urllib.request.Request(MODELS, headers=headers(), method="GET")
    with urllib.request.urlopen(req, timeout=60) as resp:
        payload = json.loads(resp.read().decode())
    return {str(m.get("id")) for m in payload.get("data") or []}


def chat(model_id: str, max_tokens: int, extra: dict | None = None) -> dict:
    body = {
        "model": model_id,
        "temperature": 0,
        "seed": 42,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": "Reply with the single digit 1."}],
    }
    if extra:
        body.update(extra)
    req = urllib.request.Request(
        CHAT, data=json.dumps(body).encode(), headers=headers(), method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            payload = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return {
            "ok": False,
            "http": e.code,
            "error": e.read().decode("utf-8", "replace")[:240],
        }
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "http": None, "error": f"{type(e).__name__}: {e}"[:240]}
    choice = (payload.get("choices") or [{}])[0]
    msg = choice.get("message") or {}
    content = msg.get("content")
    if isinstance(content, list):
        n_content = sum(len(b.get("text") or "") if isinstance(b, dict) else 0 for b in content)
    else:
        n_content = len(content or "")
    usage = payload.get("usage") or {}
    cost = usage.get("cost")
    if cost is None:
        cost = (usage.get("cost_details") or {}).get("upstream_inference_cost")
    return {
        "ok": True,
        "http": 200,
        "id": payload.get("id"),
        "routed": payload.get("model"),
        "provider": payload.get("provider"),
        "finish_reason": choice.get("finish_reason"),
        "n_content": n_content,
        "has_reasoning": bool(msg.get("reasoning")),
        "usage_keys": sorted(usage.keys()) if usage else [],
        "has_usage": bool(usage),
        "has_usage_cost": cost is not None,
        "cost": cost,
        "prompt_tokens": usage.get("prompt_tokens"),
        "completion_tokens": usage.get("completion_tokens"),
        "reasoning_tokens": (usage.get("completion_tokens_details") or {}).get("reasoning_tokens"),
    }


def generation_lookup(gen_id: str | None) -> dict:
    if not gen_id:
        return {"ok": False, "error": "no_id"}
    url = GENERATION + "?" + urllib.parse.urlencode({"id": gen_id})
    req = urllib.request.Request(url, headers=headers(), method="GET")
    try:
        time.sleep(1.2)
        with urllib.request.urlopen(req, timeout=60) as resp:
            payload = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return {"ok": False, "http": e.code, "error": e.read().decode("utf-8", "replace")[:200]}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {e}"[:200]}
    data = payload.get("data") or payload
    return {
        "ok": True,
        "keys": sorted(data.keys()) if isinstance(data, dict) else [],
        "model": data.get("model") if isinstance(data, dict) else None,
        "total_cost": data.get("total_cost") if isinstance(data, dict) else None,
        "usage": data.get("usage") if isinstance(data, dict) else None,
        "native_tokens_completion": data.get("native_tokens_completion") if isinstance(data, dict) else None,
    }


def probe_one(model: dict, catalog: set[str]) -> dict:
    mid = model["model_id"]
    base = {
        "key": model["key"],
        "model_id": mid,
        "in_catalog": mid in catalog,
    }
    got = chat(mid, 16)
    base.update(got)
    if got.get("ok"):
        base["routed_equals_requested"] = got.get("routed") == mid
    else:
        base["routed_equals_requested"] = False
    return base


def flash_extras(model_id: str) -> list[dict]:
    rows = []
    for label, extra, mt in [
        ("short_4", None, 4),
        ("longer_256", None, 256),
        ("usage_include_true", {"usage": {"include": True}}, 256),
        ("stream_include_usage", {"stream": False, "stream_options": {"include_usage": True}}, 256),
    ]:
        got = chat(model_id, mt, extra)
        got["variant"] = label
        got["max_tokens"] = mt
        if got.get("ok") and got.get("id") and not got.get("has_usage_cost"):
            got["generation"] = generation_lookup(got.get("id"))
        rows.append(got)
    return rows


def main() -> int:
    catalog = catalog_ids()
    models = list(CFG["models"])
    rows = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        futs = [pool.submit(probe_one, m, catalog) for m in models]
        for fut in as_completed(futs):
            rows.append(fut.result())
    rows.sort(key=lambda r: r["key"])
    flash = next(m for m in models if m["key"] == "gemini_3_7_flash")
    flash_rows = flash_extras(flash["model_id"])
    n_ok = sum(1 for r in rows if r.get("ok"))
    n_cost = sum(1 for r in rows if r.get("has_usage_cost"))
    n_match = sum(1 for r in rows if r.get("routed_equals_requested"))
    n_cat = sum(1 for r in rows if r.get("in_catalog"))
    mismatches = [
        {"key": r["key"], "requested": r["model_id"], "routed": r.get("routed"), "http": r.get("http")}
        for r in rows
        if r.get("ok") and not r.get("routed_equals_requested")
    ]
    out = {
        "n_models": len(rows),
        "n_in_catalog": n_cat,
        "n_ok": n_ok,
        "n_routed_equals_requested": n_match,
        "n_has_usage_cost": n_cost,
        "mismatches": mismatches,
        "missing_catalog": [r["key"] for r in rows if not r.get("in_catalog")],
        "missing_cost": [r["key"] for r in rows if r.get("ok") and not r.get("has_usage_cost")],
        "http_fail": [r["key"] for r in rows if not r.get("ok")],
        "rows": rows,
        "gemini_3_7_flash_extra": flash_rows,
    }
    print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
