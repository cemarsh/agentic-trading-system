# Agentic Trading System

**Version**: 1.0.0
**Last Updated**: 2026-04-08
**Operator**: Cloud Magic Technology Group

A high-performance autonomous trading engine built on the 3-layer architecture (Directive → Orchestration → Execution). Integrates Alpaca Markets API, PostgreSQL decision logging, smart money surveillance, and options automation via the Wheel Strategy.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                     ORCHESTRATION LAYER                      │
│              Claude Code / AI Agent (You Are Here)           │
│         Reads directives → Routes to execution scripts       │
└──────────────────────┬──────────────────────────────────────┘
                       │
         ┌─────────────┼─────────────┐
         ▼             ▼             ▼
┌──────────────┐ ┌──────────────┐ ┌──────────────────────────┐
│  DIRECTIVE   │ │  EXECUTION   │ │      MCP LAYER           │
│  LAYER       │ │  LAYER       │ │                          │
│              │ │              │ │  - Alpaca API            │
│ directives/  │ │ execution/   │ │  - PostgreSQL (logging)  │
│ *.md         │ │ *.py         │ │  - Resend (email)        │
│              │ │              │ │  - Playwright (scraping) │
└──────────────┘ └──────────────┘ └──────────────────────────┘
```

---

## The Trading Triad

### Tier 1: Whale Watch (Smart Money Surveillance)
Monitors politician trading disclosures via CapitalTrades. When a tracked trade exceeds the minimum threshold, the system cross-references 1-minute Rate of Change (ROC) via Alpaca bars and scores the move using the Stock Trading Advisor Skill.

**Entry Condition**: Trade value > `WHALE_TRADE_MIN_VALUE` AND confidence score > `MIN_CONFIDENCE_SCORE`

### Tier 2: The Wheel Strategy (Options Income)
Systematic options income generation on high-liquidity tickers:
1. **Stage 1 — Cash Secured Put (CSP)**: Sell puts at target delta with N-week expiration
2. **Stage 2 — Covered Call (CC)**: If assigned, sell calls at cost_basis × (1 + markup%)

**Management**: 24/5 via Alpaca overnight data

### Tier 3: Protective Logic
- Trailing stop on all equity positions
- Gap-down pre-emptive tightening
- Ladder buying on defined drawdown

---

## Project Structure

```
trading/
├── README.md                    # This file
├── MEM.md                       # Strategy memory and open position log
├── .env                         # API keys and secrets (NEVER commit)
├── .env.example                 # Template for environment setup
├── .gitignore
│
├── config/
│   ├── settings.py              # Centralized config loader
│   └── strategy_params.yaml     # All tunable parameters (thresholds, tickers, etc.)
│
├── directives/                  # SOPs — what to do and why
│   ├── whale_watch.md
│   ├── wheel_strategy.md
│   └── protective_logic.md
│
├── execution/                   # Deterministic Python scripts
│   ├── alpaca_client.py         # Alpaca REST + WebSocket wrapper
│   ├── whale_watch.py           # CapitalTrades scraper + ROC analysis
│   ├── wheel_strategy.py        # CSP/CC option leg management
│   ├── protective_logic.py      # Trailing stops, gap protection, laddering
│   ├── hardware_monitor.py      # CPU/temp thresholds
│   ├── notifier.py              # Resend email alerts + daily report
│   ├── db_logger.py             # PostgreSQL decision_logic table writer
│   └── market_loop.py           # Main orchestration loop
│
├── logs/
│   └── agent_state.json         # Live agent state (positions, flags, counters)
│
└── tests/
    ├── test_alpaca_client.py
    ├── test_wheel_strategy.py
    └── test_protective_logic.py
```

---

## Quick Start

### 1. Environment Setup

```bash
cp .env.example .env
# Fill in all values in .env
```

### 2. Configure Strategy Parameters

Edit `config/strategy_params.yaml` to set your thresholds, tickers, and rules.

### 3. Initialize Database

```bash
python execution/db_logger.py --init
```

### 4. Verify Connectivity

```bash
python execution/alpaca_client.py --verify
python execution/notifier.py --test
python execution/db_logger.py --ping
```

### 5. Start the Loop

```bash
# Paper trading (safe default)
python execution/market_loop.py --mode paper

