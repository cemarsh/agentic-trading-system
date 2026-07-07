# Agentic Trading System — TODO

**Last Updated**: 2026-07-06
**Status**: Live (Paper) — VM 117 home-workstation. v2.1 risk engine: pre-trade gates (position/sector/quarantine caps), selection gates (hard IV, credit floors, earnings), position ledger, dead-man's switch, attribution + config-proposal learning loop, coded live-money gates.

---

## Completed

- [x] Scaffold project structure (directives, execution, config)
- [x] Alpaca paper trading API connection (IEX feed)
- [x] Whale Watch — CapitalTrades scraper (11 politicians)
- [x] Wheel Strategy — CSP/CC options automation (18 tickers)
- [x] Protective Logic — trailing stops, gap protection, ladder buying
- [x] Hardware monitor — CPU/temp threshold enforcement
- [x] PostgreSQL decision logging (`decision_logic` table)
- [x] Resend email alerts (`noreply@cloudmagicgroup.com`)
- [x] Daily report at 4:15 PM ET
- [x] systemd service on ThinkPad (persistent, auto-restart)
- [x] Policy Intelligence Layer (policy_monitor.py)
  - [x] White House Fact Sheets + Presidential Actions (`.wp-block-post-title a`)
  - [x] Federal Register EOs (JSON API — HTML is JS-rendered)
  - [x] DoD Contract Announcements (`p.title`)
- [x] Fully autonomous mode (`verification_trades: 0`)
- [x] Killed stale claude process causing CPU threshold breaches
- [x] GitHub repo: cemarsh/agentic-trading-system
- [x] Added to ops dashboard: cloudmagic.software/weekly-ops-dashboard/
- [x] Fixed strike calculation bug (inverted formula → no contracts ever placed)
- [x] Fixed 403 halt loop — whale watch orders wrapped in individual try/except
- [x] Fixed null db guard in whale watch order logging
- [x] Fixed options symbol in protective logic (OCC regex filter, skip options positions)
- [x] Fixed exact strike matching → nearest-available strike with 8% tolerance
- [x] Alpaca error messages now include response body for easier debugging
- [x] Market regime detector (regime_detector.py) — BULL/NEUTRAL/BEAR/EXTREME_BEAR
- [x] Inverse ETF hedge module (inverse_etf_hedge.py) — auto-buy SQQQ in bear regimes
- [x] Position sizing levers: per-trade cap (6% equity) + total allocation cap (65%)
- [x] Status emails every 2 hours during market window (not just daily report)
- [x] Regime-aware wheel: BEAR → delta 0.15, EXTREME_BEAR → skip all new entries
- [x] Switched to acct3 (PKGIWVF62JODI7QGJO2CNQS7VX) with levers active
- [x] Fixed market loop running on weekends — added Alpaca /v2/clock market hours gate
- [x] Added 10-strategy framework directive (directives/strategy_framework.md)
- [x] Built strategy_advisor.py — Claude-powered ticker analysis + lessons digest
- [x] Weekly scan trigger (Monday pre-market) + monthly digest (1st of month)
- [x] strategy_analysis + strategy_lessons PostgreSQL tables
- [x] ANTHROPIC_API_KEY wired into settings.py and ThinkPad .env
- [x] **Daily journal system** (2026-04-16) — intraday insight dump (`logs/insights/*.jsonl`) + Claude-synthesized EOD wrap-up (`journal/*.md`) emailed after daily report
- [x] **Scheduler fix** (2026-04-16) — `run_scheduled_tasks()` runs regardless of market state; pin report day to last-open-day (ET); cap closed-market sleep to 5min so triggers keep ticking
- [x] **realized_pnl bug fix** (2026-04-16) — was `last_equity - last_equity` (always 0), now `equity - last_equity`
- [x] First daily report + journal wrap-up emailed end-to-end on ThinkPad (trading day 2026-04-15)
- [x] Add ANTHROPIC_API_KEY + RESEND_API_KEY + ALERT_EMAIL to WSL .env (synced from ThinkPad)
- [x] **DNS halt loop fix** (2026-04-27) — transient DNS blip caused 5-day crash loop (13k restarts). Fixed: separate `network_failures` counter (20-failure threshold) from `api_failures` (3-failure threshold); halt alert written to disk before email attempt so it delivers on next startup even if network was down

---

## Phase 2 — Intelligence Fusion

- [ ] USASpending.gov contract awards API ($7.5M+ DoD awards → ticker mapping)
- [ ] SEC EDGAR insider transaction feed (CEO/CFO purchases)
- [ ] Options flow scanner (unusual call/put volume sweeps)
- [ ] Earnings calendar integration (reduce before earnings, re-enter after)
- [ ] SEC 8-K / 13F real-time feed

