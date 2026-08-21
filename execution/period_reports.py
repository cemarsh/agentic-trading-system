"""
Monthly and quarterly wrap-ups — the tier above journal/weekly/.

The daily journal answers "what happened today" and the weekly answers "what happened
this week". Neither answers "are we actually getting anywhere", because that question
only has meaning across enough weeks for a trend to separate from noise. These two
reports exist to answer it.

  monthly_wrapup()    rolls the month's weekly wrap-ups into one learning pass:
                      what changed, what didn't, what's next.
  quarterly_wrapup()  rolls three months into a progress/negatives/priorities review.
                      Falls back to reading weeklies directly when the monthly tier
                      has no history yet (the first quarter always does this).

Both embed execution/performance.py's deterministic Needle Movement block ahead of the
narrative, so the numbers are stated before anything gets to interpret them.

Triggers (execution/market_loop.py::run_scheduled_tasks):
  monthly    1st of the month, pre-market      dedup key "YYYY-MM"
  quarterly  1st of Jan/Apr/Jul/Oct, pre-market dedup key "YYYY-Qn"

On demand:
  python execution/period_reports.py --monthly [--month YYYY-MM]
  python execution/period_reports.py --quarterly [--trailing] [--quarter YYYY-Qn]
"""

import argparse
import os
import re
import sys
from datetime import datetime, date, timezone, timedelta
from pathlib import Path
from typing import Optional

try:
    from zoneinfo import ZoneInfo
    MARKET_TZ = ZoneInfo("America/New_York")
except ImportError:
    MARKET_TZ = timezone.utc

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import settings as cfg_module
from execution.performance import (
    collect,
    build_needle_section,
    period_bounds_month,
    period_bounds_quarter,
    quarter_label,
)

PROJECT_ROOT = Path(__file__).parent.parent
JOURNAL_DIR = PROJECT_ROOT / "journal"
WEEKLY_DIR = JOURNAL_DIR / "weekly"
MONTHLY_DIR = JOURNAL_DIR / "monthly"
QUARTERLY_DIR = JOURNAL_DIR / "quarterly"

# Keep per-source excerpts bounded so a long quarter can't blow the context window.
_WEEKLY_EXCERPT = 6000
_MONTHLY_EXCERPT = 9000


# ---------------------------------------------------------------------------
# Readers
# ---------------------------------------------------------------------------

def _week_start_of(label: str) -> Optional[date]:
    """Monday of an ISO week label like '2026-W34'. None if unparseable."""
    m = re.fullmatch(r"(\d{4})-W(\d{2})", label)
    if not m:
        return None
    try:
        return date.fromisocalendar(int(m.group(1)), int(m.group(2)), 1)
    except ValueError:
        return None


def read_weeklies(start: date, end: date) -> list:
    """
    Weekly wrap-ups whose Monday falls in [start, end].

    Anchoring on the Monday (not the filename's year) keeps a week that straddles a
    month boundary attached to exactly one month rather than both or neither.
    """
    out = []
    if not WEEKLY_DIR.exists():
        return out
    for path in sorted(WEEKLY_DIR.glob("*.md")):
        mon = _week_start_of(path.stem)
        if mon and start <= mon <= end:
            out.append({
                "label": path.stem,
                "week_start": mon.isoformat(),
                "body": path.read_text(encoding="utf-8"),
            })
    return out


def read_monthlies(start: date, end: date) -> list:
    """Monthly wrap-ups whose month falls in [start, end]."""
    out = []
    if not MONTHLY_DIR.exists():
        return out
    for path in sorted(MONTHLY_DIR.glob("*.md")):
        m = re.fullmatch(r"(\d{4})-(\d{2})", path.stem)
        if not m:
            continue
        first = date(int(m.group(1)), int(m.group(2)), 1)
        if start <= first <= end:
            out.append({
                "label": path.stem,
                "month_start": first.isoformat(),
                "body": path.read_text(encoding="utf-8"),
            })
    return out


