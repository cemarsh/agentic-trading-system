"""
Terminal dashboard — the same snapshot as the web page, rendered with rich.

    python execution/dashboard_tui.py                 # live, refreshes every 30 s (Ctrl-C quits)
    python execution/dashboard_tui.py --once          # print one frame and exit (pipe-safe)
    python execution/dashboard_tui.py --from-file     # render logs/dashboard/state.json, no API calls
    python execution/dashboard_tui.py --account acct3 # one account instead of all

By default it calls dashboard_export.build_state() itself, so it still works when
trading-dashboard.service (the web server + exporter thread) is down — that is the
point of having both. Read-only for the same reason the exporter is.
"""

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

from rich import box
from rich.console import Console, Group, RenderableType
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from execution import dashboard_export

SPARK = "▁▂▃▄▅▆▇█"
STATUS_STYLE = {"ok": ("●", "green"), "late": ("●", "yellow"), "stale": ("●", "red"),
                "idle": ("○", "grey50"), "offline": ("○", "grey50"),
                "blocked": ("○", "yellow"), "quarantined": ("●", "blue")}
LEVEL_STYLE = {"error": "red", "warn": "yellow", "trade": "green", "info": "grey70"}
KIND = {"csp": "short put", "cc": "covered call", "short_call": "short call",
        "long_put": "long put", "long_call": "long call", "stock": "shares"}


def _num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def usd(v, dp: int = 0, sign: bool = False) -> str:
    if not _num(v):
        return "—"
    s = f"${abs(v):,.{dp}f}"
    return (("+" if v >= 0 else "-") if sign else ("-" if v < 0 else "")) + s


def pct(v, dp: int = 1) -> str:
    return f"{v:+.{dp}f}%" if _num(v) else "—"


def tone(v) -> str:
    return "" if not _num(v) else ("green" if v >= 0 else "red")


def sparkline(values: list, width: int = 60) -> str:
    if len(values) < 2:
        return ""
    if len(values) > width:  # keep the shape: sample evenly, always include the last point
        step = (len(values) - 1) / (width - 1)
        values = [values[round(i * step)] for i in range(width)]
    lo, hi = min(values), max(values)
    span = (hi - lo) or 1
    return "".join(SPARK[min(7, int((v - lo) / span * 7.999))] for v in values)


def max_drawdown(curve: list) -> float:
    peak, worst = float("-inf"), 0.0
    for p in curve:
        peak = max(peak, p["equity"])
        if peak > 0:
            worst = max(worst, (peak - p["equity"]) / peak * 100)
    return worst


def _ago(iso, now: datetime) -> str:
    if not iso:
        return "never"
    try:
        s = int((now - datetime.fromisoformat(iso)).total_seconds())
    except ValueError:
        return "?"
    if s < 60:
        return f"{s}s ago"
    if s < 3600:
        return f"{s // 60}m ago"
    if s < 86400:
        return f"{s // 3600}h {s % 3600 // 60}m ago"
    return f"{s // 86400}d {s % 86400 // 3600}h ago"


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------

