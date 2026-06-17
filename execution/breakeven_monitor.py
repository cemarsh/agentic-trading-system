#!/usr/bin/env python3
"""
Breakeven exit monitor — cleanup for the FJET ladder-runaway (2026-06-16).

Trims FJET back to the intended 309-share starter ONLY at/above cost basis (never
realizes a loss). The actual sell is a resting GTC limit @ breakeven on Alpaca;
this monitor (run hourly by systemd on the workstation) just:
  - re-places that GTC order if it ever goes missing, and
  - alerts once (email + Slack) when the trim completes.

Self-gates on market hours and is idempotent — safe to run anytime.
"""
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import settings as cfg_module
from execution.alpaca_client import AlpacaClient

TICKER = "FJET"
TARGET_QTY = 309
DONE_MARKER = Path(f"logs/breakeven_done_{TICKER}")


def _alert(cfg, msg: str) -> None:
    try:
        from execution.notifier import Notifier
        n = Notifier(settings=cfg)
        n.send(subject=f"[BREAKEVEN] {TICKER} trim complete", body=msg)
        n.send_slack(f":white_check_mark: {msg}")
    except Exception as e:
        print(f"[BREAKEVEN] alert failed: {e}")


def main() -> None:
    cfg = cfg_module.load()
    c = AlpacaClient(settings=cfg)
    try:
        if not c.get_clock().get("is_open"):
            print("[BREAKEVEN] market closed — skip")
            return
    except Exception as e:
        print(f"[BREAKEVEN] clock check failed ({e}) — skip")
        return

    pos = {p["symbol"]: p for p in c.get_positions()}.get(TICKER)
    qty = int(float(pos["qty"])) if pos else 0

    # --- Done? trim completed (excess sold at/above breakeven) ---
    if qty <= TARGET_QTY:
        if not DONE_MARKER.exists():
            _alert(cfg, f"{TICKER} breakeven trim COMPLETE — now {qty} shares "
                        f"(target {TARGET_QTY}). The excess sold at/above your cost basis; "
                        f"no loss realized.")
            DONE_MARKER.parent.mkdir(parents=True, exist_ok=True)
            DONE_MARKER.write_text("done")
            print(f"[BREAKEVEN] {TICKER} trim complete at {qty} — alerted")
        else:
            print(f"[BREAKEVEN] {TICKER} already trimmed ({qty}) — nothing to do")
        return

    # --- Still excess — ensure the resting GTC breakeven sell exists ---
    avg = float(pos["avg_entry_price"])
    breakeven = math.ceil(avg * 100) / 100  # >= cost basis ⇒ no realized loss
    excess = qty - TARGET_QTY
    selling = [o for o in c.get_open_orders() if o["symbol"] == TICKER and o["side"] == "sell"]
    if selling:
        last = float(pos.get("current_price", 0) or 0)
        gap = (breakeven - last) / breakeven * 100 if last else 0.0
        print(f"[BREAKEVEN] {TICKER} {qty} sh, price ${last:.2f} vs breakeven ${breakeven:.2f} "
              f"(needs +{gap:.1f}%); GTC sell resting "
              f"({selling[0]['qty']} @ {selling[0].get('limit_price')})")
        return

    body = {"symbol": TICKER, "qty": excess, "side": "sell", "type": "limit",
            "time_in_force": "gtc", "limit_price": str(breakeven)}
    o = c._post("/v2/orders", body)
    print(f"[BREAKEVEN] re-placed GTC breakeven sell: {excess} {TICKER} @ ${breakeven} "
          f"id={o.get('id', '')[:8]}")


if __name__ == "__main__":
    main()
