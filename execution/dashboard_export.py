"""
Dashboard snapshot — one read-only dict that both dashboards render.

    python execution/dashboard_export.py --once            # snapshot JSON to stdout
    python execution/dashboard_export.py --write            # logs/dashboard/state.json

`build_state()` is the only producer. The web page (dashboard/index.html, served by
dashboard_serve.py) polls the file it writes; the terminal view (dashboard_tui.py) calls
it directly, so the TUI still works when the web server or its thread is down.

Hard constraint (TODO 2026-09-18): read-only. Nothing here places, cancels or modifies
an order, and nothing writes engine state. The broker is reached only through
ReadOnlyBroker, which holds the AlpacaClient privately and exposes GETs by name. The
only files written are the snapshot and a cache under logs/dashboard/. Every section
degrades on its own: a failed broker call becomes an entry in `errors` and an empty
panel, never an exception, so a broken dashboard cannot take anything else with it.

Accounts. The engine trades exactly one Alpaca account (ALPACA_KEY). Other paper
accounts can be WATCHED — shown, never traded — by listing them:

    ALPACA_ACCOUNTS=acct3,acct1,acct2        # ids, in tab order
    ALPACA_ACCOUNT_ID=acct3                  # which id is the engine's (uses ALPACA_KEY)
    ALPACA_KEY_ACCT1=...  ALPACA_SECRET_ACCT1=...
    ALPACA_NAME_ACCT1="Sandbox"              # optional display name
    ALPACA_BASE_URL_ACCT1=...                # optional, defaults to paper

With ALPACA_ACCOUNTS unset the dashboard shows just the engine account.
Closed-trade stats (profit factor, expectancy) come from decision_logic, which has no
account column — they exist only for the engine account.
"""

import argparse
import json
import os
import re
import sys
import tempfile
import time as _time
from dataclasses import replace
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import settings as cfg_module
from execution import performance
from execution.alpaca_client import AlpacaClient

MARKET_TZ = ZoneInfo("America/New_York")

STATE_PATH = Path("logs/agent_state.json")
HEARTBEAT_PATH = Path("logs/heartbeat")
INSIGHTS_DIR = Path("logs/insights")
SNAPSHOT_PATH = Path("logs/dashboard/state.json")
CACHE_PATH = Path("logs/dashboard/cache.json")

# Portfolio history, fills and the DB ledger move slowly; refetching them every tick
# would spend the API budget the loop needs. Account, positions and orders are live.
SLOW_TTL_SECONDS = 600
CALENDAR_TTL_SECONDS = 6 * 3600
HEARTBEAT_STALE_SECONDS = 15 * 60   # same threshold as heartbeat_check.STALE_SECONDS
EVENT_LIMIT = 50
PAPER_URL = "https://paper-api.alpaca.markets"


# ---------------------------------------------------------------------------
# Broker access — reads only
# ---------------------------------------------------------------------------

class ReadOnlyBroker:
    """The only way this module reaches Alpaca. AlpacaClient can submit and cancel
    orders; this wrapper keeps it private and exposes reads, so a dashboard change
    can't reach an order method by accident."""

    def __init__(self, client: AlpacaClient):
        self._client = client

    def get_account(self) -> dict:
        return self._client.get_account()

    def get_positions(self) -> list:
        return self._client.get_positions()

    def get_open_orders(self) -> list:
        return self._client.get_open_orders()

    def get_clock(self) -> dict:
        return self._client.get_clock()

    def get_portfolio_history(self, period: str = "3M", timeframe: str = "1D") -> dict:
        return self._client.get_portfolio_history(period=period, timeframe=timeframe)

    def get_calendar(self, start: date, end: date) -> list:
        days: Any = self._client._get(
            "/v2/calendar", params={"start": start.isoformat(), "end": end.isoformat()})
        return days or []

    def get_fills(self, after: datetime) -> list:
        """Every fill since `after`, oldest first (Alpaca pages at 100)."""
        fills: list = []
        params = {"after": after.isoformat(), "direction": "asc", "page_size": 100}
        for _ in range(20):  # 2,000 fills a month is far past anything this engine does
            page: Any = self._client._get("/v2/account/activities/FILL", params=params) or []
            fills.extend(page)
            if len(page) < 100:
                break
            params["page_token"] = page[-1].get("id")
        return fills


