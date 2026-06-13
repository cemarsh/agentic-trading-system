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

try:
    from zoneinfo import ZoneInfo
    MARKET_TZ = ZoneInfo("America/New_York")
except ImportError:
    MARKET_TZ = timezone.utc

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
from execution.daily_journal import log_insight, wrap_up as journal_wrap_up
from execution.weekly_journal import weekly_wrapup
from execution.position_manager import PositionManager
from execution.morning_briefing import MorningBriefing

STATE_PATH = Path("logs/agent_state.json")
HALT_ALERT_PATH = Path("logs/halt_pending_alert.json")
# Deadman heartbeat — written at the top of every loop iteration. A systemd timer
# (heartbeat_check.py) alerts if this goes stale during market hours, catching
# hangs/crashes/silent stops that a halt-flag check alone would miss.
HEARTBEAT_PATH = Path("logs/heartbeat")
# DNS/connection blips tolerated for ~10 min (20 × 30s) before halting
NETWORK_FAILURE_HALT_THRESHOLD = 20

INITIAL_STATE = {
    "verification_trades_done": 0,
    "api_failures": 0,
    "halted": False,
    "last_daily_report": None,
    "last_status_report": None,
}


def _is_network_error(exc: Exception) -> bool:
    """True for transient DNS/connectivity errors — distinct from real API failures."""
    msg = str(exc).lower()
    return (
        "name resolution" in msg
        or "network is unreachable" in msg
        or "connection refused" in msg
        or "connection reset" in msg
        or "max retries exceeded" in msg
        or "errno -3" in msg
        or "failed to establish a new connection" in msg
    )


def _is_order_rejection(exc: Exception) -> bool:
    """True for 4xx order rejections that are business-logic conditions, not API failures.
    Insufficient buying power, margin violations, etc. should never count toward the halt
    threshold — the account being full is expected behaviour, not an API malfunction."""
    import requests as _req
    if not isinstance(exc, _req.HTTPError):
        return False
    resp = getattr(exc, "response", None)
    if resp is None:
        return False
    if resp.status_code < 400 or resp.status_code >= 500:
        return False
    try:
        code = resp.json().get("code", 0)
    except Exception:
        code = 0
    # 40310000 = insufficient buying power / margin; treat all 4xx order errors the same
    return resp.status_code in (403, 422) or code == 40310000


def _is_auth_error(exc: Exception) -> bool:
    """True for a credentials/permissions failure (401, or a 403 that isn't an order
    rejection). These never self-heal — a human must fix the key/permissions — so a
    halt caused by one is NOT eligible for auto-recovery on restart."""
    import requests as _req
    if not isinstance(exc, _req.HTTPError):
        return False
    resp = getattr(exc, "response", None)
    if resp is None:
        return False
    if resp.status_code == 401:
        return True
    if resp.status_code == 403 and not _is_order_rejection(exc):
        return True
    return False


def _notify_order_rejection(exc: Exception, state: dict, notifier) -> None:
    """Email an order-rejection alert at most once per hour so the inbox isn't flooded
    when the account is consistently over the allocation cap."""
    if not notifier:
        return
    now = datetime.now(timezone.utc)
    last_str = state.get("last_rejection_alert")
    if last_str:
        try:
            last = datetime.fromisoformat(last_str)
            if (now - last).total_seconds() < 3600:
                return
        except Exception:
            pass
    try:
        resp = getattr(exc, "response", None)
        detail = resp.json() if resp is not None else str(exc)
    except Exception:
        detail = str(exc)
    notifier.send(
        subject="[WARN] Trading — order rejected (insufficient buying power)",
        body=(
            f"An order was rejected at {now.strftime('%Y-%m-%d %H:%M UTC')} "
            f"due to a business-logic condition (not an API failure).\n\n"
            f"Detail: {detail}\n\n"
            f"The system is continuing normally. This alert fires at most once per hour.\n"
            f"Common causes: allocation cap exceeded, buying power exhausted."
        ),
    )
    state["last_rejection_alert"] = now.isoformat()


