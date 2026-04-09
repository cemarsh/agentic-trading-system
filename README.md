# Agentic Trading System

**Version**: 1.1.0  
**Last Updated**: 2026-04-09  
**Operator**: Cloud Magic Technology Group  
**Status**: Live (Paper) · ThinkPad P70 · Alpaca Markets

> The stock market is the last great information asymmetry. Institutions spend hundreds of millions
> on data feeds, quant teams, and co-location. This project is our answer: a self-directing,
> policy-aware, AI-augmented trading engine that closes the gap — running autonomously on commodity
> hardware, pulling the same signals the pros watch, and acting in milliseconds while you sleep.

---

## The Vision

Modern retail trading is broken. Platforms gave individuals access to markets but left them with
the same hand-crafted spreadsheets, delayed news, and gut-feel decisions that have never worked.
Meanwhile, every structural alpha edge — congressional insider flow, executive order sector
rotations, defense contract awards, commodity supply chain disruptions — plays out in public data
that nobody is watching systematically.

**This system watches it all. Continuously. Autonomously.**

The goal is not to beat hedge funds on execution speed. It's to beat them on *intelligence surface* —
monitoring more policy signals, tracking more informed actors, and responding to macro structural
shifts before they become obvious. The edge is in the information hierarchy, not the latency.

---

## What It Does Today

```
┌─────────────────────────────────────────────────────────────────────┐
│                      POLICY INTELLIGENCE LAYER                       │
│  L1: White House EOs + Fact Sheets (sector catalyst — immediate)    │
│  L2: DoD Contract Awards (stock catalyst — specific company)         │
│  L3: Federal Register presidential documents (confirmation signal)   │
│  L4: Congressional trade disclosures (lagging — smart money)        │
└────────────────────────────────┬────────────────────────────────────┘
                                 │
                    ┌────────────▼────────────┐
                    │   ORCHESTRATION ENGINE   │
                    │  60-second market loop   │
                    │  Autonomous · Persistent │
                    └───┬──────────┬──────────┘
                        │          │
           ┌────────────▼──┐   ┌───▼───────────────┐
           │  WHALE WATCH  │   │   WHEEL STRATEGY   │
           │               │   │                    │
           │ CapitalTrades │   │ Cash Secured Puts  │
           │ 11 politicians│   │ → Assignment       │
           │ ROC scoring   │   │ → Covered Calls    │
           │ Auto-execute  │   │ 18 tickers / 7     │
           └───────────────┘   │ policy sectors     │
                               └────────────────────┘
                        │
           ┌────────────▼──────────────────────────┐
           │           PROTECTIVE LOGIC             │
           │  Trailing stops · Gap protection       │
           │  Ladder buying on drawdown             │
           └───────────────────────────────────────┘
```

### The 10 Fortified Sectors

The system tracks and trades across every major policy-driven structural theme:

| Sector | Thesis | Tickers |
|--------|--------|---------|
| Defense / AI Battlespace | Golden Dome, drone proliferation, PLTR AIP | SHLD, RTX, AVAV, PLTR, LDOS |
| Energy Dominance | Offshore leasing, LNG exports, Hormuz premium | XOM, CVX, CCJ |
| Nuclear Renaissance | 400GW build-out, SMR licensing, Calpine deal | CEG, VST, CCJ |
| Critical Minerals | Rare earth independence, strategic stockpile | MP, ALB |
| Semiconductors | CHIPS Act fab investment, domestic wafer | INTC, AVGO, AMAT |
| Domestic Manufacturing | Reshoring, tariff beneficiaries, infrastructure | CAT, NUE |
| Border Security | ICE expansion, detention infrastructure | GEO, CXW |
| AI Infrastructure | Gov AI contracts, inference data centers | PLTR, MSFT, ORCL, VRT |
| Space / Aerospace | SpaceForce, hypersonic programs, satellite | BA, KTOS, RKLB |
| Crypto | Strategic Bitcoin reserve, stablecoin framework | MSTR, COIN |