---

## Phase 3 — Quantitative Scoring

- [ ] ML confidence model (policy signal → price move correlation)
- [ ] Sector momentum overlay (only enter if ETF above 20-day MA)
- [ ] Volatility regime detection (shift to cash when VIX elevated)
- [ ] Backtesting harness (replay historical signals)

---

## Phase 4 — Execution Quality

- [ ] IV rank / IV percentile gating (only sell premium when rank > 30)
- [ ] Smart expiration rolling (50% max profit or 21 DTE)
- [ ] VWAP-aware order splitting
- [ ] Multi-leg options (spreads to cap max loss)

---

## Near-Term Operational

- [x] Add ANTHROPIC_API_KEY to .env — needed to activate strategy_advisor weekly scan (done on ThinkPad + WSL)
- [x] **Order rejection halt fix** (2026-05-06) — 403 "insufficient buying power" was miscounted as `api_failures`, halting the system (16k restarts over 6 days). Added `_is_order_rejection()` to skip 4xx business-logic rejections from the halt counter.
- [x] **Weekly wrap-up** (2026-05-07) — Friday EOD trigger collates Mon–Fri daily journals + NotebookLM research signals from DB + MTD trade performance report. Claude synthesizes into `journal/weekly/YYYY-Www.md` and emails.
- [x] **Network halt auto-recovery** (2026-05-14) — network-only halts (`api_failures==0`, `network_failures>=20`) now probe TCP connectivity on startup; auto-clear and resume if restored. API halts still require manual reset.
- [x] **Migrated to workstation** (2026-05-25) — service stopped/disabled on ThinkPad P70, enabled on home-workstation. ThinkPad was sleeping and taking the service down with it.
- [x] **Wheel cap fix** (2026-05-25) — `max_portfolio_pct_per_trade` raised 6% → 15% ($6k → $15k/trade at $100k equity). Every ticker was blocked due to undersized cap.
- [x] **Fixed missing `anthropic` in requirements.txt** (2026-05-25) — fresh venv installs crashed at import.
- [x] **DB tables initialized** (2026-05-27) — `trading` DB + user created on dev-postgres (10.1.50.114); all 6 tables live; DATABASE_URL wired to both WSL + workstation `.env`
- [x] **ANTHROPIC_API_KEY expired** — replaced 2026-05-27 with new key from console.anthropic.com
- [x] **Verified CSP orders firing on acct3** (2026-05-27) — 5 contracts filled: CCJ, MP×2, PLTR, RTX, VST; cap fix confirmed working
- [ ] Register `notifications.cloudmagicgroup.com` subdomain on Resend for cleaner sender
- [ ] Flip `paper_mode: false` after verifying 10+ autonomous paper trades
- [ ] Add ThinkPad daily sync for ops-dashboard.json to include trading metrics
- [ ] Add IV rank/percentile check before opening CSPs (only sell when rank > 30) — needs historical IV snapshots in DB first
- [x] **Post-trade lessons** (2026-05-27) — `log_lesson()` called in `execute_stop()` with entry/exit/PnL; auto-feeds strategy review digests
- [x] **Regime detector bug** fixed (2026-05-27) — `get_bars()` returning None when market closed; added `or []` guard in alpaca_client + `not bars` guard in regime_detector
- [x] **`log_insight()` hooks extended** (2026-05-27) — wheel CSP/CC open, hedge entry/exit, protective stop/ladder all log to daily journal
- [x] **Slack alerts wired** (2026-05-27) — `SLACK_WEBHOOK_URL` in .env → #agentic-ops-alerts; critical_alert() posts to Slack + email
- [ ] Promote recurring "What Changes Tomorrow" bullets from journal into config/strategy_params.yaml or directives (manual review weekly)

## NotebookLM Trading Intelligence Bridge

- [x] Directive added: directives/notebooklm-trading-bridge.md
- [x] n8n workflow JSON added: n8n/notebooklm-trading-bridge.json
- [x] DB schema migrated: trading_signals, research_briefs, workflow_runs tables live
- [x] Workflow imported into OpenClaw n8n (workflow ID: G9zvI1EJwNidm9r3)
- [x] ANTHROPIC_API_KEY wired into both ThinkPad and OpenClaw n8n containers
- [x] PostgreSQL opened to OpenClaw (UFW rule, pg_hba.conf, trading user credentials)
- [x] Supabase HTTP nodes replaced with n8n-nodes-base.postgres (Trading Postgres credential: DX2zMV9NOKTHzqH4)
- [x] WEBHOOK_SECRET set in .env (9f506f5f...)
- [x] End-to-end test PASSED: 4 signals extracted/scored/upserted, research_briefs + workflow_runs logged
- [x] Webhook URL: http://localhost:5678/webhook/trading/research-intake (OpenClaw)
- [x] Configure Slack webhook (SLACK_WEBHOOK_URL) for high-conviction alerts (conviction >= 7) — done 2026-05-27, #agentic-ops-alerts

