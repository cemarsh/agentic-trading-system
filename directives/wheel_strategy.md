# Directive: The Wheel Strategy

**Version**: 1.0
**Tier**: 2
**Script**: `execution/wheel_strategy.py`

---

## Goal
Generate consistent options premium income by running the Wheel on high-liquidity tickers. The Wheel is capital-efficient: it either collects premium (puts/calls expire worthless) or acquires shares at a discount.

## Inputs
- Ticker list (`strategy_params.yaml → wheel.tickers`)
- Target put delta (`target_delta`)
- Expiration weeks (`expiration_weeks`)
- CC strike markup (`cc_strike_markup_pct`)
- Minimum premium threshold (`min_premium_pct`)

## Stage 1 — Cash Secured Put
**Precondition**: No open CSP or CC on this ticker (stage = 0).

1. Get current underlying price via Alpaca 1-min bar
2. Compute strike at approximate target delta (OTM %)
3. Select expiry = nearest Friday N weeks out
4. Query Alpaca options chain for matching contract
5. Confirm premium >= `min_premium_pct` of strike
6. Submit SELL_PUT order
7. Set position stage = 1

**Expected outcome**: Put expires worthless → collect premium → reset to stage 0

**Assignment outcome**: Shares assigned → proceed to Stage 2

## Stage 2 — Covered Call
**Precondition**: Assigned shares in account (stage = 2, shares_held >= 100).

1. Compute CC strike = cost_basis × (1 + cc_strike_markup_pct / 100)
2. Select expiry = nearest Friday N weeks out
3. Query options chain for matching call
4. Submit SELL_CALL order
5. Set cc_strike and cc_expiry on position

**Expected outcome**: Call expires worthless → collect premium → continue with Stage 2
**Assignment outcome**: Shares called away at profit (above cost basis) → reset to stage 0

## Outputs
- SELL_PUT or SELL_CALL orders submitted
- Position state tracked in `wheel_positions` dict
- Decisions logged to `decision_logic` table
- Position entry in `MEM.md` Wheel Stage Tracker

## Edge Cases
- **No matching contract at computed strike**: Skip this ticker this cycle. Try again next cycle with fresh price data.
- **Premium below minimum**: Skip. Force is not required — wait for better entry.
- **Assignment detection**: Alpaca positions endpoint will show shares. Sync on each loop tick.
- **Early assignment (American-style)**: Handle in `sync_positions`. If shares appear unexpectedly, move to Stage 2.

## Anneal Log
- (none yet)
