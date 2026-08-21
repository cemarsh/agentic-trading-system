# Directive: Protective Logic

**Version**: 1.0
**Tier**: 3
**Script**: `execution/protective_logic.py`

---

## Goal
Protect all equity positions from catastrophic loss using trailing stops, gap-down tightening, and ladder buying on drawdowns.

## Inputs
- Trailing stop % (`strategy_params.yaml → protection.trailing_stop_pct`)
- Gap tighten % (`gap_tighten_pct`)
- Ladder drop % (`ladder_drop_pct`)
- Ladder buy shares (`ladder_buy_shares`)

## Catastrophic Loss Floor (added 2026-08-21)

**Applies to EVERY equity long, including `no_auto_manage` names.**

`no_auto_manage` was added 2026-06-16 to stop the ladder averaging down into FJET. It did
that by dropping those tickers out of `sync_positions()` entirely — which also removed their
trailing stop, leaving them with **no exit at all**. FJET then fell for six consecutive weeks
to −31% (−$8,637, more than the whole quarter's gross win total) with nothing watching it.

1. `check_catastrophic_loss()` reads **live broker positions**, not `self._positions`,
   specifically so quarantined names cannot hide from it
2. Long equity only — a losing short leg needs a buy-to-cover, not this rule's sell
3. Breach = `(entry − price) / entry >= max_equity_loss_pct` (25%)
4. Fires **once per ticker** via `guards.acted_once`, persisted in `agent_state.json`,
   so a restart loop cannot resubmit the liquidation
5. Full-size market sell + `critical_alert`

This is deliberately far outside the 7% trailing stop. It is not a strategy exit; it is the
floor that says the thesis has failed. Suppressing the ladder must never again mean
suppressing the exit.

## Trailing Stop Logic
1. On each loop tick, `sync_positions()` is called with current Alpaca positions
2. For each new position: `stop_price = entry × (1 - trailing_stop_pct / 100)`
3. As price rises: `high_water_mark` updates, `stop_price` ratchets up proportionally
4. Stop price never moves down
5. If `current_price <= stop_price` → execute market sell of full position

## Gap Protection
- Called when overnight data indicates gap-down risk (price gapping below support)
- Tightens stop by additional `gap_tighten_pct`
- New stop = `high_water_mark × (1 - trailing_stop_pct/100 - gap_tighten_pct/100)`
- Applied preemptively before market open when flag is set

## Ladder Buying
- Triggered when `current_price` drops `ladder_drop_pct`% below `entry_price`
- Buys `ladder_buy_shares` additional shares at market
- Lowers cost basis (averaging down)
- **WARNING**: Laddering in a trending decline will increase losses. Use conservatively.

## Outputs
- SELL orders on stop trigger
- BUY orders on ladder trigger
- All decisions logged to `decision_logic` table

## Edge Cases
- **Flash crash**: Stop fires at market price — may get worse fill than stop price in fast market. Normal behavior.
- **Multiple ladder triggers**: Each `ladder_drop_pct` from original entry triggers one ladder. Track count per ticker.
- **Options positions**: Protective logic applies to EQUITY only. Options have their own expiry-based risk.
- **After-hours gap**: Gap protection must be applied before market open. Run overnight check at 9:00 AM EST.

## Anneal Log
- (none yet)
