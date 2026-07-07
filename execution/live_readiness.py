"""
Live-money readiness gates — defined in code NOW, while still on paper, so the
bar can't be lowered in the heat of the moment.

`--mode live` will not start unless ALL gates pass:

  1. Clean-alert streak: >= live_gates.min_days_since_critical_alert days since
     the last critical alert (read from logs/critical_alerts.log, which
     Notifier.critical_alert stamps). If no alert has ever been recorded, the
     streak is measured from a baseline stamp created the first time this check
     runs — observed-clean time, not assumed-clean time.
  2. Paper performance: profit factor >= min_profit_factor AND max drawdown
     <= max_drawdown_pct over the last history_window_days of account history
     (Alpaca portfolio history).
  3. Hard gates present in config: risk gate caps, IV hard gate, credit floors.

Every gate FAILS CLOSED: missing data means not ready.

initial_capital_fraction (25%) is reported as an instruction, not enforced —
capital sizing happens at the account level, not in this process.

Usage:
    python execution/live_readiness.py          # print the readiness report
"""

import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Tuple

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import settings as cfg_module

CRITICAL_LOG = Path("logs/critical_alerts.log")
BASELINE_STAMP = Path("logs/critical_alerts.baseline")


def _days_clean() -> Tuple[float, str]:
    """Days since the last critical alert, measured only over observed time."""
    now = datetime.now(timezone.utc)
    last_alert = None
    if CRITICAL_LOG.exists():
        try:
            lines = [l for l in CRITICAL_LOG.read_text().splitlines() if l.strip()]
            if lines:
                ts = lines[-1].split("\t")[0].rstrip("Z")
                last_alert = datetime.fromisoformat(ts).replace(tzinfo=timezone.utc)
        except Exception:
            pass
    if last_alert:
        days = (now - last_alert).total_seconds() / 86400
        return days, f"last critical alert {days:.1f} days ago"

    # No alert on record — measure from when we STARTED recording.
    if not BASELINE_STAMP.exists():
        try:
            BASELINE_STAMP.parent.mkdir(parents=True, exist_ok=True)
            BASELINE_STAMP.write_text(now.isoformat())
        except Exception:
            pass
        return 0.0, "no alert history — baseline stamped today, streak starts now"
    try:
        baseline = datetime.fromisoformat(BASELINE_STAMP.read_text().strip())
        days = (now - baseline).total_seconds() / 86400
        return days, f"zero critical alerts in {days:.1f} observed days"
    except Exception:
        return 0.0, "baseline unreadable — streak reset"


def _paper_performance(alpaca, window_days: int) -> Tuple[float, float, str]:
    """(profit_factor, max_drawdown_pct, note). Fails closed via (0, 100)."""
    period = "1A" if window_days > 180 else ("6M" if window_days > 90 else "3M")
    try:
        hist = alpaca.get_portfolio_history(period=period, timeframe="1D")
        equity = [float(e) for e in (hist.get("equity") or []) if e is not None]
        pl = [float(p) for p in (hist.get("profit_loss") or []) if p is not None]
    except Exception as e:
        return 0.0, 100.0, f"portfolio history unavailable ({e})"

    if len(equity) < 20:
        return 0.0, 100.0, f"only {len(equity)} days of history — need a real sample"

    gross_win = sum(p for p in pl if p > 0)
    gross_loss = sum(-p for p in pl if p < 0)
    profit_factor = (gross_win / gross_loss) if gross_loss > 0 else float("inf")

    peak = equity[0]
    max_dd = 0.0
    for e in equity:
        peak = max(peak, e)
        if peak > 0:
            max_dd = max(max_dd, (peak - e) / peak * 100)

    return profit_factor, max_dd, f"{len(equity)} days of history"


def _hard_gates_present(cfg) -> List[str]:
    """Config-level hard gates that must exist before live. Returns missing items."""
    missing = []
    risk = getattr(cfg, "risk", None)
    if not risk or not getattr(risk, "max_position_pct", 0):
        missing.append("risk.max_position_pct")
    if not risk or not getattr(risk, "sector_cap_pct", 0):
        missing.append("risk.sector_cap_pct")
    wheel = getattr(cfg, "wheel", None)
    if not wheel or not getattr(wheel, "min_iv_rank", 0):
        missing.append("wheel.min_iv_rank")
    if wheel and getattr(wheel, "iv_gate_fail_open", False):
        missing.append("wheel.iv_gate_fail_open must be false (hard gate)")
    if not wheel or not getattr(wheel, "min_credit_per_share", 0):
        missing.append("wheel.min_credit_per_share")
    pm = getattr(cfg, "position_management", None)
    if not pm or not getattr(pm, "min_roll_credit", 0):
        missing.append("position_management.min_roll_credit")
    return missing


def check_ready(settings=None, alpaca=None, verbose: bool = True) -> bool:
    cfg = settings or cfg_module.load()
    gates = getattr(cfg, "live_gates", None)
    min_days = getattr(gates, "min_days_since_critical_alert", 60) if gates else 60
    min_pf = getattr(gates, "min_profit_factor", 1.3) if gates else 1.3
    max_dd_limit = getattr(gates, "max_drawdown_pct", 8.0) if gates else 8.0
    window = getattr(gates, "history_window_days", 90) if gates else 90
    frac = getattr(gates, "initial_capital_fraction", 0.25) if gates else 0.25

    if alpaca is None:
        from execution.alpaca_client import AlpacaClient
        alpaca = AlpacaClient(settings=cfg)

    results: List[Tuple[str, bool, str]] = []

    days, note = _days_clean()
    results.append((
        f"Clean-alert streak >= {min_days}d", days >= min_days, f"{note}"
    ))

    pf, dd, perf_note = _paper_performance(alpaca, window)
    pf_str = "inf" if pf == float("inf") else f"{pf:.2f}"
    results.append((f"Profit factor >= {min_pf}", pf >= min_pf, f"PF {pf_str} ({perf_note})"))
    results.append((f"Max drawdown <= {max_dd_limit}%", dd <= max_dd_limit, f"DD {dd:.1f}%"))

    missing = _hard_gates_present(cfg)
    results.append((
        "Hard gates present in config", not missing,
        "all present" if not missing else "missing: " + ", ".join(missing)
    ))

    ready = all(ok for _, ok, _ in results)

    if verbose:
        print("=" * 62)
        print("LIVE-MONEY READINESS")
        print("=" * 62)
        for name, ok, detail in results:
            print(f"  [{'PASS' if ok else 'FAIL'}] {name} — {detail}")
        print("-" * 62)
        if ready:
            print(f"[READY] All gates pass. Go live at {frac:.0%} of capital for the "
                  f"first quarter before scaling.")
        else:
            print("[NOT READY] One or more gates failed — staying on paper.")
    return ready


if __name__ == "__main__":
    sys.exit(0 if check_ready() else 1)
