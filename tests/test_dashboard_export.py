"""Tests for the dashboard snapshot (execution/dashboard_export.py).

The dashboard is read-only by contract, and the things worth pinning are the ones that
would make it lie quietly: a position shown in the wrong rule zone, a missed weekly run
reported as healthy, collateral left out of free cash, a watched account passed off as
traded, or an order method reachable from the broker wrapper.
"""

import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

from execution import dashboard_export as dx


def _settings():
    return SimpleNamespace(
        alpaca=SimpleNamespace(key="K", secret="S", base_url=dx.PAPER_URL, paper_mode=True),
        position_management=SimpleNamespace(close_profit_pct=50, roll_dte_threshold=21,
                                            force_close_dte=7, stop_loss_pct=250),
        risk=SimpleNamespace(quarantined_tickers=["FJET"], max_position_pct=5.0,
                             quarantine_max_position_pct=1.0, sector_cap_pct=20.0,
                             sector_map={"defensive": ["GEO"]}),
        protection=SimpleNamespace(no_auto_manage=["OPTX"]),
        wheel=SimpleNamespace(iv_gate_fail_open=False),
        feeds=SimpleNamespace(whale_poll_minutes=30, policy_poll_minutes=15,
                              blocked_source_retry_hours=24),
        live_gates=SimpleNamespace(history_window_days=90),
    )


TODAY = date(2026, 9, 19)


def _opt(symbol, qty, entry, mark, upl=0.0):
    return {"symbol": symbol, "qty": str(qty), "avg_entry_price": str(entry),
            "current_price": str(mark), "unrealized_pl": str(upl)}


# --- OCC parsing / positions ------------------------------------------------

def test_parse_occ():
    p = dx.parse_occ("GEO261016P00029000")
    assert p == {"root": "GEO", "expiry": date(2026, 10, 16), "right": "P", "strike": 29.0}
    assert dx.parse_occ("FJET") is None


def test_csp_row_collateral_and_sector():
    rows, collateral = dx.build_positions(
        [_opt("GEO261016P00029000", -4, 1.00, 0.85, 60)], [], _settings(), TODAY)
    assert collateral == 29 * 100 * 4
    r = rows[0]
    assert (r["kind"], r["symbol"], r["dte"], r["action"]) == ("csp", "GEO", 27, "hold")
    assert r["sector"] == "defensive"
    assert round(r["pnl_pct"], 1) == 15.0


def test_rule_zones_in_priority_order():
    s = _settings()
    # stop beats everything; profit target beats DTE zones
    rows, _ = dx.build_positions([
        _opt("AAA260925P00010000", -1, 1.00, 3.60),   # -260% → stop, even at 6 DTE
        _opt("BBB260925P00010000", -1, 1.00, 0.40),   # +60% at 6 DTE → profit close
        _opt("CCC260925P00010000", -1, 1.00, 0.90),   # 6 DTE → force close
        _opt("DDD261002P00010000", -1, 1.00, 0.90),   # 13 DTE → roll zone
    ], [], s, TODAY)
    got = {r["symbol"]: r["action"] for r in rows}
    assert got == {"AAA": "stop", "BBB": "close_50", "CCC": "force_close", "DDD": "roll"}


def test_short_call_is_covered_only_with_shares():
    rows, _ = dx.build_positions([
        {"symbol": "MP", "qty": "100", "avg_entry_price": "50", "current_price": "52",
         "unrealized_pl": "200"},
        _opt("MP261016C00060000", -1, 1.0, 0.5),
        _opt("XOM261016C00120000", -1, 1.0, 0.5),
    ], [], _settings(), TODAY)
    kinds = {(r["symbol"], r["kind"]) for r in rows}
    assert ("MP", "cc") in kinds and ("XOM", "short_call") in kinds
    assert "uncovered" in next(r for r in rows if r["symbol"] == "XOM")["flags"]


