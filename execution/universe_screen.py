"""
Universe screening — pick tickers by tradability and correlation, not by theme.

The problem this exists to solve, measured 2026-08-21: 20 of 23 wheel tickers sat in
four sector buckets (defense / space / nuclear / critical minerals) that correlate at
**0.63** with each other. Those are separate buckets in strategy_params.yaml with a 20%
cap each, which reads as diversification and is not — four buckets at 20% is 80% of the
book in one macro position, the American industrial-policy trade. Every one of them was
hand-picked off that thesis. The entire quarter's loss (-$7,970 of -$8,135) is inside it.

So the selection criterion changes. A candidate earns a place by being *tradable for this
account* and by *not moving with what we already hold* — never by fitting a story:

  1. one contract fits the per-trade cap            (price x 100 <= cap)
  2. puts actually exist at the target expiry       (chain is real)
  3. the NBBO is tight enough to not eat the credit (spread as % of mid)
  4. correlation to the CURRENT BOOK is under a cap (the point of the module)

Screened names are handed to dynamic_universe.promote(), not written into the YAML.
That is deliberate: the IV gate is fail-closed, so a name with no history cannot trade
for MIN_HISTORY_DAYS (15) of snapshots no matter how well it screens. Promotion is what
gets a ticker into iv_tracker's snapshot set, which starts that clock. A universe change
that skipped this step would look instant and be inert for three weeks.

  python execution/universe_screen.py --screen          # report only, no changes
  python execution/universe_screen.py --screen --promote
"""

import argparse
import math
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Sequence

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import settings as cfg_module


# ---------------------------------------------------------------------------
# Return series + correlation
# ---------------------------------------------------------------------------

def daily_log_returns(alpaca_client, ticker: str, lookback_days: int) -> List[float]:
    """
    Daily log returns over the lookback. Empty list when the history is too short.

    `start` is REQUIRED on the free IEX feed or the endpoint returns only today's bar —
    the same trap that made the wheel's realized-vol gate a silent no-op.
    """
    if not alpaca_client:
        return []
    start = (date.today() - timedelta(days=int(lookback_days * 2.2) + 5)).isoformat()
    try:
        bars = alpaca_client.get_bars(ticker, "1Day", lookback_days + 1, start=start) or []
    except Exception as e:
        print(f"[SCREEN] {ticker} — bars unavailable ({e})")
        return []
    closes = [float(b["c"]) for b in bars if b.get("c")]
    return [
        math.log(closes[i] / closes[i - 1])
        for i in range(1, len(closes))
        if closes[i - 1] > 0 and closes[i] > 0
    ]


def correlation(a: Sequence[float], b: Sequence[float]) -> Optional[float]:
    """Pearson correlation over the overlapping tail. None if too short or flat."""
    n = min(len(a), len(b))
    if n < 20:
        return None
    x, y = list(a[-n:]), list(b[-n:])
    mx, my = sum(x) / n, sum(y) / n
    cov = sum((x[i] - mx) * (y[i] - my) for i in range(n))
    dx = math.sqrt(sum((v - mx) ** 2 for v in x))
    dy = math.sqrt(sum((v - my) ** 2 for v in y))
    if dx == 0 or dy == 0:
        return None
    return cov / (dx * dy)


def max_correlation_to_book(
    candidate_returns: Sequence[float],
    book_returns: Dict[str, Sequence[float]],
) -> tuple:
    """
    (worst_corr, worst_ticker) against everything currently held.

    Uses the MAXIMUM, not the average: a candidate that is uncorrelated to nine holdings
    and 0.9 to the tenth is a concentration risk, and averaging hides exactly that.
    Signed, not absolute — a strongly NEGATIVE correlation is a diversifier and must not
    be rejected for being large.
    """
    worst, worst_ticker = None, None
    for ticker, series in book_returns.items():
        c = correlation(candidate_returns, series)
        if c is None:
            continue
        if worst is None or c > worst:
            worst, worst_ticker = c, ticker
    return worst, worst_ticker


# ---------------------------------------------------------------------------
# Mechanical tradability
# ---------------------------------------------------------------------------

def _nearest_friday(weeks_out: int) -> str:
    target = date.today() + timedelta(weeks=weeks_out)
    days_ahead = 4 - target.weekday()
    if days_ahead < 0:
        days_ahead += 7
    return (target + timedelta(days=days_ahead)).isoformat()


