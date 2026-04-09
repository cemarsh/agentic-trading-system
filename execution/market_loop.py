"""
Main market loop — orchestrates all trading tiers.
Usage:
    python execution/market_loop.py --mode paper
    python execution/market_loop.py --mode live
    python execution/market_loop.py --verify-only
"""

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import settings as cfg_module
from execution.alpaca_client import AlpacaClient, verify as verify_alpaca
from execution.db_logger import DBLogger, ping as ping_db, init_schema
from execution.notifier import Notifier, test_send as test_email
from execution.hardware_monitor import HardwareMonitor
from execution.whale_watch import WhaleWatcher
from execution.wheel_strategy import WheelStrategy
from execution.protective_logic import ProtectiveLogic

STATE_PATH = Path("logs/agent_state.json")

INITIAL_STATE = {
    "verification_trades_done": 0,
    "api_failures": 0,
    "halted": False,
    "last_daily_report": None,
}


def load_state() -> dict:
    if STATE_PATH.exists():
        with open(STATE_PATH) as f:
            return json.load(f)
    return INITIAL_STATE.copy()


def save_state(state: dict):
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_PATH, "w") as f:
        json.dump(state, f, indent=2, default=str)


def verify_all(cfg) -> bool:
    ok = True
    ok &= verify_alpaca()
    ok &= ping_db()
    ok &= test_email()
    hw = HardwareMonitor(settings=cfg)
    metrics = hw.sample()
    print(f"[OK] Hardware — CPU: {metrics['cpu_pct']:.1f}%, Temp: {metrics['temp_c']:.1f}°C")
    mode = "PAPER" if cfg.guardrails.paper_mode else "LIVE"
    if ok:
        print(f"\n[READY] All systems go. Mode: {mode}")
    else:
        print("\n[FAIL] One or more connectivity checks failed. Fix before going live.")
    return ok


def run(mode: str):
    cfg = cfg_module.load()
    state = load_state()

    if state.get("halted"):
        print("[HALT] System is halted due to prior failure. Check logs and reset agent_state.json.")
        sys.exit(1)

    if mode == "live" and cfg.guardrails.paper_mode:
        print("[WARN] strategy_params.yaml has paper_mode: true. Set to false to enable live trading.")
        sys.exit(1)

    alpaca = AlpacaClient(settings=cfg)
    db = DBLogger(settings=cfg)
    notifier = Notifier(settings=cfg)
    hw = HardwareMonitor(settings=cfg, notifier=notifier)
    whale = WhaleWatcher(settings=cfg, alpaca_client=alpaca)
    wheel = WheelStrategy(settings=cfg, alpaca_client=alpaca, db_logger=db)
    protection = ProtectiveLogic(settings=cfg, alpaca_client=alpaca, db_logger=db)

    print(f"[START] Trading loop active — {mode.upper()} mode — {datetime.now().isoformat()}")

    while True:
        try:
            # --- Hardware Check ---
            metrics = hw.sample()
            if hw.check_thresholds(metrics):
                print("[HW] Threshold breach — pausing non-essential tasks for 60s")
                time.sleep(60)
                continue

            # --- Sync Positions ---
            positions = alpaca.get_positions()
            current_prices = {
                p["symbol"]: float(p.get("current_price", 0)) for p in positions
            }
            protection.sync_positions(positions)

            # --- Protective Logic ---
            stop_tickers = protection.check_stops(current_prices)
            for ticker in stop_tickers:
                protection.execute_stop(ticker)

            for ticker, price in current_prices.items():
                if protection.check_ladder(ticker, price):
                    protection.execute_ladder(ticker)

            # --- Whale Watch ---
            whale_hits = whale.get_actionable_trades()
            for trade in whale_hits:
                account = alpaca.get_account()
                equity = float(account.get("equity", 0))
                max_alloc = equity * cfg.whale_watch.max_portfolio_pct_per_trade / 100
                bars = alpaca.get_bars(trade.ticker, "1Min", 1)
                if not bars:
                    continue
                price = bars[-1]["c"]
                qty = int(max_alloc // price)
                if qty < 1:
                    continue

                # Manual confirm check
                order_value = qty * price
                vt_done = state.get("verification_trades_done", 0)
                needs_confirm = (
                    order_value > cfg.guardrails.manual_confirm_threshold
                    and vt_done < cfg.guardrails.verification_trades
                )
                if needs_confirm:
                    print(
                        f"[CONFIRM REQUIRED] {trade.ticker} {qty} shares @ ${price:.2f} "
                        f"(${order_value:,.0f}) — type CONFIRM to proceed"
                    )
                    user_input = input("> ").strip().upper()
                    if user_input != "CONFIRM":
                        print("[SKIP] Order skipped by operator")
                        continue
                    state["verification_trades_done"] = vt_done + 1
                    save_state(state)

                side = "buy" if trade.trade_type == "purchase" else "sell"
                alpaca.submit_order(trade.ticker, qty, side)
                db.log_decision(
                    ticker=trade.ticker,
                    action=side.upper(),
                    tier="whale_watch",
                    confidence=trade.confidence,
                    reasoning=(
                        f"{trade.politician} {trade.trade_type} ${trade.trade_value:,.0f} "
                        f"ROC={trade.roc_pct:.2f}%"
                    ),
                    status="submitted",
                )

            # --- Wheel Strategy ---
            wheel.run_cycle()

            # --- Daily Report ---
            now = datetime.now(timezone.utc)
            report_due = (
                now.hour == 21  # 4:15 PM EST = 21:15 UTC
                and now.minute >= 15
                and state.get("last_daily_report") != now.date().isoformat()
            )
            if report_due:
                avg = hw.averages()
                account = alpaca.get_account()
                notifier.daily_report(
                    realized_pnl=float(account.get("last_equity", 0)) - float(account.get("last_equity", 0)),
                    unrealized_pnl=sum(float(p.get("unrealized_pl", 0)) for p in positions),
                    positions=positions,
                    cpu_avg=avg["cpu_avg"],
                    temp_avg=avg["temp_avg"],
                    whale_hits=[f"{t.politician} → {t.ticker}" for t in whale_hits],
                )
                state["last_daily_report"] = now.date().isoformat()
                save_state(state)

            state["api_failures"] = 0
            save_state(state)
            time.sleep(60)

        except KeyboardInterrupt:
            print("\n[STOP] Loop interrupted by operator")
            save_state(state)
            break

        except Exception as e:
            state["api_failures"] = state.get("api_failures", 0) + 1
            print(f"[ERROR] {e} (failure #{state['api_failures']})")

            if state["api_failures"] >= cfg.guardrails.api_retry_limit:
                state["halted"] = True
                save_state(state)
                notifier.critical_alert(
                    f"Trading system HALTED after {cfg.guardrails.api_retry_limit} "
                    f"consecutive failures.\n\nLast error: {e}"
                )
                print("[HALT] Critical failure threshold reached. System halted.")
                sys.exit(1)

            save_state(state)
            time.sleep(10)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Agentic Trading System")
    parser.add_argument(
        "--mode",
        choices=["paper", "live"],
        default="paper",
        help="Trading mode (default: paper)",
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Run connectivity checks only, do not start loop",
    )
    args = parser.parse_args()

    cfg = cfg_module.load()

    if args.verify_only:
        ok = verify_all(cfg)
        sys.exit(0 if ok else 1)

    run(args.mode)