def account_specs(settings) -> list:
    """Accounts to show, engine first unless ALPACA_ACCOUNTS orders them otherwise."""
    engine_id = os.environ.get("ALPACA_ACCOUNT_ID", "").strip() or "engine"
    engine = {
        "id": engine_id,
        "name": os.environ.get(f"ALPACA_NAME_{_env_suffix(engine_id)}", "").strip()
                or ("Engine" if engine_id == "engine" else engine_id),
        "key": settings.alpaca.key, "secret": settings.alpaca.secret,
        "base_url": settings.alpaca.base_url, "traded": True,
    }
    ids = [s.strip() for s in os.environ.get("ALPACA_ACCOUNTS", "").split(",") if s.strip()]
    if not ids:
        return [engine]

    specs = []
    for acct_id in dict.fromkeys(ids):  # de-dupe, keep order
        if acct_id == engine_id:
            specs.append(engine)
            continue
        sfx = _env_suffix(acct_id)
        key = os.environ.get(f"ALPACA_KEY_{sfx}", "").strip()
        secret = os.environ.get(f"ALPACA_SECRET_{sfx}", "").strip()
        spec = {
            "id": acct_id,
            "name": os.environ.get(f"ALPACA_NAME_{sfx}", "").strip() or acct_id,
            "key": key, "secret": secret,
            "base_url": os.environ.get(f"ALPACA_BASE_URL_{sfx}", "").strip() or PAPER_URL,
            "traded": bool(key) and key == settings.alpaca.key,
        }
        if not key or not secret:
            spec["error"] = f"ALPACA_KEY_{sfx} / ALPACA_SECRET_{sfx} not set"
        specs.append(spec)
    if not any(s["traded"] for s in specs):
        specs.insert(0, engine)  # the account the engine trades is never left off
    return specs


def _env_suffix(acct_id: str) -> str:
    return re.sub(r"\W", "_", acct_id).upper()


def _broker_for(spec: dict, settings) -> ReadOnlyBroker:
    alpaca = replace(settings.alpaca, key=spec["key"], secret=spec["secret"],
                     base_url=spec["base_url"])
    return ReadOnlyBroker(AlpacaClient(replace(settings, alpaca=alpaca)))


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _f(v, default: float = 0.0) -> float:
    try:
        return float(v) if v not in (None, "") else default
    except (TypeError, ValueError):
        return default


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def _atomic_write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump(payload, fh, default=str)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _iso(ts) -> Optional[str]:
    if ts in (None, ""):
        return None
    if isinstance(ts, (int, float)):
        return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
    return str(ts)


def parse_occ(symbol: str) -> Optional[dict]:
    """ROOT + YYMMDD + C/P + 8-digit strike x1000, as performance.capital_snapshot reads it."""
    if len(symbol) <= 10 or symbol[-9] not in ("C", "P"):
        return None
    try:
        expiry = datetime.strptime(symbol[-15:-9], "%y%m%d").date()
        strike = int(symbol[-8:]) / 1000.0
    except ValueError:
        return None
    return {"root": symbol[:-15], "expiry": expiry, "right": symbol[-9], "strike": strike}


class _Cache:
    """Slow-moving broker/DB reads, shared by the server thread and the TUI via one file."""

    def __init__(self, path: Path = CACHE_PATH):
        self.path = path
        self.data = _read_json(path)
        self.dirty = False

    def get(self, key: str, ttl: float):
        hit = self.data.get(key)
        if hit and _time.time() - hit.get("at", 0) < ttl:
            return hit.get("value")
        return None

    def put(self, key: str, value) -> None:
        self.data[key] = {"at": _time.time(), "value": value}
        self.dirty = True

    def save(self) -> None:
        if self.dirty:
            try:
                _atomic_write(self.path, self.data)
            except Exception as e:
                print(f"[DASH] cache write failed: {e}")


# ---------------------------------------------------------------------------
# Per-account
# ---------------------------------------------------------------------------