def screen_ticker(
    alpaca_client, ticker: str, cfg,
    book_returns: Dict[str, Sequence[float]],
    per_trade_cap: float,
) -> dict:
    """
    Evaluate one candidate. Returns a verdict dict; never raises.

    Checks run cheapest-first so a name that cannot possibly fit never costs an
    options-chain call.
    """
    u = cfg.universe
    out = {"ticker": ticker, "ok": False, "reason": "", "price": 0.0,
           "corr": None, "corr_with": None, "spread_pct": None}

    try:
        bars = alpaca_client.get_bars(ticker, "1Min", 1) or []
        if not bars:
            out["reason"] = "no quote"
            return out
        price = float(bars[-1]["c"])
        out["price"] = price
    except Exception as e:
        out["reason"] = f"quote failed ({e})"
        return out

    # 1. One contract has to fit the per-trade cap, or the name can never trade here.
    if price * 100 > per_trade_cap:
        out["reason"] = f"${price * 100:,.0f} collateral > ${per_trade_cap:,.0f} cap"
        return out

    # 2. Correlation to the book — the reason this module exists.
    cand = daily_log_returns(alpaca_client, ticker, u.correlation_lookback_days)
    if len(cand) < 20:
        out["reason"] = "insufficient price history for correlation"
        return out
    corr, with_ticker = max_correlation_to_book(cand, book_returns)
    out["corr"], out["corr_with"] = corr, with_ticker
    if corr is not None and corr > u.max_correlation:
        out["reason"] = f"corr {corr:+.2f} to {with_ticker} > {u.max_correlation:.2f} cap"
        return out

    # 3. Puts must actually exist at the expiry we would trade.
    expiry = _nearest_friday(cfg.wheel.expiration_weeks)
    try:
        contracts = alpaca_client.get_options_contracts(ticker, expiry) or []
    except Exception as e:
        out["reason"] = f"chain failed ({e})"
        return out
    puts = [c for c in contracts if c.get("type") == "put"]
    if not puts:
        out["reason"] = f"no puts at {expiry}"
        return out

    # 4. Spread on the strike we would actually sell — a wide book eats the credit
    #    before any of the entry gates get a chance to judge it.
    target_strike = price * (cfg.wheel.target_delta * 0.15 + 0.90)
    near = min(puts, key=lambda c: abs(float(c.get("strike_price", 0)) - target_strike))
    try:
        q = alpaca_client.get_option_quote(near["symbol"]) or {}
        bid, ask = float(q.get("bid") or 0), float(q.get("ask") or 0)
    except Exception:
        bid = ask = 0.0
    if bid <= 0 or ask <= 0:
        out["reason"] = "no two-sided market on the target strike"
        return out
    mid = (bid + ask) / 2
    spread_pct = (ask - bid) / mid * 100 if mid > 0 else 999
    out["spread_pct"] = spread_pct
    if spread_pct > u.max_spread_pct:
        out["reason"] = f"spread {spread_pct:.0f}% > {u.max_spread_pct:.0f}% cap"
        return out

    out["ok"] = True
    out["reason"] = "passes"
    return out


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def build_book_returns(alpaca_client, cfg, positions: list) -> Dict[str, List[float]]:
    """
    Return series for what we ACTUALLY hold — options mapped to their underlying.

    Correlation is measured against live holdings rather than the configured universe on
    purpose: the risk that matters is what the book is exposed to right now, not what a
    YAML list says we might trade someday.
    """
    from execution.wheel_strategy import _OCC_RE
    underlyings = set()
    for p in positions or []:
        sym = (p.get("symbol") or "").upper()
        m = _OCC_RE.match(sym)
        underlyings.add(m.group(1) if m else sym)

    series: Dict[str, List[float]] = {}
    for t in sorted(underlyings):
        r = daily_log_returns(alpaca_client, t, cfg.universe.correlation_lookback_days)
        if len(r) >= 20:
            series[t] = r
    return series


