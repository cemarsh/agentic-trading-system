# Directive: Derivatives Portfolio — Account C

**Effective**: 2026-05-28  
**Account**: Account C (new Alpaca paper account — credentials in .env as ALPACA_KEY_C / ALPACA_SECRET_C)  
**Mandate**: Aggressive, derivatives-focused growth. Premium income via high-probability structures, directional plays on signal convergence, event-driven IV plays.  
**Authority**: Separate execution lane from Account A (wheel income). No cross-account position sharing.

---

## Core Philosophy

Account A (wheel) sells covered risk. Account C sells structured risk.

The difference: Account C uses multi-leg structures that define, cap, or eliminate the losing side entirely. This allows more aggressive entries, higher frequency, and better capital efficiency than naked puts alone.

Every position must answer three questions before entry:
1. **What is IV doing?** (IVR/IVP gate — see Section 1)
2. **What is the regime doing?** (BULL/NEUTRAL/BEAR/EXTREME_BEAR — see Section 4)
3. **What is the max loss?** (Position sizing — every strategy below has a hard cap)

If any of the three is unclear, the answer is: skip.

---

## Section 1 — IV Rank Gate (Master Entry Filter)

This runs before every strategy decision. No exceptions.

| IVR | IVP | Action |
|-----|-----|--------|
| ≥ 50 | ≥ 75 | **Sell premium aggressively** — iron condor, jade lizard, BWB, CSP |
| 30–49 | 50–74 | **Sell premium conservatively** — iron condor or jade lizard only |
| 25–29 | any | **Transition zone** — vertical spreads only, 50% normal size |
| < 25 | < 25 | **Buy premium** — LEAPS, long calls/puts, debit verticals |
| Divergent | (IVR/IVP disagree by >20 points) | **Skip** or reduce size 50% |

**Computing IVR and IVP**: The `iv_tracker.py` module stores daily IV snapshots per ticker. IVR and IVP are computed from the rolling 252-day window. Until 30+ days of history accumulate, use a conservative default (treat as transition zone, 50% size).

---

## Section 2 — Strategy Catalog

### 2A — Broken Wing Butterfly (BWB) — PRIMARY STRATEGY

**Why lead with this**: Highest Sharpe of any options strategy (~1.4–1.8). Enters for a net credit (you get paid). Risk is defined and limited to one side. ~35% annualized return on buying power at 65–80% win rate.

**Entry conditions**: IVR ≥ 30, DTE = 21 days, NEUTRAL or BULL regime, no earnings within 21 days.

**Construction (put BWB — neutral-to-bullish):**
```
Buy  1 put at ~30 delta (body top)
Sell 2 puts at ~25 delta (body center — where price should land)
Buy  1 put at ~15 delta (broken wing — 2× the width of narrow side)
```
Example on $150 stock: Buy $145P, Sell 2× $140P, Buy $130P
- Narrow side width: $5
- Broken side width: $10 (2× narrow)
- Target net credit: 12–15% of narrow width = $0.60–$0.75 per spread

**Tickers**: SPY, QQQ, and any wheel ticker where 21-DTE contracts exist with adequate liquidity (bid-ask spread < $0.10 on the body strikes).

**Exit rules:**
1. Close at 30–60% of initial credit received
2. Hard close at 7 DTE regardless of P&L
3. Breach of body center (stock hits short strikes) → close immediately, gamma explodes
4. Loss limit: 3× initial credit received

**Position sizing**: 2–3% of Account C equity per BWB. Max 4 concurrent BWBs = 12% of equity.

**Regime adjustments:**
- BULL: Use call BWB (mirror construction on call side), body above current price
- NEUTRAL: Put BWB with body just below ATM
- BEAR: Skip — trending markets breach the body too often
- EXTREME_BEAR: No new entries

---

### 2B — Iron Condor — NEUTRAL REGIME WORKHORSE