# Live trading (after verification period passes)
python execution/market_loop.py --mode live
```

---

## Configuration Reference

All strategy parameters live in `config/strategy_params.yaml`. Key groups:

| Group | Key | Description |
|-------|-----|-------------|
| Hardware | `cpu_threshold_pct` | CPU % to pause non-essential tasks |
| Hardware | `temp_threshold_c` | CPU temp (°C) to trigger alert |
| Intelligence | `min_confidence_score` | Minimum advisor score to execute |
| Whale Watch | `whale_trade_min_value` | Minimum $ value to act on |
| Whale Watch | `politician_names` | Tracked disclosure names |
| Whale Watch | `max_portfolio_pct_per_trade` | Max allocation per whale signal |
| Wheel | `tickers` | High-liquidity tickers for the Wheel |
| Wheel | `target_delta` | Delta for CSP entry |
| Wheel | `expiration_weeks` | Weeks to expiration |
| Wheel | `cc_strike_markup_pct` | CC strike above cost basis |
| Protection | `trailing_stop_pct` | Trailing stop on equity |
| Protection | `gap_tighten_pct` | Tightening on gap-down signal |
| Protection | `ladder_drop_pct` | Drawdown % to trigger ladder |
| Protection | `ladder_buy_shares` | Shares per ladder buy |
| Guardrails | `manual_confirm_threshold` | Order size requiring manual CONFIRM |
| Guardrails | `verification_trades` | # of trades in manual verification period |
| Guardrails | `api_retry_limit` | Consecutive failures before halt |

---

## Security

- API keys loaded from environment variables ONLY — never echoed or logged
- `.env` is in `.gitignore`
- Orders above `MANUAL_CONFIRM_THRESHOLD` require explicit `CONFIRM` for first N trades
- All credentials access goes through `config/settings.py`

---

## Decision Logging

Every trade decision writes to PostgreSQL `decision_logic` table:

```sql
CREATE TABLE decision_logic (
    id          SERIAL PRIMARY KEY,
    ts          TIMESTAMPTZ DEFAULT NOW(),
    ticker      TEXT,
    action      TEXT,          -- BUY, SELL, SELL_PUT, SELL_CALL, HOLD
    tier        TEXT,          -- whale_watch, wheel, protection
    confidence  FLOAT,
    reasoning   TEXT,
    order_id    TEXT,
    status      TEXT,          -- pending, filled, rejected, cancelled
    pnl         FLOAT
);
```

---

## Daily Report (4:15 PM EST)

Automated email containing:
- Daily P&L (realized + unrealized)
- Open positions and option legs
- Hardware metrics (avg CPU, thermal readings)
- Smart money summary (whale watch hits)

---

## Fail-Safes

| Condition | Response |
|-----------|----------|
| API fails N consecutive times | Halt all trading + critical email |
| CPU > threshold% | Pause non-essential tasks + email |
| Temp > threshold°C | Pause non-essential tasks + email |
| Gap-down detected overnight | Tighten trailing stop |
| Order > manual confirm threshold | Block until explicit CONFIRM |

---

## Development

```bash
# Run tests
python -m pytest tests/ -v

# Type check
mypy execution/ config/

# Lint
ruff check execution/ config/
```

---

## Connectivity Status

Run the verification suite before going live:

```bash
python execution/market_loop.py --verify-only
```

Expected output:
```
[OK] Alpaca API — connected (paper)
[OK] PostgreSQL — connected, decision_logic table exists
[OK] Resend email — test message delivered
[OK] Hardware monitor — CPU: X%, Temp: Y°C
[OK] Strategy params — loaded from config/strategy_params.yaml
[READY] All systems go. Run with --mode live to begin.
```