def _flush_pending_halt_alert(notifier) -> None:
    """Send a halt alert that was saved to disk when the network was down at halt time."""
    if not HALT_ALERT_PATH.exists() or not notifier:
        return
    try:
        with open(HALT_ALERT_PATH) as f:
            pending = json.load(f)
        notifier.critical_alert(
            f"[DELAYED ALERT] Trading system halted at {pending.get('halted_at', 'unknown')} "
            f"after {pending.get('failure_label', '? failures')}.\n\n"
            f"Last error: {pending.get('last_error', 'unknown')}\n\n"
            f"The original alert could not be delivered (network error at halt time). "
            f"System has recovered and restarted."
        )
        HALT_ALERT_PATH.unlink()
        print("[ALERT] Delayed halt alert delivered")
    except Exception as e:
        print(f"[ALERT] Failed to send delayed halt alert: {e}")


def _write_heartbeat() -> None:
    """Stamp the loop's liveness. Best-effort — never let a heartbeat write break the loop."""
    try:
        HEARTBEAT_PATH.parent.mkdir(parents=True, exist_ok=True)
        HEARTBEAT_PATH.write_text(datetime.now(timezone.utc).isoformat())
    except Exception:
        pass


def load_state() -> dict:
    if STATE_PATH.exists():
        with open(STATE_PATH) as f:
            return json.load(f)
    return INITIAL_STATE.copy()


def save_state(state: dict):
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_PATH, "w") as f:
        json.dump(state, f, indent=2, default=str)