**Entry conditions**: IVR ≥ 30, DTE = 45 days, NEUTRAL regime, stock range-bound 15+ trading days, no earnings within DTE window.

**Construction:**
```
Sell put at 20–25 delta
Buy  put at 5–10 delta  (put spread: 5–10 points wide)
Sell call at 20–25 delta
Buy  call at 5–10 delta (call spread: same width as put side)
```
Target credit: 30–35% of wing width. On a 10-point wing: ≥ $0.30/share = $30/contract minimum. Below this credit, skip.

**Preferred underlyings for condors**: SPY, QQQ, IWM, GLD (liquid index ETFs with tight bid-ask). Avoid single-name stocks for condors due to gap risk.

**Multi-leg submission**: Submit as single `mleg` order via `POST /v2/orders` with `order_class: "mleg"` — all 4 legs atomic.

**Exit rules (strictly mechanical):**
1. Close at 50% of credit received — primary rule, no exceptions
2. Close at 21 DTE if 50% not reached — time stop
3. Force close at 7 DTE regardless of status
4. If short strike is breached: close the losing spread only, reprice and re-enter condor at new price center

**Position sizing**: 3–5% of equity per condor. Max 5 concurrent = 25% of equity.

**Regime adjustments:**
- BULL: Shift call side 2 strikes higher. Ratio 18-delta put / 22-delta call (leaning bullish)
- NEUTRAL: Standard construction
- BEAR: Close all condors immediately if short put strike is within 2% of price. Do not open new condors.
- EXTREME_BEAR: No new entries. Close existing immediately.

---

### 2C — Jade Lizard — BULLISH REGIME WITH IV SKEW

**Why use this**: Eliminates upside assignment risk entirely. If the stock gaps up through the call spread, you still have zero loss on the call side (by construction). The only remaining risk is to the downside.

**Entry conditions**: IVR ≥ 30, put IV > call IV by 40%+ (negative skew), neutral-to-bullish bias, stock down 5–15% from recent high (mean reversion setup), DTE = 45 days.

**Construction:**
```
Sell put at 20–30 delta
Sell call at 15–20 delta
Buy  call at 5–10 points above short call
```
**Critical check**: Total credit received > call spread width. If credit is $2.80 and call spread is $3.00, do NOT enter — upside risk is not fully eliminated. This check is non-negotiable.

**Exit rules:**
1. 50% profit target, 21 DTE time stop
2. If put is threatened (stock drops through short put): close ENTIRE position, do not leg out
3. If stock rips through call spread: position remains profitable — let decay or close for small debit

**Position sizing**: 3–5% of equity per jade lizard. Max 3 concurrent = 15% of equity.

---

### 2D — Vertical Spreads — SIGNAL-TRIGGERED DIRECTIONAL

**Entry conditions**: Signal from whale_watch (confidence ≥ 0.80) OR policy_monitor (tier 1 or 2) on a specific ticker. IVR 25–50 (elevated but not extreme). DTE = 30–45 days.

**Construction (bull put credit spread for bullish signal):**
```
Sell put at 30 delta
Buy  put at 15 delta
Width: 5–10 points
Credit: 30–40% of spread width
```

**Auto-sizing from signal confidence**:
```python
position_pct = base_size_pct * confidence_score
# base_size_pct = 3.0, confidence = 0.85 → 2.55% of equity
```

**Exit rules**: 50% profit target, 21 DTE time stop, stop loss at 50% of credit paid.

**Position sizing**: 5% of equity per vertical (defined risk allows larger allocation). Max 6 concurrent = 30% of equity.

---

### 2E — LEAPS + Poor Man's Covered Call (PMCC)

**Entry conditions**: Directional conviction ≥ 0.80 from strategy_advisor, IVR < 25 (low IV = cheap to buy), no near-term catalyst that could reverse the thesis.

**Construction:**
```
Buy  call at 70–85 delta, 18 months DTE
Sell call at 30 delta, 30–45 DTE (against the LEAPS)
→ Roll the short call monthly to reduce cost basis
```

