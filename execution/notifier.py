"""
Email notification via Resend.
Usage:
    python execution/notifier.py --test
"""

import argparse
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

import resend
from config import settings as cfg_module


class Notifier:
    def __init__(self, settings=None):
        self.cfg = settings or cfg_module.load()
        resend.api_key = self.cfg.notifications.resend_key
        self.to = self.cfg.notifications.alert_email

    def send(self, subject: str, body: str, is_html: bool = False):
        params = {
            "from": "trading-system@resend.dev",
            "to": [self.to],
            "subject": subject,
        }
        if is_html:
            params["html"] = body
        else:
            params["text"] = body
        resend.Emails.send(params)

    def critical_alert(self, message: str):
        self.send(
            subject="[CRITICAL] Trading System Alert",
            body=f"CRITICAL ALERT — {datetime.utcnow().isoformat()}Z\n\n{message}",
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
            f"  Avg Temp: {temp_avg:.1f}°C",
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


def test_send(settings=None):
    try:
        n = Notifier(settings)
        n.send(
            subject="[TEST] Trading System — Connectivity Check",
            body="Email delivery confirmed.",
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
