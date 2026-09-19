# Agentic Trading System — TODO

**Last Updated**: 2026-08-21
**Status**: Live (Paper) — VM 117 home-workstation, HEAD `d1f9e70`. v2.3: report tier (weekly/monthly/quarterly with deterministic Needle Movement metrics), five structural risk fixes from the first quarterly, and correlation-based universe screening. 192 tests. Equity $83.7k. The quarterly's verdict is the headline: engineering progress real, financial progress absent — −15.59% over the trailing quarter, profit factor 0.23. Monday 08-24 is the first live test of the fixes (09:30) and the first valid universe screen (11:00).

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
- [x] Add IV rank/percentile check before opening CSPs (only sell when rank > 30) — done in v2.1 as a HARD gate (2026-07-06); snapshot pipeline fixed 2026-07-07 so history actually accumulates
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
- [x] **Deployed to VM 117** (2026-07-06, HEAD `447109e`) — service active; `db_logger.py --init` ran (proposed_config_changes live on dev-postgres); VM-local MEM.md learnings + 3 weeks of daily journals rescued from deploy autostash and committed (`caee768`, `f76cec2`)
- [x] **Splunk HEC wired** (2026-07-06) — `SPLUNK_HEC_URL=http://10.1.50.116:8088` + runbook token (95914a91) + `SPLUNK_HEC_INDEX=application` in both .env files; verified end-to-end: heartbeat events from 10.1.50.117 searchable in `index=application sourcetype="trading:heartbeat"`
- [x] **Finnhub key wired** (2026-07-07) — `FINNHUB_API_KEY` in both .env files, service restarted; earnings gate is now HARD-armed. First lookup immediately flagged: **CCJ earnings 2026-07-31 = the expiry date of both open CCJ puts** (the exact collision class the gate exists for; positions predate it). PM behavior: at 21 DTE any roll candidate also spans 7/31 earnings → all skipped → position CLOSES instead of rolling. That de-risk-before-earnings outcome is correct.
- [ ] Optional: Splunk scheduled search alerting when `trading:heartbeat` events stop arriving during market hours (independent of the VM being alive)
- [ ] Watch VM 117 DNS: two transient `github.com` resolution failures within 10 min during deploy (resolver 1.1.1.1 via systemd-resolved). Loop tolerates via network_failures counter, but if blips recur consider a fallback nameserver
- [ ] Whale Watch returned nothing recently — decide: wire to a real API (Unusual Whales) or delete the module (attribution report will make the call data-driven)
- [ ] Watch the first week of gate logs: expect CSP volume to drop sharply (hard IV gate + credit floors at VIX~16 — sitting in cash is correct behavior, not a bug)

## 2026-07-07 — First live session of v2.1 + IV pipeline RCA

- [x] **Gates verified live** — wheel skipped all tickers (hard IV gate), PM held all 4 short puts correctly (none at stop/roll thresholds), heartbeats flowing to Splunk `index=application`
- [x] **RCA: "no IV history" on every ticker** — three stacked causes, all fixed:
  1. (`741477f`) snapshot window was 8:30–8:59 ET **pre-market**, but Alpaca's indicative options feed is RTH-only → moved to 10:00–10:59 ET; derivatives scan now waits for the day's snapshot; IPO/eligibility stay pre-market
  2. (`741477f`) `get_iv_rank` demanded 30 snapshots → `MIN_HISTORY_DAYS = 15`
  3. (`3da5729`) snapshot fetch `limit=10` sampled only deep-ITM calls (sorted by symbol = ascending strike) which carry **no greeks** on the indicative feed → RTX had 0 usable contracts; `limit=100` → ~50. This was why names were "unavailable" even during RTH.
- [x] **Verified on VM during RTH**: 22/23 tickers snapshotted (OPTX has no options). Usable IV rank now: CVX, LDOS, SHLD, AADX; FJET at 13; rest 1–9 snapshots (~2–3 weeks to arm at 1/day)
- [x] Positions at check: FJET −$4.7k (breakeven GTC $5.71 resting), CCJ $98p −116% of premium (stop at −250%), CCJ $90p −87%, ALB $125p −25%, XOM $130p +25% (tracking to 50% close). Day P&L −$1,505.
- [x] Watch CCJ $98 put — resolved as predicted: PM BTC'd both CCJ puts + ALB at 21 DTE (no roll credit ≥ $0.15 floor / earnings-blocked expiries); MP stopped at −119.6%. Realized ~−$2.6k in W28 clearing the underwater book. XOM put finished +42.8% — the floor-compliant one worked.

## 2026-07-13 — W28 wrap + candidate-loop fix

- [x] **W28 results (first full v2.1 week)** — equity $89,812 → $87,925 in-week, recovered to $89,271 by Jul 13; book cleared to FJET-only (all CSPs closed by rule). Drawdown was inherited positions unwinding, not new risk: every close was a rule-fire (21-DTE + credit floor + earnings gate), zero penny rolls post-deploy, zero critical alerts.
- [x] **Wheel candidate-loop fix** (`19cfa48`) — journal filed it URGENT twice: run_cycle proposed FJET CSPs every ~60s, risk gate blocked ~170–320/day (wasted evals + insight spam). Quarantined tickers now excluded at candidate generation (upstream), taken from the risk gate's resolved set. Verified live: startup logs "excluding quarantined ticker(s): AADX, FJET, OPTX".
- [ ] **Policy classifier miss (W28)** — aviation-tariff EO mapped to AI-infra tickers (should be GE/RTX/HWM/TDG/SPR). System correctly didn't trade it, but sector mapping needs a look.
- [x] **DNS fallback for VM 117** — done 2026-08-07. Technitium `10.1.50.115` primary + `1.1.1.1` fallback in netplan; applied live and made idempotent in `deploy/deploy.sh`.
- [x] CapitolTrades 429 — root cause was our own polling (every ~60s, ~390 req/day). Now on a 30min persisted cooldown. The "real API or delete it" decision still stands but is no longer urgent.

## 2026-08-07 — v2.2: why nothing was trading (diagnosis + throughput fixes)