**Roll when**: Short call reaches 21 DTE, close and sell next month's 30-delta call.
**Exit LEAPS when**: DTE drops below 9 months (roll to new 18-month contract).

**Position sizing**: 5–8% of equity per LEAPS position. Max 4 LEAPS = 32% of equity.

---

### 2F — Event-Driven Plays

**FOMC Iron Condor:**
- Enter 2–3 days before FOMC, 7–10 DTE SPY condor, 16-delta each side
- Exit immediately after rate announcement
- Max 2 contracts, max 2% of equity
- Skip if VIX > 30 going into the meeting

**Earnings IV Crush (short straddle/strangle):**
- Enter 1–2 days before earnings, IVR > 70
- Sell ATM straddle; close immediately after announcement
- Target 25–40% credit in 24 hours
- Only enter if premium > 1.5× expected move priced in
- Max 2% of equity per earnings play

**Earnings IV Expansion (long strangle before):**
- Enter 7–10 days before earnings, IVR < 30
- Buy 20–25 delta strangle, 45–60 DTE
- Close 1–2 days before the announcement (sell into IV expansion)
- Max 2% of equity (premium at risk)

---

## Section 3 — Position Limits (Hard Caps)

| Strategy | Max Concurrent | Max % Each | Max Total % |
|----------|----------------|------------|-------------|
| BWB | 4 | 3% | 12% |
| Iron Condors | 5 | 5% | 25% |
| Jade Lizards | 3 | 5% | 15% |
| Vertical Spreads | 6 | 5% | 30% |
| LEAPS / PMCC | 4 | 8% | 32% |
| Event Plays | 3 | 2% | 6% |
| **Total deployed** | — | — | **≤ 85%** |

**Delta-Theta ratio rule**: Total portfolio delta / total portfolio theta must stay ≤ 0.5. If delta exceeds this, the portfolio has drifted directional — reduce size or add offsetting positions.

---

## Section 4 — Regime-Based Strategy Selection

| Regime | Lead Strategy | Secondary | Avoid |
|--------|--------------|-----------|-------|
| BULL | Jade lizard, bull put spreads, call BWB | Iron condor (shifted calls) | Bear-biased anything |
| NEUTRAL | Iron condor, put BWB | Jade lizard, vertical spreads | Naked directional |
| BEAR | Bear call spreads, long put verticals | Jade lizard (15-delta put) | Iron condors, BWB |
| EXTREME_BEAR | No new entries — manage existing only | Close all BWBs/condors with < 50% profit | Everything |

---

## Section 5 — Portfolio Allocation by Regime

| Bucket | BULL | NEUTRAL | BEAR | EXTREME_BEAR |
|--------|------|---------|------|--------------|
| Theta / premium sell | 30% | 50% | 20% | 0% |
| Directional spreads + LEAPS | 40% | 25% | 30% (puts only) | 0% |
| Event-driven | 10% | 10% | 5% | 0% |
| Cash / reserve | 20% | 15% | 45% | 100% |

---

## Section 6 — Data Sources

**Primary options data**: Alpaca `/v1beta1/options/snapshots/{underlying}` — returns delta, gamma, theta, vega, IV per contract.  
**Multi-leg orders**: `POST /v2/orders` with `order_class: "mleg"`, up to 4 legs.  
**IV rank**: Computed from `iv_history` table in Postgres (daily IV snapshots per ticker). Supplement with Tradier free API for ORATS-powered data when history < 30 days.  
**Real-time quotes**: `/v1beta1/options/quotes/latest` for bid/ask; mark = (bid+ask)/2.

---

## Section 7 — Anneal Log

- 2026-05-28: Directive created. Account C designated for derivatives mandate. BWB at 21 DTE is the primary strategy — highest Sharpe per research. Iron condors second. Multi-leg Alpaca API confirmed available in paper. IV rank via Tradier + Postgres accumulation.
