"""
Email notification via Resend.
Usage:
    python execution/notifier.py --test
"""

import argparse
import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

import resend
from config import settings as cfg_module

# Email delivery is a side effect, never a step the loop depends on. When Resend
# rejects a send, the failure is recorded here (persisted, so a restart loop can't
# reset it), announced on Slack — the channel that does NOT run through the Resend
# key — and re-announced at most once a day until a send succeeds again.
# 2026-10-04..20: the Resend key was revoked in an incident response and every
# email raised for 16 days. The raise halted the loop (~300 restarts/day), the halt
# alert was itself an email, and the Slack fallback sat *after* the raise.
DEGRADED_PATH = Path("logs/notifier_degraded.json")
SLACK_REMIND_SECONDS = 24 * 3600
DEFAULT_DASHBOARD_URL = "https://trading.cloudmagic.software"


def dashboard_url() -> str:
    """Where to read the live state. Env wins (same name systemd passes), then the
    YAML `notifications.dashboard_url`, then the known public address."""
    env = os.environ.get("DASHBOARD_URL", "").strip()
    if env:
        return env
    try:
        return cfg_module.load().notifications.dashboard_url or DEFAULT_DASHBOARD_URL
    except Exception:
        return DEFAULT_DASHBOARD_URL


def with_dashboard_link(text: str, url: str, is_html: bool = False) -> str:
    """Append the dashboard link once. Every outbound update goes through here so a
    reader of any email or Slack post can get to the live state in one click."""
    if not url or url in text:
        return text
    if is_html:
        footer = (f'<p style="margin-top:1.5em;font-size:0.9em;color:#666">'
                  f'Live dashboard: <a href="{url}">{url}</a></p>')
        if "</body>" in text:
            return text.replace("</body>", footer + "</body>", 1)
        return text + footer
    return f"{text.rstrip()}\n\nDashboard: {url}"


def slack_post(url: str, text: str) -> bool:
    """Post a plain-text message to a Slack incoming webhook. Never raises."""
    if not url:
        return False
    try:
        text = with_dashboard_link(text, dashboard_url())
        payload = json.dumps({"text": text}).encode()
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=10)
        return True
    except Exception as e:
        print(f"[SLACK] send failed: {e}")
        return False


def read_degraded() -> Optional[dict]:
    """The persisted email-failure marker, or None when delivery is healthy."""
    try:
        with open(DEGRADED_PATH) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _write_degraded(marker: Optional[dict]) -> None:
    try:
        if marker is None:
            DEGRADED_PATH.unlink(missing_ok=True)
            return
        DEGRADED_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(DEGRADED_PATH, "w") as f:
            json.dump(marker, f, indent=2)
    except OSError as e:
        print(f"[EMAIL] could not write {DEGRADED_PATH}: {e}")

# Some mail clients mis-decode non-ASCII in our plain-text reports (the corrupted
# P&L lines / degree signs in the daily report). Normalize the usual suspects to
# ASCII so the numbers are always readable — pretty typography is not worth an
# unreadable P&L.
_ASCII_MAP = str.maketrans({
    "—": "--", "–": "-", "°": " deg ",
    "“": '"', "”": '"', "‘": "'", "’": "'",
    "→": "->", "≥": ">=", "≤": "<=", "±": "+/-",
    " ": " ",  # non-breaking space
})


def _ascii_safe(text: str) -> str:
    return str(text).translate(_ASCII_MAP).encode("ascii", "replace").decode("ascii")


def _fmt_temp(temp_c) -> str:
    """Render a temperature that may be None (no sensor on a VM)."""
    return f"{temp_c:.1f} C" if temp_c is not None else "n/a (no sensor)"


