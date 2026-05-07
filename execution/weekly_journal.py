"""
Weekly Journal — Friday EOD synthesis of the trading week.

Three responsibilities:
  1. Collate Mon–Fri daily journal files into a weekly narrative
  2. Pull NotebookLM research signals from the DB (trading_signals + research_briefs)
  3. Generate a month-to-date trade performance report from decision_logic

Trigger: Friday after 4:15 PM ET, once per ISO week (dedup key: "YYYY-Www").
"""

import json
import os
import sys
from datetime import datetime, date, timezone, timedelta
from pathlib import Path
from typing import Optional

try:
    from zoneinfo import ZoneInfo
    MARKET_TZ = ZoneInfo("America/New_York")
except ImportError:
    MARKET_TZ = timezone.utc

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import settings as cfg_module

PROJECT_ROOT = Path(__file__).parent.parent
JOURNAL_DIR = PROJECT_ROOT / "journal"
WEEKLY_DIR = JOURNAL_DIR / "weekly"


# ---------------------------------------------------------------------------
# Data readers
# ---------------------------------------------------------------------------

def _week_bounds(ref: date) -> tuple[date, date]:
    """Return (Monday, Friday) for the ISO week containing ref."""
    mon = ref - timedelta(days=ref.weekday())
    fri = mon + timedelta(days=4)
    return mon, fri


def read_daily_journals(week_start: date) -> list[dict]:
    """Load Mon–Fri daily journal .md files for the week containing week_start."""
    mon, fri = _week_bounds(week_start)
    entries = []
    for offset in range(5):
        d = mon + timedelta(days=offset)
        path = JOURNAL_DIR / f"{d.isoformat()}.md"
        if path.exists():
            entries.append({"date": d.isoformat(), "body": path.read_text(encoding="utf-8")})
    return entries


def query_research_signals(week_start: date, settings) -> dict:
    """Fetch trading_signals and research_briefs created this week from postgres."""
    out = {"signals": [], "briefs": []}
    if not settings.database.url:
        return out
    try:
        import psycopg2
        import psycopg2.extras
    except ImportError:
        return out

    mon, fri = _week_bounds(week_start)
    # Include through end of Friday
    end_dt = datetime.combine(fri + timedelta(days=1), datetime.min.time())

    try:
        with psycopg2.connect(settings.database.url) as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                # trading_signals — all signals logged this week, highest conviction first
                cur.execute(
                    """
                    SELECT ticker, direction, thesis, conviction, sector, timeframe,
                           suggested_strategy, wheel_eligible, source_type, created_at
                    FROM trading_signals
                    WHERE created_at >= %s AND created_at < %s
                    ORDER BY conviction DESC, created_at DESC
                    LIMIT 50
                    """,
                    (mon, end_dt),
                )
                out["signals"] = [dict(r) for r in cur.fetchall()]

                # research_briefs — latest 5 this week
                cur.execute(
                    """
                    SELECT content, source, signal_count, top_conviction,
                           tickers_mentioned, created_at
                    FROM research_briefs
                    WHERE created_at >= %s AND created_at < %s
                    ORDER BY created_at DESC
                    LIMIT 5
                    """,
                    (mon, end_dt),
                )
                out["briefs"] = [dict(r) for r in cur.fetchall()]
    except Exception as e:
        print(f"[WEEKLY] DB query (signals/briefs) failed: {e}")
    return out