def _position_action(kind: str, root: str, pnl_pct: Optional[float], dte: Optional[int],
                     settings) -> str:
    """Which position_management rule this position currently sits in. This is the
    dashboard reading the rules against the mark, not the position manager's queue —
    the manager may be waiting on RTH, min_hold_hours or a working order."""
    pm = settings.position_management
    quarantined = set(getattr(settings.risk, "quarantined_tickers", None) or []) | \
        set(getattr(settings.protection, "no_auto_manage", None) or [])
    if kind in ("csp", "cc", "short_call") and pm is not None and pnl_pct is not None:
        stop = getattr(pm, "stop_loss_pct", 0) or 0
        if kind == "csp" and stop and pnl_pct <= -stop:
            return "stop"
        if pnl_pct >= (getattr(pm, "close_profit_pct", 50) or 50):
            return "close_50"
        if dte is not None and dte <= (getattr(pm, "force_close_dte", 7) or 7):
            return "force_close"
        if dte is not None and dte <= (getattr(pm, "roll_dte_threshold", 21) or 21):
            return "roll"
        return "hold"
    if root in quarantined:
        return "quarantine"
    return "hold"


def _sector_of(root: str, settings) -> Optional[str]:
    for bucket, names in (getattr(settings.risk, "sector_map", None) or {}).items():
        if root in names:
            return bucket
    return None


def build_positions(raw_positions: list, open_orders: list, settings, today: date) -> tuple:
    """Broker positions → dashboard rows, plus short-put collateral (the sector-cap basis)."""
    shares = {p.get("symbol"): _f(p.get("qty")) for p in raw_positions
              if parse_occ(p.get("symbol", "")) is None}
    working: dict[str, list] = {}
    for o in open_orders or []:
        working.setdefault(o.get("symbol"), []).append(
            f"{o.get('side', '?')} {o.get('qty') or ''} {o.get('type', '')}"
            + (f" @ {o['limit_price']}" if o.get("limit_price") else "")
            + f" {o.get('time_in_force', '')}".rstrip())

    rows, collateral = [], 0.0
    for p in raw_positions:
        sym = p.get("symbol", "")
        qty = _f(p.get("qty"))
        entry = _f(p.get("avg_entry_price"))
        mark = _f(p.get("current_price"))
        occ = parse_occ(sym)
        row = {"symbol": sym, "occ": None, "qty": abs(qty), "mark": mark,
               "pnl_usd": _f(p.get("unrealized_pl")), "flags": []}
        if occ:
            root, dte = occ["root"], (occ["expiry"] - today).days
            if qty < 0:
                if occ["right"] == "P":
                    kind = "csp"
                    collateral += occ["strike"] * 100 * abs(qty)
                else:
                    covered = shares.get(root, 0) >= 100 * abs(qty)
                    kind = "cc" if covered else "short_call"
                pnl_pct = (entry - mark) / entry * 100 if entry else None
                row.update({"credit": entry})
            else:
                kind = "long_put" if occ["right"] == "P" else "long_call"
                pnl_pct = (mark - entry) / entry * 100 if entry else None
                row.update({"cost": entry})
            row.update({"symbol": root, "occ": sym, "kind": kind, "strike": occ["strike"],
                        "expiry": occ["expiry"].isoformat(), "dte": dte,
                        "multiplier": 100, "pnl_pct": pnl_pct})
            if kind == "short_call":
                row["flags"].append("uncovered")
        else:
            root, dte, kind = sym, None, "stock"
            pnl_pct = (mark - entry) / entry * 100 if entry else None
            row.update({"kind": kind, "cost": entry, "multiplier": 1, "pnl_pct": pnl_pct})
            if qty < 0:
                row["flags"].append("short shares")
        row["action"] = _position_action(kind, root, pnl_pct, dte, settings)
        sector = _sector_of(root, settings)
        if sector:
            row["sector"] = sector
        for w in working.get(sym, []):
            row["flags"].append("working: " + w)
        rows.append(row)

    rows.sort(key=lambda r: (r.get("dte") is None, r.get("dte") or 0, r["symbol"]))
    return rows, collateral


def _net_option_premium(fills: list) -> float:
    """Option sells minus option buys: realized premium cash this period. Negative
    when buy-to-close costs exceeded premium sold — which is exactly what happened
    on the stop-loss weeks, so it is not reported as a gross 'premium collected'."""
    net = 0.0
    for f in fills:
        if parse_occ(f.get("symbol", "")) is None:
            continue
        cash = _f(f.get("price")) * _f(f.get("qty")) * 100
        net += cash if str(f.get("side", "")).startswith("sell") else -cash
    return net


