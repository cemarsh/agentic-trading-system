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
from execution.daily_journal import log_insight, INSIGHTS_DIR
from execution.position_manager import _parse_occ

PROJECT_ROOT = Path(__file__).parent.parent

BRIEFING_PROMPT = """You are a pre-market trading desk analyst for an autonomous options/equity trading system.
Synthesize overnight signals into a concise, actionable game plan for today's session ({date}, {weekday}).

The system AUTO-MANAGES short options every cycle with these EXACT rules. Your POSITIONS TO MANAGE
notes must be consistent with them — do not invent different thresholds or advice:
  - Close at >= {profit_target}% of max profit.
  - Short PUTS: buy-to-close (stop-loss) once the loss reaches {stop_pct}% of premium received.
  - DTE <= {roll_dte}: roll DOWN-and-out ~4-6 weeks to a lower strike (or close if no net credit).
  - Positions tagged MANUAL-HOLD are intentionally exempt — NEVER suggest a stop-loss or forced exit on them.

INPUT FACTS ARE PRE-COMPUTED AND AUTHORITATIVE — trust them, do not redo the math:
  - DATE is today. Every option's strike, expiry date, and DTE are already parsed and correct.
    Use them verbatim. NEVER re-parse an option symbol, recompute DTE, or speculate that a date is a "typo".
  - Each position shows its P&L (dollars and % of premium) and a rule STATUS
    (e.g. "AT STOP-LOSS", "IN ROLL WINDOW", "hold ..."). Base your management notes on that STATUS.
  - Reconcile every summary sentence with the per-position data: do NOT write "all positions underwater"
    if any line shows a positive P&L.

Your output MUST follow this exact format (plain text, no markdown headers):

MORNING BRIEFING — {date}
=========================

TOP OPPORTUNITIES (2-3 max):
1. TICKER | STRATEGY | ENTRY TRIGGER | CONVICTION (1-10) | WHY NOW
2. TICKER | STRATEGY | ENTRY TRIGGER | CONVICTION (1-10) | WHY NOW
3. TICKER | STRATEGY | ENTRY TRIGGER | CONVICTION (1-10) | WHY NOW

RISKS TO WATCH:
- <concrete risk tied to a position STATUS or a named catalyst — no generic hand-wringing>
- <key risk 2 if any>

POSITIONS TO MANAGE:
- List ONLY positions whose STATUS is AT PROFIT TARGET, AT STOP-LOSS, or IN ROLL WINDOW.
  For each, state the single action the system will take today (close / BTC / roll down-and-out).
- (none — all open positions are holds within rule thresholds) if nothing is flagged.

REGIME NOTE:
<1 sentence on macro backdrop and whether to be aggressive or defensive today>

Rules:
- Strategy must be one of: CSP, CC, WHEEL, LONG_CALL, LONG_PUT, SPREAD, SKIP
- Entry trigger must be specific — a price level, technical confirmation, or news catalyst
- If signals are thin or contradictory, say SKIP and explain in one line (do not pad with filler)
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


def _extract_policy_headlines(insights: list, recent_days: int = 3, limit: int = 8) -> list:
    """
    Pull human-readable policy headlines from the insight log.

    Policy content is logged by policy_monitor as insights with category 'signal'
    (e.g. "PolicySignal(source='Federal Register EOs', headline='...')"). The old
    code instead read logs/policy_signal_cache.json, which is only a list of dedup
    FINGERPRINT HASHES with no content — that is why the briefing used to complain
    about "unresolved policy hashes". We read the real headlines here, scanning the
    last few insight files since policy_monitor does not run every day.
    """
    seen, out = set(), []

    def _harvest(items):
        for it in items:
            cat = (it.get("category") or "").lower()
            text = (it.get("insight") or "").strip()
            if not text:
                continue
            if cat in ("signal", "policy") or text.startswith("PolicySignal"):
                head = text[:220]
                if head not in seen:
                    seen.add(head)
                    out.append(head)

    _harvest(insights)
    # Walk back over the most recent insight files for additional policy context.
    try:
        files = sorted(INSIGHTS_DIR.glob("*.jsonl"), reverse=True)[:recent_days]
        for path in files:
            with open(path, encoding="utf-8") as f:
                rows = []
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rows.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
            _harvest(rows)
    except Exception:
        pass
    return out[:limit]


def _option_status(side, otype, profit_pct, dte, stop_frac, roll_dte, profit_target, premium=0.0):
    """Per-option management verdict, mirroring PositionManager's rule order.

    The dollar stop level is pre-computed (stop fires when unrealized P&L reaches
    -stop_frac * premium) so the LLM never has to do the arithmetic itself.
    """
    if dte < 0:
        return "EXPIRED — settles today"
    if side != "short":
        return f"long option — discretionary (DTE={dte})"
    if profit_pct >= profit_target:
        return f"AT PROFIT TARGET (>= {profit_target:.0%}) — system closes today"
    if otype == "PUT" and stop_frac is not None and profit_pct <= -stop_frac:
        return f"AT STOP-LOSS ({profit_pct:+.0%} <= -{stop_frac:.0%} of premium) — system BTCs today"
    if dte <= roll_dte:
        return f"IN ROLL WINDOW (DTE {dte} <= {roll_dte}) — system rolls down-and-out or closes"
    headroom = [f"hold, profit {profit_pct:+.0%}"]
    if otype == "PUT" and stop_frac is not None:
        headroom.append(f"stop at -{stop_frac:.0%} (P&L of -${stop_frac * premium:,.0f})")
    headroom.append(f"roll window in {dte - roll_dte}d")
    return "; ".join(headroom)


def _enrich_positions(positions: list, target_date: date, settings) -> list:
    """
    Turn raw Alpaca positions into pre-computed, rule-annotated one-liners so the
    LLM never has to parse OCC symbols or do date/P&L math itself.
    """
    pm = getattr(settings, "position_management", None)
    prot = getattr(settings, "protection", None)
    stop_pct = (getattr(pm, "stop_loss_pct", 250.0) if pm else 250.0) or 0
    stop_frac = (stop_pct / 100.0) if stop_pct else None
    roll_dte = getattr(pm, "roll_dte_threshold", 21) if pm else 21
    profit_target = ((getattr(pm, "close_profit_pct", 50.0) if pm else 50.0) or 50.0) / 100.0
    manual_hold = {str(t).upper() for t in (getattr(prot, "no_auto_manage", None) or [])}

    lines = []
    for p in positions:
        sym = p.get("symbol", "")
        qty = float(p.get("qty", 0) or 0)
        unpl = float(p.get("unrealized_pl", 0) or 0)
        avg_entry = float(p.get("avg_entry_price", 0) or 0)
        parsed = _parse_occ(sym)

        if parsed:
            dte = (parsed["expiry_date"] - target_date).days
            otype = "PUT" if parsed["option_type"] == "P" else "CALL"
            contracts = abs(qty)
            side = "short" if qty < 0 else "long"
            premium = avg_entry * 100 * contracts  # credit received per contract * contracts
            profit_pct = (unpl / premium) if premium else 0.0  # +ve = profit, matches PM
            status = _option_status(side, otype, profit_pct, dte, stop_frac, roll_dte, profit_target, premium)
            lines.append(
                f"{parsed['ticker']} {otype} ${parsed['strike']:.0f} | {side} {contracts:.0f}x "
                f"| exp {parsed['expiry_date'].isoformat()} (DTE={dte}) "
                f"| premium=${premium:,.0f} P&L={unpl:+,.0f} ({profit_pct:+.0%} of premium) "
                f"| {status}"
            )
        else:
            cost = avg_entry * abs(qty)
            pnl_pct = (unpl / cost) if cost else 0.0
            tag = ""
            if sym.upper() in manual_hold:
                tag = " | MANUAL-HOLD (no_auto_manage starter — breakeven-only exit; do NOT suggest a stop-loss)"
            lines.append(
                f"{sym} EQUITY | {qty:+.0f} sh @ ${avg_entry:.2f} "
                f"| P&L={unpl:+,.0f} ({pnl_pct:+.1%}){tag}"
            )
    return lines


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
    settings,
) -> str:
    def _compact(items, limit=30):
        return json.dumps(items[:limit], default=str, indent=1)

    pos_lines = _enrich_positions(positions, target_date, settings)
    policy_lines = "\n".join(f"- {h}" for h in policy_signals) if policy_signals else "(none overnight)"

    return f"""DATE: {target_date.isoformat()}
