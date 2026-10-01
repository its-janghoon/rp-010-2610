"""s_exec: subprocess sandbox for coding. Timeout + network block."""

from __future__ import annotations

import json
import os
import subprocess
import sys

TIMEOUT_S = 6
CHECKER_ID = "010.s_exec"

RUNNER = r'''
import ast
import io
import json
import socket
import sys

class _BlockedSocket:
    def __init__(self, *a, **k):
        raise OSError("s_exec: network blocked")

socket.socket = _BlockedSocket
socket.create_connection = lambda *a, **k: (_ for _ in ()).throw(OSError("s_exec: network blocked"))
socket.getaddrinfo = lambda *a, **k: (_ for _ in ()).throw(OSError("s_exec: network blocked"))

def _strip_main(src: str) -> str:
    return src.replace('if __name__ == "__main__":', "if False:")

def _parse_args(blob: str):
    args = []
    for line in blob.replace("\r\n", "\n").split("\n"):
        if line.strip() == "":
            continue
        args.append(ast.literal_eval(line))
    return args

def _eq(got, exp) -> bool:
    try:
        if got == exp:
            return True
    except Exception:
        pass
    return str(got).strip() == str(exp).strip()

def run(payload: dict) -> dict:
    tests = payload["tests"]
    code = payload["code"]
    starter = payload.get("starter") or ""
    fn_name = payload.get("fn_name") or ""
    src = code
    if starter and "class Solution" not in code and fn_name:
        src = starter + "\n" + code
    src = _strip_main(src)
    compiled = compile(src, "<s_exec>", "exec")
    n_pass = 0
    n_fail = 0
    loc_fn = {}
    first = tests[0] if tests else {}
    if (first.get("testtype") or "stdin") == "functional":
        try:
            exec(compiled, loc_fn, loc_fn)
        except OSError as e:
            kind = "network_blocked" if "network blocked" in str(e) else "runtime"
            return {"ok": False, "kind": kind, "n_pass": 0, "n_fail": 0, "n": len(tests)}
        except Exception:
            return {"ok": False, "kind": "runtime", "n_pass": 0, "n_fail": len(tests), "n": len(tests)}
    for case in tests:
        ttype = case.get("testtype") or "stdin"
        try:
            if ttype == "functional":
                obj = loc_fn.get("Solution")
                fn = loc_fn.get(fn_name) if obj is None else getattr(obj(), fn_name)
                args = _parse_args(case["input"])
                got = fn(*args)
                try:
                    exp = ast.literal_eval(case["output"])
                except Exception:
                    exp = str(case.get("output", "")).strip()
                ok = _eq(got, exp)
            else:
                loc = {}
                buf_in = io.StringIO(case["input"] if str(case["input"]).endswith("\n") else str(case["input"]) + "\n")
                buf_out = io.StringIO()
                old_in, old_out = sys.stdin, sys.stdout
                sys.stdin, sys.stdout = buf_in, buf_out
                try:
                    exec(compiled, loc, loc)
                finally:
                    sys.stdin, sys.stdout = old_in, old_out
                ok = buf_out.getvalue().strip() == str(case.get("output") or "").strip()
            if ok:
                n_pass += 1
            else:
                n_fail += 1
        except OSError as e:
            if "network blocked" in str(e):
                return {"ok": False, "kind": "network_blocked", "n_pass": n_pass, "n_fail": n_fail, "n": len(tests)}
            n_fail += 1
        except Exception:
            n_fail += 1
    return {"ok": n_fail == 0 and n_pass == len(tests), "kind": "ok" if n_fail == 0 else "fail", "n_pass": n_pass, "n_fail": n_fail, "n": len(tests)}

print(json.dumps(run(json.loads(sys.stdin.read()))))
'''


def decode_private_tests(blob: str) -> list[dict]:
    if not blob:
        return []
    blob = blob.strip()
    if blob.startswith("["):
        return json.loads(blob)
    import base64
    import pickle
    import zlib

    inner = pickle.loads(zlib.decompress(base64.b64decode(blob)))
    if isinstance(inner, str):
        return json.loads(inner)
    if isinstance(inner, list):
        return inner
    raise TypeError(type(inner))


def extract_code(text: str) -> str | None:
    if not text or not text.strip():
        return None
    rest = text
    fences = []
    while "```" in rest:
        i = rest.find("```")
        rest = rest[i + 3 :]
        nl = rest.find("\n")
        if nl < 0:
            break
        lang = rest[:nl].strip().lower()
        rest = rest[nl + 1 :]
        j = rest.find("```")
        if j < 0:
            body = rest
            rest = ""
        else:
            body = rest[:j]
            rest = rest[j + 3 :]
        fences.append((lang, body.strip()))
    for lang, body in fences:
        if lang in {"python", "py", "python3", ""} and body:
            return body
    if "def " in text or "class Solution" in text:
        return text.strip()
    return None


def run_tests(
    code: str,
    tests: list[dict],
    *,
    starter: str = "",
    fn_name: str = "",
    timeout_s: int = TIMEOUT_S,
) -> dict:
    payload = {
        "code": code,
        "tests": tests,
        "starter": starter,
        "fn_name": fn_name,
        "timeout_s": timeout_s,
    }
    global_timeout = timeout_s * max(1, len(tests)) + 5
    try:
        proc = subprocess.run(
            [sys.executable, "-c", RUNNER],
            input=json.dumps(payload).encode(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=global_timeout,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "kind": "timeout",
            "n_pass": 0,
            "n_fail": 0,
            "n": len(tests),
            "checker_id": CHECKER_ID,
        }
    if proc.returncode != 0:
        err = (proc.stderr or b"").decode("utf-8", "replace")
        kind = "network_blocked" if "network blocked" in err else "error"
        return {
            "ok": False,
            "kind": kind,
            "n_pass": 0,
            "n_fail": 0,
            "n": len(tests),
            "checker_id": CHECKER_ID,
        }
    try:
        out = json.loads(proc.stdout.decode())
    except json.JSONDecodeError:
        return {
            "ok": False,
            "kind": "error",
            "n_pass": 0,
            "n_fail": 0,
            "n": len(tests),
            "checker_id": CHECKER_ID,
        }
    out["checker_id"] = CHECKER_ID
    return out
