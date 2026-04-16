# Trading Journal

One file per trading day: `YYYY-MM-DD.md`.

These files are the permanent narrative record of the desk. They are:

- **Generated** at 4:15 PM ET by `execution/daily_journal.py` (fired from `market_loop.py` after the daily report).
- **Synthesized** from: the day's raw insight dump (`logs/insights/YYYY-MM-DD.jsonl`), DB rows for today (`decision_logic`, `strategy_analysis`, `strategy_lessons`), the policy signal cache, and the EOD Alpaca snapshot.
- **Emailed** to the alert address via `notifier.daily_wrap_up()`.
- **Committed** to the repo — this directory is NOT gitignored.

## Sections

Every journal file contains:
1. **Daily Summary** — what happened, net direction, headline driver
2. **Strategies Pursued** — which tiers fired (wheel, whale, policy, hedge) and what they did
3. **Signals Observed** — policy / whale / research breakdown
4. **Decisions & Trades** — table of every executed action
5. **Insights & Lessons** — synthesized learnings (Observation / Confirmation / Challenge / Pattern)
6. **What Changes Tomorrow** — actionable, specific carryforward

## Regenerating a past day

```bash
python execution/daily_journal.py --wrap-up --date 2026-04-15
```

Idempotent — re-running overwrites the file from current DB + log state.

## Logging an ad-hoc insight

```bash
python execution/daily_journal.py --log "Tariff news hit semis -4% in 20min" --source manual --category observation
```

Or from any Python module:

```python
from execution.daily_journal import log_insight
log_insight(source="wheel", category="decision", insight="...", metadata={...})
```

See `directives/daily_journal.md` for the full SOP.
