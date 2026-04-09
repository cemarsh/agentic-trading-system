# Directive: Whale Watch (Smart Money Surveillance)

**Version**: 1.0
**Tier**: 1
**Script**: `execution/whale_watch.py`

---

## Goal
Monitor politician trade disclosures. When a tracked trade meets the value threshold AND passes confidence scoring, enter a position aligned with the smart money move.

## Inputs
- Politician names list (`strategy_params.yaml → whale_watch.politician_names`)
- Minimum trade value (`whale_trade_min_value`)
- Max portfolio allocation per trade (`max_portfolio_pct_per_trade`)
- Minimum confidence score (`min_confidence_score`)

## Process
1. Fetch CapitalTrades disclosure page via `execution/whale_watch.py`
2. Filter rows matching tracked politician names
3. Filter rows where trade value >= `whale_trade_min_value`
4. For each qualifying trade, call `score_trade()`:
   - Fetch 1-min ROC via Alpaca (`execution/alpaca_client.py`)
   - Compute confidence score (base + ROC contribution + value contribution)
5. If confidence >= `min_confidence_score`:
   - Compute share quantity based on `max_portfolio_pct_per_trade` of current equity
   - Check manual confirm guardrail (first N trades)
   - Submit market order via Alpaca
   - Log to `decision_logic` table

## Outputs
- Market order submitted to Alpaca
- Decision logged to PostgreSQL
- Entry in `MEM.md` Whale Watch Log

## Edge Cases
- **CapitalTrades page structure changes**: Scraper will fail silently. Check logs. Update BeautifulSoup selectors and anneal.
- **Low liquidity ticker**: ROC will be 0; confidence will be lower. May not meet threshold — correct behavior.
- **After-hours disclosure**: Trade queued but ROC computed on stale data. Flag and wait for next market open.
- **Politician sells**: Side is "sell" — only enter if you hold the position already. Do not short.

## Anneal Log
- **2026-04-09**: CapitalTrades page structure differs from assumed format. Real layout:
  - `cell[0]`: `"NamePartyChambeerState"` — extract name by splitting on party keyword
  - `cell[1]`: `"Company NameTICKER:US"` — extract ticker via regex `([A-Z]{1,5}):US`
  - `cell[6]`: trade type `"buy"` or `"sell"`
  - `cell[7]`: value range `"1K–15K"` — parse to midpoint float
  - Non-equity instruments (treasuries, bonds) have `N/A` ticker — skip them
