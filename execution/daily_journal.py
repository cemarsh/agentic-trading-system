"""
Daily Journal — intraday insight dump + end-of-day synthesis.

Two responsibilities:
  1. log_insight(...)       — append a structured insight to today's .jsonl dump
  2. wrap_up(...)            — synthesize the day's dump + DB rows + caches into
                               journal/YYYY-MM-DD.md and email the wrap-up

CLI:
    python execution/daily_journal.py --log "..." --source wheel --category decision
    python execution/daily_journal.py --wrap-up
    python execution/daily_journal.py --wrap-up --date 2026-04-14
    python execution/daily_journal.py --show
"""

import argparse
import json
import os
import sys
from datetime import datetime, date, timezone
from pathlib import Path
from typing import Optional

try:
    from zoneinfo import ZoneInfo
    MARKET_TZ = ZoneInfo("America/New_York")
except ImportError:  # py <3.9
    MARKET_TZ = timezone.utc

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import settings as cfg_module

PROJECT_ROOT = Path(__file__).parent.parent
INSIGHTS_DIR = PROJECT_ROOT / "logs" / "insights"
JOURNAL_DIR = PROJECT_ROOT / "journal"
POLICY_CACHE_PATH = PROJECT_ROOT / "logs" / "policy_signal_cache.json"
MEM_PATH = PROJECT_ROOT / "MEM.md"

VALID_SOURCES = {
    "wheel", "whale_watch", "policy", "regime", "hedge",
    "protection", "advisor", "notebooklm", "manual", "system",
}
VALID_CATEGORIES = {"signal", "decision", "observation", "error", "learning"}


def _trading_day() -> date:
    """Return today's date in market timezone — the trading day, not UTC."""
    return datetime.now(MARKET_TZ).date()


# ---------------------------------------------------------------------------
# Intraday: append an insight
# ---------------------------------------------------------------------------

def log_insight(
    source: str,
    category: str,
    insight: str,
    metadata: Optional[dict] = None,
    when: Optional[datetime] = None,
) -> None:
    """
    Append a structured insight to today's .jsonl dump.
    Safe to call from any module — never raises on disk issues, only prints.
    """
    if source not in VALID_SOURCES:
        print(f"[JOURNAL] warn: unknown source '{source}' (allowed: {sorted(VALID_SOURCES)})")
    if category not in VALID_CATEGORIES:
        print(f"[JOURNAL] warn: unknown category '{category}' (allowed: {sorted(VALID_CATEGORIES)})")

    ts = (when or datetime.now(timezone.utc)).isoformat()
    record = {
        "ts": ts,
        "source": source,
        "category": category,
        "insight": insight,
        "metadata": metadata or {},
    }
    try:
        INSIGHTS_DIR.mkdir(parents=True, exist_ok=True)
        path = INSIGHTS_DIR / f"{_trading_day().isoformat()}.jsonl"
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, default=str) + "\n")
    except Exception as e:
        print(f"[JOURNAL] failed to write insight: {e}")


# ---------------------------------------------------------------------------
# Readers
# ---------------------------------------------------------------------------

def read_insights(target_date: date) -> list:
    path = INSIGHTS_DIR / f"{target_date.isoformat()}.jsonl"
    if not path.exists():
        return []
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def read_policy_cache_for_day(target_date: date) -> list:
    if not POLICY_CACHE_PATH.exists():
        return []
    try:
        with open(POLICY_CACHE_PATH, encoding="utf-8") as f:
            cache = json.load(f)
    except Exception:
        return []
    # Cache shape varies; best-effort filter by date prefix if entries carry a ts/date
    day_str = target_date.isoformat()
    if isinstance(cache, dict):
        return [
            {"key": k, **(v if isinstance(v, dict) else {"value": v})}
            for k, v in cache.items()
            if isinstance(v, dict) and day_str in json.dumps(v, default=str)
        ]
    if isinstance(cache, list):
        return [item for item in cache if day_str in json.dumps(item, default=str)]
    return []


def query_db_for_day(target_date: date, settings) -> dict:
    """Fetch today's decision_logic, strategy_analysis, strategy_lessons rows."""
    out = {"decisions": [], "analyses": [], "lessons": []}
    if not settings.database.url:
        return out
    try:
        import psycopg2
        import psycopg2.extras
    except ImportError:
        return out
    try:
        with psycopg2.connect(settings.database.url) as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                for table, key in [
                    ("decision_logic", "decisions"),
                    ("strategy_analysis", "analyses"),
                    ("strategy_lessons", "lessons"),
                ]:
                    cur.execute(
                        f"SELECT * FROM {table} WHERE ts::date = %s ORDER BY ts ASC",
                        (target_date,),
                    )
                    out[key] = [dict(r) for r in cur.fetchall()]
    except Exception as e:
        print(f"[JOURNAL] DB query failed: {e}")
    return out


