# Daily Journal — SOP

## Purpose

Produce one living document per trading day that captures:

1. **The raw dump** — every insight / observation / signal recorded during the session
2. **The daily summaries** — P&L, positions, regime, signal counts (the existing status/daily reports)
3. **The wrap-up** — a synthesized narrative: what strategies were pursued, what was gleaned, and how that changes tomorrow

The journal is the permanent institutional memory of the trading desk. `MEM.md` is a rolling state snapshot; the journal is the append-only ledger you can read a year from now and understand exactly why a decision was made.

---

## File Layout

```
trading/
  journal/
    YYYY-MM-DD.md            # the daily wrap-up (the deliverable — readable narrative)
  logs/
    insights/
      YYYY-MM-DD.jsonl       # raw intraday insight dump (append-only, structured)
```

- `.jsonl` files are the source of truth for the day's raw observations.
- `.md` journal files are generated (or regenerated) from those + the DB + the policy/whale caches.
- Journal files are committed. `.jsonl` insight logs are NOT committed (they live under `logs/`, which is already gitignored).

---

## Inputs (what the wrap-up pulls from)

| Source | Captured | Reason |
|--------|----------|--------|
| `logs/insights/YYYY-MM-DD.jsonl` | Free-form insights logged during the session | The raw dump |
| `decision_logic` DB table | Every trade decision fired today | What was actually executed |
| `strategy_analysis` DB table | Any pre-trade analyses run today | What we thought before acting |
| `strategy_lessons` DB table | Any post-trade lessons logged today | What we learned from closes |
| `logs/policy_signal_cache.json` | Policy signals seen today | Exogenous catalysts |
| `whale_hits_session` (in-memory → logged via `log_insight`) | Whale trades that triggered | Smart-money tail |
| Alpaca account + positions | End-of-day P&L, holdings | Performance snapshot |
| Regime detector output | Final regime + SPY change | Context framing |

---

## Outputs

### `logs/insights/YYYY-MM-DD.jsonl` (raw dump)

One JSON object per line. Every module can append via `log_insight()`. Example:

```json
{"ts":"2026-04-15T14:32:11Z","source":"whale_watch","category":"signal","insight":"Pelosi bought $50K NVDA — within 1min ROC +0.42%","metadata":{"ticker":"NVDA","roc":0.42}}
{"ts":"2026-04-15T15:01:04Z","source":"wheel","category":"decision","insight":"Sold PLTR $22 CSP 5/2 for $0.68 (delta=0.26)","metadata":{"ticker":"PLTR","credit":0.68}}
{"ts":"2026-04-15T18:44:00Z","source":"manual","category":"observation","insight":"Tariff headline hit mid-session — IV jumped, sector rotation out of semis"}
```

### `journal/YYYY-MM-DD.md` (wrap-up)

Synthesized at EOD (4:15 PM ET, right after the existing daily report). Structured as:

