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
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import settings as cfg_module
from execution.alpaca_client import AlpacaClient, verify as verify_alpaca
from execution.hardware_monitor import HardwareMonitor
from execution.whale_watch import WhaleWatcher
from execution.wheel_strategy import WheelStrategy
from execution.protective_logic import ProtectiveLogic
from execution.policy_monitor import PolicyMonitor
from execution.regime_detector import RegimeDetector
from execution.inverse_etf_hedge import InverseETFHedge
from execution.strategy_advisor import run_weekly_scan, generate_digest

STATE_PATH = Path("logs/agent_state.json")

INITIAL_STATE = {
    "verification_trades_done": 0,
    "api_failures": 0,
    "halted": False,
    "last_daily_report": None,
    "last_status_report": None,
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

    # Optional services — degrade gracefully when not configured
    db = None
    if cfg.database.url:
        try:
            from execution.db_logger import DBLogger
            db = DBLogger(settings=cfg)
            print("[OK] PostgreSQL — connected")
        except Exception as e:
            print(f"[WARN] PostgreSQL unavailable — logging disabled ({e})")

    notifier = None
    if cfg.notifications.resend_key:
        try:
            from execution.notifier import Notifier
            notifier = Notifier(settings=cfg)
            print("[OK] Resend — email enabled")
        except Exception as e:
            print(f"[WARN] Resend unavailable — email disabled ({e})")
    else:
        print("[INFO] No RESEND_API_KEY — email alerts disabled")

    hw = HardwareMonitor(settings=cfg, notifier=notifier)
    whale = WhaleWatcher(settings=cfg, alpaca_client=alpaca)
    wheel = WheelStrategy(settings=cfg, alpaca_client=alpaca, db_logger=db)
    protection = ProtectiveLogic(settings=cfg, alpaca_client=alpaca, db_logger=db)
    policy = PolicyMonitor(settings=cfg, notifier=notifier, db=db)
    regime = RegimeDetector(settings=cfg, alpaca_client=alpaca)
    hedge = InverseETFHedge(settings=cfg, alpaca_client=alpaca, db_logger=db)

    print(f"[START] Trading loop active — {mode.upper()} mode — {datetime.now().isoformat()}")

    whale_hits_session: list = []
    policy_feed_ok: bool = True
    wheel_tickers_scanned: int = 0
    wheel_contracts_found: int = 0
    current_regime: str = "NEUTRAL"

    while True:
        try:
            # --- Hardware Check ---
            metrics = hw.sample()
            if hw.check_thresholds(metrics):
                print("[HW] Threshold breach — pausing non-essential tasks for 60s")
                time.sleep(60)
                continue

            # --- Market Hours Gate ---
            clock = alpaca.get_clock()
            if not clock.get("is_open"):
                next_open_str = clock.get("next_open", "")
                try:
                    next_open = datetime.fromisoformat(next_open_str.replace("Z", "+00:00"))
                    sleep_secs = max(60, (next_open - datetime.now(timezone.utc)).total_seconds())
                    wake_at = next_open.strftime("%Y-%m-%d %H:%M ET")
                except Exception:
                    sleep_secs = 3600
                    wake_at = "unknown"
                print(f"[MARKET] Closed — sleeping {sleep_secs/3600:.1f}h until {wake_at}")
                time.sleep(sleep_secs)
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

            # --- Regime Detection ---
            current_regime = regime.detect()

            # --- Whale Watch ---
            try:
                whale_hits = whale.get_actionable_trades()
            except Exception as we:
                print(f"[WHALE] Fetch error: {we}")
                whale_hits = []
            if whale_hits:
                whale_hits_session = whale_hits  # keep latest batch for status reports
            for trade in whale_hits:
                # Skip new equity entries in extreme bear — preserve capital
                if current_regime == "EXTREME_BEAR":
                    print(f"[WHALE] Skipping {trade.ticker} — EXTREME_BEAR regime")
                    continue
                try:
                    account = alpaca.get_account()
                    equity = float(account.get("equity", 0))
                    alloc_pct = cfg.whale_watch.max_portfolio_pct_per_trade * regime.allocation_multiplier()
                    max_alloc = equity * alloc_pct / 100
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
                    print(f"[WHALE] {side.upper()} {qty}x {trade.ticker} @ ~${price:.2f}  ({trade.politician})")
                    alpaca.submit_order(trade.ticker, qty, side)
                    if db:
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
                except Exception as oe:
                    print(f"[WHALE] Order failed {trade.ticker}: {oe}")

            # --- Policy Intelligence Monitor ---
            try:
                policy_signals = policy.scan()
                policy_feed_ok = True
                if policy_signals:
                    print(f"[POLICY] {len(policy_signals)} new signal(s) detected and logged")
            except Exception as pe:
                policy_feed_ok = False
                print(f"[POLICY] scan error: {pe}")

            # --- Wheel Strategy ---
            wheel_tickers_scanned = len(cfg.wheel.tickers)
            if current_regime == "EXTREME_BEAR":
                print("[WHEEL] EXTREME_BEAR regime — skipping new CSP entries")
                wheel_contracts_found = 0
            else:
                # In BEAR regime, override target delta to be more conservative
                delta_override = regime.target_delta_override()
                if delta_override:
                    cfg.wheel.target_delta = delta_override
                wheel_contracts_found = wheel.run_cycle()

            # --- Inverse ETF Hedge ---
            hedge.run(regime=current_regime, positions=positions, equity=float(alpaca.get_account().get("equity", 0)))

            # --- Status Check (every N hours during market window) ---
            now = datetime.now(timezone.utc)
            # Market window: 13:30–20:30 UTC (9:30 AM–4:30 PM ET)
            in_market_window = (now.hour, now.minute) >= (13, 30) and now.hour < 20
            interval_hours = cfg.notifications.status_check_interval_hours
            last_sr = state.get("last_status_report")
            status_due = False
            if last_sr:
                elapsed = now - datetime.fromisoformat(last_sr)
                status_due = elapsed >= timedelta(hours=interval_hours)
            else:
                status_due = in_market_window  # first run: fire as soon as market opens

            if status_due and in_market_window and notifier:
                account = alpaca.get_account()
                equity = float(account.get("equity", 0))
                unrealized_pnl = sum(float(p.get("unrealized_pl", 0)) for p in positions)
                notifier.status_report(
                    mode=mode,
                    positions=positions,
                    equity=equity,
                    unrealized_pnl=unrealized_pnl,
                    cpu_pct=metrics["cpu_pct"],
                    temp_c=metrics["temp_c"],
                    api_failures=state.get("api_failures", 0),
                    whale_hits_today=[
                        f"{t.politician} → {t.ticker}" for t in whale_hits_session
                    ],
                    policy_feed_ok=policy_feed_ok,
                    wheel_tickers_scanned=wheel_tickers_scanned,
                    wheel_contracts_found=wheel_contracts_found,
                    regime=current_regime,
                    spy_change_pct=regime.spy_change_pct,
                )
                state["last_status_report"] = now.isoformat()
                print(f"[STATUS] Status report sent at {now.strftime('%H:%M UTC')}")
                save_state(state)

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

            # --- Weekly Scan (Monday pre-market, once per week) ---
            now_for_weekly = datetime.now(timezone.utc)
            is_monday_premarket = (
                now_for_weekly.weekday() == 0  # Monday
                and now_for_weekly.hour < 14   # before 9:30 AM ET (14:00 UTC)
            )
            last_weekly = state.get("last_weekly_scan")
            weekly_due = (
                is_monday_premarket
                and last_weekly != now_for_weekly.date().isoformat()
            )
            if weekly_due:
                try:
                    run_weekly_scan(alpaca, current_regime, settings=cfg, db=db, notifier=notifier)
                    state["last_weekly_scan"] = now_for_weekly.date().isoformat()
                    save_state(state)
                    if db and notifier:
                        lessons = db.get_lessons(days=7)
                        digest_body = generate_digest("weekly", lessons, settings=cfg)
                        notifier.strategy_digest("weekly", digest_body)
                        print("[ADVISOR] Weekly digest sent")
                except Exception as ae:
                    print(f"[ADVISOR] Weekly scan error: {ae}")

            # --- Monthly Digest (1st of month, once per month) ---
            now_for_monthly = datetime.now(timezone.utc)
            is_first_of_month = now_for_monthly.day == 1 and now_for_monthly.hour < 14
            last_monthly = state.get("last_monthly_digest")
            monthly_due = (
                is_first_of_month
                and last_monthly != now_for_monthly.strftime("%Y-%m")
            )
            if monthly_due and db and notifier:
                try:
                    lessons = db.get_lessons(days=30)
                    digest_body = generate_digest("monthly", lessons, settings=cfg)
                    notifier.strategy_digest("monthly", digest_body)
                    state["last_monthly_digest"] = now_for_monthly.strftime("%Y-%m")
                    save_state(state)
                    print("[ADVISOR] Monthly digest sent")
                except Exception as me:
                    print(f"[ADVISOR] Monthly digest error: {me}")

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
                if notifier:
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