def query_mtd_trades(settings) -> dict:
    """
    Pull decision_logic rows for the current month and compute MTD stats.
    Returns a dict with raw rows + computed stats.
    """
    out = {
        "rows": [],
        "total_trades": 0,
        "wins": 0,
        "losses": 0,
        "win_rate": 0.0,
        "total_pnl": 0.0,
        "by_ticker": {},
        "by_strategy": {},
    }
    if not settings.database.url:
        return out
    try:
        import psycopg2
        import psycopg2.extras
    except ImportError:
        return out

    now = datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    try:
        with psycopg2.connect(settings.database.url) as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT ticker, action, tier, confidence, pnl, status, ts
                    FROM decision_logic
                    WHERE ts >= %s
                    ORDER BY ts ASC
                    """,
                    (month_start,),
                )
                rows = [dict(r) for r in cur.fetchall()]
    except Exception as e:
        print(f"[WEEKLY] DB query (MTD trades) failed: {e}")
        return out

    closed = [r for r in rows if r.get("pnl") is not None]
    total_pnl = sum(r["pnl"] for r in closed)
    wins = [r for r in closed if r["pnl"] > 0]
    losses = [r for r in closed if r["pnl"] <= 0]

    by_ticker: dict = {}
    for r in closed:
        t = r.get("ticker") or "?"
        if t not in by_ticker:
            by_ticker[t] = {"trades": 0, "pnl": 0.0, "wins": 0}
        by_ticker[t]["trades"] += 1
        by_ticker[t]["pnl"] += r["pnl"]
        if r["pnl"] > 0:
            by_ticker[t]["wins"] += 1

    by_strategy: dict = {}
    for r in closed:
        s = r.get("tier") or "?"
        if s not in by_strategy:
            by_strategy[s] = {"trades": 0, "pnl": 0.0, "wins": 0}
        by_strategy[s]["trades"] += 1
        by_strategy[s]["pnl"] += r["pnl"]
        if r["pnl"] > 0:
            by_strategy[s]["wins"] += 1

    out.update({
        "rows": rows,
        "total_trades": len(closed),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": (len(wins) / len(closed) * 100) if closed else 0.0,
        "total_pnl": total_pnl,
        "by_ticker": by_ticker,
        "by_strategy": by_strategy,
    })
    return out


# ---------------------------------------------------------------------------
# MTD report builder (deterministic — no Claude needed)
# ---------------------------------------------------------------------------

def build_mtd_report(mtd: dict, month_label: str) -> str:
    lines = [
        f"## Month-to-Date Performance — {month_label}",
        "",
        f"**Closed trades:** {mtd['total_trades']}  |  "
        f"**Wins:** {mtd['wins']}  |  **Losses:** {mtd['losses']}  |  "
        f"**Win rate:** {mtd['win_rate']:.1f}%  |  "
        f"**Total P&L:** ${mtd['total_pnl']:+,.2f}",
        "",
    ]

    if mtd["by_ticker"]:
        lines += [
            "### By Ticker",
            "",
            "| Ticker | Trades | Wins | P&L |",
            "|--------|--------|------|-----|",
        ]
        for ticker, s in sorted(mtd["by_ticker"].items(), key=lambda x: -x[1]["pnl"]):
            wr = f"{s['wins']}/{s['trades']}"
            lines.append(f"| {ticker} | {s['trades']} | {wr} | ${s['pnl']:+,.2f} |")
        lines.append("")

    if mtd["by_strategy"]:
        lines += [
            "### By Strategy",
            "",
            "| Strategy | Trades | Wins | P&L |",
            "|----------|--------|------|-----|",
        ]
        for strat, s in sorted(mtd["by_strategy"].items(), key=lambda x: -x[1]["pnl"]):
            wr = f"{s['wins']}/{s['trades']}"
            lines.append(f"| {strat} | {s['trades']} | {wr} | ${s['pnl']:+,.2f} |")
        lines.append("")

    if mtd["total_trades"] == 0:
        lines.append("_No closed trades logged this month yet._")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Claude synthesis
# ---------------------------------------------------------------------------

WEEKLY_SYSTEM_PROMPT = """You are the senior analyst for an autonomous options/equity trading system.
Your job is to write a weekly synthesis that a trader reads Friday evening to plan the following week.

Style:
- Specific, data-driven, no padding. Reference actual tickers and signals.
- Distinguish what the system did vs what the market did vs what external signals said.
- The NotebookLM research signals should be cross-referenced against actual trades — did we act on them? Should we?
- "Focus for Next Week" must be ACTIONABLE — specific tickers, strategies, thresholds.
- If data is thin (e.g. no research signals this week), say so clearly and reason from what's available.

Output format (plain markdown, exactly these sections):

## Weekly Summary
<3-5 sentences: net direction, dominant regime, headline driver of the week>

## What the System Did
<bulleted — which strategies fired most, what was executed vs skipped and why>

## Signal Intelligence
<bulleted by source: Policy / Whale / Research (NotebookLM). Include conviction scores and tickers>

## What Worked / What Didn't
<two sub-bullets per row: Worked → evidence; Didn't → evidence. Be honest about failures.>

## NotebookLM Insights
<synthesize the research_briefs content — what is the AI research saying about market conditions?
 Cross-reference: are these signals consistent with what the wheel strategy is doing?>

## Focus for Next Week
<bulleted — specific tickers, strategy adjustments, thresholds to watch. Reference config params by name>
"""


def _synthesize_weekly(
    journals: list[dict],
    research: dict,
    week_label: str,
    settings,
) -> Optional[str]:
    api_key = getattr(getattr(settings, "anthropic", None), "api_key", None) or os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return None
    try:
        import anthropic
    except ImportError:
        return None

    def _compact(items, limit=20):
        return json.dumps(items[:limit], default=str, indent=1)

    briefs_text = ""
    for b in research.get("briefs", []):
        ts = str(b.get("created_at", ""))[:10]
        briefs_text += f"\n[{ts}] {b.get('content', '')[:1500]}\n"

    user_input = f"""WEEK: {week_label}

DAILY_JOURNALS ({len(journals)} days):
{chr(10).join(f"--- {j['date']} ---{chr(10)}{j['body'][:2000]}" for j in journals)}

NOTEBOOKLM_RESEARCH_SIGNALS ({len(research.get('signals', []))} signals this week):
{_compact(research.get('signals', []))}

