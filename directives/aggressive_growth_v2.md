# Directive: Aggressive Growth Strategy v2.0

**Effective**: 2026-05-28  
**Replaces**: Passive wheel-only approach  
**Mandate**: Grow equity every day, week, and month. Use all available intelligence. Act on signals. Stop sitting in cash.

---

## The Problem With v1

The v1 system collected data but did not act on it:
- Policy signals fired → logged → nothing traded
- Whale signals fired → logged → maybe 1 equity buy per month
- NotebookLM signals → 0 rows in DB ever executed
- $70k average idle buying power on a $100k account
- 5 CSPs averaging 0.9% annualized return — not a trading system, a savings account

**The fix**: Every signal must complete a loop. Signal → Analysis → Decision → Trade → Review → Learn.

---

## Account Architecture (3-Account Mandate)

### Account A — Income Engine (current acct3)
**Mandate**: Maximum theta income via active wheel management  
**Rule**: Never hold a position past 50% max profit or 21 DTE — whichever comes first  
**Target**: 3-5% monthly return on deployed capital (not equity — on capital at risk)  
**Position count**: 10-15 simultaneous open legs (vs. 5 now)  
**Key change**: Close at 50% profit → immediately recycle into new position

### Account B — Momentum / Event-Driven
**Mandate**: Trade policy + whale signal convergence with equity positions  
**Triggers**: Policy signal (tier 1 or 2) + whale signal on same ticker within 48h = BUY  
**Position size**: 5-8% equity per trade, trailing stop at 7%  
**Target**: 3-5 active equity positions at all times during open signals

### Account C — High-Conviction Research
**Mandate**: NotebookLM signals with conviction ≥ 7 → CSP or equity position  
**Entry**: Only when NotebookLM + at least one of (policy OR whale) align  
**Sizing**: 10% equity per position (higher conviction = larger size)  
**Target**: 2-4 positions, 30-60 day holds

---

## Daily Operating Rhythm

### 9:00 AM ET — Morning Briefing (automated)
System generates and emails/Slacks:
- Overnight policy signals (any tier 1s? DoD contracts?)
- Whale trades filed in last 48h
- NotebookLM signals active (conviction ≥ 6)
- Positions at or near 50% profit (close candidates)
- Positions at or near 21 DTE (roll candidates)
- **2-3 specific trade ideas for today** with entry levels

### 9:30–10:00 AM ET — Position Management (automated)
PositionManager runs:
1. Close any position at ≥50% max profit
2. Roll any position ≤21 DTE that is not at 50%
3. Open new positions if buying power allows

### 10:00 AM–3:30 PM ET — Signal Execution (automated)
For each new confirmed signal:
- Tier 1 policy (EO signing, DoD contract >$500M) + ticker in wheel universe → CSP same day
- Whale buy ($25k+) + ticker in universe + ROC > 0.5% → equity buy (Account B)
- NotebookLM conviction ≥ 8 + policy OR whale alignment → Account C position

### 4:05 PM ET — Daily Wrap-Up (automated, existing)
Daily report + journal synthesis + lessons logged

### Friday 4:15 PM ET — Weekly Review (automated, existing)
Weekly scan, digest, recalibration

---

## Signal Convergence Rules

```
STRONG BUY (Account B + C):
  Policy Tier 1 + Whale Signal + NotebookLM ≥ 7 → 10% equity position

MODERATE BUY (Account A — new CSP):
  Policy Tier 2 + ticker in wheel universe + IV rank > 25 → CSP 2-3 weeks out

WHEEL ENTRY (Account A):
  Ticker at 50%+ profit close freed → immediately sell new CSP on same or next ticker

SKIP:
  Any signal on earnings week
  Any signal when regime = EXTREME_BEAR
```

---

## Position Management Rules (Non-Negotiable)

| Condition | Action |
|-----------|--------|
| Premium ≥ 50% profit | Buy to close immediately — do not wait |
| DTE ≤ 21, < 50% profit | Roll out 4-6 weeks for net credit |
| DTE ≤ 21, net credit impossible | Close and take the loss |
| DTE ≤ 7, any status | Close — do not let options expire or get assigned passively |
| Assignment | Sell covered call immediately (wheel stage 2) |

---

## Ticker Expansion

Beyond the current 18 tickers, add active monitoring for:

**Momentum triggers** (buy equity on breakout + policy signal):
- RKLB — Space Force, satellite constellation contracts
- KTOS — drone autonomy, Skyborg program
- ASTS — AST SpaceMobile, satellite broadband FCC approvals
- JOBY — FAA certification catalyst
- SMR — NuScale SMR licensing

**Event-driven** (earnings + catalyst):
- Any ticker with DoD contract announced within 30 days of earnings

**Rotation watch** (sector momentum):
- XLE vs XLK — energy vs tech rotation signal
- GDX — gold miners when DXY weakens

---

## Learning Loop (Operational)

**Daily**: Every `log_insight()` entry tagged as `category="learning"` gets surfaced in morning briefing  
**Weekly**: Strategy advisor must identify: which signals fired but didn't produce trades (missed opportunities)?  
**Monthly**: P&L attribution by signal source — policy vs. whale vs. NotebookLM vs. wheel mechanical  

The goal is to know by the end of each month: **where is our edge actually coming from?**

---

## What "Growth Every Day" Means

- **Daily**: At least 1 position event (open, close, or roll) on every market day. A day with zero position activity is a system failure to investigate.
- **Weekly**: Deployed capital should increase or theta collected should show vs. prior week.
- **Monthly**: Total equity should be higher than prior month. If not, a post-mortem is required.

---

## Anneal Log

- 2026-05-28: v2.0 created. Mandate: growth. Replacing passive wheel-only approach with active position management, signal convergence trading, pre-market briefing, and multi-account architecture.