DAY_OF_WEEK: {target_date.strftime("%A")}

CURRENT_POSITIONS ({len(positions)} open — strike/DTE/P&L/STATUS pre-computed, authoritative):
{chr(10).join(pos_lines) if pos_lines else "(none)"}

RECENT_POLICY_SIGNALS ({len(policy_signals)} headlines):
{policy_lines}

OVERNIGHT_INSIGHTS ({len(insights)} entries):
{_compact(insights)}

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
    pm = getattr(settings, "position_management", None)
    stop_pct = (getattr(pm, "stop_loss_pct", 250.0) if pm else 250.0) or 0
    roll_dte = getattr(pm, "roll_dte_threshold", 21) if pm else 21
    profit_target = int((getattr(pm, "close_profit_pct", 50.0) if pm else 50.0) or 50.0)
    system_prompt = (
        BRIEFING_PROMPT
        .replace("{date}", target_date.isoformat())
        .replace("{weekday}", target_date.strftime("%A"))
        .replace("{profit_target}", str(profit_target))
        .replace("{stop_pct}", f"{stop_pct:.0f}")
        .replace("{roll_dte}", str(roll_dte))
    )
    try:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1500,
            system=system_prompt,
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
    settings=None,
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
    if policy_signals:
        for head in policy_signals[:3]:
            lines.append(f"- {head}")
    else:
        lines.append("- No policy signals overnight")

    lines += [
        "",
        "POSITIONS TO MANAGE:",
    ]
    if positions and settings is not None:
        for line in _enrich_positions(positions, target_date, settings):
            lines.append(f"- {line}")
    elif positions:
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
        policy_signals = _extract_policy_headlines(insights)

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
            settings=self.cfg,
        )

        briefing = _synthesize_with_claude(prompt_body, target_date, self.cfg)
        if briefing is None:
            briefing = _fallback_briefing(
                target_date, insights, policy_signals, db_signals, positions, settings=self.cfg
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
