"""
Per-module P&L attribution + conviction calibration.

Modules have to earn their keep: if the position_manager or IPO scanner is
net-negative over a quarter, it should be turned off — but that's only decidable
if per-module P&L is measured. Likewise the conviction scores logged with every
decision are decoration unless they're checked against realized outcomes: if
0.90-conviction trades win at the same rate as 0.70 ones, the number must not
gate sizing.

Reads decision_logic (rows with a realized pnl) and renders a markdown section
that the weekly wrap-up embeds.

Usage (standalone):
    python execution/attribution.py [--days 90]
"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import settings as cfg_module

CONVICTION_BUCKETS = [(0.0, 0.7), (0.7, 0.85), (0.85, 1.01)]


def _query_closed_decisions(days: int, settings) -> list:
    if not settings.database.url:
        return []
    try:
        import psycopg2
        import psycopg2.extras
    except ImportError:
        return []
    since = datetime.now(timezone.utc) - timedelta(days=days)
    try:
        with psycopg2.connect(settings.database.url) as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT ticker, action, tier, confidence, pnl, ts
                    FROM decision_logic
                    WHERE pnl IS NOT NULL AND ts >= %s
                    ORDER BY ts ASC
                    """,
                    (since,),
                )
                return [dict(r) for r in cur.fetchall()]
    except Exception as e:
        print(f"[ATTRIB] DB query failed: {e}")
        return []


def module_attribution(rows: list) -> dict:
    """tier → {trades, wins, pnl, profit_factor}"""
    out: dict = {}
    for r in rows:
        tier = r.get("tier") or "?"
        s = out.setdefault(tier, {"trades": 0, "wins": 0, "pnl": 0.0,
                                  "gross_win": 0.0, "gross_loss": 0.0})
        pnl = float(r["pnl"])
        s["trades"] += 1
        s["pnl"] += pnl
        if pnl > 0:
            s["wins"] += 1
            s["gross_win"] += pnl
        else:
            s["gross_loss"] += -pnl
    for s in out.values():
        s["profit_factor"] = (s["gross_win"] / s["gross_loss"]) if s["gross_loss"] > 0 else float("inf")
    return out


def conviction_calibration(rows: list) -> list:
    """[(bucket_label, trades, win_rate, avg_pnl)] — is conviction predictive at all?"""
    out = []
    for lo, hi in CONVICTION_BUCKETS:
        bucket = [r for r in rows if r.get("confidence") is not None and lo <= float(r["confidence"]) < hi]
        if not bucket:
            out.append((f"{lo:.2f}-{min(hi, 1.0):.2f}", 0, None, None))
            continue
        wins = sum(1 for r in bucket if float(r["pnl"]) > 0)
        avg_pnl = sum(float(r["pnl"]) for r in bucket) / len(bucket)
        out.append((f"{lo:.2f}-{min(hi, 1.0):.2f}", len(bucket), wins / len(bucket) * 100, avg_pnl))
    return out


def build_report(days: int = 90, settings=None) -> str:
    cfg = settings or cfg_module.load()
    rows = _query_closed_decisions(days, cfg)

    lines = [f"## Module Attribution & Conviction Calibration (last {days} days)", ""]
    if not rows:
        lines.append("_No closed (pnl-bearing) decisions in the window — nothing to attribute yet._")
        return "\n".join(lines)

    lines += [
        "### P&L by Module — modules must earn their keep",
        "",
        "| Module | Trades | Wins | P&L | Profit factor | Verdict |",
        "|--------|--------|------|-----|---------------|---------|",
    ]
    for tier, s in sorted(module_attribution(rows).items(), key=lambda x: -x[1]["pnl"]):
        pf = "inf" if s["profit_factor"] == float("inf") else f"{s['profit_factor']:.2f}"
        verdict = "OK" if s["pnl"] >= 0 else "NET-NEGATIVE — candidate for shutdown"
        lines.append(
            f"| {tier} | {s['trades']} | {s['wins']}/{s['trades']} | "
            f"${s['pnl']:+,.2f} | {pf} | {verdict} |"
        )

    lines += [
        "",
        "### Conviction Calibration — is the score decoration?",
        "",
        "| Conviction bucket | Trades | Win rate | Avg P&L |",
        "|-------------------|--------|----------|---------|",
    ]
    cal = conviction_calibration(rows)
    for label, n, wr, avg in cal:
        wr_s = f"{wr:.0f}%" if wr is not None else "-"
        avg_s = f"${avg:+,.2f}" if avg is not None else "-"
        lines.append(f"| {label} | {n} | {wr_s} | {avg_s} |")

    populated = [(label, wr) for label, n, wr, _ in cal if n >= 5 and wr is not None]
    if len(populated) >= 2 and populated[-1][1] <= populated[0][1]:
        lines += [
            "",
            "**Flag:** high-conviction trades are NOT outperforming low-conviction ones — "
            "the conviction score is currently decoration and must not gate sizing.",
        ]

    return "\n".join(lines)


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--days", type=int, default=90)
    args = p.parse_args()
    print(build_report(days=args.days))