---

## The Roadmap: Where This Is Going

### Phase 2 — Multi-Source Intelligence Fusion (Q2 2026)

The current system scrapes headlines. Phase 2 turns it into a proper intelligence pipeline:

- **SEC 8-K / 13F real-time feed** — catch institutional accumulation before it moves price
- **USASpending.gov contract awards API** — $7.5M+ DoD awards to specific companies, parsed
  and mapped to tickers automatically
- **EDGAR insider transaction feed** — CEO/CFO purchases, not just politicians
- **Earnings calendar integration** — auto-reduce position before earnings, re-enter after
- **Options flow scanner** — detect unusual call/put volume sweeps as confirmation signal

### Phase 3 — Quantitative Signal Scoring (Q3 2026)

Replace the binary keyword match with a proper scoring model:

- **Confidence scoring v2** — ML model trained on historical policy signal → price move
  correlation. Did the last 50 defense EOs actually move RTX? By how much? Over what timeframe?
- **Sector momentum overlay** — only enter if sector ETF (SHLD, XLE, NLR) is above 20-day MA
- **Volatility regime detection** — automatically shift from Wheel to protective cash when VIX
  regime is elevated
- **Correlation matrix** — avoid over-concentration across tickers that move together
- **Backtesting harness** — replay any date range against historical policy signals to validate
  strategy changes before deploying

### Phase 4 — Adaptive Execution (Q4 2026)

Current execution is naive — market orders, fixed quantities. Phase 4 makes it surgical:

- **VWAP-aware order splitting** — break large orders into child orders to minimize market impact
- **Bid/ask spread analysis** — skip entries when spread > X% of premium on options
- **IV rank / IV percentile gating** — only sell premium when IV rank > 30 (elevated, not spike)
- **Multi-leg options automation** — spreads to cap max loss while preserving theta income
- **Gamma hedging** — auto-delta hedge short option positions when delta drifts past threshold
- **Smart expiration rolling** — roll positions at 50% max profit or 21 DTE automatically

### Phase 5 — Distributed Architecture (2027)

The ThinkPad is a proof of concept. The production system runs on hardened infrastructure:

- **Multi-broker routing** — Alpaca for equities, IBKR for options depth, TastyTrade for
  spreads. Best execution across brokers, not just one
- **Hot standby failover** — primary on ThinkPad, secondary on cloud VM. Automatic takeover
  on primary failure
- **Real-time Splunk dashboard** — every decision, every order, every signal on a live
  operations dashboard. P&L tick-by-tick, drawdown alerts, sector exposure heatmap
- **WebSocket price feeds** — replace polling with streaming quotes for sub-second reaction
- **Co-located news processing** — NLP pipeline on White House and Federal Register RSS feeds
  for sub-second signal detection (response time: seconds, not minutes)

### Phase 6 — AI-Native Decision Layer (2027+)

The current system is rule-based. The future system reasons:

- **LLM policy analyst** — pass full EO or fact sheet text to a language model. Ask it:
  "Which publicly traded companies benefit from this order, and on what timeframe?" Map the
  answer to positions
- **Earnings call NLP** — parse management tone, guidance language, and competitor mentions
  from transcripts. Score against sector thesis
- **Geopolitical risk model** — Strait of Hormuz tension → energy premium; Taiwan friction →
  semiconductor risk; NATO article 5 invocation → defense surge. Trained on historical
  geopolitical events vs. sector returns
- **Self-improving strategy** — the system reviews its own trade log weekly, identifies
  losing patterns, and proposes parameter changes for human approval
- **Natural language operations** — text "buy more AVAV" or "what's my exposure to
  nuclear?" and the system responds and acts

---

## Current System Architecture