def read_config_history(start: date, end: date) -> list:
    """
    Commits touching config/ or directives/ in the window — the record of what we
    deliberately changed, as opposed to what the market did to us. Lets the report
    separate "we adjusted X and Y moved" from "Y moved on its own".
    """
    import subprocess
    try:
        result = subprocess.run(
            ["git", "log", f"--since={start.isoformat()}", f"--until={end.isoformat()}",
             "--pretty=format:%ad|%s", "--date=short", "--", "config/", "directives/"],
            cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=20,
        )
        if result.returncode != 0:
            return []
        return [
            {"date": line.split("|", 1)[0], "subject": line.split("|", 1)[1]}
            for line in result.stdout.strip().splitlines() if "|" in line
        ]
    except Exception as e:
        print(f"[PERIOD] git config history failed: {e}")
        return []


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

MONTHLY_SYSTEM_PROMPT = """You are the senior analyst for an autonomous options/equity trading system.
You are writing the MONTHLY review: the month's weekly wrap-ups rolled into one learning pass.

The reader already sees daily and weekly reports and feels like nothing is improving. Your job is
to establish, from evidence, whether that feeling is correct — and if it is, say so plainly.

Rules:
- The Needle Movement numbers are given to you and are authoritative. Never restate them
  incorrectly, never soften them, never invent figures that are not in the input.
- Distinguish three things every time: what WE changed (config/code), what the MARKET did,
  and what the system's BEHAVIOUR was. Confusing these is the main failure mode of these reports.
- A recurring finding that appeared in multiple weeklies and was never actioned is the single
  most important thing you can surface. Hunt for these explicitly and name how many weeks each ran.
- Be specific: real tickers, real config parameter names, real dollar figures.
- Do not congratulate the system for mechanical correctness if it lost money.

Output format (plain markdown, exactly these sections):

## Month in One Paragraph
<4-6 sentences: net result, what drove it, whether this month differed from last>

## What Changed
<bulleted — config/strategy/code changes made this month and their observable effect.
 If a change had no measurable effect, say that.>

## What Did NOT Change
<bulleted — problems that persisted all month. For each, note how many weeks it recurred
 and whether it was ever actioned. This section is the point of the report.>

## Lessons Carried Forward
<bulleted — what the month taught. Each lesson must be falsifiable and tied to evidence,
 not a platitude.>

## What We're Working On Next
<bulleted and prioritized — specific, actionable, with the config parameter or module named.
 Order by expected impact on the equity curve.>
"""

QUARTERLY_SYSTEM_PROMPT = """You are the senior analyst for an autonomous options/equity trading system.
You are writing the QUARTERLY review covering roughly three months.

The reader's stated concern is that they do not believe real progress is being made. Treat that as a
hypothesis to test against the evidence, not a mood to manage. If the evidence says the system is not
progressing, your report must say so directly in the first paragraph.

Rules:
- The Needle Movement numbers are authoritative. Lead with what they say.
- Separate ENGINEERING progress (bugs fixed, features shipped, reliability) from FINANCIAL progress
  (equity, realized P&L, profit factor). A quarter can be strongly positive on the first and clearly
  negative on the second — if so, say exactly that, because conflating them is what makes progress
  feel imaginary.
- Identify structural problems, not incidents. A structural problem is one the system will keep
  reproducing until something is redesigned.
- Name recurring findings that survived the whole quarter unactioned, with counts.
- Every recommendation must be concrete enough to implement: name the module, the config parameter,
  or the specific rule to change.
- Do not pad. No encouragement. The reader wants the truth about a losing quarter.

Output format (plain markdown, exactly these sections):

## Verdict
<3-5 sentences answering directly: is the system making progress? Engineering vs financial.
 State the headline number.>

## Progress Made
<bulleted — genuine advances this quarter, with evidence. Separate engineering from financial.
 If financial progress is absent, state that rather than padding this section.>

## The Negatives
<bulleted — what got worse or stayed broken. Quantify each. Include losses, recurring
 unactioned findings, and capital that sat idle.>

## Structural Problems
<numbered — the root causes that will keep reproducing. For each: the mechanism, the evidence,
 and what would have to change. This is the most important section.>

## What Needs To Be Worked On
<numbered and strictly prioritized by expected impact on the equity curve. Each item names the
 module/parameter and states the expected effect and how you would measure it.>
"""


