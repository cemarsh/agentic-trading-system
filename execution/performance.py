"""
Performance metrics — the deterministic "did the needle move" numbers.

The weekly/monthly/quarterly reports are Claude-synthesized narrative; this module is
the hard-number counterpart they all embed. Nothing here calls an LLM, so the figures
are reproducible and a report is still worth reading with no ANTHROPIC_API_KEY set.

Three independent sources, deliberately kept separate so one failing degrades to a
partial report rather than no report:
  - equity_curve()     Alpaca portfolio history (broker truth, includes unrealized)
  - trade_stats()      decision_logic in postgres (our own closed-trade ledger)
  - capital_snapshot() live account + positions (how much capital is actually working)

Alpaca's portfolio-history endpoint only accepts coarse periods (1M/3M/6M/1A), so we
fetch the smallest period covering the request and slice locally by date.
"""

import sys
from datetime import datetime, date, timezone, timedelta
from pathlib import Path


sys.path.insert(0, str(Path(__file__).parent.parent))

# Alpaca portfolio-history periods, smallest first. We ask for the first one that
# covers the requested span; anything longer is wasted payload.
_PERIOD_LADDER = [(31, "1M"), (93, "3M"), (186, "6M"), (372, "1A"), (10**6, "2A")]


def _alpaca_period_for(days: int) -> str:
    for limit, period in _PERIOD_LADDER:
        if days <= limit:
            return period
    return "2A"


def _pct(numerator: float, denominator: float) -> float:
    """Percent change guarded against a zero/absent starting value."""
    if not denominator:
        return 0.0
    return (numerator / denominator - 1) * 100


# ---------------------------------------------------------------------------
# Equity curve (broker truth)
# ---------------------------------------------------------------------------

def equity_curve(alpaca_client, start: date, end: date) -> dict:
    """
    Equity start/end/peak/trough + max drawdown over [start, end] inclusive.

    Returns zeros with points=0 when the broker is unreachable or the window
    predates the account — callers render "insufficient data" rather than fail.
    """
    out = {
        "points": 0, "start_equity": 0.0, "end_equity": 0.0,
        "change": 0.0, "change_pct": 0.0,
        "peak": 0.0, "trough": 0.0, "max_drawdown_pct": 0.0,
        "start_date": start.isoformat(), "end_date": end.isoformat(),
        "series": [],
    }
    if not alpaca_client:
        return out

    span_days = (end - start).days + 1
    try:
        hist = alpaca_client.get_portfolio_history(
            period=_alpaca_period_for(span_days), timeframe="1D"
        ) or {}
    except Exception as e:
        print(f"[PERF] portfolio history failed: {e}")
        return out

    # Alpaca returns key-with-None (not a missing key) outside market hours.
    stamps = hist.get("timestamp") or []
    equities = hist.get("equity") or []

    series = []
    for ts, eq in zip(stamps, equities):
        if not eq:  # None or 0.0 — both are "no data for this bar"
            continue
        day = datetime.fromtimestamp(ts, tz=timezone.utc).date()
        if start <= day <= end:
            series.append((day, float(eq)))

    if not series:
        return out

    series.sort(key=lambda x: x[0])
    values = [v for _, v in series]

    # Max drawdown: deepest peak-to-trough decline walking the curve forward.
    peak_so_far = values[0]
    max_dd = 0.0
    for v in values:
        peak_so_far = max(peak_so_far, v)
        if peak_so_far:
            max_dd = max(max_dd, (peak_so_far - v) / peak_so_far * 100)

    out.update({
        "points": len(series),
        "start_equity": values[0],
        "end_equity": values[-1],
        "change": values[-1] - values[0],
        "change_pct": _pct(values[-1], values[0]),
        "peak": max(values),
        "trough": min(values),
        "max_drawdown_pct": max_dd,
        "start_date": series[0][0].isoformat(),
        "end_date": series[-1][0].isoformat(),
        "series": series,
    })
    return out


# ---------------------------------------------------------------------------
# Closed-trade stats (our ledger)
# ---------------------------------------------------------------------------