def run_scheduled_tasks(
    state: dict,
    cfg,
    alpaca,
    notifier,
    hw,
    db,
    positions: list,
    whale_hits_session: list,
    current_regime: str,
    mode: str,
) -> None:
    """
    Fire time-based triggers (daily report + journal, weekly scan, monthly digest).
    Runs every loop iteration regardless of market open/closed — each trigger
    self-gates on ET clock and per-period dedup keys in state.
    """
    now_et = datetime.now(MARKET_TZ)
    today_et = now_et.date().isoformat()

    # --- Daily report + journal wrap-up ---
    # Report day is the last day the market was actually open (per last_status_report),
    # NOT "today" — this handles the case where service was sleeping past 4 PM ET and
    # it's now past midnight. We fire once per trading day, after 4:05 PM ET of that day.
    last_sr = state.get("last_status_report")
    report_day = None
    daily_due = False
    if last_sr:
        try:
            last_sr_et = datetime.fromisoformat(last_sr).astimezone(MARKET_TZ)
            report_day = last_sr_et.date().isoformat()
            min_report_time = last_sr_et.replace(hour=16, minute=5, second=0, microsecond=0)
            past_close_for_that_day = now_et >= min_report_time
            daily_due = (
                past_close_for_that_day
                and state.get("last_daily_report") != report_day
            )
        except Exception as e:
            print(f"[DAILY] last_status_report parse error: {e}")

    if daily_due and notifier:
        try:
            account = alpaca.get_account() if alpaca else {}
            equity = float(account.get("equity", 0) or 0)
            last_equity = float(account.get("last_equity", 0) or 0)
            realized_pnl = equity - last_equity  # day change vs prior close
            unrealized_pnl = sum(float(p.get("unrealized_pl", 0)) for p in (positions or []))
            avg = hw.averages() if hw else {"cpu_avg": 0.0, "temp_avg": 0.0}
            notifier.daily_report(
                realized_pnl=realized_pnl,
                unrealized_pnl=unrealized_pnl,
                positions=positions or [],
                cpu_avg=avg["cpu_avg"],
                temp_avg=avg["temp_avg"],
                whale_hits=[f"{t.politician} → {t.ticker}" for t in (whale_hits_session or [])],
            )
            state["last_daily_report"] = report_day
            print(f"[DAILY] Report sent for trading day {report_day} at {now_et.strftime('%Y-%m-%d %H:%M ET')}")
            save_state(state)
        except Exception as e:
            print(f"[DAILY] report failed: {e}")

        # Journal wrap-up immediately after — pin to the trading day being reported
        try:
            from datetime import date as _date
            journal_wrap_up(
                target_date=_date.fromisoformat(report_day),
                alpaca_client=alpaca,
                regime=current_regime,
                notifier=notifier,
                settings=cfg,
            )
        except Exception as je:
            print(f"[JOURNAL] wrap-up failed: {je}")

    # --- Weekly scan (Monday pre-market, before 9:30 ET) ---
    is_monday_premarket = (
        now_et.weekday() == 0
        and (now_et.hour < 9 or (now_et.hour == 9 and now_et.minute < 30))
    )
    weekly_due = is_monday_premarket and state.get("last_weekly_scan") != today_et
    if weekly_due:
        try:
            run_weekly_scan(alpaca, current_regime, settings=cfg, db=db, notifier=notifier)
            state["last_weekly_scan"] = today_et
            save_state(state)
            if db and notifier:
                lessons = db.get_lessons(days=7)
                digest_body = generate_digest("weekly", lessons, settings=cfg)
                notifier.strategy_digest("weekly", digest_body)
                print("[ADVISOR] Weekly digest sent")
        except Exception as ae:
            print(f"[ADVISOR] Weekly scan error: {ae}")

    # --- Monthly digest (1st of month, before 9:30 ET) ---
    is_first_premarket = (
        now_et.day == 1
        and (now_et.hour < 9 or (now_et.hour == 9 and now_et.minute < 30))
    )
    month_key = now_et.strftime("%Y-%m")
    monthly_due = is_first_premarket and state.get("last_monthly_digest") != month_key
    if monthly_due and db and notifier:
        try:
            lessons = db.get_lessons(days=30)
            digest_body = generate_digest("monthly", lessons, settings=cfg)
            notifier.strategy_digest("monthly", digest_body)
            state["last_monthly_digest"] = month_key
            save_state(state)
            print("[ADVISOR] Monthly digest sent")
        except Exception as me:
            print(f"[ADVISOR] Monthly digest error: {me}")

    # --- Weekly wrap-up (Friday after 4:15 PM ET) ---
    # Fires once per ISO week after Friday's daily report window.
    # Dedup key: ISO week string e.g. "2026-W19"
    is_friday_eod = (
        now_et.weekday() == 4
        and (now_et.hour > 16 or (now_et.hour == 16 and now_et.minute >= 15))
    )
    week_key = now_et.strftime("%Y-W%V")
    weekly_wrapup_due = is_friday_eod and state.get("last_weekly_wrapup") != week_key
    if weekly_wrapup_due and notifier:
        try:
            weekly_wrapup(
                ref_date=now_et.date(),
                alpaca_client=alpaca,
                regime=current_regime,
                notifier=notifier,
                settings=cfg,
            )
            state["last_weekly_wrapup"] = week_key
            save_state(state)
            print(f"[WEEKLY] Wrap-up complete for {week_key}")
        except Exception as we:
            print(f"[WEEKLY] Wrap-up error: {we}")

    # --- IV snapshot (Mon–Fri, 8:30–8:59 AM ET, once per day) ---
    is_weekday = now_et.weekday() < 5
    is_iv_window = now_et.hour == 8 and now_et.minute >= 30
    iv_due = is_weekday and is_iv_window and state.get("last_iv_snapshot") != today_et
    if iv_due:
        try:
            from execution.iv_tracker import snapshot_all_tickers
            snapshot_all_tickers(settings=cfg)
            state["last_iv_snapshot"] = today_et
            save_state(state)
            print(f"[IV] Daily snapshot complete for {today_et}")
        except Exception as ive:
            print(f"[IV] Snapshot error: {ive}")

    # --- IPO scan (Mon–Fri, 8:30–8:59 AM ET, once/day) — broadens the universe ---
    ipo_due = is_weekday and is_iv_window and state.get("last_ipo_scan") != today_et
    if ipo_due:
        try:
            from execution.ipo_calendar import IPOCalendar
            res = IPOCalendar(settings=cfg, alpaca_client=alpaca, db_logger=db,
                              notifier=notifier).scan(days=10)
            state["last_ipo_scan"] = today_et
            save_state(state)
            if res.get("watchlist"):
                print(f"[IPO] watchlist: {', '.join(res['watchlist'][:15])}")
        except Exception as ipe:
            print(f"[IPO] Scan error: {ipe}")

    # --- Derivatives (IV-rank) scan — runs after the IV snapshot so history is fresh ---
    deriv_due = is_weekday and is_iv_window and state.get("last_derivatives_scan") != today_et
    if deriv_due:
        try:
            from execution.derivatives_signals import DerivativesSignals
            DerivativesSignals(settings=cfg, db_logger=db).scan(list(cfg.wheel.tickers))
            state["last_derivatives_scan"] = today_et
            save_state(state)
        except Exception as dse:
            print(f"[DERIV] Scan error: {dse}")

    # --- Morning briefing (Mon–Fri, 9:00–9:29 AM ET, once per day) ---
    is_briefing_window = now_et.hour == 9 and now_et.minute < 30
    briefing_due = (
        is_weekday
        and is_briefing_window
        and state.get("last_morning_briefing") != today_et
    )
    if briefing_due:
        try:
            mb = MorningBriefing(
                settings=cfg,
                alpaca_client=alpaca,
                db_logger=db,
                notifier=notifier,
            )
            mb.generate()
            state["last_morning_briefing"] = today_et
            save_state(state)
            print(f"[BRIEFING] Morning briefing sent for {today_et}")
        except Exception as be:
            print(f"[BRIEFING] Morning briefing error: {be}")


