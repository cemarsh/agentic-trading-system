# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

An autonomous options-trading engine (Python, no framework) that runs as a systemd service on
**VM 117 `home-workstation`** (`ssh workstation`, user `ubuntu`, `/home/ubuntu/projects/trading`).
This WSL checkout is for development only — **never run the loop here.** A laptop/WSL host that
sleeps silently kills the service.

Trades Alpaca **paper** (`acct3`). Live mode exists but is gated in code, not by a flag.

## Commands

Everything runs from the **repo root** — state files are hard-coded relative paths
(`logs/agent_state.json`, `logs/heartbeat`, `logs/policy_signal_cache.json`, …). Running a module
from another CWD silently creates a second, empty state.

There is no dotenv loader; `config/settings.py` reads `os.environ` directly. Locally you must:

```bash
set -a; source .env; set +a          # systemd does this via EnvironmentFile=
source venv/bin/activate
```

```bash
# Tests — no pytest config; tests self-insert the repo root on sys.path
python -m pytest tests/ -q                              # full suite (65 tests, <1s)
python -m pytest tests/test_wheel_sizing.py -q          # one file
python -m pytest tests/test_risk_gate.py::test_name -q  # one test

# Lint / types (declared in requirements.txt; ruff runs on defaults, mypy reads mypy.ini)
ruff check .
mypy execution/        # mypy.ini sets explicit_package_bases — there are no __init__.py files

# The loop
python execution/market_loop.py --verify-only   # connectivity checks, exits nonzero on failure
python execution/market_loop.py --mode paper

# Individual subsystems (each has its own __main__)
python execution/iv_tracker.py --rank-all       # IV rank/percentile + gate verdict per ticker
python execution/iv_tracker.py --snapshot       # record today's IV (feeds the wheel's IV gate)
python execution/dynamic_universe.py --list     # policy-promoted wheel candidates
python execution/position_manager.py            # one close/roll cycle against live positions
python execution/daily_journal.py               # regenerate a day's wrap-up (idempotent)
python execution/heartbeat_check.py             # deadman check (normally on a 5-min timer)
python execution/dashboard_tui.py               # read-only terminal dashboard (--once, --from-file)
python execution/dashboard_serve.py             # web dashboard on 127.0.0.1:8765 (trading-dashboard.service)
```

### Deploy

```bash
ssh workstation 'cd ~/projects/trading && bash deploy/sync-check.sh'   # drift check, exit 1 = drifted
ssh workstation 'cd ~/projects/trading && bash deploy/deploy.sh'       # pull, deps, units, restart
ssh workstation 'journalctl -u trading -f'
ssh workstation 'journalctl -u trading --since today | grep -E "SELL CSP|WHEEL|RISK"'
```

`deploy.sh` does `git reset --hard origin/main` — **push before deploying; never leave work
uncommitted on the VM.** It re-execs itself once after the pull (so a changed deploy.sh takes
effect on the first run), and re-applies two host-level fixes that cloud-init wipes on rebuild:
IPv4 precedence in `/etc/gai.conf` (VM 117 has a global IPv6 address but no v6 route, so
dual-stack APIs hang on a dead address) and a second nameserver in netplan.

If you rsync instead: **always exclude `.env`** (it has been overwritten before), and never copy
`venv/` between hosts — rebuild it on the target.

## Architecture

`execution/market_loop.py` (`run()`) is a single-threaded 60-second `while True` loop. It
constructs every subsystem once, then each cycle: heartbeat → hardware check → market-hours gate →
regime → feeds → strategies → scheduled tasks. State lives in one `logs/agent_state.json` dict
threaded through everything and `save_state()`-ed after each side effect.

**Layering that matters:** signal modules (`whale_watch`, `policy_monitor`, `ipo_calendar`,
`derivatives_signals`) only *propose*. `execution/risk_gate.py` *sizes and rejects*, always against
live broker positions rather than module-internal state. `execution/position_ledger.py` is the
single owner of an open position so two modules can't both manage it. A rejection from the gate is
a hard stop the caller logs and skips — never a warning it proceeds past.

