# Directive: 10-Strategy Financial Analysis Framework

**Version**: 1.0
**Script**: `execution/strategy_advisor.py`

---

## Goal

Provide systematic, multi-strategy analysis of every asset before a position is entered and after every closed trade. The advisor cross-references all 10 strategies against current price action, fundamentals, and macro context to identify the highest-probability setup — and forces a behavioral finance check to catch crowd-driven distortions.

---

## The 10 Strategies

### 1. Value Investing
**What**: Buy assets trading below intrinsic value.
**Metrics**: P/E ratio, CAPE ratio, free cash flow yield, margin of safety.
**Trap to avoid**: Value traps — businesses that are cheap for a reason (structural deterioration). Confirm FCF is stable or growing before entry.

### 2. Growth Investing
**What**: Target companies expanding revenue, profits, or users at high rates.
**Metrics**: Revenue CAGR (>20% preferred), improving gross margins, price-to-sales vs. growth rate sanity check.
**Trap to avoid**: Chasing growth at any price. P/S >20 without a clear path to profitability is speculation, not investing.

### 3. Momentum Trading
**What**: Ride recent relative winners; avoid recent relative losers.
**Metrics**: Price momentum (52-week relative strength), earnings surprise magnitude, volume expansion on up-days.
**Execution**: Enter on continuation; use trailing moving averages (e.g., 10-period) to lock in gains before reversal.

### 4. Trend Following
**What**: Enter confirmed directional moves; never predict tops or bottoms.
**Metrics**: 50-period vs. 200-period MA crossover, trend line integrity, ADX > 25 confirms trend strength.
**Execution**: Enter after trend confirmation. Use wide trailing stops to absorb noise. Do not fight the trend.

### 5. Mean Reversion
**What**: Capture snapback from statistically extreme price extensions.
**Metrics**: RSI < 30 (oversold) or > 70 (overbought), Bollinger Band touches, deviation from 20-day mean.
**Confirmation required**: Reversal candle (hammer, doji, engulfing) before entry. Never catch a falling knife without a signal.

### 6. Support & Resistance (Price Action)
**What**: Trade from high-probability structural levels.
**Metrics**: Levels with 3+ historical touches, volume at level, reaction candle confirmation.
**Execution**: Buy near support with stop below it. Short near resistance with stop above it. Respect the structure.

### 7. Breakout Trading
**What**: Enter when price escapes a defined consolidation range with conviction.
**Confirmation required**: Volume expansion (>1.5× average) on breakout candle. Enter on close outside the range.
**Stop placement**: Just inside the broken structure to guard against head fakes.

### 8. Dividend Investing
**What**: Build income from companies with growing, sustainable dividend track records.
**Metrics**: Dividend Aristocrats (25+ years of increases), payout ratio < 60%, FCF coverage > 1.5×.
**Trap to avoid**: High yield ≠ safe yield. A 10% yield on a declining stock is a value trap in disguise.

### 9. Event-Driven Trading
**What**: Trade around catalysts that shift market expectations.
**Catalysts**: Earnings, product launches, regulatory decisions, Fed announcements, congressional hearings.
**Execution**: Chart scenarios vs. consensus. Enter on confirming signal, not in advance. Capture post-earnings drift.

### 10. Sector Rotation
**What**: Rotate capital toward leading sectors; exit laggards as the economic cycle evolves.
**Metrics**: Relative strength of sector ETF vs. SPY, macro cycle phase (expansion/contraction), sector momentum.
**Framework**: Energy in inflation → Technology in growth → Utilities/Healthcare in contraction → Financials in recovery.

---

## Operational Framework

### Step 1 — Strategy Identification
Evaluate the asset against all 10 strategies. Identify the 1–2 that most strongly align with current price action, fundamental profile, and macro regime.

### Step 2 — Fundamental & Technical Synthesis
Cross-reference at least one fundamental metric with one technical confirmation. A single metric is never sufficient. The thesis must hold from both perspectives.

### Step 3 — Risk Management (Non-Negotiable)
- Max risk per trade: **2% of total portfolio equity**
- Minimum Reward-to-Risk Ratio: **2:1**
- Stop-loss: structural level (just below prior swing low or broken resistance)
- Position size: derived from stop distance and 2% equity risk cap

### Step 4 — Behavioral Finance Check
Before finalizing: evaluate whether the current price reflects rational valuation or behavioral distortion.
- **Herd behavior**: Is everyone piling in because of narrative, not fundamentals?
- **Loss aversion**: Are holders refusing to cut losers, inflating the float above technical support?
- **Confirmation bias**: Are bullish analysts dismissing contrary evidence?

### Step 5 — Output Format (Required for Every Analysis)
Every trade analysis must include:
- **Primary strategy**: which of the 10 fits best and why
- **Catalyst**: the specific driver expected to move price
- **Entry plan**: price level, trigger condition
- **Stop-loss**: structural level and distance in %
- **Target**: price objective and RRR confirmation
- **Invalidation**: the exact condition that kills the thesis
- **Behavioral check**: distortion identified (or confirmed absent)
- **Conviction score**: 0.0–1.0

---

## Lessons-Learned Cadence

### Weekly (Every Monday Pre-Market)
- Analyze all wheel tickers against the 10 strategies and current regime
- Log analysis to `strategy_analysis` records in DB
- Generate "Week in Review" email: which signals fired, which theses held, which failed, what was learned

### Monthly (1st of Every Month)
- Synthesize all weekly lessons from the prior month
- Identify patterns: which strategies are working in the current regime, which are not
- Update confidence calibration: are our 0.8+ conviction calls actually hitting at >80%?
- Generate "Monthly Strategy Review" email with compounding insight narrative

### Post-Trade (Every Closed Position)
- Log: ticker, strategy used, regime at entry, entry/exit price, P&L, did the thesis play out?
- Capture the lesson: was the entry signal clean? Was the stop respected? Was the exit disciplined?
- Feed into weekly digest for pattern recognition

---

## Anneal Log

- 2026-04-13: Framework created. Integrated with strategy_advisor.py, weekly/monthly digest pipeline, and market_loop.py triggers.