def _slow_account_data(spec: dict, broker: ReadOnlyBroker, settings, today: date,
                       cache: _Cache, errors: list) -> dict:
    key = f"slow:{spec['id']}"
    hit = cache.get(key, SLOW_TTL_SECONDS)
    if hit is not None:
        return hit

    data: dict[str, Any] = {"equity_curve": [], "inception_equity": None, "inception_date": None,
            "premium_mtd": None, "trade_stats": None}

    curve = performance.equity_curve(broker, today - timedelta(days=365), today)
    if curve.get("points"):
        data["equity_curve"] = [{"date": d.isoformat(), "equity": round(v, 2)}
                                for d, v in curve["series"]]
        data["inception_equity"] = curve["start_equity"]
        data["inception_date"] = curve["start_date"]
    else:
        errors.append(f"{spec['id']}: no portfolio history")

    try:
        month_start = datetime.combine(today.replace(day=1), time.min, tzinfo=MARKET_TZ)
        data["premium_mtd"] = round(_net_option_premium(broker.get_fills(month_start)), 2)
    except Exception as e:
        errors.append(f"{spec['id']}: fills unavailable ({e})")

    if spec.get("traded"):
        window = getattr(settings.live_gates, "history_window_days", 90) or 90
        stats = performance.trade_stats(settings, today - timedelta(days=window), today)
        if stats.get("available"):
            data["trade_stats"] = {
                "window_days": window,
                "trades_closed": stats["total_trades"],
                "win_rate": stats["win_rate"] / 100 if stats["total_trades"] else None,
                "profit_factor": stats["profit_factor"] if stats["gross_loss"] else None,
                "expectancy": stats["expectancy"] if stats["total_trades"] else None,
                "total_pnl": stats["total_pnl"],
            }
        else:
            errors.append("trade stats unavailable (no DATABASE_URL or DB unreachable)")

    cache.put(key, data)
    return data


def build_account(spec: dict, settings, today: date, cache: _Cache, errors: list) -> dict:
    out = {
        "id": spec["id"], "name": spec["name"], "broker": "Alpaca",
        "mode": "paper" if "paper" in spec.get("base_url", "") else "live",
        "traded": bool(spec.get("traded")), "error": spec.get("error"),
        "account": None, "stats": None, "equity_curve": [], "positions": [],
    }
    if out["error"]:
        errors.append(f"{spec['id']}: {out['error']}")
        return out
    broker = _broker_for(spec, settings)
    try:
        acct = broker.get_account() or {}
        raw_positions = broker.get_positions() or []
        orders = broker.get_open_orders() or []
    except Exception as e:
        out["error"] = f"broker unreachable: {e}"
        errors.append(f"{spec['id']}: {out['error']}")
        return out

    positions, collateral = build_positions(raw_positions, orders, settings, today)
    equity = _f(acct.get("equity"))
    cash = _f(acct.get("cash"))
    free_cash = max(0.0, cash - collateral)
    out["account"] = {
        "equity": equity,
        "day_pnl": equity - _f(acct.get("last_equity"), equity),
        "buying_power": _f(acct.get("buying_power")),
        "options_buying_power": _f(acct.get("options_buying_power")),
        "cash": cash,
        "short_put_collateral": collateral,
        "cash_reserve_pct": round(free_cash / equity * 100, 1) if equity else 0.0,
        "unrealized_pl": sum(p["pnl_usd"] for p in positions),
        "open_orders": len(orders),
        "account_number": acct.get("account_number"),
    }
    out["positions"] = positions

    slow = _slow_account_data(spec, broker, settings, today, cache, errors)
    ts = slow.get("trade_stats") or {}
    out["equity_curve"] = slow.get("equity_curve") or []
    out["stats"] = {
        "inception_equity": slow.get("inception_equity") or equity,
        "inception_date": slow.get("inception_date"),
        "premium_mtd": slow.get("premium_mtd"),
        "trades_closed": ts.get("trades_closed"),
        "win_rate": ts.get("win_rate"),
        "profit_factor": ts.get("profit_factor"),
        "expectancy": ts.get("expectancy"),
        "window_days": ts.get("window_days"),
    }
    return out


# ---------------------------------------------------------------------------
# Engine-wide: market, modules, events
# ---------------------------------------------------------------------------