NOTEBOOKLM_RESEARCH_BRIEFS ({len(research.get('briefs', []))} briefs this week):
{briefs_text[:3000] or '(none logged this week)'}
"""

    try:
        client = anthropic.Anthropic(api_key=api_key)
        msg = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2500,
            system=[{
                "type": "text",
                "text": WEEKLY_SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }],
            messages=[{"role": "user", "content": user_input}],
        )
        return msg.content[0].text.strip()
    except Exception as e:
        print(f"[WEEKLY] Claude synthesis failed: {e}")
        return None


def _template_fallback_weekly(journals: list, research: dict, week_label: str) -> str:
    signals = research.get("signals", [])
    briefs = research.get("briefs", [])
    lines = [
        "## Weekly Summary",
        f"Auto-generated fallback (no Claude key). Week {week_label}. "
        f"{len(journals)} daily journal(s) available. "
        f"{len(signals)} research signal(s); {len(briefs)} research brief(s).",
        "",
        "## What the System Did",
    ]
    for j in journals:
        lines.append(f"- {j['date']}: journal available (see {j['date']}.md)")
    if not journals:
        lines.append("- (no daily journals found for this week)")

    lines += ["", "## Signal Intelligence"]
    for s in signals[:10]:
        lines.append(
            f"- [{s.get('source_type','?')}] {s.get('ticker','?')} — "
            f"{s.get('direction','?')} (conviction {s.get('conviction','?')}) — {s.get('thesis','')[:120]}"
        )
    if not signals:
        lines.append("- (no research signals this week)")

    lines += [
        "",
        "## NotebookLM Insights",
        f"- {len(briefs)} brief(s) archived this week.",
        "",
        "## Focus for Next Week",
        "- (Claude synthesis unavailable — set ANTHROPIC_API_KEY for actionable forward guidance)",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def weekly_wrapup(
    ref_date: Optional[date] = None,
    alpaca_client=None,
    regime: str = "NEUTRAL",
    notifier=None,
    settings=None,
) -> Path:
    """
    Generate journal/weekly/YYYY-Www.md for the week containing ref_date.
    Emails the report via notifier. Returns the path written.
    """
    cfg = settings or cfg_module.load()
    ref = ref_date or datetime.now(MARKET_TZ).date()

    mon, fri = _week_bounds(ref)
    week_label = mon.strftime("%Y-W%V")  # ISO week e.g. "2026-W19"
    month_label = ref.strftime("%B %Y")

    print(f"[WEEKLY] Generating wrap-up for {week_label} ({mon} → {fri})")

    journals = read_daily_journals(mon)
    research = query_research_signals(mon, cfg)
    mtd = query_mtd_trades(cfg)

    print(
        f"[WEEKLY] Found {len(journals)} daily journals, "
        f"{len(research['signals'])} signals, "
        f"{len(research['briefs'])} briefs, "
        f"{mtd['total_trades']} MTD closed trades"
    )

    # Synthesize weekly narrative
    body = _synthesize_weekly(journals, research, week_label, cfg)
    if body is None:
        body = _template_fallback_weekly(journals, research, week_label)

    # Build MTD report (always deterministic)
    mtd_section = build_mtd_report(mtd, month_label)

    # Assemble full document
    equity = 0.0
    mode = "paper" if cfg.guardrails.paper_mode else "live"
    if alpaca_client:
        try:
            account = alpaca_client.get_account()
            equity = float(account.get("equity", 0))
        except Exception:
            pass

    header = (
        f"# Weekly Trading Journal — {week_label}\n\n"
        f"**Period:** {mon.isoformat()} → {fri.isoformat()}  |  "
        f"**Regime:** {regime}  |  **Mode:** {mode}  |  **Equity:** ${equity:,.2f}\n\n"
        f"**Daily journals:** {len(journals)}/5  |  "
        f"**Research signals:** {len(research['signals'])}  |  "
        f"**NotebookLM briefs:** {len(research['briefs'])}\n\n"
        "---\n\n"
    )
    divider = "\n\n---\n\n"
    footer = (
        f"\n\n---\n"
        f"*Generated {datetime.now(timezone.utc).isoformat()} by execution/weekly_journal.py*\n"
    )
    full = header + body + divider + mtd_section + footer

    WEEKLY_DIR.mkdir(parents=True, exist_ok=True)
    path = WEEKLY_DIR / f"{week_label}.md"
    path.write_text(full, encoding="utf-8")
    print(f"[WEEKLY] wrote {path}")

    if notifier:
        try:
            notifier.send(
                subject=f"[WEEKLY WRAP-UP] Trading Journal — {week_label}",
                body=full,
            )
            print("[WEEKLY] wrap-up emailed")
        except Exception as e:
            print(f"[WEEKLY] email failed: {e}")

    return path