def test_quarantined_stock_and_working_order_flag():
    rows, _ = dx.build_positions(
        [{"symbol": "FJET", "qty": "4570", "avg_entry_price": "5.70", "current_price": "1.64",
          "unrealized_pl": "-18565"}],
        [{"symbol": "FJET", "side": "sell", "qty": "4261", "type": "limit",
          "limit_price": "5.71", "time_in_force": "gtc"}],
        _settings(), TODAY)
    r = rows[0]
    assert r["action"] == "quarantine"
    assert r["flags"] == ["working: sell 4261 limit @ 5.71 gtc"]


def test_net_option_premium_counts_buybacks_against_sales():
    fills = [
        {"symbol": "GEO261016P00029000", "side": "sell", "qty": "4", "price": "1.00"},
        {"symbol": "KTOS261016P00080000", "side": "buy", "qty": "1", "price": "8.52"},
        {"symbol": "FJET", "side": "buy", "qty": "100", "price": "5"},   # shares ignored
    ]
    assert dx._net_option_premium(fills) == 400 - 852


# --- schedule health ---------------------------------------------------------

def _now_et(y, m, d, hh, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=dx.MARKET_TZ)


def test_parse_run_key_formats():
    assert dx._parse_run_key("2026-09-18") == date(2026, 9, 18)
    assert dx._parse_run_key("2026-W38") == date(2026, 9, 18)   # Friday of ISO week 38
    assert dx._parse_run_key(None) is None


def test_missed_monday_scan_is_late_then_stale():
    monday = lambda d: d.weekday() == 0
    state = {"last_weekly_scan": "2026-09-07"}
    m = dx._scheduled_module("weekly scan", "", "last_weekly_scan", state,
                             _now_et(2026, 9, 19, 12), monday, 0, 0, "weekly", 9 * 60 + 30)
    assert (m["status"], m["missed"], m["expected"]) == ("late", 1, "2026-09-14")
    m = dx._scheduled_module("weekly scan", "", "last_weekly_scan", state,
                             _now_et(2026, 9, 21, 12), monday, 0, 0, "weekly", 9 * 60 + 30)
    assert (m["status"], m["missed"]) == ("stale", 2)


def test_task_inside_its_window_is_not_late():
    weekday = lambda d: d.weekday() < 5
    state = {"last_iv_snapshot": "2026-09-17"}
    # Friday 10:20 ET: today's 10:00 snapshot may still be running — expect Thursday's.
    m = dx._scheduled_module("IV", "", "last_iv_snapshot", state, _now_et(2026, 9, 18, 10, 20),
                             weekday, 10, 0, "weekdays")
    assert m["status"] == "ok"
    m = dx._scheduled_module("IV", "", "last_iv_snapshot", state, _now_et(2026, 9, 18, 11, 30),
                             weekday, 10, 0, "weekdays")
    assert m["status"] == "late"


def test_feeds_idle_when_market_closed_and_blocked_whale_flagged():
    now = datetime(2026, 9, 19, 12, tzinfo=timezone.utc)
    state = {"whale_source_blocked": True,
             "_feed_polls": {"whale": now.timestamp() - 60},
             "_feed_blocked_retries": {"whale": now.timestamp() - 3600}}
    mods = {m["name"]: m for m in dx.build_modules(state, _settings(), now, False, [])}
    assert mods["policy feed"]["status"] == "idle"
    assert mods["whale feed"]["status"] == "blocked"
    assert mods["whale feed"]["next_retry"]


# --- accounts ------------------------------------------------------------------

def test_single_account_default(monkeypatch):
    monkeypatch.delenv("ALPACA_ACCOUNTS", raising=False)
    monkeypatch.delenv("ALPACA_ACCOUNT_ID", raising=False)
    specs = dx.account_specs(_settings())
    assert [(s["id"], s["traded"]) for s in specs] == [("engine", True)]


