# Agentic Trading System — TODO

**Last Updated**: 2026-04-09
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

- [ ] Verify Alpaca options order flow end-to-end (paper test CSP on SHLD)
- [ ] Register `notifications.cloudmagicgroup.com` subdomain on Resend for cleaner sender
- [ ] Flip `paper_mode: false` after verifying 10+ autonomous paper trades
- [ ] Add ThinkPad daily sync for ops-dashboard.json to include trading metrics