def _synthesize(system_prompt: str, user_input: str, settings, tag: str,
                max_tokens: int = 4000) -> Optional[str]:
    """Claude synthesis. Returns None (never raises) so callers fall back to template."""
    api_key = (
        getattr(getattr(settings, "anthropic", None), "api_key", None)
        or os.environ.get("ANTHROPIC_API_KEY", "")
    )
    if not api_key:
        print(f"[{tag}] no ANTHROPIC_API_KEY — using template fallback")
        return None
    try:
        import anthropic
    except ImportError:
        print(f"[{tag}] anthropic package missing — using template fallback")
        return None
    try:
        client = anthropic.Anthropic(api_key=api_key)
        msg = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=max_tokens,
            system=[{
                "type": "text",
                "text": system_prompt,
                "cache_control": {"type": "ephemeral"},
            }],
            messages=[{"role": "user", "content": user_input}],
        )
        return msg.content[0].text.strip()
    except Exception as e:
        print(f"[{tag}] Claude synthesis failed: {e}")
        return None


def _template_fallback(period_label: str, sources: list, source_kind: str) -> str:
    """Deterministic body when Claude is unavailable. The metrics block still carries."""
    lines = [
        f"## {period_label} — Summary (fallback)",
        "",
        f"Claude synthesis unavailable. {len(sources)} {source_kind} wrap-up(s) in scope:",
        "",
    ]
    lines += [f"- `{s['label']}`" for s in sources] or ["- _(none found)_"]
    lines += [
        "",
        "See the Needle Movement section above for the period's hard numbers, and the "
        "source wrap-ups listed for narrative detail.",
        "",
    ]
    return "\n".join(lines)


def _config_section(commits: list) -> str:
    if not commits:
        return "## Config & Strategy Changes\n\n_No config/ or directives/ commits in this period._\n"
    lines = ["## Config & Strategy Changes", "",
             "Deliberate changes made in this window (config/ and directives/ commits):", ""]
    lines += [f"- `{c['date']}` — {c['subject']}" for c in commits]
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Monthly
# ---------------------------------------------------------------------------

def monthly_wrapup(
    ref_date: Optional[date] = None,
    alpaca_client=None,
    regime: str = "NEUTRAL",
    notifier=None,
    settings=None,
) -> Path:
    """
    Generate journal/monthly/YYYY-MM.md for the month containing ref_date.

    Note ref_date is the month being REPORTED. The scheduler fires on the 1st and
    passes the previous month, not the day it happens to be running.
    """
    cfg = settings or cfg_module.load()
    ref = ref_date or datetime.now(MARKET_TZ).date()
    first, last = period_bounds_month(ref)
    label = ref.strftime("%Y-%m")
    pretty = ref.strftime("%B %Y")

    print(f"[MONTHLY] Generating wrap-up for {pretty} ({first} → {last})")

    weeklies = read_weeklies(first, last)
    commits = read_config_history(first, last)
    metrics = collect(alpaca_client, cfg, first, last)

    print(f"[MONTHLY] {len(weeklies)} weekly wrap-ups, {len(commits)} config commits, "
          f"{metrics['trades']['total_trades']} closed trades")

    needle = build_needle_section(metrics, pretty)

    user_input = f"""MONTH: {pretty} ({first} → {last})

NEEDLE_MOVEMENT (authoritative figures — do not contradict):
{needle}

CONFIG_AND_STRATEGY_CHANGES_THIS_MONTH ({len(commits)} commits):
{chr(10).join(f"- {c['date']} — {c['subject']}" for c in commits) or "(none)"}

WEEKLY_WRAP_UPS ({len(weeklies)} weeks):
{chr(10).join(f"===== {w['label']} (week of {w['week_start']}) ====={chr(10)}{w['body'][:_WEEKLY_EXCERPT]}" for w in weeklies) or "(no weekly wrap-ups found for this month)"}
"""

    body = _synthesize(MONTHLY_SYSTEM_PROMPT, user_input, cfg, "MONTHLY")
    if body is None:
        body = _template_fallback(pretty, weeklies, "weekly")

    mode = "paper" if cfg.guardrails.paper_mode else "live"
    header = (
        f"# Monthly Trading Review — {pretty}\n\n"
        f"**Period:** {first.isoformat()} → {last.isoformat()}  |  "
        f"**Regime:** {regime}  |  **Mode:** {mode}\n\n"
        f"**Weekly wrap-ups rolled up:** {len(weeklies)}  |  "
        f"**Config changes:** {len(commits)}\n\n"
        "---\n\n"
    )
    footer = (
        f"\n\n---\n*Generated {datetime.now(timezone.utc).isoformat()} "
        f"by execution/period_reports.py*\n"
    )
    full = (
        header + needle + "\n\n---\n\n" + body
        + "\n\n---\n\n" + _config_section(commits) + footer
    )

    MONTHLY_DIR.mkdir(parents=True, exist_ok=True)
    path = MONTHLY_DIR / f"{label}.md"
    path.write_text(full, encoding="utf-8")
    print(f"[MONTHLY] wrote {path}")

    if notifier:
        try:
            notifier.send(subject=f"[MONTHLY REVIEW] {pretty}", body=full)
            print("[MONTHLY] emailed")
        except Exception as e:
            print(f"[MONTHLY] email failed: {e}")

    return path