```
trading/
├── README.md                    # This file
├── MEM.md                       # Strategy memory, open positions, event log
├── .env                         # API keys (NEVER committed)
├── config/
│   ├── settings.py              # Centralized config loader
│   └── strategy_params.yaml     # All tunable parameters
├── directives/                  # SOPs — living documents
│   ├── whale_watch.md
│   ├── wheel_strategy.md
│   └── protective_logic.md
├── execution/                   # Deterministic execution layer
│   ├── market_loop.py           # Main orchestration loop (systemd managed)
│   ├── alpaca_client.py         # Alpaca REST wrapper
│   ├── whale_watch.py           # CapitalTrades scraper + ROC scoring
│   ├── wheel_strategy.py        # CSP/CC option leg management
│   ├── protective_logic.py      # Trailing stops, gap protection, laddering
│   ├── policy_monitor.py        # Policy intelligence scanner (L1–L4)
│   ├── hardware_monitor.py      # CPU/temp threshold enforcement
│   ├── notifier.py              # Resend email (noreply@cloudmagicgroup.com)
│   └── db_logger.py             # PostgreSQL decision_logic writer
└── tests/
    ├── test_alpaca_client.py
    ├── test_wheel_strategy.py
    └── test_protective_logic.py
```

---

## Quick Start

```bash
# 1. Clone and install dependencies
git clone <repo>
cd trading
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# 2. Configure environment
cp .env.example .env
# Fill in: ALPACA_KEY, ALPACA_SECRET, ALPACA_BASE_URL,
#          RESEND_API_KEY, ALERT_EMAIL, DATABASE_URL

# 3. Configure strategy
# Edit config/strategy_params.yaml — tickers, thresholds, politician watchlist

# 4. Verify all connectivity
python execution/market_loop.py --verify-only

# 5. Run paper trading
python execution/market_loop.py --mode paper

# 6. (Optional) Install as systemd service for 24/7 autonomous operation
sudo cp trading.service /etc/systemd/system/
sudo systemctl enable --now trading
```

---

## Autonomous Operation

The system is designed to run indefinitely without human intervention:

| Event | Autonomous Response |
|-------|---------------------|
| Policy signal detected | Classify sector → identify tickers → email alert → log to DB |
| Congressional trade filed | Score confidence → check ROC → execute if threshold met |
| Trailing stop hit | Liquidate position → log decision → update state |
| Gap-down overnight | Tighten trailing stop by `gap_tighten_pct` |
| CSP expiring worthless | Roll to next cycle or take assignment |
| CPU > 85% | Pause non-essential tasks → resume when clear |
| API fails 3x | Halt all trading → critical email → wait for operator |
| Daily at 4:15 PM ET | Email P&L report, position summary, whale watch log |
| System restart | Restore state from `logs/agent_state.json`, resume |

---

## Key Configuration

```yaml
# config/strategy_params.yaml
guardrails:
  paper_mode: true              # Switch to false only when ready for live

intelligence:
  min_confidence_score: 0.72   # Raise to 0.80+ to be more selective

whale_watch:
  whale_trade_min_value: 15000 # $15K minimum to filter noise
  max_portfolio_pct_per_trade: 5

wheel:
  target_delta: 0.25           # Conservative in volatile markets
  expiration_weeks: 2
  min_premium_pct: 0.8         # Demand premium when IV is elevated
```

---

## Decision Audit Trail

Every signal, order, and outcome is logged to PostgreSQL:

```sql
SELECT tier, action, ticker, confidence, reasoning, status, pnl
FROM decision_logic
ORDER BY ts DESC
LIMIT 20;
```

---

## Philosophy

Most retail trading systems optimize for *reaction speed*. This one optimizes for
*information breadth*. The thesis: in a policy-driven market regime, the trader who first
connects an Executive Order to a supply chain beneficiary — and acts before the analyst
note hits Bloomberg — captures the entire move.

We are building the infrastructure to do that. Systematically. At scale. Autonomously.

---

*Built by Cloud Magic Technology Group · Powered by Alpaca Markets · Running 24/7 on ThinkPad P70*
