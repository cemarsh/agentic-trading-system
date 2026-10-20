"""
Credential health — are the keys in .env still alive?

2026-10-04: every Resend API key on the account was revoked during an incident
response (a leaked key had been used to send spam from board@cloudmagicgroup.com),
and the Anthropic key died the next day. The VM's .env kept the dead values for
16 days. Nothing noticed: the only alert channel *was* the revoked key, the loop
kept trading, and the daily journal/status/halt emails all failed into the
systemd journal, ~1,200 times a day.

A key that is rotated somewhere else is a routine event, not an outage. This
module makes it visible: each probe is a cheap authenticated call that
classifies the key as `ok`, `invalid` (a human must rotate it), `unset`, or
`unknown` (network/5xx — don't alarm). The loop probes at startup and every
`RECHECK_SECONDS`, keeps the result in `state["credential_health"]` for the
dashboard, and posts to Slack on an ok→invalid transition (Slack is the
channel that does NOT depend on the Resend key).

    python execution/credential_health.py      # probe everything in .env, exit 1 on any invalid
"""
import json
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

OK, INVALID, UNSET, UNKNOWN = "ok", "invalid", "unset", "unknown"
RECHECK_SECONDS = 6 * 3600
_TIMEOUT = 10
# Resend sits behind Cloudflare, which bans urllib's default User-Agent outright
# (error 1010, an HTML page). Only the provider's own JSON verdict may mark a key
# invalid; a WAF block, a 5xx or a network error is `unknown` — never an alarm.
_UA = "cmtg-trading-credential-health/1.0"


def _get(url: str, headers: dict) -> tuple:
    """(status_code, body_text). Network failures come back as (None, message)."""
    req = urllib.request.Request(url, headers={"User-Agent": _UA, **headers})
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            return resp.status, resp.read(2000).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        try:
            body = e.read(2000).decode("utf-8", "replace")
        except Exception:
            body = ""
        return e.code, body
    except Exception as e:  # DNS, timeout, TLS
        return None, str(e)


def probe_resend(key: str) -> tuple:
    """GET /api-keys. A sending-only key is *expected* to be refused with
    `restricted_api_key` — that still proves the key is live. Shapes seen 2026-10-20:
      200                                   -> full-access key
      401 {"name":"restricted_api_key"}     -> sending-only key, alive
      400 {"name":"validation_error","message":"API key is invalid"} -> dead
      401 {"name":"missing_api_key"}        -> no key sent
    """
    if not key:
        return UNSET, "RESEND_API_KEY not set"
    status, body = _get("https://api.resend.com/api-keys", {"Authorization": f"Bearer {key}"})
    if status is None:
        return UNKNOWN, f"network: {body[:120]}"
    if status == 200:
        return OK, "full-access key"
    verdict = _json(body)
    if verdict.get("name") == "restricted_api_key":
        return OK, "sending-only key"
    if status in (400, 401, 403) and verdict.get("name") in ("validation_error", "missing_api_key"):
        return INVALID, _message(body) or f"HTTP {status}"
    return UNKNOWN, f"HTTP {status}: {_message(body) or body[:80]}"


def probe_anthropic(key: str) -> tuple:
    """GET /v1/models — free, authenticated. 401 = dead key."""
    if not key:
        return UNSET, "ANTHROPIC_API_KEY not set"
    status, body = _get("https://api.anthropic.com/v1/models?limit=1",
                        {"x-api-key": key, "anthropic-version": "2023-06-01"})
    if status is None:
        return UNKNOWN, f"network: {body[:120]}"
    if status == 200:
        return OK, "key accepted"
    verdict = _json(body).get("error")
    if status in (401, 403) and isinstance(verdict, dict) \
            and verdict.get("type") in ("authentication_error", "permission_error"):
        return INVALID, _message(body) or f"HTTP {status}"
    return UNKNOWN, f"HTTP {status}: {_message(body) or body[:80]}"


def _json(body: str) -> dict:
    try:
        d = json.loads(body)
    except Exception:
        return {}
    return d if isinstance(d, dict) else {}


def _message(body: str) -> str:
    d = _json(body)
    if not d:
        return ""
    if isinstance(d.get("error"), dict):
        return str(d["error"].get("message", ""))[:120]
    return str(d.get("message", ""))[:120]


def probe_all(cfg, now: Optional[datetime] = None) -> dict:
    """{name: {"status", "detail", "checked_at"}} for every credential the loop uses
    besides Alpaca (the loop's own API calls already prove that one every cycle)."""
    now = now or datetime.now(timezone.utc)
    checks = {
        "resend": probe_resend(getattr(cfg.notifications, "resend_key", "") or ""),
        "anthropic": probe_anthropic(getattr(getattr(cfg, "anthropic", None), "api_key", "") or ""),
    }
    return {name: {"status": status, "detail": detail, "checked_at": now.isoformat()}
            for name, (status, detail) in checks.items()}


def transitions(previous: Optional[dict], current: dict) -> list:
    """[(name, old_status, new_status)] where the status changed between two probes.
    A first probe (no previous) reports every non-ok key so startup after a rotation
    still shouts."""
    out = []
    for name, cur in current.items():
        old = (previous or {}).get(name, {}).get("status")
        if old != cur["status"] and (old is not None or cur["status"] in (INVALID,)):
            out.append((name, old, cur["status"]))
    return out


def describe(health: dict) -> str:
    return " · ".join(f"{n} {h['status']}" + (f" ({h['detail']})" if h["status"] != OK else "")
                      for n, h in health.items())


if __name__ == "__main__":
    from config import settings as cfg_module
    health = probe_all(cfg_module.load())
    for name, h in health.items():
        tag = "OK" if h["status"] == OK else "SKIP" if h["status"] == UNSET else "FAIL"
        print(f"[{tag}] {name}: {h['status']} — {h['detail']}")
    sys.exit(1 if any(h["status"] == INVALID for h in health.values()) else 0)
