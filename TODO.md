# Agentic Trading System — TODO

**Last Updated**: 2026-04-13
**Status**: Live (Paper) — ThinkPad P70

---

## Completed

- [x] Scaffold project structure (directives, execution, config)
- [x] Alpaca paper trading API connection (IEX feed)
- [x] Whale Watch — CapitalTrades scraper (11 politicians)
- [x] Wheel Strategy — CSP/CC options automation (18 tickers)
- [x] Protective Logic — trailing stops, gap protection, ladder buying
- [x] Hardware monitor — CPU/temp threshold enforcement
- [x] PostgreSQL decision logging (`decision_logic` table)
- [x] Resend email alerts (`noreply@cloudmagicgroup.com`)
- [x] Daily report at 4:15 PM ET
- [x] systemd service on ThinkPad (persistent, auto-restart)
- [x] Policy Intelligence Layer (policy_monitor.py)
  - [x] White House Fact Sheets + Presidential Actions (`.wp-block-post-title a`)
  - [x] Federal Register EOs (JSON API — HTML is JS-rendered)
  - [x] DoD Contract Announcements (`p.title`)
- [x] Fully autonomous mode (`verification_trades: 0`)
- [x] Killed stale claude process causing CPU threshold breaches
- [x] GitHub repo: cemarsh/agentic-trading-system
- [x] Added to ops dashboard: cloudmagic.software/weekly-ops-dashboard/
- [x] Fixed strike calculation bug (inverted formula → no contracts ever placed)
- [x] Fixed 403 halt loop — whale watch orders wrapped in individual try/except
- [x] Fixed null db guard in whale watch order logging
- [x] Fixed options symbol in protective logic (OCC regex filter, skip options positions)
- [x] Fixed exact strike matching → nearest-available strike with 8% tolerance
- [x] Alpaca error messages now include response body for easier debugging
- [x] Market regime detector (regime_detector.py) — BULL/NEUTRAL/BEAR/EXTREME_BEAR
- [x] Inverse ETF hedge module (inverse_etf_hedge.py) — auto-buy SQQQ in bear regimes
- [x] Position sizing levers: per-trade cap (6% equity) + total allocation cap (65%)
- [x] Status emails every 2 hours during market window (not just daily report)
- [x] Regime-aware wheel: BEAR → delta 0.15, EXTREME_BEAR → skip all new entries
- [x] Switched to acct3 (PKGIWVF62JODI7QGJO2CNQS7VX) with levers active
- [x] Fixed market loop running on weekends — added Alpaca /v2/clock market hours gate
- [x] Added 10-strategy framework directive (directives/strategy_framework.md)
- [x] Built strategy_advisor.py — Claude-powered ticker analysis + lessons digest
- [x] Weekly scan trigger (Monday pre-market) + monthly digest (1st of month)
- [x] strategy_analysis + strategy_lessons PostgreSQL tables
- [x] ANTHROPIC_API_KEY wired into settings.py and ThinkPad .env

---

## Phase 2 — Intelligence Fusion

- [ ] USASpending.gov contract awards API ($7.5M+ DoD awards → ticker mapping)
- [ ] SEC EDGAR insider transaction feed (CEO/CFO purchases)
- [ ] Options flow scanner (unusual call/put volume sweeps)
- [ ] Earnings calendar integration (reduce before earnings, re-enter after)
- [ ] SEC 8-K / 13F real-time feed

---

## Phase 3 — Quantitative Scoring

- [ ] ML confidence model (policy signal → price move correlation)
- [ ] Sector momentum overlay (only enter if ETF above 20-day MA)
- [ ] Volatility regime detection (shift to cash when VIX elevated)
- [ ] Backtesting harness (replay historical signals)

---

## Phase 4 — Execution Quality

- [ ] IV rank / IV percentile gating (only sell premium when rank > 30)
- [ ] Smart expiration rolling (50% max profit or 21 DTE)
- [ ] VWAP-aware order splitting
- [ ] Multi-leg options (spreads to cap max loss)

---

## Near-Term Operational

- [ ] Add ANTHROPIC_API_KEY to .env — needed to activate strategy_advisor weekly scan
- [ ] Init new DB tables: `python execution/db_logger.py --init` (adds strategy_analysis + strategy_lessons)
- [ ] Verify first properly-sized CSP orders fired on acct3 (eligible: MP, ABT, CCJ, PLTR, XOM, VST within $15k)
- [ ] Register `notifications.cloudmagicgroup.com` subdomain on Resend for cleaner sender
- [ ] Flip `paper_mode: false` after verifying 10+ autonomous paper trades
- [ ] Add ThinkPad daily sync for ops-dashboard.json to include trading metrics
- [ ] Add IV rank/percentile check before opening CSPs (only sell when rank > 30)
- [ ] Log post-trade lessons to strategy_lessons table as positions close (wire into daily report)