# ---------------------------------------------------------------------------
# Synthesis
# ---------------------------------------------------------------------------

SYNTHESIS_PROMPT = """You are the desk journalist for an autonomous options/equity trading system.
Your job is to write a single, concise, information-dense daily wrap-up for the trader to read at end of day and again tomorrow morning before the bell.

Style:
- Direct, specific, no filler. Reference actual tickers and numbers.
- Distinguish observation from inference. Flag anything speculative.
- "What Changes Tomorrow" must be ACTIONABLE and SPECIFIC — not generic advice.
- If insights are thin, say so honestly rather than padding.

Output format (plain markdown, exactly these sections, in this order):

## Daily Summary
<2-4 sentences: what happened, net direction, headline driver>

## Strategies Pursued
<bulleted — which tiers fired, what did they do>

## Signals Observed
<bulleted by type: Policy / Whale / Research / Other. Include times and tickers>

## Decisions & Trades
<markdown table: Time | Ticker | Action | Tier | Conviction | Result>

## Insights & Lessons
<bulleted — the synthesized learning from raw insights + post-trade lessons. Label each as Observation/Confirmation/Challenge/Pattern>

## What Changes Tomorrow
<bulleted — specific, actionable adjustments. Reference config params or tickers by name>
"""


def _build_synthesis_input(
    target_date: date,
    insights: list,
    db_data: dict,
    policy_today: list,
    regime: str,
    equity: float,
    realized_pnl: float,
    unrealized_pnl: float,
    positions: list,
    mode: str,
) -> str:
    def _compact(items, limit=40):
        return json.dumps(items[:limit], default=str, indent=1)

    return f"""DATE: {target_date.isoformat()}
MODE: {mode}
REGIME: {regime}
EQUITY: ${equity:,.2f}
REALIZED_PNL: ${realized_pnl:+,.2f}
UNREALIZED_PNL: ${unrealized_pnl:+,.2f}
OPEN_POSITIONS: {len(positions)}

POSITIONS:
{_compact(positions)}

RAW_INSIGHTS ({len(insights)} entries):
{_compact(insights, limit=200)}

DECISIONS_TODAY ({len(db_data.get('decisions', []))} rows from decision_logic):
{_compact(db_data.get('decisions', []))}

PRE_TRADE_ANALYSES_TODAY ({len(db_data.get('analyses', []))} rows from strategy_analysis):
{_compact(db_data.get('analyses', []))}

POST_TRADE_LESSONS_TODAY ({len(db_data.get('lessons', []))} rows from strategy_lessons):
{_compact(db_data.get('lessons', []))}

POLICY_SIGNALS_TODAY ({len(policy_today)} entries):
{_compact(policy_today)}
"""


def _synthesize_with_claude(prompt_input: str, settings) -> Optional[str]:
    api_key = settings.anthropic.api_key or os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return None
    try:
        import anthropic
    except ImportError:
        return None
    try:
        client = anthropic.Anthropic(api_key=api_key)
        msg = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2000,
            system=[{
                "type": "text",
                "text": SYNTHESIS_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }],
            messages=[{"role": "user", "content": prompt_input}],
        )
        return msg.content[0].text.strip()
    except Exception as e:
        print(f"[JOURNAL] Claude synthesis failed: {e}")
        return None