Three weeks of journals had been stranded on the VM; once rescued they showed the
same two findings repeated almost daily and never actioned. Root-caused the whole
"engine healthy, no trades" picture. Deployed HEAD `ad4bb52`, 65 tests green.

**Diagnosis — four causes, three of them bugs:**
- [x] **FJET mis-bucketed** — its dead $18.1k equity (21.1%) sat in `defense_aerospace`, putting the bucket over the 20% sector cap and hard-blocking CSPs on all 7 defense names for weeks, incl. AVAV at IV rank 100%. Speculative IPO micro-caps now have their own `space_micro` bucket.
- [x] **`qty=1` hardcoded** in `open_csp` — caps authorized 4 contracts, it sold 1. Now sized to the smallest of per-trade / sector / allocation headroom + a contract ceiling, with the SIZED order re-checked against the gate. Added `RiskGate.collateral_headroom()`.
- [x] **File-order allocation** — candidates were evaluated in YAML order, so the first name consumed the shared collateral budget (sold GEO at IVR 20% for $23 while AVAV at IVR 100% got nothing). Now ranked by IV rank descending.
- [x] **Short-history IV rank** — `iv_history` holds only 19–26 snapshot days/ticker (48 max). A 30% floor against a ~1-month window is far stricter than against 52 weeks. Floor 0.30 → **0.15 TEMPORARY, revisit 2026-12-01**.

**Throughput + hygiene:**
- [x] **Universe rebuilt to the account** — 11 names could never trade at $86k (one contract > $12,870 cap; CAT needed $80,550). Parked with prices in a YAML comment; replaced with 11 live-validated affordable names (OKLO/SMR/UUUU/NNE, AA/FCX/CLF, APA, CSCO, LUNR/ASTS). Wheel now logs unreachable names once per process.
- [x] **Policy → execution pathway** — `execution/dynamic_universe.py`. Policy-flagged tickers become candidates (cap 8, 30-day TTL, never quarantined), still clearing every gate, and are added to the iv_tracker snapshot set so their IV history starts accruing.
- [x] **Skip-log spam killed** — journal flagged it URGENT on 07-23 and 4 more times. 150–320 duplicate entries/day, now de-duped per (ticker, reason) on a 4h cooldown.
- [x] **Wheel stage now broker-derived** — was in-memory only, so a restart reset all tickers to "flat" and could re-sell a CSP on a name already short a put (service restarted 07-31; only the sector cap absorbed it).
- [x] **Feed polling backed off** — whale 30min / policy 15min, persisted in agent_state so a restart loop can't reset them.
- [x] **DoD source repointed** — defense.gov 403s everything (Akamai); department rebranded to war.gov. Now on the war.gov RSS Contracts channel (`ContentType=400`).
- [x] **FJET share-lock mystery closed** — the 4,261 "locked" shares are our own resting GTC sell @ $5.71 (the breakeven order). Decision: keep it, write no CCs (a CC at/above breakeven collects ~nothing; below it caps the exit).