def _trading_days(broker: Optional[ReadOnlyBroker], today: date, cache: _Cache) -> list:
    hit = cache.get("calendar", CALENDAR_TTL_SECONDS)
    if hit is None and broker is not None:
        try:
            cal = broker.get_calendar(today - timedelta(days=40), today + timedelta(days=7))
            hit = [c["date"] for c in cal if c.get("date")]
            cache.put("calendar", hit)
        except Exception:
            hit = None
    return [date.fromisoformat(d) for d in hit] if hit else []


def _occurrences(now_et: datetime, days_ok, hh: int, mm: int, grace: timedelta, n: int = 3):
    """The last `n` scheduled times at least `grace` in the past (so a task still inside
    its own window isn't reported late)."""
    cutoff = now_et - grace
    out, d = [], cutoff.date()
    for _ in range(60):
        if days_ok(d):
            t = datetime.combine(d, time(hh, mm), tzinfo=MARKET_TZ)
            if t <= cutoff:
                out.append(t)
                if len(out) >= n:
                    break
        d -= timedelta(days=1)
    return out


def _parse_run_key(value) -> Optional[date]:
    """agent_state stores run markers as '2026-09-18', '2026-W38' or ISO timestamps."""
    if not value:
        return None
    s = str(value)
    m = re.fullmatch(r"(\d{4})-W(\d{2})", s)
    if m:
        return date.fromisocalendar(int(m.group(1)), int(m.group(2)), 5)
    try:
        return datetime.fromisoformat(s).astimezone(MARKET_TZ).date() if "T" in s \
            else date.fromisoformat(s[:10])
    except ValueError:
        return None


def _scheduled_module(name: str, note: str, last_key: str, state: dict, now_et: datetime,
                      days_ok, hh: int, mm: int, every: str, grace_min: int = 60) -> dict:
    last = _parse_run_key(state.get(last_key))
    occ = _occurrences(now_et, days_ok, hh, mm, timedelta(minutes=grace_min))
    missed = sum(1 for t in occ if last is None or t.date() > last)
    status = "ok" if missed == 0 else "late" if missed == 1 else "stale"
    return {"name": name, "note": note, "kind": "scheduled", "every": every,
            "last_run": last.isoformat() if last else None,
            "expected": occ[0].date().isoformat() if occ else None,
            "missed": missed, "status": status}


def _interval_module(name: str, note: str, last_seen: Optional[str], interval_s: int,
                     stale_s: int, now: datetime, market_hours_only: bool,
                     market_open: Optional[bool]) -> dict:
    age = None
    if last_seen:
        try:
            age = (now - datetime.fromisoformat(last_seen)).total_seconds()
        except ValueError:
            age = None
    if market_hours_only and market_open is False:
        status = "idle"
    elif age is None:
        status = "stale"
    elif age <= interval_s * 2:
        status = "ok"
    elif age <= stale_s:
        status = "late"
    else:
        status = "stale"
    return {"name": name, "note": note, "kind": "interval", "interval_s": interval_s,
            "last_seen": last_seen, "status": status}


