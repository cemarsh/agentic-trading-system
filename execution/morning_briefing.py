"""
Morning Briefing — Pre-market daily game plan.

Runs at 9:00–9:29 AM ET, Monday–Friday. Reads overnight signals, current
positions, and DB trading_signals to produce a Claude-synthesized game plan
for the trading day. Sends via email + Slack.

CLI:
    python execution/morning_briefing.py [--date YYYY-MM-DD]
"""

import argparse
import json
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

try:
    from zoneinfo import ZoneInfo
    MARKET_TZ = ZoneInfo("America/New_York")
except ImportError:
    MARKET_TZ = timezone.utc

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import settings as cfg_module
from execution.daily_journal import log_insight, INSIGHTS_DIR, POLICY_CACHE_PATH

PROJECT_ROOT = Path(__file__).parent.parent

BRIEFING_PROMPT = """You are a pre-market trading desk analyst for an autonomous options/equity trading system.
Your job is to synthesize overnight signals into a concise, actionable game plan for today's session.

You will receive:
- Today's overnight insight log
- Recent policy signals (tariffs, Fed commentary, executive orders)
- Current open positions (so you can avoid doubling up)
- Research signals from the trading_signals database (conviction-ranked)

Your output MUST follow this exact format (plain text, no markdown headers):

MORNING BRIEFING — {date}
=========================

TOP OPPORTUNITIES (2-3 max):
1. TICKER | STRATEGY | ENTRY TRIGGER | CONVICTION (1-10) | WHY NOW
2. TICKER | STRATEGY | ENTRY TRIGGER | CONVICTION (1-10) | WHY NOW
3. TICKER | STRATEGY | ENTRY TRIGGER | CONVICTION (1-10) | WHY NOW

RISKS TO WATCH:
- <key risk 1>
- <key risk 2 if any>

POSITIONS TO MANAGE:
- <any existing positions approaching 50% profit or 21 DTE that need attention today>
- (none) if nothing pressing

REGIME NOTE:
<1 sentence on macro backdrop and whether to be aggressive or defensive today>

Rules:
- Strategy must be one of: CSP, CC, WHEEL, LONG_CALL, LONG_PUT, SPREAD, SKIP
- Entry trigger must be specific — a price level, technical confirmation, or news catalyst
- If signals are thin or contradictory, say SKIP and explain briefly
- Never recommend a position that is already open (check CURRENT_POSITIONS)
- Conviction 1-10 where 7+ = act immediately at open, 5-6 = wait for confirmation, <5 = skip
"""


def _read_insights_for_date(target_date: date) -> list:
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


def _read_policy_cache() -> list:
    if not POLICY_CACHE_PATH.exists():
        return []
    try:
        with open(POLICY_CACHE_PATH, encoding="utf-8") as f:
            cache = json.load(f)
    except Exception:
        return []
    if isinstance(cache, list):
        return cache[:20]
    if isinstance(cache, dict):
        return [{"key": k, **(v if isinstance(v, dict) else {"value": v})} for k, v in list(cache.items())[:20]]
    return []


def _query_trading_signals(settings) -> list:
    """Fetch top trading_signals rows from DB, ordered by conviction DESC."""
    if not settings.database.url:
        return []
    try:
        import psycopg2
        import psycopg2.extras
    except ImportError:
        return []
    try:
        with psycopg2.connect(settings.database.url) as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT ticker, direction, thesis, conviction, suggested_strategy,
                           timeframe, catalysts, risk_factors, wheel_eligible
                    FROM trading_signals
                    WHERE status = 'active'
                    ORDER BY conviction DESC
                    LIMIT 15
                    """
                )
                return [dict(r) for r in cur.fetchall()]
    except Exception as e:
        print(f"[BRIEFING] DB query failed: {e}")
        return []


def _build_prompt(
    target_date: date,
    insights: list,
    policy_signals: list,
    positions: list,
    db_signals: list,
) -> str:
    def _compact(items, limit=30):
        return json.dumps(items[:limit], default=str, indent=1)

    # Summarize open positions concisely
    open_pos_summary = []
    for p in positions:
        sym = p.get("symbol", "")
        qty = p.get("qty", "?")
        unpl = float(p.get("unrealized_pl", 0))
        avg_entry = float(p.get("avg_entry_price", 0))
        open_pos_summary.append(
            f"{sym}  qty={qty}  avg_entry={avg_entry:.4f}  unrealized_pl={unpl:+.2f}"
        )

    return f"""DATE: {target_date.isoformat()}
DAY_OF_WEEK: {target_date.strftime("%A")}

CURRENT_POSITIONS ({len(positions)} open):
{chr(10).join(open_pos_summary) if open_pos_summary else "(none)"}

OVERNIGHT_INSIGHTS ({len(insights)} entries):
{_compact(insights)}

RECENT_POLICY_SIGNALS ({len(policy_signals)} entries):
{_compact(policy_signals)}

