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

- **2026-08-07**: **FJET — define the exit:** With -$7,779 unrealized on a 4,570-share position in a thinly-traded AMEX micro-cap, set a hard rule: if FJET closes below $3.80 (prior day's close), begin partial liquidation of available 309 shares. Document max loss tolerance for this position explicitly. Do not add to it.

- **2026-08-06**: **FJET — requires explicit exit decision:** Define a stop or managed exit threshold NOW. At $3.80 vs $5.70 avg entry, the position needs either a documented hold thesis (with price target and time horizon) or a staged liquidation plan. With only 309 shares available, check margin/borrow constraints. If no thesis exists, begin reducing — do not let -$8.7K unrealized grow further by default.

- **2026-08-05**: **FJET — Determine share lock cause immediately:** Pull open orders and existing options on FJET before the bell. If a short call exists, review strike vs. current price ($3.745). If shares are margin-locked, assess whether a partial liquidation to cut the position is appropriate given the -34% drawdown. Do not hold 4,570 shares passively without a defined exit thesis.

- **2026-08-04**: **Fix wheel scanner loop:** Add a per-ticker, per-expiry dedup cache so that `SKIP CSP [TICKER] — earnings inside expiry window` logs only *once per session* per ticker/expiry pair, not every 65 seconds. This is generating ~300 junk log entries per day and masking real signal volume.

- **2026-08-03**: **[FJET — URGENT]** Investigate why 4,261 of 4,570 shares are unavailable (`qty_available = 309`). If margin lock: assess whether reducing position is possible. If a partial assignment artifact: confirm status. Set a manual exit target: consider selling the 309 available shares near open if FJET shows continuation above $3.85. Do not average down further.

- **2026-07-31**: **FJET — Investigate share lock immediately at open:** Determine why only 309/4,570 shares are qty_available. If covered call is outstanding, identify strike/expiry. If margin hold, assess whether adding capital or reducing position releases shares. This is the #1 priority — a 37% loss position with locked shares and no exit flexibility is a structural risk.

- **2026-07-30**: **Fix wheel scan loop immediately:** The scan is re-evaluating and re-logging identical SKIP decisions every ~60 seconds. Add a session-level deduplication cache: if `(ticker, reason, expiry)` tuple was already logged this session, suppress re-logging. This is the #1 system issue today.

- **2026-07-29**: **Fix the wheel skip-log spam immediately.** Add session-level dedup: once a ticker is logged as skipped for a given reason+expiry, suppress further identical entries until session reset. 1,400 log entries for 5 skip decisions is a noise/storage problem that will bury real signals.

- **2026-07-28**: **Fix the wheel loop:** Add a session-level cache so earnings-blocked tickers (MP, GEO, CCJ, ALB, KTOS vs. Aug 14 expiry) are excluded at scan initialization, not re-evaluated every 60 seconds. This eliminates ~150 wasted decision records per day.

- **2026-07-27**: **Fix wheel loop deduplication:** Add session-level cache so CCJ/MP/GEO earnings-blocked SKIPs fire **once per session**, not every 60 seconds. This is a config/logic fix — the current behavior generated ~150 redundant log entries today with zero informational value.

- **2026-07-24**: **FJET covered call:** Evaluate writing covered calls on the 309 available shares immediately at open. With IV rank 50%, target the Aug 7 $3.50 or $4.00 strike. Check why 4,261 shares are unavailable (`qty_available = 309`) — resolve or document the restriction before market open.

- **2026-07-23**: **🔴 Fix MP skip-loop deduplication immediately:** Add a session-level or DB-level check: if `(ticker='MP', expiry='2026-08-07', action='SKIP', date='2026-07-24')` already exists in decision_logic, suppress re-insert. Do not log again until expiry or ticker changes.

- **2026-07-22**: **FJET — Define exit criteria NOW.** With current price $3.70 and avg entry $5.70, this position has no technical floor defined in the data. Before the open, establish a hard stop: either exit all 309 available shares at market open, or set a limit to liquidate available qty if FJET trades below $3.50. Do not let another 8% day pass without action.

- **2026-07-21**: **FJET — Define exit threshold NOW:** With only 309 shares available and -29.7% unrealized, set a hard stop-review: if FJET fails to hold $4.00 on open, begin scaling out the 309 available shares. Do not average down. Target: reduce position size, not increase it.

- **2026-07-20**: **FJET — Assess exit immediately at open.** Current price $3.72, avg entry $5.70, -34.8% unrealized. Clarify why only 309/4,570 shares are qty_available — if locked by margin restriction, this is a forced-hold risk. If tradable, evaluate whether to cut the remaining available 309 shares to reduce exposure. Do not add. This position is the single largest systemic risk to the account.

- **2026-07-17**: **FJET — Investigate share availability lock immediately at open.** Determine why only 309/4,570 shares are available. If a GTC sell order exists, confirm price and adjust if bid is unreachable at current $3.825. If margin hold, assess whether broker is approaching a margin call threshold.

- **2026-07-16**: (Claude synthesis unavailable — set ANTHROPIC_API_KEY for actionable forward-looking carryforward)

- **2026-07-15**: **FJET triage first:** At open, evaluate whether a stop-loss or partial liquidation is warranted. At $4.365 with avg entry $5.702 and -23.5% drawdown, continued holding requires a documented thesis. If no recovery catalyst exists, set a hard stop at $4.00 or begin scaling out the 309 available shares immediately. Do not let this become a permanent capital impairment.

- **2026-07-14**: **FJET — assess exit/hedge:** With only 309 shares available, determine immediately why 4,261 shares are restricted. If it's a settlement issue, clarify T+1 availability. If open orders are holding them, cancel and re-evaluate. At $4.72 vs. $5.70 avg entry, the position needs a defined max-loss level or covered call to reduce cost basis. Suggest selling covered calls on available shares at the $5.00 strike (nearest OTM) if IVR recovers above 20%.

- **2026-07-13**: **[URGENT — Engineering]** Fix the FJET CSP candidate loop: add quarantine-status check to the **wheel candidate generator** (upstream of risk_gate), not just the gate itself. Target: zero blocked-CSP log entries for quarantined tickers. This is generating ~320 wasted cycles/day.

- **2026-07-10**: **[CRITICAL — Engineering] Fix FJET CSP signal loop:** The signal generator must check the quarantine list *before* generating a CSP candidate signal for FJET. Add a pre-filter step: `if ticker in QUARANTINE_LIST: skip signal generation`. This eliminates ~170 wasted risk_gate evaluations per session.

- **2026-07-09**: (Claude synthesis unavailable — set ANTHROPIC_API_KEY for actionable forward-looking carryforward)

- **2026-07-08**: **CCJ P98 ($7.80, -108%):** This position requires immediate review at open. With 23 days to expiry and $7.80 premium, intrinsic value is deep. Evaluate closing the short put (buy to close) to stop further delta bleed, or rolling down-and-out to a later expiry at a lower strike to recapture time value. Do not hold passively to expiry.

- **2026-07-07**: (Claude synthesis unavailable — set ANTHROPIC_API_KEY for actionable forward-looking carryforward)

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