class Notifier:
    def __init__(self, settings=None):
        self.cfg = settings or cfg_module.load()
        resend.api_key = self.cfg.notifications.resend_key
        self.to = self.cfg.notifications.alert_email
        self.dashboard_url = (os.environ.get("DASHBOARD_URL", "").strip()
                              or getattr(self.cfg.notifications, "dashboard_url", "")
                              or DEFAULT_DASHBOARD_URL)

    def send(self, subject: str, body: str, is_html: bool = False,
             raise_on_error: bool = False) -> bool:
        """Deliver one email. Returns False instead of raising when Resend rejects it
        (see DEGRADED_PATH) — only `--verify-only` wants the exception."""
        params: resend.Emails.SendParams = {
            "from": "Trading System <noreply@cloudmagicgroup.com>",
            "to": [self.to],
            "subject": _ascii_safe(subject),
        }
        body = with_dashboard_link(body, self.dashboard_url, is_html)
        if is_html:
            params["html"] = body
        else:
            params["text"] = _ascii_safe(body)
        try:
            resend.Emails.send(params)
        except Exception as e:
            self._record_failure(e, subject)
            if raise_on_error:
                raise
            return False
        self._record_success()
        return True

    def _record_failure(self, err: Exception, subject: str) -> None:
        now = time.time()
        marker = read_degraded() or {"since": _iso(now), "failures": 0, "last_slack": None}
        marker["failures"] += 1
        marker["last_error"] = str(err)[:200]
        marker["last_subject"] = subject[:80]
        marker["last_failure"] = _iso(now)
        print(f"[EMAIL] send failed ({marker['failures']} since {marker['since']}): {err} "
              f"— subject {subject!r}")
        last_slack = marker.get("last_slack")
        if not last_slack or now - last_slack >= SLACK_REMIND_SECONDS:
            if self.send_slack(
                f":warning: *Trading email delivery is failing* since {marker['since']} "
                f"({marker['failures']} failure(s)) — {marker['last_error']}\n"
                f"Status, daily and halt emails are NOT arriving. Check RESEND_API_KEY in "
                f".env on VM 117 (and the WSL copy), then `systemctl restart trading`."
            ):
                marker["last_slack"] = now
        _write_degraded(marker)

    def _record_success(self) -> None:
        marker = read_degraded()
        if marker is None:
            return
        self.send_slack(f":white_check_mark: *Trading email delivery restored* — "
                        f"{marker.get('failures', '?')} failure(s) since {marker.get('since')}.")
        print(f"[EMAIL] delivery restored after {marker.get('failures')} failure(s)")
        _write_degraded(None)

    def send_slack(self, text: str) -> bool:
        """Post a plain-text message to the configured Slack webhook. No-ops if unset."""
        return slack_post(self.cfg.notifications.slack_webhook_url, text)

    def critical_alert(self, message: str) -> bool:
        """Email + Slack. Slack goes FIRST: if the email key is what broke, the Slack
        message is the only alert that will arrive. Returns True if either channel
        accepted the alert."""
        now = datetime.utcnow().isoformat()
        # Stamp the critical-alert log FIRST — live_readiness gates "N days with
        # zero critical alerts" off this file, so it must record even if delivery fails.
        try:
            log = Path("logs/critical_alerts.log")
            log.parent.mkdir(parents=True, exist_ok=True)
            first_line = message.strip().splitlines()[0][:200] if message.strip() else ""
            with open(log, "a") as f:
                f.write(f"{now}Z\t{first_line}\n")
        except Exception:
            pass
        body = f"CRITICAL ALERT — {now}Z\n\n{message}"
        slack_ok = self.send_slack(f":rotating_light: *CRITICAL* — {message[:500]}")
        email_ok = self.send(subject="[CRITICAL] Trading System Alert", body=body)
        return slack_ok or email_ok

    def status_report(
        self,
        mode: str,
        positions: list,
        equity: float,
        unrealized_pnl: float,
        cpu_pct: float,
        temp_c: float,
        api_failures: int,
        whale_hits_today: list,
        policy_feed_ok: bool,
        wheel_tickers_scanned: int,
        wheel_contracts_found: int,
        regime: str = "NEUTRAL",
        spy_change_pct: float = 0.0,
    ):
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M ET")
        lines = [
            f"System Status — {now_str}",
            "=" * 50,
            f"Mode:           {mode.upper()}",
            f"Regime:         {regime}  (SPY {spy_change_pct:+.2f}% intraday)",
            f"Account Equity: ${equity:,.2f}",
            f"Unrealized P&L: ${unrealized_pnl:+,.2f}",
            f"Open Positions: {len(positions)}",
            f"API Failures:   {api_failures}",
            "",
            "--- Positions ---",
        ]
        if positions:
            for p in positions:
                lines.append(
                    f"  {p['symbol']:8s}  qty={p['qty']:>6}  "
                    f"unrealized={float(p.get('unrealized_pl', 0)):+,.2f}"
                )
        else:
            lines.append("  (no open positions)")

        lines += [
            "",
            "--- Wheel Strategy ---",
            f"  Tickers scanned:   {wheel_tickers_scanned}",
            f"  Contracts found:   {wheel_contracts_found}",
        ]
        if wheel_contracts_found == 0:
            lines.append("  NOTE: No contracts matched — strikes may be above current prices")

        lines += [
            "",
            "--- Signal Sources ---",
            f"  Policy feed:  {'OK' if policy_feed_ok else 'DEGRADED (403 on whitehouse.gov)'}",
            f"  Whale watch:  {len(whale_hits_today)} signal(s) today",
        ]
        if whale_hits_today:
            for h in whale_hits_today:
                lines.append(f"    {h}")

        lines += [
            "",
            "--- Hardware ---",
            f"  CPU:  {cpu_pct:.1f}%",
            f"  Temp: {_fmt_temp(temp_c)}",
        ]

        self.send(
            subject=f"[STATUS] Trading System — {now_str}",
            body="\n".join(lines),
        )

    def daily_report(
        self,
        realized_pnl: float,
        unrealized_pnl: float,
        positions: list,
        cpu_avg: float,
        temp_avg: float,
        whale_hits: list,
    ):
        lines = [
            f"Daily Trading Report — {datetime.now().strftime('%Y-%m-%d')}",
            "=" * 50,
            f"Realized P&L:   ${realized_pnl:+,.2f}",
            f"Unrealized P&L: ${unrealized_pnl:+,.2f}",
            f"Total P&L:      ${realized_pnl + unrealized_pnl:+,.2f}",
            "",
            "--- Portfolio Health ---",
        ]
        if positions:
            for p in positions:
                lines.append(f"  {p['symbol']:8s}  qty={p['qty']}  unrealized={p.get('unrealized_pl', '?')}")
        else:
            lines.append("  (no open positions)")

        lines += [
            "",
            "--- Hardware ---",
            f"  Avg CPU:  {cpu_avg:.1f}%",
            f"  Avg Temp: {_fmt_temp(temp_avg)}",
            "",
            "--- Smart Money (Whale Watch) ---",
        ]
        if whale_hits:
            for h in whale_hits:
                lines.append(f"  {h}")
        else:
            lines.append("  (no whale signals today)")

        self.send(
            subject=f"Trading Report {datetime.now().strftime('%Y-%m-%d')}",
            body="\n".join(lines),
        )


    def strategy_digest(self, period: str, content: str):
        label = "Weekly" if period == "weekly" else "Monthly"
        date_str = datetime.now().strftime("%Y-%m-%d")
        self.send(
            subject=f"[{label.upper()} REVIEW] Strategy Lessons — {date_str}",
            body=f"{label} Strategy Review — {date_str}\n{'=' * 55}\n\n{content}",
        )

    def daily_wrap_up(self, date_str: str, body: str):
        """Send the full end-of-day journal synthesis (markdown)."""
        self.send(
            subject=f"[JOURNAL] Daily Wrap-Up — {date_str}",
            body=body,
        )


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(timespec="seconds")


def test_send(settings=None):
    try:
        n = Notifier(settings)
        n.send(
            subject="[TEST] Trading System — Connectivity Check",
            body="Email delivery confirmed.",
            raise_on_error=True,
        )
        print("[OK] Resend email — test message sent")
        return True
    except Exception as e:
        print(f"[FAIL] Resend email — {e}")
        return False


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--test", action="store_true")
    args = parser.parse_args()
    if args.test:
        ok = test_send()
        sys.exit(0 if ok else 1)