## 2026-06-11 — Silent halt-loop outage RCA + monitoring hardening

- [x] **RCA: 5-day silent outage (Jun 6–11)** — transient `ConnectionReset` burst set `halted=true` (`api_failures=3, network_failures=3`); `run()` exited 1 each start, systemd respawned every 30s (counter hit 1801), **no alert**. Auto-recovery missed it (keys on exact `api_failures<=2`). VM was also 10 commits behind `main` + redundant uncommitted hotfixes.
- [x] **Restored** — cleared stale halt (backed up to `logs/agent_state.json.halt-bak-20260611`), `reset-failed`, restart → live again
- [x] **Item 1 — systemd hardening** — `deploy/trading.service`: `StartLimitIntervalSec=300`/`StartLimitBurst=5` (enters `failed`, no infinite loop) + `OnFailure=trading-alert.service` → `execution/alert_on_failure.py`
- [x] **Item 2 — heartbeat deadman** — loop writes `logs/heartbeat`; `execution/heartbeat_check.py` on `deploy/trading-heartbeat.timer` (5min) alerts on stale heartbeat >15min during market hours (alerts on stale, not missing, to avoid restart false-positives)
- [x] **Item 5 — deployment drift fixed** — VM synced to `origin/main`; `deploy/deploy.sh` + `deploy/sync-check.sh` added. **v2.0 aggressive-growth now LIVE** (position_manager, iv_tracker, morning_briefing). Commits `8f57021`, `ee199e3`.
- [x] **Item 3 — retry transient errors** (commit `c434b7a`) — `AlpacaClient` uses a urllib3 Retry session: GET/HEAD/OPTIONS retry `ConnectionReset`/429/5xx with backoff before raising, so blips never reach the halt counter. Order POSTs are NOT read-retried (double-fill risk); only safe connect failures retry for POST.
- [x] **Item 4 — smarter auto-recovery** (commit `45175c1`) — halts record `halt_reason` + `last_halt_error`; loop stamps `last_api_success` each healthy cycle. On restart: auth halts (401/403-not-order) stay halted for a human; all else runs a live authenticated `get_clock()` probe and auto-clears if the API answers. Replaces the brittle `network>=20 and api<=2` count rule (which let the Jun-6 `api_failures=3` halt loop for 5 days). Backward-compatible with halt states lacking `halt_reason`.
- [x] **Bug — `verify_all()` NameError** fixed (commit `c434b7a`) — now calls `db_logger.ping(cfg)` + `notifier.test_send(cfg)` (guarded for optional services); `--verify-only` passes `[READY]` on the VM.
- [x] **Underwater-puts review + position_manager fixes** (commit `2721f7c`) — the 3 ITM CSPs (CCJ/CEG/VST) exposed PM bugs (paper, no real loss). Fixed: (1) **stop-loss on short PUTS** — BTC when loss >= `stop_loss_pct` of premium (default 250%; covered calls excluded); (2) **roll-credit was always-positive** (`current_mark*(new_dte/current_dte)`) — now priced off REAL NBBO via `AlpacaClient.get_option_quote` (`new_bid - current_ask`), rolls only on genuine credit else closes; (3) **rolls DOWN-and-out** (lower strike for puts, `spot*(1-roll_otm_buffer)`) instead of same deep-ITM strike; (4) **limit orders** not market (market options orders rejected outside RTH); (5) **open-order guard** (`get_open_orders`) so resting limits don't double-submit each cycle.
- [x] **Closed CCJ** per decision (close worst only, hold CEG/VST to wheel) — GTC buy-to-close limit resting (mkt was closed); fills at next open. CEG/VST held (below 250% stop, DTE>21).
- [ ] At next open: confirm CCJ GTC filled; watch PM apply new rules to CEG/VST (stop at -250%, down-and-out roll at 21 DTE ≈ Jun 19)
- [ ] Consider delta-exact roll-strike selection (currently OTM-buffer approximation) + wiring the existing PM module constants (50%/21DTE) to config like the new keys