def test_watched_accounts_and_missing_keys(monkeypatch):
    monkeypatch.setenv("ALPACA_ACCOUNTS", "acct3,acct1,acct2")
    monkeypatch.setenv("ALPACA_ACCOUNT_ID", "acct3")
    monkeypatch.setenv("ALPACA_KEY_ACCT1", "K1")
    monkeypatch.setenv("ALPACA_SECRET_ACCT1", "S1")
    monkeypatch.setenv("ALPACA_NAME_ACCT1", "Sandbox")
    monkeypatch.delenv("ALPACA_KEY_ACCT2", raising=False)
    specs = {s["id"]: s for s in dx.account_specs(_settings())}
    assert list(specs) == ["acct3", "acct1", "acct2"]
    assert specs["acct3"]["traded"] and specs["acct3"]["key"] == "K"
    assert not specs["acct1"]["traded"] and specs["acct1"]["name"] == "Sandbox"
    assert "ALPACA_KEY_ACCT2" in specs["acct2"]["error"]


def test_engine_account_added_when_not_listed(monkeypatch):
    monkeypatch.setenv("ALPACA_ACCOUNTS", "acct1")
    monkeypatch.setenv("ALPACA_KEY_ACCT1", "K1")
    monkeypatch.setenv("ALPACA_SECRET_ACCT1", "S1")
    monkeypatch.delenv("ALPACA_ACCOUNT_ID", raising=False)
    specs = dx.account_specs(_settings())
    assert specs[0]["traded"] and specs[0]["id"] == "engine"


def test_free_cash_subtracts_short_put_collateral(monkeypatch):
    broker = MagicMock()
    broker.get_account.return_value = {"equity": "100000", "last_equity": "99000",
                                       "cash": "60000", "buying_power": "1"}
    broker.get_positions.return_value = [_opt("GEO261016P00029000", -4, 1.0, 0.85)]
    broker.get_open_orders.return_value = []
    monkeypatch.setattr(dx, "_broker_for", lambda spec, s: broker)
    monkeypatch.setattr(dx, "_slow_account_data", lambda *a, **k: {})
    spec = {"id": "x", "name": "x", "base_url": dx.PAPER_URL, "traded": False}
    a = dx.build_account(spec, _settings(), TODAY, None, [])
    assert a["account"]["short_put_collateral"] == 11600
    assert a["account"]["cash_reserve_pct"] == round((60000 - 11600) / 100000 * 100, 1)
    assert a["account"]["day_pnl"] == 1000


def test_broker_wrapper_exposes_no_order_methods():
    exposed = {n for n in dir(dx.ReadOnlyBroker) if not n.startswith("_")}
    assert not exposed & {"submit_order", "submit_option_order", "cancel_order",
                          "cancel_all_orders"}
    client = MagicMock()
    dx.ReadOnlyBroker(client).get_account()
    client.get_account.assert_called_once()


# --- events ----------------------------------------------------------------------

def test_events_collapse_bursts_and_classify(tmp_path, monkeypatch):
    lines = [{"ts": f"2026-09-18T14:00:2{i}+00:00", "source": "derivatives", "category": "signal",
              "insight": f"T{i} IV rank 5% — cheap premium"} for i in range(5)]
    lines += [
        {"ts": "2026-09-18T15:00:00+00:00", "source": "wheel", "category": "decision",
         "insight": "SELL CSP GEO 4x $29.0 exp 2026-10-16 @ $1.00/sh credit"},
        {"ts": "2026-09-18T15:01:00+00:00", "source": "wheel", "category": "decision",
         "insight": "[RISK] CSP blocked — sector cap"},
    ]
    (tmp_path / "2026-09-18.jsonl").write_text("\n".join(json.dumps(x) for x in lines))
    monkeypatch.setattr(dx, "INSIGHTS_DIR", tmp_path)
    ev = dx.build_events("acct3")
    assert [e["level"] for e in ev] == ["warn", "trade", "info"]
    assert ev[1]["account"] == "acct3"
    assert ev[2]["text"].endswith("(+4 similar)")