**Tracked in Notion:** [New Work — Agentic Trading System v2.2](https://app.notion.com/p/3b5ce64fe31f8170baacd31dce6f81f3?pvs=204) — same to-dos with the Monday verification checklist and dated follow-ups.

**Open / next:**
- [ ] **Monday 08-10 09:30 ET — verify the throughput fix live.** Expect ~6 contracts across ALB/RKLB/GEO. Confirm sizing >1 contract, IV-ranked ordering, and that skip-log volume collapses. Also confirm feed backoff (whale 30min / policy 15min) now that market hours exercise that branch.
  `ssh workstation "journalctl -u trading --since today | grep -E 'SELL CSP|WHEEL|RISK'"`
- [ ] **~3 weeks (from 08-10) — the 11 new tickers become eligible** once iv_tracker accrues `MIN_HISTORY_DAYS` (15) of snapshots. Nothing to do but watch; they are hard-gated until then.
- [ ] **Revisit `min_iv_rank` 0.15 → 0.30 on 2026-12-01** once ~6 months of IV history exists.
- [ ] **USASpending.gov awards API** — the war.gov contracts feed is healthy but title-only ("Contracts for Aug. 7, 2026"); award bodies naming companies are on Akamai-blocked article pages. This is the real fix for contract→ticker signal (already Phase 2).
- [ ] Consider IV percentile (or a longer provider-sourced lookback) instead of short-window IV rank.

## 2026-08-21 — v2.2 verification closed + the reporting tier that was missing

Closed both open items from 08-07, then built the report layer that answers "is this
working" rather than "what happened today". Deployed HEAD `f655a6b`, 92 tests green.

**Verification of the 08-07 throughput fix — PASSED, but the check itself was broken:**
- [x] **The Monday 08-10 verification command in the last section does not work.** It greps
  journalctl for `SELL CSP`, but that string is an *insight* payload written to
  `logs/insights/*.jsonl` by `log_insight()` — it is never emitted as a systemd log line.
  The grep returns zero on a perfectly healthy system. Read the insight files instead:
  `ssh workstation 'cd ~/projects/trading && grep -c "SELL CSP" logs/insights/2026-08-*.jsonl'`
- [x] **The fix itself worked.** CSP opens per day from 08-10: 4, 2, 1, 2, 1, 5, 0, 2, 1, 5 —
  against 1 contract per cycle before. Sizing >1 confirmed, IV-rank ordering confirmed,
  skip-log volume down from 150–320/day to ~25/day/ticker.
- [x] **The 11 new tickers are on track, not stuck.** They hold 9–10 snapshots against
  `MIN_HISTORY_DAYS` 15. The 08-07 note said "~3 weeks" but the gate counts *trading* days,
  so eligibility lands ~2026-08-28, not 08-21. Nothing to fix; `--rank-all` shows
  INSUFFICIENT_DATA/SKIP for all 11 as designed.

**What the verification actually surfaced — throughput was never the real problem:**

The engine is mechanically healthy and losing money. Trailing 3 months: equity
$100,037 → $84,438, **−$15,599 (−15.59%)**, max drawdown 16.79%, 55 closed trades,
win rate 25.5%, **profit factor 0.23**, expectancy −$147.91/trade. 79.8% of capital
($66,924) sits idle while the deployed 36.4% loses. KTOS alone is −$4,005 across 0/6 wins.
Fixing throughput made the system trade more of a negative-expectancy strategy.

**New: the report tier above weekly** (`execution/performance.py`, `execution/period_reports.py`)
- [x] **`performance.py`** — deterministic metrics, no LLM: equity curve (start/end/peak/trough
  + max drawdown, sliced locally since Alpaca only accepts coarse periods), closed-trade stats
  from `decision_logic` (win rate, profit factor, expectancy), and capital deployment counting
  short-put collateral as `strike × 100 × qty` the way the sector cap does. Renders the
  **Needle Movement** block now embedded at the top of every period report.
- [x] **Monthly review** (`journal/monthly/YYYY-MM.md`) — rolls the month's weeklies into what
  changed / what did NOT change / lessons / what's next. The "did NOT change" section is the
  point: it counts how many weeks a finding recurred unactioned.
- [x] **Quarterly review** (`journal/quarterly/<label>.md`) — progress / negatives / structural
  problems / priorities. Reads the monthly tier when ≥2 documents exist, else falls back to
  weeklies; the first quarterly always takes the fallback path. `--trailing` covers the last
  3 months from an arbitrary day instead of a calendar quarter.
- [x] Both prompts are required to separate **engineering progress from financial progress** —
  conflating them is what made a losing quarter read as a stalled one.
- [x] Scheduler: monthly on the 1st pre-market, quarterly on the 1st of Jan/Apr/Jul/Oct, each
  reporting the period that just *ended* (dedup keys `YYYY-MM` / `YYYY-Qn`), outside the
  market-open branch per the `run_scheduled_tasks` invariant.
- [x] Seeded `journal/monthly/2026-06.md` and `2026-07.md` so the next quarterly rolls up
  monthlies rather than weeklies.

**Open / next — ranked by the quarterly's own priority order:**
- [ ] **FJET has no exit architecture, and the gap is generic to equity longs.** −$8,637
  unrealized, deteriorated six consecutive weeks with zero automated response. `position_manager`
  enforces stops on options but has no `max_equity_drawdown_pct` for equity longs. Biggest
  single line item in the quarter.
- [ ] **The CSP stop-loss monitor is not intraday.** KTOS breached at −852% against a −250%
  threshold, meaning the mark was checked at most once a day. Short puts on high-beta names gap
  through the threshold between checks. Needs 30-min polling during RTH and a tighter
  high-beta threshold.
- [ ] **The wheel does not consult `position_ledger` before generating candidates** — it reads
  the universe list, so it opens into a book that is already stressed (same-day open/close on
  ALB and XOM). v2.1 shipped the ledger; the wheel was never wired to it.
- [ ] **No minimum expected value on entry.** CSPs written for $0.05–$0.23/share premium then
  stopped out for multiples of the credit. Needs a `premium / max_loss_at_stop` floor and an
  OTM% floor scaled to realized vol.
- [ ] **Policy signals still have no execution pathway** — 90+ signals at conviction 0.85 over
  three weeks, zero orders. `status: SIGNAL` is a terminal state. The sector classifier also
  mis-maps aviation/agricultural/automotive/chemical policy to AI-infra tickers (VRT, MSFT,
  ORCL, PLTR, SMCI) — flagged in five separate weeklies, never remediated. Fix the classifier
  before wiring execution, not after.
- [ ] **Confirm AVAV/VST/CAT/CEG are actually reachable candidates.** All four showed IVR 51–100%
  for weeks and generated no orders; `--rank-all` no longer lists several of them at all, which
  suggests the snapshot set and the wheel universe have diverged.

## 2026-08-21 (later) — the five structural fixes from the quarterly

Implemented every item the quarterly ranked. Deployed HEAD `18fff51`, 170 tests green
(was 92). Two of the quarterly's own diagnoses were wrong when checked against the code;
both are corrected below, because the wrong mechanism would have produced the wrong fix.

**1. Equity longs had no exit — `protection.max_equity_loss_pct` 25%**
- [x] `no_auto_manage` (2026-06-16) stopped the ladder averaging into FJET by dropping those
  tickers out of `sync_positions()` entirely — which also removed their trailing stop, leaving
  **no exit at all**. That is why FJET fell six straight weeks to −32% unattended.
- [x] `check_catastrophic_loss()` reads **live broker positions**, so quarantined names cannot
  hide from it. Long equity only; fires once per ticker via `guards.acted_once`.
- [x] It cancels our own resting sells first. Shares committed to a working order are not
  available, so the liquidation would have been rejected and *appeared* to fire — FJET has
  4,261 of 4,570 shares locked by the GTC breakeven sell.

**2. The stop-loss was never "once daily" — stale close orders muted their own position**
- [x] The quarterly inferred a daily poll. `run_cycle()` runs every 60s. The real mechanism:
  the stop **did** fire at −250%, its marketable limit at `ask × 1.03` did not fill, and the
  "already has a working order" guard then skipped that symbol every cycle for the rest of the
  day (TIF is `day`). A resting close order silently muted the position and the loss ran to −852%.
- [x] Working orders are now aged. Past `stale_order_seconds` (180) the order is cancelled and
  re-priced, crossing the spread `reprice_aggression` harder each time, bounded by
  `max_reprice_attempts` (3) and then alerting instead of chasing forever.
- [x] Added `AlpacaClient.cancel_order()` — only `cancel_all_orders()` existed.

**3. The wheel never consulted the book — `max_book_loss_pct` 15% + `skip_losing_underlying`**
- [x] It read the universe list and nothing else, so it opened into an already-bleeding book.
  v2.1 shipped `position_ledger` for exactly this and the wheel was never wired to it.
- [x] Book health is a cycle-level gate (a stressed book is a property of the book, not of a
  ticker); the losing-underlying check is per-name. Both fed from live positions.

**4. No expected value on entry — and the quarterly's proposed formula was a no-op**
- [x] It proposed `credit / max_loss_at_stop`. With a *percentage* stop that is
  `C / (2.5 × C)` = **0.4 for every trade ever placed** — it can never reject anything.
- [x] Replaced with two gates measured against the underlying's own 1-sigma move over the
  holding period (`spot × daily_vol × √DTE`): `min_otm_vol_mult` 1.0 and
  `min_credit_vs_expected_move` 0.15. Both **fail open** on unavailable vol so they cannot
  become a second silent IV gate.
- [x] **`select_csp_strike()` is now vol-aware too.** Shipping only the gate would have had the
  selector propose the same too-close strike forever and the gate reject it — the wheel would
  have stopped trading entirely. Measured live: the old fixed ~6.25% strike sat INSIDE 1 sigma
  on KTOS, RKLB, CCJ and ABT (4 of 5 sampled, both big losers among them).
  New vs old OTM: RKLB 6.0%→23.7%, KTOS 6.7%→14.7%, MP 6.0%→13.3%, GEO 6.1%→7.6%,
  SHLD 6.1%→6.9%. Quiet names barely move; volatile names move a lot. That is the point.
- [x] **`_realized_vol()` shipped as a no-op first.** `get_bars()` needs an explicit `start` to
  return >1 day on the free IEX feed (its own docstring says so); without it vol was always
  None and both gates failed open. Caught by dry-running the gates against the live book.

**5. Policy classifier matched SUBSTRINGS**
- [x] Matching was `kw in text`. `"ai"` matched **AI**rcraft, d**ai**ry, rem**ai**n, ch**ai**n;
  `"ice"` matched pr**ice**, serv**ice**, Off**ice**, not**ice**. That is the entire explanation
  for aviation/agricultural/automotive/dairy headlines returning VRT/MSFT/ORCL/PLTR/SMCI —
  logged as a mysterious "classifier artifact" in five separate weeklies.
- [x] Now whole-word with an optional plural. Plain `\b` alone would have dropped "tariffs" for
  keyword "tariff" and lost real signal — the fix needed a fix.
- [x] The signal→order pathway itself already exists (`dynamic_universe`, 2026-08-07). It
  produced zero orders because promoted names have no IV history and the gate is fail-closed —
  working as designed, not broken. Fix the classifier first; the pathway then feeds it clean input.

**FJET decision (2026-08-21):** keep the position and its GTC breakeven sell rather than
realize −$8,420 today; write covered calls instead. Recorded in `protection.catastrophic_exempt`
with its reasoning — anything on that list must carry a stated plan, and comes off when it ends.
- [x] `run_cycle()` only ever called `open_csp()`. `open_cc()` was reachable **only** from
  `handle_assignment()`, so no covered call was ever written against a holding acquired any
  other way — the six-week "FJET CC eligible, no action" finding. `run_cycle()` now writes CCs,
  quarantined names included: quarantine blocks new *risk*, and a call on shares already owned
  reduces it.
- [x] CCs size to **available** shares (FJET: 309 free → 3 contracts) and, past
  `underwater_cc_loss_pct`, price off **spot** — a basis-derived strike is ~50% OTM and bids
  ~$0.00, which is exactly why 08-07 concluded "write no CCs". Trade-off is explicit: the
  spot-based strike ($4.50 vs $5.70 basis) caps recovery below cost.
- [x] `sync_positions()` now detects short **calls**. It never did, so the CC loop would have
  sold another one every cycle — `guards.py` repeat-without-a-record, with real orders.

**Open / watch on Monday 08-24:**
- [ ] **Expect FEWER trades, not more.** Wider strikes collect less premium, so some names will
  now fail `min_credit_per_share` / `min_credit_vs_expected_move`. With a profit factor of 0.23,
  trading less is the intended direction — but confirm it is not trading *zero*.
  `ssh workstation 'cd ~/projects/trading && grep -c "SELL CSP" logs/insights/2026-08-24.jsonl'`
- [ ] **Confirm the FJET covered call is written** — 3 contracts at ~$4.50, and confirm the
  spot-based strike logic picked it (log line says "pricing CC off spot").
- [ ] **Sanity-check realized vol against a second source.** ABT prints 2.51% daily (≈40%
  annualized), which is high for Abbott and suggests the free IEX daily feed may be sparse or
  gappy. Overestimated vol makes the OTM gate stricter and silently blocks good trades.
- [ ] **The 11 new tickers become IV-eligible ~08-28** (15 trading days from 08-07).

## 2026-08-21 (later still) — the concentration nobody was measuring

Prompted by a direct question: the founding tenet was government-action trading, and the
system was supposed to have evolved past depending on it. It had not. It had narrowed
onto it. Deployed HEAD `c7df0ee`, 189 tests.

**What the measurement showed:**
- **20 of 23 wheel tickers** sit in four sector buckets — defense, space, nuclear,
  critical minerals — whose daily returns correlate at **0.63** with each other
  (defense↔space 0.78, nuclear↔minerals 0.71). Those are four separate buckets in the
  YAML with a 20% cap each, which reads as diversification and is not: 4 × 20% is **80%
  of the book in one macro position**. The sector caps were measuring the wrong thing.
- The only genuinely uncorrelated sleeve is ABT/CSCO/GEO at **0.12** — three names.
- **The entire quarter's loss is inside the correlated sleeve**: −$7,970 of −$8,135.
  "Everything else" is −$165, and only because it saw 4 trades against 51.
- **The 10-strategy framework was never built.** `directives/strategy_framework.md`
  specifies value/growth/momentum/trend/mean-reversion/S&R/breakout/dividend/event/
  rotation. `strategy_analysis` has **0 rows, ever**. The advisor has never written a
  record. `policy_monitor` logged 51 decisions and produced 0 trades.
- The deeper monoculture is not sectoral: **every trade is a short put.** That is
  short-vol and long-delta. Diversifying tickers alone would not change that a drawdown
  hits every position at once — which is what a 0.23 profit factor over 55 trades is.

**Decision (user): universe first, then a second engine, wheel validated in between.**

**Shipped — `execution/universe_screen.py`:**
- [x] Selection is now mechanical: one contract fits the per-trade cap, puts exist at the
  target expiry, NBBO tight enough not to eat the credit, and **correlation to the
  current book** under `universe.max_correlation` (0.60).
- [x] Correlation is measured against **live holdings**, not the YAML — the risk that
  matters is present exposure — and uses the **maximum**, not the average: a name
  uncorrelated to nine holdings and 0.9 to the tenth is precisely the concentration an
  average hides. Sign is preserved so a negatively correlated name reads as a diversifier.
- [x] Passing names go to `dynamic_universe.promote()`, not into the YAML. The IV gate is
  fail-closed, so promotion into iv_tracker's snapshot set is what starts the 15-day
  clock; writing them to the YAML would have looked instant and been inert for 3 weeks.
- [x] Seed pool spans the nine sectors the book has **zero** exposure to (financials,
  healthcare, staples, discretionary, tech, utilities, comms, transport, REITs), all
  under the ~$125 the per-trade cap allows.
- [x] **Market-hours guard.** The first run at 17:40 ET passed 1 of 28 and rejected KO at
  a 55% spread, T at 186%, SBUX at 183% — three of the most liquid options markets there
  are. Stale after-hours quotes, not illiquidity. `run_screen()` now refuses when the
  clock says closed rather than returning a confident wrong answer, and the weekly
  trigger is **Monday 11:00 ET, mid-session** — not pre-market, for the same reason the
  IV snapshot was moved off 8:30.

**Open / next:**
- [ ] **Re-run the screen during RTH** — Monday 08-24 11:00 ET, automatically. The only
  honest read so far is that AEP fails on price ($12,570 vs a $12,559 cap) and INTC
  passes at +0.26 correlation. Everything else needs live quotes.
- [ ] **Watch the seed pool's real pass rate.** If most names still fail on spread during
  RTH, the 25% cap is too tight for 2-week expiries on $30–90 underlyings and should be
  measured before it is loosened.
- [ ] **Then the second engine.** The wheel is short-vol/long-delta; a genuine complement
  has to make money when that loses. The natural candidate is upgrading the crude
  "regime says BEAR → buy SQQQ" hedge into a real trend sleeve that can hold short.
  Gated on 2–3 weeks of evidence that the wheel's expectancy actually turned.
- [ ] **`strategy_analysis` still has 0 rows.** Whatever we add next, the advisor that was
  supposed to score it has never run. Fix that before trusting any attribution.

## 2026-08-21 (wrapup) — report plumbing verified end-to-end

- [x] **Scheduler replayed over 60 days** to confirm each trigger fires once per period:
  monthly next 2026-09-01 (reporting August), quarterly next 2026-10-01 (reporting Q3),
  universe screen Mondays 11:00 ET, weekly each Friday 16:15 ET.
- [x] **Added `weekly_journal.py --week`.** The monthly and quarterly had CLIs; the weekly
  did not, so the only way to produce one was to wait for Friday. That mattered: W34 fired
  at 16:15 ET, ~80 min BEFORE the Needle block deployed, and its dedup key was already set —
  the enhanced weekly would have been invisible until W35.
- [x] **Two rendering bugs found by regenerating W34** (a 0-win / 7-loss week) — both in the
  block that leads every report, both making a losing week read as a winning one:
  profit factor printed "n/a (no losing trades)" when the truth was *no winning trades*
  (0.0 means two opposite things), and best/worst markers came from rank position rather
  than sign, so the three least-bad losses rendered with green ticks.

**Standing watch list — Monday 2026-08-24:**
- [ ] 09:30 — first live test of the five structural fixes. Expect FEWER trades, not more.
- [ ] 11:00 — first valid universe screen (RTH). Watch the real pass rate on spread.
- [ ] Confirm the FJET covered call writes: 3 contracts near $4.50, log line "pricing CC off spot".
- [ ] ~08-28 — the 11 new tickers clear MIN_HISTORY_DAYS and become IV-eligible.
- [ ] Sanity-check realized vol against a second source (ABT at ~40% annualized looks high).

## 2026-09-15 — the 3-day halt, the advisor crash, and three weeks without Claude

**What broke.** Alpaca paper returned 500 on `/v2/clock` for a few minutes on Fri 09-11 ~09:16 PT.
A 5xx was not classified as transient, so it counted against `api_retry_limit` (3) and the loop
halted in ~90s. On restart `_attempt_halt_recovery` probed, got the same 500, and exited; after 5
fast restarts `StartLimitBurst` put `trading.service` in `failed` and nothing ever retried. The
OnFailure alert (Fri) and the deadman (Mon, hourly) both fired, but the service stayed down
through all of Mon 09-14 RTH and the W37 weekly. Restarted by hand 09-15 01:56 PT; the halt
cleared on the first probe.

- [x] **Halt fix (uncommitted)** — `_is_server_error` / `_is_transient_error` in `market_loop.py`:
  a broker 5xx now takes the network path (`NETWORK_FAILURE_HALT_THRESHOLD` 20 × 30s ≈ 10 min)
  instead of `api_retry_limit`. Startup recovery waits through transient probe errors in-process
  with backoff (30/60/120/300s, last repeats) instead of exiting, so an outage can no longer
  exhaust the systemd start limit. Auth halts and non-transient probe errors still exit.
  While it waits there is no heartbeat, so the deadman still alerts during RTH.
- [x] **Advisor digest crash (uncommitted)** — `generate_digest` sliced `ts` as a string, but
  `get_lessons` (RealDictCursor) returns a datetime. Every weekly and monthly digest raised
  `'datetime.datetime' object is not subscriptable`. Now `str(l['ts'])[:10]`.
- [x] **Verified** — new `tests/test_halt_recovery.py` (15) and `tests/test_strategy_advisor_digest.py`
  (1) fail 13/16 on the old code and pass on the fix. Full suite 206 passed; the 2
  `test_stale_order_reprice` failures predate this change. Ruff and mypy unchanged vs. HEAD.
  Digest dry-run against the 11 live lessons (Claude stubbed) builds the prompt correctly.
- [x] **Claude credits** — every synthesis (journal, weekly, briefing, advisor) had fallen back to
  templates since **2026-08-25** ("credit balance is too low"). New `ANTHROPIC_API_KEY` pushed to
  the VM .env (only that line; backup at `~/.env.trading.bak-20260915`), tested with
  `claude-sonnet-4-6`, service restarted 02:19 PT.
- [x] **Monday's "cancelled 1 order" alerts explained** — not a rogue trader. `breakeven-monitor.timer`
  re-arms the FJET GTC sell (4,261 @ $5.71) hourly; with the loop down the deadman cancelled it
  and the monitor re-placed it, all day.

**Still open:**
- [ ] **Commit, push, `deploy.sh`** the two fixes — nothing above is live on VM 117 yet.
- [x] **Weekly scan analyzes nothing (fixed, uncommitted — see below).**
- [x] **CapitolTrades 429s (fixed, uncommitted — see "the 429 that was never a rate limit" below).**
- [ ] **Regenerate** the 09-11 journal and the missed W37 weekly now that Claude works.
- [ ] `mypy execution/` stops on a pre-existing module-path error before checking anything.

## 2026-09-15 (later) — the weekly scan never analyzed a ticker

**What broke.** `run_weekly_scan` fires in the Monday pre-market window, in practice at 00:00 ET,
and priced each ticker with `get_bars(ticker, "1Min", 1)`. With no `start`, that covers today only,
and at midnight there are no prints yet, so every ticker hit "no price data, skipping". Nothing
was ever analyzed, logged or emailed — this, not the digest crash, is why `strategy_analysis` has
0 rows. The CLI `--ticker` path had the same bug. Live check at 06:00 ET: 1-minute bars were
already back for most names once pre-market prints began, but still empty for LDOS, GEO, ABT,
FJET and OPTX.

- [x] **`AlpacaClient.get_latest_price`** — latest-trade endpoint (returns the last print at any
  hour), falling back to the last daily close via `get_bars(..., "1Day", start=...)`; 0.0 if neither.
- [x] **Scan + CLI use it**, and the scan now logs "analyzed N of M tickers" plus a WARNING when it
  produces nothing, so this can't go silent again.
- [x] **Verified** — `tests/test_weekly_scan.py` (5) fails on the old code, passes on the fix; full
  suite 211 passed (the 2 `test_stale_order_reprice` failures predate this); ruff unchanged.
  Live dry-run on VM 117 with the market closed: all 23 wheel tickers priced, the scan with Claude
  stubbed analyzed 23 of 23, and one real `analyze_ticker("GEO")` returned valid JSON (WATCH, 0.52).

**Still open:**
- [ ] **Commit, push, `deploy.sh`.** First real run: Monday 2026-09-21 00:00 ET — expect 23 rows in
  `strategy_analysis` and a scan email.
- [ ] Other 1-minute-bar callers (`position_manager`, `wheel_strategy`, `inverse_etf_hedge`,
  `universe_screen`) run during RTH and were left alone; revisit only if one gains a pre-market path.

## 2026-09-15 (later still) — the CapitolTrades 429 that was never a rate limit

**What broke.** Whale watch has not received one congressional trade since at least 2026-06-02.
The August fix assumed 60s polling had earned a rate limit and slowed polling to 30 min; the
errors continued at ~7 per trading day. Probed from VM 117: our bot UA gets `403` from Vercel's
firewall; a real Chrome UA with full browser headers gets `429` with `x-vercel-mitigated:
challenge` and a "Vercel Security Checkpoint" page — a JavaScript challenge no HTTP client passes.
`bff.capitoltrades.com` returns `503 LambdaExecutionError`. No polling rate could ever have fixed it.

- [x] **`SourceBlocked`** — `whale_watch` recognises the checkpoint (challenge header or page title)
  and Vercel firewall 403s; a plain 429 is still an ordinary HTTP error.
- [x] **`_poll_whale` in `market_loop`** — a blocked source is flagged in `agent_state.json`, logged
  and emailed ONCE, and retried once per `feeds.blocked_source_retry_hours` (24) via a persisted
  `Cooldown`; a successful retry clears the flag and resumes normal polling.
- [x] **Verified** — `tests/test_whale_blocked.py` (10) cannot import against the old code and passes
  on the fix; full suite 221 passed (the 2 `test_stale_order_reprice` failures predate this); ruff
  unchanged. Live on VM 117: a real fetch raises `SourceBlocked`, and 3 consecutive polls
  produced 1 fetch and 1 alert.

**Replacement sources checked (for the open decision below):**
- Finnhub `/stock/congressional-trading` — `403`, premium-only on our key.
- House/Senate Stock Watcher S3 datasets — `403`, gone.
- **House Clerk** `disclosures-clerk.house.gov/public_disc/financial-pdfs/2026FD.zip` — works:
  1,628 filings, 388 periodic transaction reports (PTRs), newest 2026-09-09. PTR PDFs at
  `.../ptr-pdfs/2026/<DocID>.pdf` extract cleanly with `pdftotext -layout` (already on the VM):
  asset + `(TICKER)`, P/S, transaction and notification dates, `$1,001 - $15,000` ranges.
  Tracked House members with 2026 PTRs: McCormick 4 (latest 08-14), Kelly 10, Gottheimer 8,
  Pelosi 3, Davidson 1, Sewell 1, Crenshaw 1; Norcross and Greene 0.
- Senate eFD (`efdsearch.senate.gov`) — reachable, but needs an agreement/CSRF session flow.

**Still open:**
- [ ] **Commit, push, `deploy.sh`.** Expect one "[WHALE] Congressional trade feed blocked" email on
  the first poll after deploy, then one log line per day.
- [ ] **Decide on a replacement feed.** House Clerk PTRs cover 9 of 11 tracked names (both senators
  would need eFD). Note disclosures lag trades by up to 45 days, and `WhaleTrade.trade_date` is
  currently stamped `date.today()` — any replacement must carry the real transaction date.
- [ ] `whale_watch.source_url` in the YAML is ignored; `fetch_recent_trades` hard-codes the URL.

## 2026-09-18 — NEXT SESSION: terminal dashboard (decided, not started)

**Decision.** Build a **terminal dashboard** run over ssh on VM 117 (option 1 of three: TUI vs a
page the loop writes vs Metabase). Prompted by a Twitter/X "Claude Code turned $68 into $750K"
crypto-arb post — the claims are marketing (the screenshot itself says SIMULATED, 100% win rate on
261 trades), but the *cockpit layout* is worth copying honestly. Nothing about that bot's strategy
is being adopted: retail cross-venue crypto arb is latency-bound and irrelevant to a paper options
wheel, and our measured problem is entry quality/exit enforcement, not throughput.

**Hard constraint: read-only.** The dashboard must never write state, place orders, or import the
trading path in a way that can block the loop. A crashed dashboard must not be able to affect an
order. Run it as a separate process (`python execution/dashboard.py`), not inside `market_loop`.

**Panels, and the data that already exists for each (verified 2026-09-18):**
| Panel | Source |
|---|---|
| Equity curve, realized/unrealized, day change | `performance.equity_curve` / `capital_snapshot` (Alpaca portfolio history) |
| Open positions + wheel stage + resting orders | Alpaca `/v2/positions`, `/v2/orders`; FJET GTC breakeven @ $5.71 |
| Win rate / profit factor / expectancy | `performance.trade_stats` (same numbers as the weekly/monthly needle block) |
| "Why nothing traded" | `decision_logic` table (680 rows) |
| IV gate eligibility per ticker | `iv_history` (1,360 rows), `iv_tracker --rank-all` |
| System health | `logs/heartbeat` age, `agent_state.json` (halt flag, last_* scheduled runs), feed block flags |
| Live activity log | `logs/insights/*.jsonl` (15,442 lines) |
| Lessons / signals | `strategy_lessons` (65), `trading_signals` (60) |

Empty on purpose, do not design around them: `strategy_analysis` (0 rows until the first fixed
weekly scan on Mon 2026-09-22), `derivatives_positions`, `workflow_runs`, `proposed_config_changes`.

**Open questions for next session:**
- [ ] Library: plain ANSI/curses (no new dependency) vs `rich`/`textual` (nicer, adds a dependency
      to `requirements.txt` and the VM venv). Lean `rich` unless we want zero new deps.
- [ ] Refresh cadence and API budget — the loop already polls Alpaca every 60s; the dashboard
      should read `agent_state.json` / DB / heartbeat where it can and hit Alpaca sparingly.
- [ ] Does it run on the VM over ssh (authoritative data, no extra creds) or locally in WSL
      against the same Postgres? VM is the honest answer; WSL has no `.env` parity guarantee.
- [ ] One-shot mode (`--once`) for piping into the daily report, alongside the live refresh loop.

**Still open from earlier today:**
- [ ] The CapitolTrades blocked-source fix is committed but **not deployed** — run `deploy.sh` to
      stop the daily 429 lines and arm the one-time "feed blocked" email.
- [ ] Replacement congressional feed (House Clerk PTRs) — still an open decision, see above.

## 2026-09-19 — deploy of the 09-15/09-18 fixes, and the dashboard (both web and terminal)

**Deploy.** `deploy.sh` ran at 03:45 PDT; `trading` restarted clean on `fe83c77` (paper, Postgres +
Resend OK, market closed). The VM had been at `c63b2f0`, 4 commits behind. Worth recording: the
process that was replaced had been up **4d 26m — since ~09-14 23:19 PDT**, i.e. from *before*
the 09-15 commits. So the advisor-crash fix and the weekly-scan fix were on disk but **not running
until today**, and the CapitolTrades backoff (`ccc5f21`) went live with them. "Committed" and
"pulled" are not "running": check `systemctl show trading -p ActiveEnterTimestamp` against the
commit time.

The VM also had 4 dailies, the W38 weekly and a modified `MEM.md` uncommitted. `deploy.sh`'s
journal pre-commit handled them correctly (committed + pushed as `fe83c77` before the reset). A
belt-and-braces copy is in `~/vm-data-backup/20260919-0345/` on the VM — delete when satisfied.

**Dashboard — decision changed from "TUI only" to both, sharing one data builder.**

| File | Role |
|---|---|
| `execution/dashboard_export.py` | `build_state()` — the only producer. Read-only: broker reached via `ReadOnlyBroker` (GETs only, no order methods — a test pins that). Writes only `logs/dashboard/{state,cache}.json` (gitignored so `deploy.sh`'s `stash -u` can't sweep them). |
| `execution/dashboard_serve.py` + `deploy/trading-dashboard.service` | Exporter thread every 60 s + a 3-route HTTP server on **127.0.0.1:8765**. Not tied to `trading.service`; `Nice=10`. View: `ssh -L 8765:127.0.0.1:8765 workstation`. |
| `dashboard/index.html` | The uploaded page, adapted: HTML-escaped, market state from `/v2/clock`, profit factor + expectancy next to win rate, rules footer from YAML, chart guard for <2 points, stale-snapshot alert (>3 min). `?demo` renders built-in data. |
| `execution/dashboard_tui.py` | `rich` terminal view of the same dict. Calls `build_state()` directly, so it works when the service is down. `--once` for piping, `--from-file` for zero API calls. |

Module health is computed from `agent_state.json` run markers against each task's actual schedule
(weekday 08:30/09:00/10:00, Monday pre-market, Friday 16:15, trading-day close via `/v2/calendar`),
with a grace window so a task inside its own hour isn't "late". Feeds are `idle` when the market is
closed (they only poll in the open branch) and the whale feed shows `blocked` from
`whale_source_blocked`.

**Multi-account.** The engine still trades exactly one account (`ALPACA_KEY`). Other paper accounts
are **watched** (shown, never traded) via env on the VM:
`ALPACA_ACCOUNTS=acct3,acct1,…`, `ALPACA_ACCOUNT_ID=acct3`, `ALPACA_KEY_<ID>`/`ALPACA_SECRET_<ID>`,
optional `ALPACA_NAME_<ID>`. Profit factor/expectancy exist only for the traded account —
`decision_logic` has no account column, and the page never blends them.

**What the first real snapshot said (2026-09-19, market closed):** equity $73,272, −26.7% since
2026-04-08; 90-day ledger PF **0.06**, win rate 17%, expectancy −$187 over 46 closed trades — worse
than the Q3 baseline (0.23). Unrealized is −$18.5k and FJET alone is −$18.6k (−71%, GTC exit resting at
$5.71). The wheel is correctly refusing new CSPs on the 15% book-loss limit every day. `weekly scan`
and `universe screen` show **missed 1** (2026-09-14) — the service was down that Monday, not a new bug.

**Still open:**
- [ ] Commit, push, `deploy.sh`, then `systemctl status trading-dashboard` and open the tunnel.
      `deploy.sh` now installs/enables/restarts the unit and prints its state; a dashboard failure
      only prints a warning — trading is unaffected.
- [ ] Add the watched paper accounts' keys to the VM `.env` (and WSL `.env` — see env-sync rule).
- [ ] Mon 09-21: weekly scan's first run with the fix — the dashboard's `weekly scan` row should go
      green and `strategy_analysis` should get rows.
- [x] `tests/test_stale_order_reprice.py` has 2 failures that are a **date time-bomb**, not a
      regression: fixtures use `KTOS260904P…`, which expired 2026-09-04, so the manager skips it.
      Pin the contract to a future expiry relative to `date.today()`. **Done 09-19:** `_occ()`
      builds the symbol 30 days out; suite is 239/239. Then every other fixture's hard-coded
      expiry (8 files) moved to the shared `tests/_symbols.occ()`. Verified by running the suite
      with the clock shifted to 2027-06-15 (`time-machine`): 239/239, while the pre-fix reprice
      file fails 2 under the same shift. New fixtures: use `occ()`, never a literal OCC date.
- [x] `mypy execution/` module-path error — **fixed 09-19** with `mypy.ini`
      (`explicit_package_bases = True`), so the documented command works unchanged.
- [ ] That fix un-hid the real backlog: **147 errors in 22 files** (0 left — see the two passes below) that mypy had never reported.
      Mostly `union-attr` (67 — Optional values used without a None check) and `assignment` (26);
      19 are missing third-party stubs (`types-requests`, `types-PyYAML`, …). Heaviest:
      strategy_advisor 22, daily_journal 17, iv_tracker 16, weekly_journal 15, morning_briefing 15,
      period_reports 14. The union-attr ones are worth a pass — they are the None-handling bugs
      the RTH-only-data and `get_bars() or []` incidents were made of. The dashboard files are clean.
- [x] **union-attr pass (09-19): 67 → 0.** Correction to the line above: only **1** was a None
      check (`breakeven_monitor.py:70`, unreachable — made explicit). The other 66 were one
      pattern at 6 Claude call sites, `message.content[0].text`, which assumes the first block is
      text. On an empty or refused turn that raised a bare `IndexError: list index out of range`,
      and `analyze_ticker` returned JSON cut off at `max_tokens` as if complete, so the ticker
      fell out of the weekly scan as a "parse error". New `execution/claude_text.response_text()`
      joins text blocks and raises `ClaudeNoText` naming the stop_reason (refusal / no text /
      truncated JSON); every caller already falls back on exceptions, so behavior is unchanged
      apart from honest log lines. Checked against real SDK `Message` objects on 1.5.0 (WSL) and
      0.104.1 (VM).
- [x] **Remaining 79 mypy errors → 0 (09-19).** `mypy execution/` and `mypy config/` are clean.
      19 were missing stubs (now in requirements: types-PyYAML/psycopg2/psutil/requests). The rest
      were annotation gaps, not bugs: `= None` defaults typed as non-Optional (settings,
      alpaca_client, db_logger, protective_logic), `_get()` typed `-> dict` while /positions and
      /orders return lists (now `-> Any`), mixed-value dict literals mypy inferred as `object`
      (policy SECTOR_MAP/SOURCES, iv_tracker result), and the py<3.9 `timezone.utc` fallback
      clashing with `ZoneInfo`. Two looked like bugs and weren't: `live_readiness` reusing the
      name `e` after an `except … as e` (loop reassigns it first — renamed), and
      `date.fromisoformat(report_day)` with `report_day: Optional` (guarded by `daily_due`; now
      explicit). Only runtime-visible changes: the IV snapshot iterates tickers sorted (was set
      order), and `limit="100"` in one request (same query string).
- [ ] The synthesis calls pin `claude-sonnet-4-6` / `claude-haiku-4-5-20251001`. Not changed here
      (a model change alters report content and cost); worth a deliberate decision.

**Public link (09-19): https://trading.cloudmagic.software.** Same pattern as the other
`*.cloudmagic.software` apps — remotely-managed tunnel `pve01-trading`, connector
`cloudflared-trading.service` on **pve01** (token in `/etc/cloudflared/trading.env`, 0600), origin
`http://10.1.50.117:8765`. Unlike ainews/kanban (no Access app at all), it sits behind a Cloudflare
Access app with one policy, **Owner only** (chris@cloudmagicgroup.com, email one-time PIN,
24 h session). Verified unauthenticated `/`, `/index.html` and `/state.json` all 302 to the Access
login. The server binds 0.0.0.0 but answers only loopback + pve01 (`DASHBOARD_ALLOW_FROM`) —
VM 117 has no host firewall; other LAN clients get 403. Created with `cf-token auto --preset tunnel`
(token revoked after). To add a viewer: add an include rule to the app's policy in Zero Trust.
- [ ] First login through Access (needs the OTP email) — the one step not verified from here.
- [ ] Separate finding: `ainews.cloudmagic.software` and `kanban.cloudmagic.software` have **no**
      Access app, and kanban runs `DISABLE_AUTH=true` — both are publicly readable. Deliberate?