Optional services degrade rather than fail: no `DATABASE_URL` → no logging, no `RESEND_API_KEY` →
no email, no `ANTHROPIC_API_KEY` → no Claude synthesis. The loop still trades.

### Invariants learned from outages — don't regress these

- **Every repeat-on-condition side effect goes through `execution/guards.py`.** The halt loop, the
  ladder runaway, whale re-buys and alert spam were all one bug: acting every cycle while a
  condition held, with no record of having acted. Use `acted_once()` for idempotency or
  `Cooldown(seconds, store=state[...])` for rate limits, and persist the store — an in-memory
  cooldown is reset by exactly the restart loop it exists to stop.
- **Market hours come from Alpaca `/v2/clock`**, never a UTC hour comparison.
- **`run_scheduled_tasks()` runs regardless of market state.** Time-of-day triggers must never sit
  inside the market-open branch; the closed-branch sleep is capped at 5 min so they keep firing.
  Use ET, and pin "report day" to the last day the market was actually open, not to today.
- **The IV gate is fail-closed** (`wheel.iv_gate_fail_open: false`): no IV history means no trade.
  A newly added ticker cannot trade until `iv_tracker` accrues `MIN_HISTORY_DAYS` (15) of
  snapshots — roughly three trading weeks. Expect silence from new names, and check
  `--rank-all` before assuming a bug.
- **The wheel's stage is derived from broker positions**, not remembered in memory — a restart
  once re-sold a CSP on a name already short a put.
- `trading.service` has `StartLimitBurst=5` / `StartLimitIntervalSec=300` with
  `OnFailure=trading-alert.service`, so a crash loop enters `failed` and shouts instead of
  respawning silently. `trading-heartbeat.timer` runs the deadman check every 5 min; a stale
  heartbeat during market hours *cancels open orders*, it doesn't just email.

### Configuration

`config/strategy_params.yaml` is the single tunable surface; `config/settings.py` maps it onto
dataclasses. The newer sections (`position_management`, `risk`, `live_gates`) filter unknown keys,
so a typo there is silently dropped rather than raising — confirm a new setting actually lands.
The older sections splat the dict directly, so an unknown key there is a `TypeError` at startup.
Secrets are env-only and never in YAML.

The YAML carries the *reasoning* for its values in comments — parked tickers with the price that
disqualified them, why `space_micro` is a separate sector bucket from `defense_aerospace`, why the
IV floor is temporarily 0.15. Preserve that when editing; it is the record of why a limit exists.

Risk knobs: `risk.max_position_pct` 5%, `risk.quarantine_max_position_pct` 1% (auto-applies to
`protection.no_auto_manage` IPO starters), `risk.sector_cap_pct` 20% counting equity value **plus**
short-put collateral. `live_gates` (clean-alert streak, profit factor, drawdown) are enforced by
`execution/live_readiness.py` before `--mode live` will start.

### Alpaca gotchas

Options snapshots need `limit≈100` and regular trading hours or you get no greeks/IV. Options
market orders are rejected outside RTH — use limit + GTC. `get_bars()` returns the key with a
`None` value when the market is closed rather than omitting it, so use `or []`, not `default=[]`.
CSP collateral is `strike × 100 × qty`, which is what the sector cap counts.

## Repo conventions

- `directives/*.md` are the strategy SOPs (wheel, whale watch, protective logic, journal). They are
  the intent behind the code — read the relevant one before changing a strategy's behavior.
- `TODO.md` is the project's work log, not a checklist: each dated section is an RCA of what broke,
  what was diagnosed, and what is still open. Append a section when you finish a body of work.
- `journal/` holds Claude-synthesized end-of-day wrap-ups, committed automatically by the loop;
  `logs/insights/*.jsonl` is the raw intraday dump they are built from. `MEM.md` is a
  strategy-memory scratchpad appended by the journal.
- `debug_*.py` at the root are ad-hoc scrapers/selectors probes, not part of the loop.
