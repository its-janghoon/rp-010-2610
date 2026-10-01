"""Status classification. No model bodies."""

from __future__ import annotations


def hit_cap(finish_reason: str | None, completion_tokens: int | None, cap: int | None) -> bool:
    fr = (finish_reason or "").lower()
    if fr in {"length", "max_tokens"}:
        return True
    if completion_tokens is None or cap is None:
        return False
    return int(completion_tokens) >= int(cap)


def classify_outcome(
    *,
    sandbox_status: str | None,
    parse_ok: bool,
    finish_reason: str | None,
    completion_tokens: int | None,
    cap: int,
) -> tuple[str, int | None]:
    """Return (status, correct_override).

    cap_hit beats sandbox_error: a truncated generation is not infra.
    cap_hit and parse_failed both force correct=0. cap_hit is the recorded status
    when both apply so the diagnostic split is recoverable.
    """
    capped = hit_cap(finish_reason, completion_tokens, cap)
    if capped:
        return "cap_hit", 0
    if sandbox_status == "sandbox_error":
        return "sandbox_error", None
    if not parse_ok:
        return "parse_failed", 0
    return "ok", None
