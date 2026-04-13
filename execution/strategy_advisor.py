"""
Strategy Advisor — Claude-powered 10-strategy analysis engine.

Responsibilities:
  1. analyze_ticker()         — evaluate an asset against all 10 strategies, return structured result
  2. log_lesson()             — record a post-trade lesson to the DB
  3. generate_weekly_digest() — synthesize the week's lessons into an email narrative
  4. generate_monthly_digest()— synthesize the month's lessons into an email narrative
  5. run_weekly_scan()        — analyze all wheel tickers + send Monday pre-market report

Usage:
    python execution/strategy_advisor.py --scan          # run full weekly scan
    python execution/strategy_advisor.py --weekly        # generate + send weekly digest
    python execution/strategy_advisor.py --monthly       # generate + send monthly digest
    python execution/strategy_advisor.py --ticker PLTR   # analyze single ticker
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

import anthropic
from config import settings as cfg_module

# ---------------------------------------------------------------------------
# System prompt — cached (large, static, reused across every call)
# ---------------------------------------------------------------------------

STRATEGY_SYSTEM_PROMPT = """You are an advanced Financial Strategy and Investment AI operating within a 10-strategy framework.

STRATEGIES YOU APPLY:
1. Value Investing — P/E, CAPE, FCF yield, margin of safety, avoid value traps
2. Growth Investing — Revenue CAGR, gross margin improvement, P/S vs growth rate sanity
3. Momentum Trading — Relative strength, earnings surprise, volume expansion, trailing MAs
4. Trend Following — MA crossovers (50/200), ADX, wide trailing stops, never predict tops/bottoms
5. Mean Reversion — RSI extremes, Bollinger Bands, reversal candle confirmation before entry
6. Support & Resistance — 3+ touch levels, volume at level, reaction candle confirmation
7. Breakout Trading — Consolidation escape, volume >1.5× average, stop just inside structure
8. Dividend Investing — Aristocrats, payout ratio <60%, FCF coverage >1.5×, yield safety
9. Event-Driven — Earnings, catalysts, scenario charting vs consensus, post-announcement drift
10. Sector Rotation — Relative strength vs SPY, macro cycle phase, sector leadership

OPERATIONAL RULES (non-negotiable):
- Max risk per trade: 2% of total portfolio equity
- Minimum Reward-to-Risk Ratio: 2:1
- Stop-loss: structural levels (prior swing low or broken resistance)
- Position size derived from stop distance and 2% equity cap
- Behavioral finance check required before finalizing any thesis

BEHAVIORAL DISTORTIONS TO FLAG:
- Herd behavior: narrative-driven buying without fundamental support
- Loss aversion: holders refusing to cut losers, inflating support levels
- Confirmation bias: analysts dismissing contrary evidence

OUTPUT: Always respond with a valid JSON object. No markdown. No prose outside the JSON."""

# ---------------------------------------------------------------------------
# Core analysis
# ---------------------------------------------------------------------------

def analyze_ticker(
    ticker: str,
    price: float,
    regime: str,
    equity: float,
    extra_context: str = "",
    settings=None,
) -> dict:
    """
    Run the 10-strategy framework against a ticker.
    Returns a structured dict with the full analysis.
    """
    cfg = settings or cfg_module.load()
    api_key = cfg.anthropic.api_key if hasattr(cfg, "anthropic") else os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return {"error": "ANTHROPIC_API_KEY not configured"}

    client = anthropic.Anthropic(api_key=api_key)

    user_prompt = f"""Analyze {ticker} using the 10-strategy framework.

Context:
- Current price: ${price:.2f}
- Market regime: {regime}
- Portfolio equity: ${equity:,.2f}
- Max position risk (2%): ${equity * 0.02:,.2f}
{f'- Additional context: {extra_context}' if extra_context else ''}