def verify_all(cfg) -> bool:
    ok = True
    ok &= verify_alpaca()
    # PostgreSQL + Resend are optional — only check them when configured.
    if cfg.database.url:
        from execution import db_logger
        ok &= db_logger.ping(cfg)
    else:
        print("[SKIP] PostgreSQL — DATABASE_URL not set (logging disabled)")
    if cfg.notifications.resend_key:
        from execution.notifier import test_send
        ok &= test_send(cfg)
    else:
        print("[SKIP] Resend — RESEND_API_KEY not set (email disabled)")
    hw = HardwareMonitor(settings=cfg)
    metrics = hw.sample()
    print(f"[OK] Hardware — CPU: {metrics['cpu_pct']:.1f}%, Temp: {metrics['temp_c']:.1f}°C")
    mode = "PAPER" if cfg.guardrails.paper_mode else "LIVE"
    if ok:
        print(f"\n[READY] All systems go. Mode: {mode}")
    else:
        print("\n[FAIL] One or more connectivity checks failed. Fix before going live.")
    return ok


def _attempt_halt_recovery(state: dict, cfg) -> None:
    """On startup with a halt flag set, decide whether to self-heal or stay halted.

    Replaces the old brittle count rule (`network>=20 and api<=2`). Logic:
      - A genuine AUTH halt (bad/expired key, permissions) never self-heals → stay
        halted for a human to fix.
      - Otherwise run a LIVE authenticated API probe (get_clock via AlpacaClient,
        which carries Item-3 retries). If it succeeds, connectivity AND credentials
        are confirmed healthy *now* → clear the halt and resume. If it fails → stay
        halted. Any auto-recover→re-halt flapping is bounded by the systemd
        StartLimitBurst, which alerts and stops the unit after a few fast cycles.
    """
    reason = state.get("halt_reason", "unknown")
    nf = state.get("network_failures", 0)
    af = state.get("api_failures", 0)
    last_err = state.get("last_halt_error", "")
    last_ok = state.get("last_api_success", "never")

    if reason == "auth":
        print(f"[HALT] Auth/permission halt — will not auto-recover. Last error: {last_err}\n"
              f"       Fix credentials, then reset logs/agent_state.json to resume.")
        sys.exit(1)

    print(f"[RECOVERY] Halt (reason={reason}, network={nf}, api={af}, "
          f"last_api_success={last_ok}) — probing live API ...")
    try:
        clock = AlpacaClient(settings=cfg).get_clock()
        print(f"[RECOVERY] Live API healthy (market_open={clock.get('is_open')}) — "
              f"clearing halt and resuming")
        state["halted"] = False
        state["network_failures"] = 0
        state["api_failures"] = 0
        state.pop("halt_reason", None)
        save_state(state)
        HALT_ALERT_PATH.unlink(missing_ok=True)
        _send_recovery_slack_alert(nf, af)
    except Exception as probe_err:
        print(f"[HALT] Live API probe failed ({probe_err}). Staying halted.")
        sys.exit(1)


