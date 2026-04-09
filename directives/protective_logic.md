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