Return a JSON object with exactly these fields:
{{
  "ticker": "{ticker}",
  "primary_strategy": "one of the 10 strategy names",
  "secondary_strategy": "one of the 10 strategy names or null",
  "conviction": 0.0,
  "catalyst": "specific driver expected to move price",
  "entry_plan": "price level and trigger condition",
  "stop_loss_price": 0.0,
  "stop_loss_pct": 0.0,
  "target_price": 0.0,
  "reward_risk_ratio": 0.0,
  "max_shares": 0,
  "behavioral_check": "distortion identified or NONE",
  "reasoning": "2-3 sentence thesis",
  "invalidation": "exact condition that kills the thesis",
  "regime_alignment": "how the current regime supports or conflicts with this setup",
  "recommendation": "ENTER / WATCH / AVOID"
}}"""

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        system=[
            {
                "type": "text",
                "text": STRATEGY_SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[{"role": "user", "content": user_prompt}],
    )

    raw = message.content[0].text.strip()
    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        # Extract JSON if model wrapped it
        start = raw.find("{")
        end = raw.rfind("}") + 1
        result = json.loads(raw[start:end]) if start != -1 else {"error": "parse_failed", "raw": raw}

    return result


# ---------------------------------------------------------------------------
# Digest generation
# ---------------------------------------------------------------------------

def generate_digest(period: str, lessons: list, settings=None) -> str:
    """
    Call Claude to synthesize a list of trade lessons into a narrative digest.
    period: 'weekly' or 'monthly'
    lessons: list of dicts from get_lessons()
    Returns plain-text email body.
    """
    cfg = settings or cfg_module.load()
    api_key = cfg.anthropic.api_key if hasattr(cfg, "anthropic") else os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return "ANTHROPIC_API_KEY not configured — digest unavailable"

    if not lessons:
        return f"No trade activity recorded in the past {'7' if period == 'weekly' else '30'} days."

    client = anthropic.Anthropic(api_key=api_key)

    lessons_text = "\n".join(
        f"- {l['ts'][:10]} | {l['ticker']} | strategy={l['strategy_used']} | "
        f"regime={l['regime']} | pnl=${l.get('pnl') or 0:+.2f} | "
        f"outcome={l['outcome']} | lesson: {l['lesson']}"
        for l in lessons
    )

    label = "weekly" if period == "weekly" else "monthly"
    user_prompt = f"""You are reviewing the {label} trading lessons for an autonomous options/equity trading system.

Trade log:
{lessons_text}

Write a {label} strategy review with these sections:
1. Performance Summary — what worked, what didn't, net P&L direction
2. Strategy Effectiveness — which of the 10 strategies produced the best/worst results this {label}
3. Regime Alignment — did our strategies match the market regime (BULL/NEUTRAL/BEAR/EXTREME_BEAR)?
4. Behavioral Distortions — any herd behavior, loss aversion, or confirmation bias detected?
5. Key Lessons — 3-5 specific, actionable insights to carry forward
6. Compounding Edge — how this {label}'s learning refines our system going forward