```markdown
# Trading Journal — 2026-04-15

**Regime:** BEAR (SPY -1.2%, VIX 28.4)
**Mode:** paper
**Equity:** $98,432.10 (-$412.88 realized, +$88.20 unrealized)

## Daily Summary
<2-3 sentences: what happened today, net direction, headline events>

## Strategies Pursued
- **Wheel:** scanned 18 tickers, opened 2 CSPs (PLTR, RTX), closed 1 (NVDA 50% profit)
- **Hedge:** SQQQ position maintained at 3% (BEAR regime)
- **Whale follow:** skipped 1 signal (EXTREME_BEAR guardrail)
- **Policy:** 2 EOs logged, 1 DoD award mapped to AVAV (no auto-execute — below confidence threshold)

## Signals Observed
### Policy (2)
- 14:02 ET — EO on critical minerals → sectors: mining, MP, USAR
- 15:38 ET — DoD award to Raytheon $412M → RTX confirm

### Whale (3, 1 actioned)
- Pelosi → NVDA $50K (ACTIONED: bought 12 shares @ $118.40)
- Kelly → AAPL $25K (below ROC threshold)
- Davidson → LMT $40K (skipped — EXTREME_BEAR guardrail)

### Research (NotebookLM bridge)
- 1 brief ingested — top signal: PLTR conviction 8 (wheel_eligible)

## Decisions & Trades
| Time | Ticker | Action | Tier | Conviction | Result |
|------|--------|--------|------|------------|--------|
| 09:45 | PLTR | SOLD_CSP | wheel | 0.78 | filled @ $0.68 |
| 10:22 | NVDA | BUY | whale_watch | 0.71 | filled @ $118.40 |
| 13:10 | NVDA_CSP | CLOSED | wheel | — | +$34 (50% profit rule) |

## Insights & Lessons
<synthesized from insights JSONL + strategy_lessons table — the meat of the learning>
- **Observation:** Tariff headlines continue to dominate intraday — IV expansion in 30min windows.
  **Implication:** Better to sell CSPs mid-session once IV spike normalizes (not at open).
- **Confirmation:** Wheel 50%-profit rule fired correctly on NVDA_CSP. Keep.
- **Challenge:** Whale signal latency ~2hr behind CapitalTrades publish. Consider tightening roc_lookback.

## What Changes Tomorrow
<explicit, actionable — these feed back into config/strategy_params.yaml if persistent>
- Keep delta target tightened at 0.25 (BEAR regime persists).
- Watch AVAV pre-market (DoD contract tailwind).
- If SPY opens > -3%, consider lightening SQQQ by 1%.
- Re-check whale signal lookback if another 2hr-lag signal hits.

---
*Generated by execution/daily_journal.py at 16:18 ET*
```

---

## Operational Flow

### Intraday (throughout market hours)

Any module can append an insight:

```python
from execution.daily_journal import log_insight

log_insight(
    source="wheel",
    category="decision",
    insight="Sold PLTR $22 CSP 5/2 for $0.68 (delta=0.26)",
    metadata={"ticker": "PLTR", "credit": 0.68, "delta": 0.26},
)
```

Sources (canonical): `wheel`, `whale_watch`, `policy`, `regime`, `hedge`, `protection`, `advisor`, `notebooklm`, `manual`, `system`.
Categories: `signal`, `decision`, `observation`, `error`, `learning`.

### End of day (4:15 PM ET)

`market_loop.py` calls `daily_journal.wrap_up()` right after `notifier.daily_report()`. The wrap-up:

1. Reads today's `insights/YYYY-MM-DD.jsonl`
2. Queries DB for today's rows in `decision_logic`, `strategy_analysis`, `strategy_lessons`
3. Reads `logs/policy_signal_cache.json` (today's entries)
4. Pulls EOD account snapshot + current regime
5. Sends all of the above to Claude with a synthesis prompt
6. Writes `journal/YYYY-MM-DD.md`
7. Emails the wrap-up via `notifier.daily_wrap_up()`
8. Appends a one-line summary to `MEM.md` under "Learnings & Annealings"

### Manual operations

```bash
# Log an ad-hoc observation
python execution/daily_journal.py --log "Tariff news moved semis -4% in 20min" --source manual --category observation

# Force-generate today's wrap-up (e.g., if the loop missed it)
python execution/daily_journal.py --wrap-up

# Regenerate a past day's wrap-up from logs + DB (idempotent)
python execution/daily_journal.py --wrap-up --date 2026-04-14

# Print today's raw insight dump
python execution/daily_journal.py --show
```

---

## Self-Annealing Loop

Every wrap-up ends with **What Changes Tomorrow**. Those bullets are the learning signal. When a bullet recurs across 3+ days, it's no longer a day-specific tweak — it's a rule, and should be promoted to:

- `config/strategy_params.yaml` (if it's a numeric parameter change)
- `directives/*.md` (if it's a process change)
- A new check in the relevant execution script (if it's mechanical)

This is how the system compounds: journal → pattern → rule → code.

---

## Guardrails

- The wrap-up **never** exposes credentials, API keys, or raw PII. It only synthesizes structured trading data.
- If `ANTHROPIC_API_KEY` is missing, the wrap-up still writes the journal file using a templated summary (no synthesis) — do not fail silently.
- If the DB is unavailable, the wrap-up uses only the `.jsonl` dump + state files — still produces a usable journal.
- Journal files are append-only in spirit: once committed, treat them as historical. Corrections go in a new day's entry.