## 2026-06-13 — Broaden methodology: IPO + derivatives signal sources

Trigger: system captured **nothing** on the SpaceX IPO (narrow inputs: whale + policy + fixed wheel list + SPY regime).

- [x] **IPO calendar** (`execution/ipo_calendar.py`, commit b13c048) — SEC EDGAR 424B4 (Nasdaq API is IP-blocked); filters SPACs + established-company secondaries (CEG false-positive dropped via price-history length); checks Alpaca tradability/options; persists research_briefs + trading_signals(source_type='ipo'). **SPCX (SpaceX) is now the first trading_signals row.**
- [x] **Derivatives signals** (`execution/derivatives_signals.py`, commit 121fe73) — IV-rank premium environment (rich/normal/cheap); persists 'rich' names as derivatives signals.
- [x] **Wheel IV-gate** — `open_csp` skips CSPs when IV rank < `wheel.min_iv_rank` (0.30); fail-open with thin IV history.
- [x] Wired both into `run_scheduled_tasks` (daily ~8:30am ET); deployed to VM (HEAD 121fe73, active).
- [ ] **NotebookLM producer** — `nlm` CLI + Chrome installed on VM 117; **user owns Google auth + wiring**.
- [ ] **Verify (during market hours)** whether Alpaca's options snapshot exposes OI/volume for unusual-flow. IV already works on the existing Alpaca token (indicative feed, RTH-only) — earlier "quotes-only / need Tradier" was an after-hours testing artifact. Only consider an external feed if the RTH check shows Alpaca lacks OI/volume.
- [ ] Promote vetted IPO watchlist names into the tradable wheel universe (manual; fresh IPOs lack options for weeks).
- [ ] Optional: earnings calendar + general market-news scanner (further breadth).
- [ ] Optional: surface IPO watchlist + rich-premium names in the morning briefing (currently journal only).

## 2026-06-16 → 06-18 — Incident week: runaways, signal sources, guards

### FJET ladder runaway (2026-06-16)
- [x] **RCA + fix** (`e4eae32`) — ladder-buy fired every cycle (no rung cap / no stepped-drop), bought FJET 10sh/~60s for 2 days (4,570 sh, 26% equity). Fixed: `max_ladder_rungs=3` + each rung needs a further step down. Same class as halt-loop.
- [x] **no_auto_manage** (`76100d4`) — protective logic ignores IPO starters (FJET/OPTX/AADX): no trailing stop / no ladder, so a speculative starter can't be stop-sold at a loss.
- [x] **FJET breakeven exit** (`d9d651a`) — restore to 309-share starter ONLY at cost basis: resting GTC limit sell @ $5.71 + hourly `breakeven_monitor` systemd timer on VM 117 (re-arms order, alerts on completion). User: "don't get hit underwater."
- [x] **deploy.sh self-update fix** (`dad6f6e`) — `git reset --hard` rewrote deploy.sh mid-run → new units skipped on first deploy; re-exec the pulled copy once.

### Unbounded-loop sweep (2026-06-18)
- [x] **Whale buy** (`bda7c88`) — was unbounded: re-bought a FULL allocation of the same congressional disclosures every cycle (no dedup). Fixed: fingerprint dedup in `state["whale_acted"]`.
- [x] **Hardware alert** (`bda7c88`) — fired email+Slack every cycle on sustained breach. Fixed: 1h per-type cooldown.
- [x] **Swept clean** — all scheduled tasks, policy_monitor, n8n_watchdog, hedge, wheel verified bounded.
- [x] **`execution/guards.py`** (`8eafb08`) — shared util: `has_acted`/`mark_acted`/`acted_once` (idempotency) + `Cooldown` (rate-limit). Whale + hardware refactored to use it. Use for any new per-cycle order/alert/write.
- [ ] (optional) migrate `policy_monitor._seen` + order-rejection cooldown to guards.py for consistency
- [ ] (optional) hedge pending-order guard; wheel CSP-stage re-sync from live positions on restart

### Signal sources (earlier this week, 2026-06-13)
- [x] IPO calendar (SEC EDGAR), derivatives IV-rank + wheel IV-gate, wired into loop — SpaceX (SPCX) captured. See section above.
- [ ] NotebookLM producer — `nlm` CLI on VM 117; **user owns Google auth + wiring**

## 2026-06-24 — Claude journal insights broken (IPv6 egress)