def trade_stats(settings, start: date, end: date) -> dict:
    """
    Closed-trade performance from decision_logic over [start, end].

    A row counts as closed once it has a non-null pnl. Profit factor is
    gross_win / abs(gross_loss) — the metric live_gates screens on, so the
    reports and the live-readiness check speak the same language.
    """
    out = {
        "total_trades": 0, "wins": 0, "losses": 0, "win_rate": 0.0,
        "total_pnl": 0.0, "gross_win": 0.0, "gross_loss": 0.0,
        "profit_factor": 0.0, "avg_win": 0.0, "avg_loss": 0.0, "expectancy": 0.0,
        "by_ticker": {}, "by_strategy": {}, "available": False,
    }
    if not settings or not getattr(settings.database, "url", ""):
        return out
    try:
        import psycopg2
        import psycopg2.extras
    except ImportError:
        return out

    start_ts = datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc)
    end_ts = datetime.combine(end, datetime.max.time(), tzinfo=timezone.utc)

    try:
        with psycopg2.connect(settings.database.url) as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT ticker, action, tier, confidence, pnl, status, ts
                    FROM decision_logic
                    WHERE ts >= %s AND ts <= %s AND pnl IS NOT NULL
                    ORDER BY ts ASC
                    """,
                    (start_ts, end_ts),
                )
                rows = [dict(r) for r in cur.fetchall()]
    except Exception as e:
        print(f"[PERF] DB query (trade stats) failed: {e}")
        return out

    out["available"] = True
    if not rows:
        return out

    pnls = [float(r["pnl"]) for r in rows]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))

    def _bucket(key_field: str) -> dict:
        acc: dict = {}
        for r in rows:
            k = r.get(key_field) or "?"
            slot = acc.setdefault(k, {"trades": 0, "pnl": 0.0, "wins": 0})
            slot["trades"] += 1
            slot["pnl"] += float(r["pnl"])
            if float(r["pnl"]) > 0:
                slot["wins"] += 1
        return acc

    out.update({
        "total_trades": len(rows),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": len(wins) / len(rows) * 100,
        "total_pnl": sum(pnls),
        "gross_win": gross_win,
        "gross_loss": gross_loss,
        # No losses at all → profit factor is undefined, not infinite. 0.0 reads
        # as "not computable" everywhere downstream.
        "profit_factor": (gross_win / gross_loss) if gross_loss else 0.0,
        "avg_win": (gross_win / len(wins)) if wins else 0.0,
        "avg_loss": (-gross_loss / len(losses)) if losses else 0.0,
        "expectancy": sum(pnls) / len(pnls),
        "by_ticker": _bucket("ticker"),
        "by_strategy": _bucket("tier"),
    })
    return out


# ---------------------------------------------------------------------------
# Capital deployment (right now)
# ---------------------------------------------------------------------------

def capital_snapshot(alpaca_client) -> dict:
    """
    How much of the account is actually working. Idle cash is the quietest way for
    this system to underperform — nothing errors, it just doesn't trade.

    Short puts carry no market value on the equity side, so their collateral
    (strike x 100 x qty) is counted explicitly the same way the sector cap does.
    """
    out = {
        "equity": 0.0, "cash": 0.0, "long_value": 0.0, "short_put_collateral": 0.0,
        "deployed": 0.0, "deployed_pct": 0.0, "idle_cash_pct": 0.0,
        "positions": 0, "equity_positions": 0, "option_positions": 0,
        "unrealized_pl": 0.0, "available": False,
    }
    if not alpaca_client:
        return out
    try:
        account = alpaca_client.get_account() or {}
        positions = alpaca_client.get_positions() or []
    except Exception as e:
        print(f"[PERF] capital snapshot failed: {e}")
        return out

    equity = float(account.get("equity", 0) or 0)
    cash = float(account.get("cash", 0) or 0)

    long_value = 0.0
    collateral = 0.0
    equity_ct = opt_ct = 0
    unrealized = 0.0

    for p in positions:
        symbol = p.get("symbol", "")
        qty = float(p.get("qty", 0) or 0)
        unrealized += float(p.get("unrealized_pl", 0) or 0)
        # OCC option symbols are 15+ chars: ROOT + YYMMDD + C/P + 8-digit strike.
        if len(symbol) > 10 and symbol[-9] in ("C", "P"):
            opt_ct += 1
            if qty < 0 and symbol[-9] == "P":
                strike = int(symbol[-8:]) / 1000.0
                collateral += strike * 100 * abs(qty)
        else:
            equity_ct += 1
            long_value += float(p.get("market_value", 0) or 0)

    deployed = long_value + collateral
    out.update({
        "equity": equity, "cash": cash, "long_value": long_value,
        "short_put_collateral": collateral, "deployed": deployed,
        "deployed_pct": (deployed / equity * 100) if equity else 0.0,
        "idle_cash_pct": (cash / equity * 100) if equity else 0.0,
        "positions": len(positions), "equity_positions": equity_ct,
        "option_positions": opt_ct, "unrealized_pl": unrealized,
        "available": True,
    })
    return out


# ---------------------------------------------------------------------------
# Collection + rendering
# ---------------------------------------------------------------------------

def collect(alpaca_client, settings, start: date, end: date) -> dict:
    """Gather all three metric families for a period. Each degrades independently."""
    return {
        "start": start, "end": end,
        "equity": equity_curve(alpaca_client, start, end),
        "trades": trade_stats(settings, start, end),
        "capital": capital_snapshot(alpaca_client),
    }


def build_needle_section(metrics: dict, label: str) -> str:
    """
    Render the 'Needle Movement' block embedded at the top of every period report.

    This is the section that answers "did anything actually change" before any
    narrative gets a chance to editorialize.
    """
    eq = metrics.get("equity", {})
    tr = metrics.get("trades", {})
    cap = metrics.get("capital", {})

    lines = [f"## Needle Movement — {label}", ""]

    # --- Equity ---
    if eq.get("points"):
        arrow = "▲" if eq["change"] >= 0 else "▼"
        lines += [
            f"**Equity:** ${eq['start_equity']:,.2f} → ${eq['end_equity']:,.2f}  "
            f"{arrow} **${eq['change']:+,.2f} ({eq['change_pct']:+.2f}%)**",
            "",
            f"| Metric | Value |",
            f"|--------|-------|",
            f"| Period | {eq['start_date']} → {eq['end_date']} ({eq['points']} sessions) |",
            f"| Peak equity | ${eq['peak']:,.2f} |",
            f"| Trough equity | ${eq['trough']:,.2f} |",
            f"| Max drawdown | {eq['max_drawdown_pct']:.2f}% |",
            "",
        ]
    else:
        lines += ["_Equity curve unavailable for this period._", ""]

    # --- Closed trades ---
    if tr.get("total_trades"):
        # Profit factor is 0.0 in two completely different situations and they must not
        # print the same way. gross_loss == 0 means the ratio is undefined (nothing lost);
        # gross_win == 0 with real losses means it is genuinely zero. Labelling the second
        # as "no losing trades" inverted a 0-win / 7-loss week into a clean sheet.
        pf = tr["profit_factor"]
        if tr.get("gross_loss", 0) <= 0:
            pf_text = "n/a (no losing trades)"
        elif pf <= 0:
            pf_text = "0.00 (no winning trades)"
        else:
            pf_text = f"{pf:.2f}"
        lines += [
            "### Closed Trades",
            "",
            f"| Metric | Value |",
            f"|--------|-------|",
            f"| Closed trades | {tr['total_trades']} |",
            f"| Win / loss | {tr['wins']} / {tr['losses']} |",
            f"| Win rate | {tr['win_rate']:.1f}% |",
            f"| Realized P&L | ${tr['total_pnl']:+,.2f} |",
            f"| Gross win / gross loss | ${tr['gross_win']:,.2f} / ${tr['gross_loss']:,.2f} |",
            f"| Profit factor | {pf_text} |",
            f"| Avg win / avg loss | ${tr['avg_win']:+,.2f} / ${tr['avg_loss']:+,.2f} |",
            f"| Expectancy per trade | ${tr['expectancy']:+,.2f} |",
            "",
        ]
        ranked = sorted(tr["by_ticker"].items(), key=lambda x: -x[1]["pnl"])
        if ranked:
            # The marker comes from the SIGN, never from rank position. Ranking alone put
            # a green tick on "ALB: -$273.00" in a week where every single trade lost.
            shown = ranked[:3] + [r for r in ranked[-3:] if r not in ranked[:3]]
            lines += ["**Best / worst tickers:**", ""]
            for ticker, s in shown:
                mark = "✅" if s["pnl"] > 0 else "❌"
                lines.append(f"- {mark} {ticker}: ${s['pnl']:+,.2f} ({s['wins']}/{s['trades']} wins)")
            lines.append("")
    elif tr.get("available"):
        lines += ["### Closed Trades", "", "_No closed trades logged in this period._", ""]
    else:
        lines += ["### Closed Trades", "", "_Trade ledger unavailable (no DATABASE_URL)._", ""]

    # --- Capital deployment ---
    if cap.get("available"):
        lines += [
            "### Capital Deployment (current)",
            "",
            f"| Metric | Value |",
            f"|--------|-------|",
            f"| Equity | ${cap['equity']:,.2f} |",
            f"| Deployed | ${cap['deployed']:,.2f} ({cap['deployed_pct']:.1f}%) |",
            f"| — long equity | ${cap['long_value']:,.2f} |",
            f"| — short-put collateral | ${cap['short_put_collateral']:,.2f} |",
            f"| Idle cash | ${cap['cash']:,.2f} ({cap['idle_cash_pct']:.1f}%) |",
            f"| Open positions | {cap['positions']} ({cap['equity_positions']} equity / {cap['option_positions']} options) |",
            f"| Unrealized P&L | ${cap['unrealized_pl']:+,.2f} |",
            "",
        ]

    return "\n".join(lines)


def period_bounds_month(ref: date) -> tuple:
    """(first, last) calendar day of the month containing ref."""
    first = ref.replace(day=1)
    next_month = (first + timedelta(days=32)).replace(day=1)
    return first, next_month - timedelta(days=1)


def period_bounds_quarter(ref: date) -> tuple:
    """(first, last) calendar day of the quarter containing ref."""
    q_index = (ref.month - 1) // 3
    first = date(ref.year, q_index * 3 + 1, 1)
    next_q_month = first.month + 3
    year = first.year + (1 if next_q_month > 12 else 0)
    month = next_q_month - 12 if next_q_month > 12 else next_q_month
    return first, date(year, month, 1) - timedelta(days=1)


def quarter_label(ref: date) -> str:
    return f"{ref.year}-Q{(ref.month - 1) // 3 + 1}"