def build_modules(state: dict, settings, now: datetime, market_open: Optional[bool],
                  trading_days: list) -> list:
    now_et = now.astimezone(MARKET_TZ)
    weekday = lambda d: d.weekday() < 5      # the loop's own gate: weekdays, not market days
    monday = lambda d: d.weekday() == 0
    friday = lambda d: d.weekday() == 4
    tdays = set(trading_days)
    trading_day = (lambda d: d in tdays) if tdays else weekday

    hb = None
    try:
        hb = HEARTBEAT_PATH.read_text().strip() or None
    except OSError:
        pass
    feeds = getattr(settings, "feeds", None)
    whale_iv = int((getattr(feeds, "whale_poll_minutes", 30) or 30) * 60)
    policy_iv = int((getattr(feeds, "policy_poll_minutes", 15) or 15) * 60)
    polls = state.get("_feed_polls") or {}

    mods = [
        _interval_module("loop heartbeat", "written every cycle; watchdog cancels orders if stale",
                         hb, 60 if market_open else 300, HEARTBEAT_STALE_SECONDS, now,
                         False, market_open),
        _interval_module("broker API", "last successful Alpaca call in the open branch",
                         state.get("last_api_success"), 60, HEARTBEAT_STALE_SECONDS, now,
                         True, market_open),
    ]

    whale = _interval_module("whale feed", "last poll attempt (CapitolTrades)",
                             _iso(polls.get("whale")), whale_iv, whale_iv * 4, now,
                             True, market_open)
    if state.get("whale_source_blocked"):
        retry_at = (state.get("_feed_blocked_retries") or {}).get("whale")
        hours = getattr(feeds, "blocked_source_retry_hours", 24) or 24
        whale["status"] = "blocked"
        whale["note"] = f"source blocked (bot checkpoint); retried every {hours:g}h"
        if retry_at:
            whale["next_retry"] = _iso(retry_at + hours * 3600)
    mods.append(whale)
    mods.append(_interval_module("policy feed", "last poll attempt", _iso(polls.get("policy")),
                                 policy_iv, policy_iv * 4, now, True, market_open))

    mods += [
        _scheduled_module("ipo scan", "weekdays 08:30 ET", "last_ipo_scan", state, now_et,
                          weekday, 8, 30, "weekdays"),
        _scheduled_module("eligibility check", "weekdays 08:30 ET", "last_eligibility_check",
                          state, now_et, weekday, 8, 30, "weekdays"),
        _scheduled_module("morning briefing", "weekdays 09:00 ET", "last_morning_briefing",
                          state, now_et, weekday, 9, 0, "weekdays"),
        _scheduled_module("IV snapshot", "weekdays 10:00 ET; feeds the fail-closed IV gate",
                          "last_iv_snapshot", state, now_et, weekday, 10, 0, "weekdays"),
        _scheduled_module("derivatives scan", "after the IV snapshot", "last_derivatives_scan",
                          state, now_et, weekday, 10, 0, "weekdays", grace_min=90),
        _scheduled_module("daily report", "after the close, trading days", "last_daily_report",
                          state, now_et, trading_day, 16, 5, "trading days", grace_min=90),
        _scheduled_module("weekly scan", "Monday pre-market", "last_weekly_scan", state,
                          now_et, monday, 0, 0, "weekly", grace_min=9 * 60 + 30),
        _scheduled_module("universe screen", "Monday 11:00 ET", "last_universe_screen", state,
                          now_et, monday, 11, 0, "weekly"),
        _scheduled_module("weekly wrap-up", "Friday 16:15 ET", "last_weekly_wrapup", state,
                          now_et, friday, 16, 15, "weekly", grace_min=90),
    ]
    return mods


_TRADE_RE = re.compile(r"^(SELL|BUY|ROLL|CLOSE|BTC|STO|BOUGHT|SOLD)\b|\bfilled\b", re.IGNORECASE)


def _event_level(ev: dict) -> str:
    cat = str(ev.get("category", "")).lower()
    text = str(ev.get("insight", ""))
    if cat in ("alert", "error", "critical") or "[HALT]" in text or "CRITICAL" in text:
        return "error"
    if cat == "decision" and _TRADE_RE.search(text) and "[RISK]" not in text:
        return "trade"
    if "[RISK]" in text or "blocked" in text.lower() or "no new" in text.lower():
        return "warn"
    return "info"


def build_events(engine_id: str, limit: int = EVENT_LIMIT) -> list:
    """Newest `limit` insights, with bursts collapsed: the IV scan writes one line per
    ticker in the same second, and 90 'cheap premium' rows would bury every trade."""
    files = sorted(INSIGHTS_DIR.glob("*.jsonl"))[-3:]
    raw = []
    for fp in files:
        try:
            for line in fp.read_text().splitlines():
                try:
                    raw.append(json.loads(line))
                except ValueError:
                    continue
        except OSError:
            continue
    raw.sort(key=lambda e: e.get("ts", ""))

    events: list = []
    for ev in raw:
        level = _event_level(ev)
        item = {"ts": ev.get("ts"), "module": ev.get("source", "?"),
                "account": engine_id if ev.get("category") == "decision" else None,
                "level": level, "text": str(ev.get("insight", ""))[:300]}
        prev = events[-1] if events else None
        if (prev and level == "info" and prev["level"] == "info"
                and prev["module"] == item["module"] and prev.get("_cat") == ev.get("category")
                and abs(_ts_seconds(item["ts"]) - _ts_seconds(prev["ts"])) < 120):
            prev["_n"] = prev.get("_n", 1) + 1
            prev["ts"] = item["ts"]
            continue
        item["_cat"] = ev.get("category")
        events.append(item)

    out = []
    for e in events[-limit:]:
        n = e.pop("_n", 1)
        e.pop("_cat", None)
        if n > 1:
            e["text"] += f"  (+{n - 1} similar)"
        out.append(e)
    out.reverse()
    return out