def _template_fallback(
    target_date: date,
    insights: list,
    db_data: dict,
    policy_today: list,
    regime: str,
    equity: float,
    realized_pnl: float,
    unrealized_pnl: float,
    positions: list,
) -> str:
    """Deterministic fallback when Claude is unavailable."""
    lines = [
        "## Daily Summary",
        f"Auto-generated fallback (no Claude key). Regime {regime}. "
        f"Equity ${equity:,.2f}; realized {realized_pnl:+,.2f}, unrealized {unrealized_pnl:+,.2f}. "
        f"{len(positions)} open position(s); {len(insights)} insight(s) logged; "
        f"{len(db_data.get('decisions', []))} decision(s); {len(policy_today)} policy signal(s).",
        "",
        "## Strategies Pursued",
    ]
    tiers = sorted({d.get("tier") for d in db_data.get("decisions", []) if d.get("tier")})
    if tiers:
        for t in tiers:
            n = sum(1 for d in db_data.get("decisions", []) if d.get("tier") == t)
            lines.append(f"- {t}: {n} decision(s)")
    else:
        lines.append("- (no tiered decisions logged today)")

    lines += ["", "## Signals Observed"]
    whale = [i for i in insights if i.get("source") == "whale_watch"]
    policy_ins = [i for i in insights if i.get("source") == "policy"] + policy_today
    research = [i for i in insights if i.get("source") == "notebooklm"]
    if policy_ins:
        lines.append(f"- Policy: {len(policy_ins)} signal(s)")
        for p in policy_ins[:10]:
            lines.append(f"  - {p.get('insight') or p.get('key') or str(p)[:120]}")
    if whale:
        lines.append(f"- Whale: {len(whale)} signal(s)")
        for w in whale[:10]:
            lines.append(f"  - {w.get('insight', '')}")
    if research:
        lines.append(f"- Research: {len(research)} signal(s)")
    if not (policy_ins or whale or research):
        lines.append("- (no signals observed today)")

    lines += ["", "## Decisions & Trades"]
    if db_data.get("decisions"):
        lines.append("| Time | Ticker | Action | Tier | Conviction | Status |")
        lines.append("|------|--------|--------|------|-----------|--------|")
        for d in db_data["decisions"]:
            ts = str(d.get("ts", ""))[11:16]
            lines.append(
                f"| {ts} | {d.get('ticker', '')} | {d.get('action', '')} | "
                f"{d.get('tier', '')} | {d.get('confidence', '') or ''} | {d.get('status', '')} |"
            )
    else:
        lines.append("_(no decisions logged)_")

    lines += ["", "## Insights & Lessons"]
    if insights or db_data.get("lessons"):
        for i in insights:
            cat = i.get("category", "obs").capitalize()
            lines.append(f"- **{cat}** ({i.get('source', '?')}): {i.get('insight', '')}")
        for l in db_data.get("lessons", []):
            lines.append(f"- **Lesson** ({l.get('ticker', '?')}): {l.get('lesson', '')}")
    else:
        lines.append("_(none recorded — consider a manual log tomorrow)_")

    lines += [
        "",
        "## What Changes Tomorrow",
        "- (Claude synthesis unavailable — set ANTHROPIC_API_KEY for actionable forward-looking carryforward)",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main wrap-up
# ---------------------------------------------------------------------------

def wrap_up(
    target_date: Optional[date] = None,
    alpaca_client=None,
    regime: str = "NEUTRAL",
    notifier=None,
    settings=None,
) -> Path:
    """
    Generate journal/YYYY-MM-DD.md for target_date (default: today).
    Emails the wrap-up via notifier if provided.
    Returns the path to the written journal file.
    """
    cfg = settings or cfg_module.load()
    target_date = target_date or _trading_day()

    insights = read_insights(target_date)
    db_data = query_db_for_day(target_date, cfg)
    policy_today = read_policy_cache_for_day(target_date)

    equity = 0.0
    realized_pnl = 0.0
    unrealized_pnl = 0.0
    positions = []
    mode = "paper" if cfg.guardrails.paper_mode else "live"

    if alpaca_client:
        try:
            account = alpaca_client.get_account()
            equity = float(account.get("equity", 0))
            # Resolves to the day's equity change; Alpaca's 'last_equity' is prior-day close.
            realized_pnl = float(account.get("equity", 0)) - float(account.get("last_equity", 0))
            positions = alpaca_client.get_positions() or []
            unrealized_pnl = sum(float(p.get("unrealized_pl", 0)) for p in positions)
        except Exception as e:
            print(f"[JOURNAL] Alpaca snapshot failed: {e}")

    synth_input = _build_synthesis_input(
        target_date=target_date,
        insights=insights,
        db_data=db_data,
        policy_today=policy_today,
        regime=regime,
        equity=equity,
        realized_pnl=realized_pnl,
        unrealized_pnl=unrealized_pnl,
        positions=positions,
        mode=mode,
    )

    body = _synthesize_with_claude(synth_input, cfg)
    if body is None:
        body = _template_fallback(
            target_date, insights, db_data, policy_today, regime,
            equity, realized_pnl, unrealized_pnl, positions,
        )

    header = (
        f"# Trading Journal — {target_date.isoformat()}\n\n"
        f"**Regime:** {regime}  |  **Mode:** {mode}  |  "
        f"**Equity:** ${equity:,.2f}  |  **Realized:** ${realized_pnl:+,.2f}  |  "
        f"**Unrealized:** ${unrealized_pnl:+,.2f}\n\n"
        f"**Insights logged:** {len(insights)}  |  "
        f"**Decisions:** {len(db_data.get('decisions', []))}  |  "
        f"**Pre-trade analyses:** {len(db_data.get('analyses', []))}  |  "
        f"**Post-trade lessons:** {len(db_data.get('lessons', []))}  |  "
        f"**Policy signals:** {len(policy_today)}\n\n"
        "---\n\n"
    )
    footer = (
        f"\n\n---\n"
        f"*Generated {datetime.now(timezone.utc).isoformat()} by execution/daily_journal.py*\n"
    )
    full = header + body + footer

    JOURNAL_DIR.mkdir(parents=True, exist_ok=True)
    path = JOURNAL_DIR / f"{target_date.isoformat()}.md"
    path.write_text(full, encoding="utf-8")
    print(f"[JOURNAL] wrote {path}")

    if notifier:
        try:
            notifier.daily_wrap_up(target_date.isoformat(), full)
            print("[JOURNAL] wrap-up emailed")
        except Exception as e:
            print(f"[JOURNAL] email failed: {e}")

    _append_mem_summary(target_date, body)
    return path


def _append_mem_summary(target_date: date, body: str):
    """Append a one-line summary to MEM.md's Learnings section."""
    if not MEM_PATH.exists():
        return
    # Extract the first bullet under "What Changes Tomorrow" if present
    summary = ""
    in_section = False
    for line in body.splitlines():
        if line.strip().startswith("## What Changes Tomorrow"):
            in_section = True
            continue
        if in_section and line.strip().startswith("- "):
            summary = line.strip()[2:].strip()
            break
    if not summary:
        summary = "(wrap-up generated — see journal/)"
    try:
        content = MEM_PATH.read_text(encoding="utf-8")
        marker = "## Learnings & Annealings"
        if marker in content:
            insertion = f"\n- **{target_date.isoformat()}**: {summary}"
            # Insert directly after the marker line
            idx = content.index(marker) + len(marker)
            # Move past the single newline after the marker
            nl = content.find("\n", idx)
            if nl != -1:
                content = content[: nl + 1] + insertion + content[nl:]
            MEM_PATH.write_text(content, encoding="utf-8")
    except Exception as e:
        print(f"[JOURNAL] MEM.md update failed: {e}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Daily Journal — dump & wrap-up")
    parser.add_argument("--log", type=str, help="Append an insight to today's dump")
    parser.add_argument("--source", type=str, default="manual", help="Insight source")
    parser.add_argument("--category", type=str, default="observation", help="Insight category")
    parser.add_argument("--wrap-up", action="store_true", help="Generate today's wrap-up")
    parser.add_argument("--date", type=str, help="YYYY-MM-DD (for --wrap-up of a past day)")
    parser.add_argument("--show", action="store_true", help="Print today's raw insight dump")
    args = parser.parse_args()

    if args.log:
        log_insight(source=args.source, category=args.category, insight=args.log)
        print(f"[JOURNAL] logged: [{args.source}/{args.category}] {args.log}")
        return

    if args.show:
        for i in read_insights(_trading_day()):
            print(json.dumps(i, default=str))
        return

    if args.wrap_up:
        target = date.fromisoformat(args.date) if args.date else _trading_day()
        cfg = cfg_module.load()

        alpaca = None
        try:
            from execution.alpaca_client import AlpacaClient
            alpaca = AlpacaClient(settings=cfg)
        except Exception as e:
            print(f"[JOURNAL] Alpaca unavailable: {e}")

        regime = "NEUTRAL"
        try:
            from execution.regime_detector import RegimeDetector
            if alpaca:
                regime = RegimeDetector(settings=cfg, alpaca_client=alpaca).detect()
        except Exception as e:
            print(f"[JOURNAL] regime detect failed: {e}")

        notifier = None
        if cfg.notifications.resend_key:
            try:
                from execution.notifier import Notifier
                notifier = Notifier(settings=cfg)
            except Exception as e:
                print(f"[JOURNAL] notifier unavailable: {e}")

        wrap_up(target_date=target, alpaca_client=alpaca, regime=regime, notifier=notifier, settings=cfg)
        return

    parser.print_help()


if __name__ == "__main__":
    main()