# ---------------------------------------------------------------------------
# Quarterly
# ---------------------------------------------------------------------------

def quarterly_wrapup(
    ref_date: Optional[date] = None,
    alpaca_client=None,
    regime: str = "NEUTRAL",
    notifier=None,
    settings=None,
    trailing: bool = False,
) -> Path:
    """
    Generate journal/quarterly/<label>.md.

    trailing=False  calendar quarter containing ref_date (the scheduled behaviour).
    trailing=True   the ~3 months ending at ref_date. Use when you want "the last
                    three months" from an arbitrary day rather than a calendar quarter.

    Monthly wrap-ups are the preferred source; when fewer than two exist for the window
    the report reads the weeklies directly instead. The first quarterly always takes
    that path, since the monthly tier has no history behind it yet.
    """
    cfg = settings or cfg_module.load()
    ref = ref_date or datetime.now(MARKET_TZ).date()

    if trailing:
        # ~3 calendar months back, inclusive of ref.
        first = (ref.replace(day=1) - timedelta(days=62)).replace(day=1)
        last = ref
        label = f"{ref.isoformat()}-trailing3m"
        pretty = f"Trailing 3 Months ending {ref.isoformat()}"
    else:
        first, last = period_bounds_quarter(ref)
        label = quarter_label(ref)
        pretty = label

    print(f"[QUARTERLY] Generating review for {pretty} ({first} → {last})")

    monthlies = read_monthlies(first, last)
    weeklies = read_weeklies(first, last)
    commits = read_config_history(first, last)
    metrics = collect(alpaca_client, cfg, first, last)

    # Prefer the monthly tier; fall back to weeklies when it is too thin to be a summary.
    use_monthlies = len(monthlies) >= 2
    sources = monthlies if use_monthlies else weeklies
    source_kind = "monthly" if use_monthlies else "weekly"

    print(f"[QUARTERLY] {len(monthlies)} monthly, {len(weeklies)} weekly wrap-ups "
          f"(using {source_kind} tier), {len(commits)} config commits, "
          f"{metrics['trades']['total_trades']} closed trades")

    needle = build_needle_section(metrics, pretty)
    excerpt = _MONTHLY_EXCERPT if use_monthlies else _WEEKLY_EXCERPT

    source_note = (
        f"Source tier: {source_kind} wrap-ups ({len(sources)} documents)."
        if use_monthlies else
        f"Source tier: weekly wrap-ups ({len(weeklies)} documents) — the monthly tier has "
        f"only {len(monthlies)} document(s) for this window, too few to summarize from."
    )

    user_input = f"""QUARTER: {pretty} ({first} → {last})

{source_note}

NEEDLE_MOVEMENT (authoritative figures — do not contradict):
{needle}

CONFIG_AND_STRATEGY_CHANGES_THIS_QUARTER ({len(commits)} commits):
{chr(10).join(f"- {c['date']} — {c['subject']}" for c in commits) or "(none)"}

{source_kind.upper()}_WRAP_UPS ({len(sources)} documents):
{chr(10).join(f"===== {s['label']} ====={chr(10)}{s['body'][:excerpt]}" for s in sources) or "(none found)"}
"""

    body = _synthesize(QUARTERLY_SYSTEM_PROMPT, user_input, cfg, "QUARTERLY", max_tokens=5000)
    if body is None:
        body = _template_fallback(pretty, sources, source_kind)

    mode = "paper" if cfg.guardrails.paper_mode else "live"
    header = (
        f"# Quarterly Trading Review — {pretty}\n\n"
        f"**Period:** {first.isoformat()} → {last.isoformat()}  |  "
        f"**Regime:** {regime}  |  **Mode:** {mode}\n\n"
        f"**Monthly wrap-ups:** {len(monthlies)}  |  **Weekly wrap-ups:** {len(weeklies)}  |  "
        f"**Config changes:** {len(commits)}\n\n"
        f"_{source_note}_\n\n"
        "---\n\n"
    )
    footer = (
        f"\n\n---\n*Generated {datetime.now(timezone.utc).isoformat()} "
        f"by execution/period_reports.py*\n"
    )
    full = (
        header + needle + "\n\n---\n\n" + body
        + "\n\n---\n\n" + _config_section(commits) + footer
    )

    QUARTERLY_DIR.mkdir(parents=True, exist_ok=True)
    path = QUARTERLY_DIR / f"{label}.md"
    path.write_text(full, encoding="utf-8")
    print(f"[QUARTERLY] wrote {path}")

    if notifier:
        try:
            notifier.send(subject=f"[QUARTERLY REVIEW] {pretty}", body=full)
            print("[QUARTERLY] emailed")
        except Exception as e:
            print(f"[QUARTERLY] email failed: {e}")

    return path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="Generate monthly / quarterly trading reviews")
    ap.add_argument("--monthly", action="store_true", help="generate a monthly review")
    ap.add_argument("--quarterly", action="store_true", help="generate a quarterly review")
    ap.add_argument("--month", help="target month YYYY-MM (default: current)")
    ap.add_argument("--quarter", help="target quarter YYYY-Qn (default: current)")
    ap.add_argument("--trailing", action="store_true",
                    help="quarterly over the trailing 3 months from today, not the calendar quarter")
    ap.add_argument("--no-email", action="store_true", help="write the file but do not email")
    args = ap.parse_args()

    if not args.monthly and not args.quarterly:
        ap.error("pass --monthly and/or --quarterly")

    cfg = cfg_module.load()

    from execution.alpaca_client import AlpacaClient
    alpaca = AlpacaClient(settings=cfg)

    notifier = None
    if not args.no_email:
        try:
            from execution.notifier import Notifier
            notifier = Notifier(settings=cfg)
        except Exception as e:
            print(f"[REPORT] notifier unavailable ({e}) — writing file only")

    regime = "NEUTRAL"
    try:
        from execution.regime_detector import RegimeDetector
        regime = RegimeDetector(settings=cfg, alpaca_client=alpaca).detect() or "NEUTRAL"
    except Exception:
        pass

    if args.monthly:
        ref = datetime.now(MARKET_TZ).date()
        if args.month:
            y, m = args.month.split("-")
            ref = date(int(y), int(m), 1)
        monthly_wrapup(ref_date=ref, alpaca_client=alpaca, regime=regime,
                       notifier=notifier, settings=cfg)

    if args.quarterly:
        ref = datetime.now(MARKET_TZ).date()
        if args.quarter:
            y, q = args.quarter.upper().split("-Q")
            ref = date(int(y), (int(q) - 1) * 3 + 1, 1)
        quarterly_wrapup(ref_date=ref, alpaca_client=alpaca, regime=regime,
                         notifier=notifier, settings=cfg, trailing=args.trailing)


if __name__ == "__main__":
    main()
