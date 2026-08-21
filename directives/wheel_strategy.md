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

## Entry Gates (order of evaluation)

A CSP must clear every gate below. Each is a hard reject, not a warning.

| # | Gate | Config | Rejects |
|---|------|--------|---------|
| 0 | Book health *(cycle-level)* | `max_book_loss_pct` 15% | Any new CSP while the book's total unrealized loss exceeds 15% of equity |
| 0a | Losing underlying | `skip_losing_underlying` | A name we already hold at a loss |
| 0b | IV rank | `min_iv_rank`, `iv_gate_fail_open` | Cheap premium; **fail-closed** — no history, no trade |
| 1 | Allocation cap | `max_wheel_allocation_pct` 65% | Book already fully deployed |
| 2 | Per-trade cap | `max_portfolio_pct_per_trade` 15% | Underlying too expensive for the account |
| 3 | Earnings | `earnings_gate` | Expiry window contains an earnings date |
| 4 | Risk gate | `risk.*` | Quarantine + sector-correlation caps |
| 5 | Credit floor | `min_credit_per_share`, `min_premium_pct` | Absolute premium too thin |
| 5b | **Expected value** | `min_otm_vol_mult` 1.0, `min_credit_vs_expected_move` 0.15 | Strike inside 1σ, or credit < 15% of the 1σ move |
| 6 | Sized re-check | `risk.*` | The *sized* order breaching a cap |

**Why gate 0 exists (added 2026-08-21):** the wheel read the universe list and nothing else,
so it opened into an already-bleeding book — on one W26 morning it sold six new CSPs while the
position manager was closing and rolling the same names. v2.1 shipped `position_ledger` for
exactly this coordination and the wheel was never wired to it.

**Why gate 5b exists (added 2026-08-21):** the credit floors bound premium in absolute terms
but say nothing about what is risked to earn it, and `select_csp_strike()` places every name at
the same ~6.25% OTM regardless of volatility — far away on a quiet name, inside a normal week's
range on KTOS or RKLB. Both sub-gates measure against the underlying's own 1-sigma move over the
holding period (`spot × daily_vol × √DTE`).

Note this is **not** "credit ÷ max loss at the stop". With a percentage stop that ratio is
`C / (2.5 × C)` = 0.4 for every trade ever placed, so it can never reject anything. The expected
move is what the premium is actually being paid to cover. Both sub-gates **fail open** when
realized vol is unavailable, so an unmeasurable vol cannot become a second silent IV gate.

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