def run_screen(alpaca_client=None, settings=None, promote: bool = False,
               allow_closed: bool = False) -> dict:
    """Screen the seed pool. Returns {'passed': [...], 'rejected': [...]}"""
    cfg = settings or cfg_module.load()
    u = getattr(cfg, "universe", None)
    if u is None or not u.enabled:
        print("[SCREEN] universe screening disabled")
        return {"passed": [], "rejected": []}

    if alpaca_client is None:
        from execution.alpaca_client import AlpacaClient
        alpaca_client = AlpacaClient(settings=cfg)

    # The spread test is meaningless outside regular trading hours. Options quotes go
    # stale and wide at the close, and the screen then rejects the most liquid names in
    # the market: a first run at 17:40 ET scored KO at 55%, T at 186% and SBUX at 183%,
    # and passed 1 of 28. Those are artifacts, not illiquidity. Refuse rather than
    # produce a confident, wrong answer — a screen that silently rejects good names
    # looks identical to a screen that is working.
    if not allow_closed:
        try:
            if not (alpaca_client.get_clock() or {}).get("is_open"):
                print("[SCREEN] market is CLOSED — option spreads are stale and this "
                      "screen would reject liquid names as illiquid. Re-run during RTH, "
                      "or pass allow_closed=True to see the non-spread checks only.")
                return {"passed": [], "rejected": [], "skipped": "market closed"}
        except Exception as e:
            print(f"[SCREEN] could not confirm market hours ({e}) — proceeding")

    try:
        account = alpaca_client.get_account() or {}
        equity = float(account.get("equity", 0) or 0)
        positions = alpaca_client.get_positions() or []
    except Exception as e:
        print(f"[SCREEN] cannot reach broker ({e})")
        return {"passed": [], "rejected": []}

    per_trade_cap = equity * cfg.wheel.max_portfolio_pct_per_trade / 100.0
    book = build_book_returns(alpaca_client, cfg, positions)

    print(f"[SCREEN] equity ${equity:,.0f}  per-trade cap ${per_trade_cap:,.0f}")
    print(f"[SCREEN] correlating against held book: {', '.join(book) or '(empty book)'}")

    existing = {t.upper() for t in cfg.wheel.tickers}
    passed, rejected = [], []
    for ticker in u.seed_pool:
        t = ticker.upper()
        if t in existing:
            continue
        verdict = screen_ticker(alpaca_client, t, cfg, book, per_trade_cap)
        (passed if verdict["ok"] else rejected).append(verdict)

    passed.sort(key=lambda v: (v["corr"] if v["corr"] is not None else 1.0))

    if promote and passed:
        from execution.dynamic_universe import promote as _promote
        names = [v["ticker"] for v in passed[:u.max_new_per_run]]
        added = _promote(
            names, source="universe_screen",
            reason=f"mechanical screen, corr cap {u.max_correlation:.2f}",
            exclude=existing,
            max_tickers=u.max_promoted,
        )
        print(f"[SCREEN] promoted {len(added)}: {', '.join(added) or '(none new)'}")
        print("[SCREEN] these start accruing IV history at the next snapshot; "
              "they cannot trade for ~15 trading days (fail-closed IV gate)")

    return {"passed": passed, "rejected": rejected}


def format_report(result: dict, cfg=None) -> str:
    """Human-readable screen result for the journal / terminal."""
    passed, rejected = result["passed"], result["rejected"]
    lines = ["", f"PASSED ({len(passed)}) — ranked by lowest correlation to the book", ""]
    lines.append(f"  {'tkr':6s} {'price':>9s} {'maxCorr':>8s} {'with':>6s} {'spread':>7s}")
    for v in passed:
        c = f"{v['corr']:+.2f}" if v["corr"] is not None else "n/a"
        s = f"{v['spread_pct']:.0f}%" if v["spread_pct"] is not None else "n/a"
        lines.append(f"  {v['ticker']:6s} {v['price']:9.2f} {c:>8s} "
                     f"{str(v['corr_with'] or '-'):>6s} {s:>7s}")
    lines += ["", f"REJECTED ({len(rejected)})", ""]
    for v in sorted(rejected, key=lambda x: x["ticker"]):
        lines.append(f"  {v['ticker']:6s} {v['reason']}")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="Screen wheel candidates by tradability + correlation")
    ap.add_argument("--screen", action="store_true", help="run the screen and report")
    ap.add_argument("--promote", action="store_true",
                    help="promote passing names into the dynamic universe (starts the IV clock)")
    ap.add_argument("--allow-closed", action="store_true",
                    help="run outside RTH; spread results will be stale and unreliable")
    args = ap.parse_args()
    if not args.screen:
        ap.error("pass --screen")

    cfg = cfg_module.load()
    result = run_screen(settings=cfg, promote=args.promote,
                        allow_closed=args.allow_closed)
    print(format_report(result, cfg))


if __name__ == "__main__":
    main()