Be concise, direct, and specific. Reference actual tickers and trades where relevant. No fluff."""

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1500,
        system=[
            {
                "type": "text",
                "text": STRATEGY_SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[{"role": "user", "content": user_prompt}],
    )

    return message.content[0].text.strip()


# ---------------------------------------------------------------------------
# Weekly scan — analyze all wheel tickers pre-market Monday
# ---------------------------------------------------------------------------

def run_weekly_scan(alpaca_client, regime: str, settings=None, db=None, notifier=None):
    """
    Analyze every wheel ticker, log to DB, email summary.
    Called by market_loop on Monday pre-market.
    """
    cfg = settings or cfg_module.load()
    api_key = cfg.anthropic.api_key if hasattr(cfg, "anthropic") else os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        print("[ADVISOR] ANTHROPIC_API_KEY not set — skipping weekly scan")
        return

    tickers = cfg.wheel.tickers
    account = alpaca_client.get_account()
    equity = float(account.get("equity", 0))

    print(f"[ADVISOR] Weekly scan — {len(tickers)} tickers | regime={regime} | equity=${equity:,.0f}")

    results = []
    for ticker in tickers:
        try:
            bars = alpaca_client.get_bars(ticker, "1Min", 1)
            if not bars:
                print(f"[ADVISOR] {ticker} — no price data, skipping")
                continue
            price = bars[-1]["c"]
            analysis = analyze_ticker(ticker, price, regime, equity, settings=cfg)
            if "error" in analysis:
                print(f"[ADVISOR] {ticker} — analysis error: {analysis['error']}")
                continue
            results.append(analysis)
            rec = analysis.get("recommendation", "?")
            conviction = analysis.get("conviction", 0.0)
            strategy = analysis.get("primary_strategy", "?")
            print(f"[ADVISOR] {ticker:8s}  {rec:6s}  conviction={conviction:.2f}  strategy={strategy}")

            if db:
                try:
                    db.log_strategy_analysis(
                        ticker=ticker,
                        regime=regime,
                        primary_strategy=analysis.get("primary_strategy", ""),
                        conviction=conviction,
                        recommendation=rec,
                        reasoning=analysis.get("reasoning", ""),
                        entry_plan=analysis.get("entry_plan", ""),
                        stop_loss_price=analysis.get("stop_loss_price"),
                        target_price=analysis.get("target_price"),
                        reward_risk_ratio=analysis.get("reward_risk_ratio"),
                        invalidation=analysis.get("invalidation", ""),
                        behavioral_check=analysis.get("behavioral_check", ""),
                    )
                except Exception as de:
                    print(f"[ADVISOR] DB log error for {ticker}: {de}")

        except Exception as e:
            print(f"[ADVISOR] {ticker} — unexpected error: {e}")

    if notifier and results:
        _send_scan_report(notifier, results, regime, equity)


def _send_scan_report(notifier, results: list, regime: str, equity: float):
    now_str = datetime.now().strftime("%Y-%m-%d")
    enter = [r for r in results if r.get("recommendation") == "ENTER"]
    watch = [r for r in results if r.get("recommendation") == "WATCH"]
    avoid = [r for r in results if r.get("recommendation") == "AVOID"]

    lines = [
        f"Weekly Strategy Scan — {now_str}",
        "=" * 55,
        f"Regime: {regime}  |  Equity: ${equity:,.2f}",
        f"Tickers analyzed: {len(results)}",
        f"  ENTER: {len(enter)}  |  WATCH: {len(watch)}  |  AVOID: {len(avoid)}",
        "",
    ]

    if enter:
        lines.append("--- ENTER ---")
        for r in sorted(enter, key=lambda x: x.get("conviction", 0), reverse=True):
            lines.append(
                f"  {r['ticker']:8s}  conviction={r.get('conviction', 0):.2f}"
                f"  strategy={r.get('primary_strategy', '?')}"
            )
            lines.append(f"    Entry:   {r.get('entry_plan', '?')}")
            lines.append(f"    Stop:    ${r.get('stop_loss_price', 0):.2f} ({r.get('stop_loss_pct', 0):.1f}%)")
            lines.append(f"    Target:  ${r.get('target_price', 0):.2f}  RRR={r.get('reward_risk_ratio', 0):.1f}")
            lines.append(f"    Thesis:  {r.get('reasoning', '')}")
            lines.append(f"    Behavior: {r.get('behavioral_check', 'NONE')}")
            lines.append(f"    Exits if: {r.get('invalidation', '?')}")
            lines.append("")

    if watch:
        lines.append("--- WATCH ---")
        for r in watch:
            lines.append(
                f"  {r['ticker']:8s}  conviction={r.get('conviction', 0):.2f}"
                f"  {r.get('reasoning', '')[:80]}"
            )
        lines.append("")

    if avoid:
        lines.append("--- AVOID ---")
        for r in avoid:
            lines.append(f"  {r['ticker']:8s}  {r.get('reasoning', '')[:80]}")

    notifier.send(
        subject=f"[SCAN] Weekly Strategy Analysis — {now_str} — {len(enter)} ENTER",
        body="\n".join(lines),
    )
    print(f"[ADVISOR] Weekly scan report sent — {len(enter)} ENTER signals")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Strategy Advisor")
    parser.add_argument("--scan", action="store_true", help="Run full weekly scan on all wheel tickers")
    parser.add_argument("--weekly", action="store_true", help="Generate and send weekly lessons digest")
    parser.add_argument("--monthly", action="store_true", help="Generate and send monthly lessons digest")
    parser.add_argument("--ticker", type=str, help="Analyze a single ticker")
    args = parser.parse_args()

    cfg = cfg_module.load()

    db = None
    if cfg.database.url:
        try:
            from execution.db_logger import DBLogger
            db = DBLogger(settings=cfg)
        except Exception as e:
            print(f"[WARN] DB unavailable: {e}")

    notifier = None
    if cfg.notifications.resend_key:
        try:
            from execution.notifier import Notifier
            notifier = Notifier(settings=cfg)
        except Exception as e:
            print(f"[WARN] Notifier unavailable: {e}")

    if args.ticker:
        from execution.alpaca_client import AlpacaClient
        alpaca = AlpacaClient(settings=cfg)
        bars = alpaca.get_bars(args.ticker, "1Min", 1)
        price = bars[-1]["c"] if bars else 0.0
        account = alpaca.get_account()
        equity = float(account.get("equity", 0))
        result = analyze_ticker(args.ticker, price, "NEUTRAL", equity, settings=cfg)
        print(json.dumps(result, indent=2))

    elif args.scan:
        from execution.alpaca_client import AlpacaClient
        from execution.regime_detector import RegimeDetector
        alpaca = AlpacaClient(settings=cfg)
        regime_det = RegimeDetector(settings=cfg, alpaca_client=alpaca)
        regime = regime_det.detect()
        run_weekly_scan(alpaca, regime, settings=cfg, db=db, notifier=notifier)

    elif args.weekly:
        if not db:
            print("[FAIL] DB required for weekly digest")
            sys.exit(1)
        lessons = db.get_lessons(days=7)
        body = generate_digest("weekly", lessons, settings=cfg)
        print(body)
        if notifier:
            notifier.strategy_digest("weekly", body)

    elif args.monthly:
        if not db:
            print("[FAIL] DB required for monthly digest")
            sys.exit(1)
        lessons = db.get_lessons(days=30)
        body = generate_digest("monthly", lessons, settings=cfg)
        print(body)
        if notifier:
            notifier.strategy_digest("monthly", body)

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