DB_TRADING_SIGNALS ({len(db_signals)} signals, conviction-ranked):
{_compact(db_signals)}
"""


def _synthesize_with_claude(prompt_body: str, target_date: date, settings) -> Optional[str]:
    api_key = settings.anthropic.api_key or os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return None
    try:
        import anthropic
    except ImportError:
        return None
    try:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1500,
            system=BRIEFING_PROMPT.replace("{date}", target_date.isoformat()),
            messages=[{"role": "user", "content": prompt_body}],
        )
        return response.content[0].text.strip()
    except Exception as e:
        print(f"[BRIEFING] Claude synthesis failed: {e}")
        return None


def _fallback_briefing(
    target_date: date,
    insights: list,
    policy_signals: list,
    db_signals: list,
    positions: list,
) -> str:
    """Template-based fallback when Claude is unavailable."""
    lines = [
        f"MORNING BRIEFING — {target_date.isoformat()} (template fallback — no Claude key)",
        "=" * 60,
        "",
        "TOP OPPORTUNITIES (from DB signals, unfiltered):",
    ]
    if db_signals:
        for i, sig in enumerate(db_signals[:3], 1):
            ticker = sig.get("ticker", "?")
            direction = sig.get("direction", "?")
            conviction = sig.get("conviction", "?")
            thesis = (sig.get("thesis") or "")[:120]
            strategy = sig.get("suggested_strategy") or "WHEEL"
            lines.append(
                f"{i}. {ticker} | {strategy} | {direction.upper()} | "
                f"CONVICTION {conviction} | {thesis}"
            )
    else:
        lines.append("1. (no DB signals available — run NotebookLM ingestion)")

    lines += [
        "",
        "RISKS TO WATCH:",
    ]
    policy_tickers = [p.get("key") or p.get("ticker") for p in policy_signals[:3] if p]
    if policy_tickers:
        lines.append(f"- Policy signals active: {', '.join(str(t) for t in policy_tickers if t)}")
    else:
        lines.append("- No policy signals overnight")

    lines += [
        "",
        "POSITIONS TO MANAGE:",
    ]
    if positions:
        for p in positions:
            lines.append(f"- {p.get('symbol', '?')}  unrealized={float(p.get('unrealized_pl', 0)):+.2f}")
    else:
        lines.append("- (none)")

    lines += [
        "",
        "REGIME NOTE:",
        f"(Claude unavailable — set ANTHROPIC_API_KEY for synthesized analysis. "
        f"{len(insights)} overnight insights, {len(policy_signals)} policy signals.)",
    ]
    return "\n".join(lines)


# -----------------------------------------------------------------------
# Public class
# -----------------------------------------------------------------------

class MorningBriefing:
    """
    Synthesizes overnight signals into a pre-market game plan.
    """

    def __init__(self, settings=None, alpaca_client=None, db_logger=None, notifier=None):
        self.cfg = settings or cfg_module.load()
        self._alpaca = alpaca_client
        self._db = db_logger
        self._notifier = notifier

    def generate(self, target_date: Optional[date] = None) -> str:
        """
        Build and send the morning briefing.

        Args:
            target_date: Date to build the briefing for (default: today in ET).

        Returns:
            The briefing text (also sent via notifier).
        """
        if target_date is None:
            target_date = datetime.now(MARKET_TZ).date()

        insights = _read_insights_for_date(target_date)
        policy_signals = _read_policy_cache()

        positions = []
        if self._alpaca:
            try:
                positions = self._alpaca.get_positions() or []
            except Exception as e:
                print(f"[BRIEFING] Alpaca get_positions failed: {e}")

        db_signals = _query_trading_signals(self.cfg)

        prompt_body = _build_prompt(
            target_date=target_date,
            insights=insights,
            policy_signals=policy_signals,
            positions=positions,
            db_signals=db_signals,
        )

        briefing = _synthesize_with_claude(prompt_body, target_date, self.cfg)
        if briefing is None:
            briefing = _fallback_briefing(
                target_date, insights, policy_signals, db_signals, positions
            )

        # Log to insight file
        log_insight(
            source="system",
            category="observation",
            insight=f"Morning briefing generated ({len(insights)} overnight insights, "
                    f"{len(db_signals)} DB signals, {len(positions)} open positions)",
            metadata={
                "date": target_date.isoformat(),
                "insight_count": len(insights),
                "signal_count": len(db_signals),
                "position_count": len(positions),
                "policy_signal_count": len(policy_signals),
            },
        )

        # Send via notifier
        if self._notifier:
            date_str = target_date.strftime("%Y-%m-%d %A")
            try:
                self._notifier.send(
                    subject=f"[BRIEFING] Morning Game Plan — {date_str}",
                    body=briefing,
                )
                print(f"[BRIEFING] Email sent for {target_date.isoformat()}")
            except Exception as e:
                print(f"[BRIEFING] Email send failed: {e}")

            try:
                # Slack gets a compact version (first 500 chars)
                slack_preview = briefing[:500] + ("..." if len(briefing) > 500 else "")
                self._notifier.send_slack(
                    f":sunrise: *Morning Briefing — {date_str}*\n{slack_preview}"
                )
            except Exception as e:
                print(f"[BRIEFING] Slack send failed: {e}")
        else:
            print("[BRIEFING] No notifier configured — briefing not sent")
            print(briefing)

        return briefing


# -----------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Morning Briefing — pre-market game plan")
    parser.add_argument("--date", type=str, help="YYYY-MM-DD (default: today ET)")
    args = parser.parse_args()

    target_date = None
    if args.date:
        target_date = date.fromisoformat(args.date)

    cfg = cfg_module.load()

    alpaca = None
    try:
        from execution.alpaca_client import AlpacaClient
        alpaca = AlpacaClient(settings=cfg)
    except Exception as e:
        print(f"[BRIEFING] Alpaca unavailable: {e}")

    notifier = None
    if cfg.notifications.resend_key:
        try:
            from execution.notifier import Notifier
            notifier = Notifier(settings=cfg)
        except Exception as e:
            print(f"[BRIEFING] Notifier unavailable: {e}")

    mb = MorningBriefing(settings=cfg, alpaca_client=alpaca, notifier=notifier)
    briefing = mb.generate(target_date=target_date)
    print("[BRIEFING] Done.")
    if not notifier:
        print(briefing)


if __name__ == "__main__":
    main()