- [x] **RCA: daily Claude synthesis failed Jun 22-23** (`Connection error.`) — engine healthy; root cause was VM 117 advertising a global IPv6 address (ULA + Tailscale) with **no IPv6 default route**. glibc RFC 3484 default handed dual-stack hosts (`api.anthropic.com` has A+AAAA) their dead IPv6 addr first → anthropic SDK/httpx intermittently raised `APIConnectionError`. curl survived via Happy Eyeballs; the SDK did not. Journal still emailed via template fallback (Claude analysis missing).
- [x] **Fix applied on VM** — uncommented `precedence ::ffff:0:0/96 100` in `/etc/gai.conf` → `getaddrinfo` now returns IPv4 first. Verified: raw SDK calls + real `_synthesize_with_claude()` both green. No restart needed.
- [x] **Made durable** (`fe63062`) — idempotent gai.conf step added to `deploy/deploy.sh` so a VM rebuild re-applies it. Fixes the whole class (Anthropic, Alpaca, Resend, Slack, SEC EDGAR all stop trying dead IPv6 first).

## 2026-07-06 — v2.1 Risk Engine (external review applied)

Source: full-system review — "the system sells puts where it *can*, not where it *should*;
signal modules propose, only a risk engine should size." All five layers implemented:

- [x] **Layer 4 — pre-trade risk gate** (`execution/risk_gate.py`) — hard 5%-of-equity position cap (the FJET check), 1% IPO-quarantine cap + no options on quarantined names, 20% sector-correlation cap (equity value + CSP collateral per `risk.sector_map` bucket). Wired into whale buys, ladder buys, wheel CSPs. Fails closed on unknown equity. *Reality check at deploy time: current book violates every cap — XOM 28.7%, FJET 24.6% (quarantined), CCJ 20.9%, ALB 13.9%; 3 sectors >20%. Gate blocks NEW adds; existing positions wind down via wheel/PM/breakeven paths.*
- [x] **Layer 3 — selection gates** — IV gate now HARD (`iv_gate_fail_open: false`; no history → no trade), CSP credit floor off real NBBO bid (≥ max($0.15/sh, `min_premium_pct`·strike)), roll credit floor `min_roll_credit: 0.15` (kills $0.01 rolls), earnings gate (`execution/earnings_calendar.py`, Finnhub — **needs `FINNHUB_API_KEY` in both .env files**; fail-open + loud warning without it), wheel entries now limit-at-bid (never market).
- [x] **Layer 2 — one brain per position** (`execution/position_ledger.py`) — owner/state/opened_at per symbol (crash-safe JSON); PM defers rolls on legs held < 24h (`min_hold_hours`); stop-loss/profit-close exempt. PM thresholds (50%/21DTE) now wired to config (closed the old TODO).
- [x] **Layer 1 — watchdog with authority** — heartbeat_check now CANCELS all open orders on stale heartbeat during market hours (`risk.deadman_cancel_orders`) before alerting; pushes heartbeat events to Splunk HEC (`SPLUNK_HEC_URL`/`SPLUNK_HEC_TOKEN`, optional). Telemetry fixed: temp reads `None`→"n/a (no sensor)" instead of fake 0.0°C; email bodies ASCII-normalized (mojibake in P&L lines).
- [x] **Layer 5 — learning loop** — `execution/attribution.py` (per-module P&L + profit factor, conviction-bucket calibration) + `proposed_config_changes` table with `execution/config_proposals.py` CLI (propose/list/approve/reject/applied); both surfaced in the Friday weekly wrap-up.
- [x] **Live-money gates in code** (`execution/live_readiness.py`) — `--mode live` refuses to start unless: ≥60d clean-alert streak, PF ≥1.3, max DD ≤8% over 90d, hard gates in config. First run: **NOT READY** (PF 0.44, DD 11.2%, streak 0d) — honest baseline.
- [x] 42/42 tests green (new: test_risk_gate, test_position_ledger, test_wheel_gates; fixed stale mock in test_protective_logic)
- [ ] **Deploy to VM 117** (`bash deploy/deploy.sh`) + run `db_logger.py --init` for the `proposed_config_changes` table + restart service
- [ ] **Get a free Finnhub key** and add `FINNHUB_API_KEY` to WSL + workstation `.env` (earnings gate is fail-open until then)
- [ ] Optional: `SPLUNK_HEC_URL`/`SPLUNK_HEC_TOKEN` in VM .env + a Splunk scheduled search alerting on missing `trading:heartbeat` events
- [ ] Whale Watch returned nothing recently — decide: wire to a real API (Unusual Whales) or delete the module (attribution report will make the call data-driven)
- [ ] Watch the first week of gate logs: expect CSP volume to drop sharply (hard IV gate + credit floors at VIX~16 — sitting in cash is correct behavior, not a bug)