def header(snap: dict, now: datetime) -> Text:
    m = snap.get("market") or {}
    if m.get("is_open") is True and m.get("next_close"):
        mins = max(0, int((datetime.fromisoformat(m["next_close"]) - now).total_seconds() // 60))
        mkt = Text(f"market open, closes in {mins // 60}h {mins % 60}m", style="green")
    elif m.get("is_open") is False and m.get("next_open"):
        opens = datetime.fromisoformat(m["next_open"]).astimezone(dashboard_export.MARKET_TZ)
        mkt = Text(f"market closed, opens {opens:%a %H:%M} ET", style="grey70")
    else:
        mkt = Text("market clock unavailable", style="yellow")
    gen = datetime.fromisoformat(snap["generated_at"])
    age = (now - gen).total_seconds()
    t = Text.assemble(("Wheel Engine", "bold"), "  ", mkt, "  ",
                      (f"snapshot {gen.astimezone():%H:%M:%S}", "red" if age > 180 else "grey50"))
    return t


def alerts(snap: dict, now: datetime):
    items = list(snap.get("alerts") or [])
    age = (now - datetime.fromisoformat(snap["generated_at"])).total_seconds()
    if age > 180:
        items.insert(0, {"level": "error",
                         "text": f"snapshot is {int(age // 60)}m old — numbers are not current"})
    if not items:
        return None
    body = Text("\n").join(Text(a["text"], style=LEVEL_STYLE.get(a["level"], "yellow"))
                           for a in items)
    return Panel(body, title="alerts", border_style="red", box=box.ROUNDED)


def accounts_table(accts: list) -> Table:
    t = Table(box=box.SIMPLE_HEAD, expand=True, pad_edge=False, title="accounts", title_justify="left",
              title_style="bold")
    for col, j in (("account", "left"), ("equity", "right"), ("today", "right"),
                   ("total P&L", "right"), ("free", "right"),
                   ("prem MTD", "right"), ("PF", "right"), ("exp", "right"),
                   ("win", "right"), ("closed", "right"), ("max DD", "right")):
        t.add_column(col, justify=j, no_wrap=True)  # type: ignore[arg-type]
    for a in accts:
        name = Text(a["name"])
        name.append(f" {a['mode']}", style="yellow" if a["mode"] == "paper" else "green")
        if not a["traded"]:
            name.append(" watched", style="grey50")
        if a.get("error") or not a.get("account"):
            t.add_row(name, Text(a.get("error") or "no data", style="red"),
                      *[""] * 9)
            continue
        acc, st, curve = a["account"], a["stats"] or {}, a["equity_curve"]
        cum = acc["equity"] - (st.get("inception_equity") or acc["equity"])
        cum_pct = cum / st["inception_equity"] * 100 if st.get("inception_equity") else None
        pf = st.get("profit_factor")
        pf_style = "" if pf is None else ("green" if pf >= 1 else "red")
        t.add_row(
            name, usd(acc["equity"]),
            Text(usd(acc["day_pnl"], sign=True), style=tone(acc["day_pnl"])),
            Text(f"{usd(cum, sign=True)} {pct(cum_pct)}", style=tone(cum)),
            f"{acc['cash_reserve_pct']:.0f}%",
            Text(usd(st.get("premium_mtd"), sign=True), style=tone(st.get("premium_mtd"))),
            Text(f"{pf:.2f}" if _num(pf) else "—",
                 style=pf_style),
            Text(usd(st.get("expectancy"), sign=True), style=tone(st.get("expectancy"))),
            f"{st['win_rate'] * 100:.0f}%" if _num(st.get("win_rate")) else "—",
            str(st["trades_closed"]) if _num(st.get("trades_closed")) else "—",
            Text(f"-{max_drawdown(curve):.1f}%" if len(curve) > 1 else "—", style="red"),
        )
    return t


def curves(accts: list, width: int):
    """One sparkline per account, full width — too wide to share a row with the numbers."""
    lines = []
    for a in accts:
        curve = a.get("equity_curve") or []
        if len(curve) < 2:
            continue
        first, last = curve[0], curve[-1]
        label = f"{a['name']:<10} {first['date']} {usd(first['equity'])} "
        tail = f" {usd(last['equity'])} {last['date']}"
        spark = sparkline([p["equity"] for p in curve], max(10, width - len(label) - len(tail) - 2))
        lines.append(Text.assemble((label, "grey50"),
                                   (spark, "green" if last["equity"] >= first["equity"] else "red"),
                                   (tail, "grey50")))
    return Text("\n").join(lines) if lines else None


def positions_table(accts: list, rules: dict, market_open) -> Table:
    multi = len(accts) > 1
    title = "open positions" + ("  (marks as of last close)" if market_open is False else "")
    t = Table(box=box.SIMPLE_HEAD, expand=True, pad_edge=False, title=title, title_justify="left",
              title_style="bold")
    if multi:
        t.add_column("acct", no_wrap=True)
    for col, j in (("symbol", "left"), ("kind", "left"), ("contract", "left"),
                   ("DTE", "right"), ("entry", "right"), ("mark", "right"),
                   ("P&L", "right"), ("$", "right"), ("rule", "left"), ("notes", "left")):
        t.add_column(col, justify=j, no_wrap=col not in ("notes",))  # type: ignore[arg-type]
    rule_text = {
        "hold": ("hold", ""),
        "close_50": (f"at {rules.get('close_profit_pct', 50)}% target", "green"),
        "roll": (f"≤{rules.get('roll_dte', 21)} DTE roll zone", "yellow"),
        "force_close": (f"≤{rules.get('force_close_dte', 7)} DTE force close", "red"),
        "stop": (f"past -{rules.get('stop_loss_pct', 250)}% stop", "red"),
        "quarantine": ("quarantined", "blue"),
    }
    rows = 0
    for a in accts:
        for p in a.get("positions") or []:
            rows += 1
            entry = p.get("credit") if p.get("credit") is not None else p.get("cost")
            contract = (f"{p['qty']:g}× {p['strike']:g} {p['expiry']}" if p.get("expiry")
                        else f"{p['qty']:g} sh")
            dte = p.get("dte")
            dte_style = ("red" if dte is not None and dte <= rules.get("force_close_dte", 7)
                         else "yellow" if dte is not None and dte <= rules.get("roll_dte", 21)
                         else "")
            label, style = rule_text.get(p.get("action"), (p.get("action") or "", ""))
            notes = ", ".join(filter(None, [p.get("sector")] + list(p.get("flags") or [])))
            cells = [p["symbol"], KIND.get(p["kind"], p["kind"]), contract,
                     Text(str(dte) if dte is not None else "—", style=dte_style),
                     f"{entry:.2f}" if _num(entry) else "—",
                     f"{p['mark']:.2f}" if _num(p.get("mark")) else "—",
                     Text(pct(p.get("pnl_pct")), style=tone(p.get("pnl_pct"))),
                     Text(usd(p.get("pnl_usd"), sign=True), style=tone(p.get("pnl_usd"))),
                     Text(label, style=style), Text(notes, style="grey70")]
            t.add_row(*([a["name"]] if multi else []) + cells)
    if not rows:
        t.add_row(*([""] if multi else []), Text("no open positions", style="grey50"),
                  *[""] * 9)
    return t


def modules_table(mods: list, now: datetime) -> Table:
    t = Table(box=box.SIMPLE_HEAD, expand=True, pad_edge=False, title="modules", title_justify="left",
              title_style="bold")
    t.add_column("", no_wrap=True, width=1)
    t.add_column("module", no_wrap=True)
    t.add_column("last", no_wrap=True)
    t.add_column("note", style="grey50", overflow="ellipsis", no_wrap=True)
    for m in mods:
        glyph, style = STATUS_STYLE.get(m["status"], ("?", "red"))
        if m.get("kind") == "scheduled":
            last = (m.get("last_run") or "never") + (f", missed {m['missed']}" if m.get("missed") else "")
        elif m["status"] == "blocked":
            last = "blocked" + (f", retry {datetime.fromisoformat(m['next_retry']).astimezone():%a %H:%M}"
                                if m.get("next_retry") else "")
        elif m["status"] == "idle":
            last = "idle, market closed"
        else:
            last = _ago(m.get("last_seen"), now)
        t.add_row(Text(glyph, style=style), m["name"],
                  Text(last, style=style if m["status"] != "ok" else ""), m.get("note", ""))
    return t


def activity_table(events: list, limit: int) -> Table:
    t = Table(box=box.SIMPLE_HEAD, expand=True, pad_edge=False, title="activity", title_justify="left",
              title_style="bold")
    t.add_column("time", no_wrap=True, style="grey50")
    t.add_column("source", no_wrap=True, style="grey50")
    t.add_column("event", overflow="fold")
    for e in events[:limit]:
        try:
            when = datetime.fromisoformat(e["ts"]).astimezone().strftime("%m-%d %H:%M")
        except (ValueError, TypeError):
            when = "?"
        t.add_row(when, e.get("module", ""), Text(e.get("text", ""),
                                                  style=LEVEL_STYLE.get(e.get("level"), "")))
    return t


def render(snap: dict, account: Optional[str] = None, events: int = 12, width: int = 120):
    now = datetime.now(timezone.utc)
    accts = snap.get("accounts") or []
    if account:
        accts = [a for a in accts if a["id"] == account]
        if not accts:
            return Text(f"no account '{account}' in snapshot "
                        f"({', '.join(a['id'] for a in snap.get('accounts') or [])})", style="red")
    parts: list[RenderableType] = [header(snap, now)]
    al = alerts(snap, now)
    if al:
        parts.append(al)
    parts.append(accounts_table(accts))
    cv = curves(accts, width)
    if cv:
        parts.append(cv)
    parts.append(positions_table(accts, snap.get("rules") or {},
                                 (snap.get("market") or {}).get("is_open")))
    parts.append(modules_table(snap.get("modules") or [], now))
    ev = snap.get("events") or []
    if account:
        ev = [e for e in ev if not e.get("account") or e["account"] == account]
    parts.append(activity_table(ev, events))
    rules = snap.get("rules") or {}
    errs = snap.get("errors") or []
    foot = Text(f"rules: close {rules.get('close_profit_pct')}%, roll ≤{rules.get('roll_dte')} DTE, "
                f"force ≤{rules.get('force_close_dte')} DTE, put stop -{rules.get('stop_loss_pct')}%, "
                f"position cap {rules.get('max_position_pct')}%, sector cap "
                f"{rules.get('sector_cap_pct')}%", style="grey50")
    if errs:
        foot.append(f"\n{len(errs)} data error(s): " + "; ".join(errs), style="yellow")
    parts.append(foot)
    return Group(*parts)


def get_snapshot(from_file: bool) -> dict:
    if from_file:
        return json.loads(dashboard_export.SNAPSHOT_PATH.read_text())
    return dashboard_export.build_state()


def main():
    ap = argparse.ArgumentParser(description="Terminal trading dashboard (read-only)")
    ap.add_argument("--once", action="store_true", help="print one frame and exit")
    ap.add_argument("--from-file", action="store_true",
                    help=f"render {dashboard_export.SNAPSHOT_PATH} instead of querying")
    ap.add_argument("--account", help="show one account id")
    ap.add_argument("--interval", type=int, default=30, help="refresh seconds (live mode)")
    ap.add_argument("--events", type=int, default=12, help="activity rows")
    ap.add_argument("--width", type=int, help="fixed width (useful with --once in a pipe)")
    args = ap.parse_args()

    console = Console(width=args.width) if args.width else Console()
    if args.once or not console.is_terminal:
        console.print(render(get_snapshot(args.from_file), args.account, args.events, console.width))
        return

    interval = max(10, args.interval)
    with Live(render(get_snapshot(args.from_file), args.account, args.events, console.width),
              console=console, screen=True, auto_refresh=False) as live:
        try:
            while True:
                time.sleep(interval)
                try:
                    live.update(render(get_snapshot(args.from_file), args.account, args.events, console.width),
                                refresh=True)
                except Exception as e:  # keep the last frame on a failed refresh
                    console.log(f"[red]refresh failed: {e}")
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