def _ts_seconds(ts) -> float:
    try:
        return datetime.fromisoformat(str(ts)).timestamp()
    except ValueError:
        return 0.0


def _rules(settings) -> dict:
    pm, risk = settings.position_management, settings.risk
    return {
        "close_profit_pct": getattr(pm, "close_profit_pct", None),
        "roll_dte": getattr(pm, "roll_dte_threshold", None),
        "force_close_dte": getattr(pm, "force_close_dte", None),
        "stop_loss_pct": getattr(pm, "stop_loss_pct", None),
        "max_position_pct": getattr(risk, "max_position_pct", None),
        "quarantine_max_position_pct": getattr(risk, "quarantine_max_position_pct", None),
        "sector_cap_pct": getattr(risk, "sector_cap_pct", None),
        "iv_gate_fail_open": getattr(settings.wheel, "iv_gate_fail_open", None),
    }


# ---------------------------------------------------------------------------
# The snapshot
# ---------------------------------------------------------------------------

def build_state(settings=None, now: Optional[datetime] = None) -> dict:
    """Assemble the full snapshot. Never raises for a data problem; see `errors`."""
    settings = settings or cfg_module.load()
    now = now or datetime.now(timezone.utc)
    today = now.astimezone(MARKET_TZ).date()
    cache = _Cache()
    errors: list = []
    state = _read_json(STATE_PATH)
    if not state:
        errors.append(f"{STATE_PATH} unreadable — is this running from the repo root?")

    specs = account_specs(settings)
    engine_spec = next(s for s in specs if s["traded"])

    market: dict[str, Any] = {"is_open": None, "next_open": None, "next_close": None}
    engine_broker = None
    try:
        engine_broker = _broker_for(engine_spec, settings)
        clock = engine_broker.get_clock() or {}
        market = {"is_open": bool(clock.get("is_open")), "next_open": clock.get("next_open"),
                  "next_close": clock.get("next_close")}
    except Exception as e:
        errors.append(f"market clock unavailable: {e}")

    accounts = [build_account(s, settings, today, cache, errors) for s in specs]
    trading_days = _trading_days(engine_broker, today, cache)
    modules = build_modules(state, settings, now, market["is_open"], trading_days)

    alerts = []
    if state.get("halted"):
        alerts.append({"level": "error", "text": "Loop is HALTED — "
                       + str(state.get("last_halt_error") or "no error recorded")})
    for m in modules:
        if m["status"] == "stale":
            detail = ""
            if m["kind"] == "scheduled":
                detail = (f" (last run {m['last_run']}, missed {m['missed']})" if m["last_run"]
                          else " (never run)")
            alerts.append({"level": "error", "text": f"{m['name']} is stale{detail}"})
    for a in accounts:
        if a.get("error"):
            alerts.append({"level": "warn", "text": f"{a['name']}: {a['error']}"})

    cache.save()
    return {
        "generated_at": now.isoformat(),
        "engine_account": engine_spec["id"],
        "market": market,
        "rules": _rules(settings),
        "accounts": accounts,
        "modules": modules,
        "events": build_events(engine_spec["id"]),
        "alerts": alerts,
        "errors": errors,
    }


def write_snapshot(path: Path = SNAPSHOT_PATH, settings=None) -> dict:
    snap = build_state(settings)
    _atomic_write(path, snap)
    return snap


def main():
    ap = argparse.ArgumentParser(description="Read-only dashboard snapshot")
    ap.add_argument("--once", action="store_true", help="print the snapshot JSON to stdout")
    ap.add_argument("--write", nargs="?", const=str(SNAPSHOT_PATH), metavar="PATH",
                    help=f"write the snapshot (default {SNAPSHOT_PATH})")
    args = ap.parse_args()
    if args.write:
        snap = write_snapshot(Path(args.write))
        print(f"[DASH] wrote {args.write} — {len(snap['accounts'])} account(s), "
              f"{len(snap['errors'])} error(s)")
    else:
        print(json.dumps(build_state(), indent=2, default=str))


if __name__ == "__main__":
    main()
