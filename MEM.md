# Strategy Memory

**Last Updated**: 2026-04-08
**Status**: INITIALIZED — awaiting first market session

---

## Open Positions

| Ticker | Tier | Type | Entry | Strike | Expiry | Qty | Cost Basis | Status |
|--------|------|------|-------|--------|--------|-----|------------|--------|
| —      | —    | —    | —     | —      | —      | —   | —          | —      |

---

## Wheel Stage Tracker

| Ticker | Current Stage | Put Strike | Put Expiry | Assigned? | Call Strike | Call Expiry |
|--------|---------------|------------|------------|-----------|-------------|-------------|
| —      | —             | —          | —          | —         | —           | —           |

---

## Whale Watch Log

| Date | Politician | Ticker | Trade Value | ROC Signal | Confidence | Action Taken |
|------|------------|--------|-------------|------------|------------|--------------|
| —    | —          | —      | —           | —          | —          | —            |

---

## P&L Summary

| Date | Realized P&L | Unrealized P&L | Total |
|------|-------------|----------------|-------|
| —    | —           | —              | —     |

---

## System Events

| Timestamp | Event Type | Detail |
|-----------|------------|--------|
| 2026-04-08 | INIT | System scaffolded — awaiting configuration |

---

## Active Strategy — April 2026 Tariff Regime

**Regime**: High-volatility tariff selloff. Elevated IV = fat premiums. Defensive tilt.
**Last Updated**: 2026-04-09

---

## Learnings & Annealings

- **2026-07-06**: **XOM sequencing fix:** Investigate why wheel opened XOM260724P00128000 at 16:59 and position_manager rolled it at 17:04. Add a `min_hold_before_roll_hours` guard (suggest: 24h minimum) to prevent same-session roll of freshly opened positions.

- **2026-07-02**: **MP260724P00057000 — URGENT:** At -119.6% with 22 DTE and mark at $5.95. Evaluate BTC immediately at open. Check whether a roll to 8/21 at $57 or lower strike can generate any credit. If no credit available, BTC to cap loss before it worsens. This is the highest-priority position.

- **2026-07-01**: **CCJ — urgent review:** Mark $7.50, strike $98, exp 7/31. Define max loss threshold now. If underlying does not recover above $98 by end of week, consider BTC to cap loss or roll to lower strike/later expiry. Do not let this reach expiry ITM without a decision.

- **2026-06-30**: **MP260724P00057000 — URGENT:** Strike $57, expiry July 24, current price $4.65 vs. $2.71 entry, -71.6% unrealized. With 17 trading days to expiry, assess whether to buy-to-close now (lock ~$194 loss) or roll. If MP continues rallying toward $57, loss accelerates sharply. Set a hard stop: if MP closes above $52, close or roll immediately.

- **2026-06-29**: **CRITICAL — Fix the same-session BTC loop:** Add a guard: if `position_age_hours < 4` (or `dte_at_open == dte_current`), skip the 21-DTE BTC/roll check entirely. Do not allow position_manager to close a position opened in the same session.

- **2026-06-26**: (Claude synthesis unavailable — set ANTHROPIC_API_KEY for actionable forward-looking carryforward)

- **2026-06-25**: **FJET risk review:** With $-5,677 unrealized and 4,261 shares locked (unavailable), determine what position is consuming the shares as collateral. If it's a covered-call or similar, assess whether rolling or closing the collar makes sense. Do not let FJET breach $4.00 without a defined exit plan — that level would push unrealized loss past $7,500.

- **2026-06-24**: **FJET — Urgent:** With only 309 shares available to sell, investigate why 4,261 shares are locked. If locked against nothing actionable, seek to free up shares and begin scaling out. At $4.18, a move to $3.50 adds another ~$3,100 loss. Set a hard stop-review at $3.90.

- **2026-06-23**: (Claude synthesis unavailable — set ANTHROPIC_API_KEY for actionable forward-looking carryforward)

- **2026-06-22**: (Claude synthesis unavailable — set ANTHROPIC_API_KEY for actionable forward-looking carryforward)

- **2026-06-18**: **FJET — Investigate locked shares immediately:** 4,261 of 4,570 shares are unavailable. Confirm whether a covered call is written against them and at what strike/expiry. If no hedge exists, this is unmanaged downside at -$2,106. If below the $5.24 price level by open, set a hard stop-loss review threshold or initiate a covered call to reduce cost basis.

- **2026-04-16**: (Claude synthesis unavailable — set ANTHROPIC_API_KEY for actionable forward-looking carryforward)

- **2026-04-09**: CapitalTrades scraper cell indices wrong. Fixed: name=cell[0], ticker=cell[1] regex, type=cell[6], value=cell[7] range midpoint.

---

## Verification Trade Counter

Manual confirmation required for first N trades. Progress: **0 / [NUMBER_OF_VERIFICATION_TRADES]**

---

## API Health

| Service | Last OK | Consecutive Failures |
|---------|---------|----------------------|
| Alpaca  | —       | 0                    |
| Postgres| —       | 0                    |
| Resend  | —       | 0                    |