def _send_recovery_slack_alert(network_failures: int, api_failures: int) -> None:
    """Fire a Slack message when the system self-heals from a network halt."""
    import os, json, urllib.request
    url = os.environ.get("SLACK_WEBHOOK_URL", "")
    if not url:
        return
    try:
        msg = (f":white_check_mark: *Trading system auto-recovered* — "
               f"network restored after {network_failures} network + {api_failures} API failures. "
               f"Loop resuming.")
        payload = json.dumps({"text": msg}).encode()
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=10)
    except Exception:
        pass


def run(mode: str):
    cfg = cfg_module.load()
    state = load_state()

    if state.get("halted"):
        # Self-heal transient/network halts via a live API probe; only genuine
        # auth halts require a manual reset. (Supersedes the old exact-count rule.)
        _attempt_halt_recovery(state, cfg)

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
    position_mgr = PositionManager(settings=cfg, alpaca_client=alpaca, db_logger=db)
    protection = ProtectiveLogic(settings=cfg, alpaca_client=alpaca, db_logger=db)
    policy = PolicyMonitor(settings=cfg, notifier=notifier, db=db)
    regime = RegimeDetector(settings=cfg, alpaca_client=alpaca)
    hedge = InverseETFHedge(settings=cfg, alpaca_client=alpaca, db_logger=db)

    # Send any halt alert that was queued when the network was down at halt time
    _flush_pending_halt_alert(notifier)

    print(f"[START] Trading loop active — {mode.upper()} mode — {datetime.now().isoformat()}")

    whale_hits_session: list = []
    policy_feed_ok: bool = True
    wheel_tickers_scanned: int = 0
    wheel_contracts_found: int = 0
    current_regime: str = "NEUTRAL"

    while True:
        try:
            # --- Liveness heartbeat (first thing every cycle, incl. market-closed sleeps) ---
            _write_heartbeat()

            # --- Hardware Check ---
            metrics = hw.sample()
            if hw.check_thresholds(metrics):
                print("[HW] Threshold breach — pausing non-essential tasks for 60s")
                time.sleep(60)
                continue

            # --- Market Hours Gate ---
            clock = alpaca.get_clock()
            if not clock.get("is_open"):
                # Market closed: still run scheduled tasks (daily wrap-up after close,
                # weekly scan Monday pre-market, monthly digest 1st pre-market), then
                # short-sleep so those triggers get a chance to fire on time.
                run_scheduled_tasks(
                    state=state, cfg=cfg, alpaca=alpaca, notifier=notifier, hw=hw, db=db,
                    positions=alpaca.get_positions() or [],
                    whale_hits_session=whale_hits_session,
                    current_regime=current_regime,
                    mode=mode,
                )
                next_open_str = clock.get("next_open", "")
                try:
                    next_open = datetime.fromisoformat(next_open_str.replace("Z", "+00:00"))
                    secs_until_open = (next_open - datetime.now(timezone.utc)).total_seconds()
                    # Cap at 5 min so scheduled triggers keep checking
                    sleep_secs = max(60, min(secs_until_open, 300))
                    wake_at = next_open.strftime("%Y-%m-%d %H:%M ET")
                except Exception:
                    sleep_secs = 300
                    wake_at = "unknown"
                print(f"[MARKET] Closed — sleeping {sleep_secs:.0f}s (next open {wake_at})")
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
            prev_regime = current_regime
            current_regime = regime.detect()
            if prev_regime != current_regime:
                log_insight(
                    source="regime",
                    category="observation",
                    insight=f"Regime transition: {prev_regime} → {current_regime} (SPY {regime.spy_change_pct:+.2f}%)",
                    metadata={"from": prev_regime, "to": current_regime, "spy_change_pct": regime.spy_change_pct},
                )

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
                    log_insight(
                        source="whale_watch",
                        category="decision",
                        insight=(
                            f"{side.upper()} {qty}x {trade.ticker} @ ~${price:.2f} "
                            f"following {trade.politician} {trade.trade_type} "
                            f"${trade.trade_value:,.0f} (ROC {trade.roc_pct:.2f}%)"
                        ),
                        metadata={
                            "ticker": trade.ticker,
                            "qty": qty,
                            "side": side,
                            "price": price,
                            "politician": trade.politician,
                            "trade_value": trade.trade_value,
                            "roc_pct": trade.roc_pct,
                            "confidence": trade.confidence,
                        },
                    )
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
                    for sig in policy_signals:
                        log_insight(
                            source="policy",
                            category="signal",
                            insight=str(sig)[:300] if not isinstance(sig, dict)
                                    else sig.get("title") or sig.get("headline") or str(sig)[:300],
                            metadata=sig if isinstance(sig, dict) else {"raw": str(sig)},
                        )
            except Exception as pe:
                policy_feed_ok = False
                print(f"[POLICY] scan error: {pe}")
                log_insight(
                    source="policy",
                    category="error",
                    insight=f"policy scan error: {pe}",
                )

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

            # --- Active Position Management (50% profit close + 21-DTE roll) ---
            try:
                pm_result = position_mgr.run_cycle(positions)
                if pm_result["closed"] or pm_result["rolled"]:
                    print(
                        f"[PM] Closed: {pm_result['closed']}  Rolled: {pm_result['rolled']}"
                    )
            except Exception as pme:
                print(f"[PM] Position manager error: {pme}")

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

            # --- Scheduled tasks (daily report + journal, weekly, monthly) ---
            run_scheduled_tasks(
                state=state, cfg=cfg, alpaca=alpaca, notifier=notifier, hw=hw, db=db,
                positions=positions,
                whale_hits_session=whale_hits_session,
                current_regime=current_regime,
                mode=mode,
            )

            state["api_failures"] = 0
            state["network_failures"] = 0
            state["last_api_success"] = datetime.now(timezone.utc).isoformat()
            save_state(state)
            time.sleep(60)

        except KeyboardInterrupt:
            print("\n[STOP] Loop interrupted by operator")
            save_state(state)
            break

        except Exception as e:
            if _is_network_error(e):
                state["network_failures"] = state.get("network_failures", 0) + 1
                nf = state["network_failures"]
                print(f"[NET] Network error #{nf}/{NETWORK_FAILURE_HALT_THRESHOLD}: {e}")
                save_state(state)
                if nf < NETWORK_FAILURE_HALT_THRESHOLD:
                    time.sleep(30)
                    continue
                failure_label = f"{nf} consecutive network errors"
                halt_reason = "network"
            elif _is_order_rejection(e):
                # Business-logic rejection (e.g. insufficient buying power) — not an API
                # malfunction. Log it and move on; never count toward the halt threshold.
                print(f"[WARN] Order rejected (skipping, no halt credit): {e}")
                _notify_order_rejection(e, state, notifier)
                save_state(state)
                time.sleep(10)
                continue
            else:
                state["api_failures"] = state.get("api_failures", 0) + 1
                af = state["api_failures"]
                print(f"[ERROR] {e} (failure #{af})")
                save_state(state)
                if af < cfg.guardrails.api_retry_limit:
                    time.sleep(10)
                    continue
                failure_label = f"{af} consecutive API failures"
                # Auth/permission failures can't self-heal — mark so restart won't auto-recover.
                halt_reason = "auth" if _is_auth_error(e) else "api"

            # --- HALT: write alert to disk first, email may also fail ---
            halt_info = {
                "halted_at": datetime.now(timezone.utc).isoformat(),
                "failure_label": failure_label,
                "halt_reason": halt_reason,
                "last_error": str(e),
            }
            state["halt_reason"] = halt_reason
            state["last_halt_error"] = str(e)
            try:
                HALT_ALERT_PATH.parent.mkdir(parents=True, exist_ok=True)
                with open(HALT_ALERT_PATH, "w") as hf:
                    json.dump(halt_info, hf, indent=2)
            except Exception:
                pass

            state["halted"] = True
            save_state(state)
            if notifier:
                try:
                    notifier.critical_alert(
                        f"Trading system HALTED after {failure_label}.\n\nLast error: {e}"
                    )
                    HALT_ALERT_PATH.unlink(missing_ok=True)
                except Exception as ae:
                    print(f"[HALT] Alert email failed ({ae}) — saved to disk for retry on next start")
            print("[HALT] Critical failure threshold reached. System halted.")
            sys.exit(1)


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
