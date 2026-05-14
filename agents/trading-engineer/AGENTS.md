# TradingEngineer — Scaffolder Output

## 1. Project Discovery

**Project**: Agentic Trading System  
**Path**: `/home/stacksbyc/projects/trading/`  
**Version**: 1.5.0  
**Status**: Live (Paper Trading) — ThinkPad P70, systemd service  
**Broker**: Alpaca Markets (paper mode)

**Architecture**:
```
Policy Intelligence Layer
  L1: White House EOs + Fact Sheets (sector catalyst)
  L2: DoD Contract Awards (stock catalyst)
  L3: Federal Register presidential documents
  L4: Congressional trade disclosures (Capitol Trades)
       ↓
Orchestration Engine (60-second market loop)
  ├── Regime Detector
  └── Wheel Strategy (cash-secured puts → covered calls)
```

**Key Assets**:
- `config/` — Trading parameters, strategy config
- `directives/` — Policy intelligence SOPs
- `execution/` — Order execution modules
- `journal/` — Trade journal + performance logs
- `n8n/` — n8n workflow configs (policy monitor)
- `tests/` — Strategy backtests
- `debug_*.py` — Live debugging tools
- `test_policy.py` — Policy signal tests

**Related Skill**: `stock-trading-advisor.skill` in `.skills-db/` (wheel strategy, CSP, covered calls, congressional trades, Capitol Trades, position sizing)

---

## 2. Agent Skill Inventory

| Skill | Confidence | Source |
|-------|-----------|--------|
| Wheel strategy (CSP → CC) | High | .skills-db/stock-trading-advisor.skill |
| Policy intelligence parsing | High | trading/directives/ |
| Alpaca Markets API | High | trading/execution/ |
| Congressional trade analysis | High | Capitol Trades integration |
| Regime detection logic | High | trading/config/ |
| Position sizing + risk management | High | stock-trading-advisor skill |
| n8n workflow for policy signals | Medium | trading/n8n/ |
| DoD contract award parsing | Medium | directives/ |

---

## 3. Gap Analysis

| Gap | Severity | Mitigation |
|-----|---------|-----------|
| Paper mode only — not live | High | Switch Alpaca keys after performance validation |
| No real-time options chain data | Medium | Add Tradier/CBOE data feed |
| Policy signal latency (polling vs webhook) | Low | Acceptable for current strategy |
| No drawdown circuit breaker | High | Add max-drawdown halt in orchestration engine |

---

## 4. Safety Rules

- **NEVER switch to live mode** without explicit user confirmation
- All trades logged to `journal/` with signal source
- Risk per trade capped at policy in `config/`
- Human confirmation required before any strategy parameter change
