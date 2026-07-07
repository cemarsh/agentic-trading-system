"""
Config-change proposal loop — the difference between a diary and a learning system.

The journal logs dozens of insights a day and the system wakes up identical the
next morning. This closes the loop with the smallest reviewable mechanism:

  1. Anything (a module, the journal synthesis, you) files a proposal:
         propose("wheel.min_iv_rank", "0.35", rationale="...", source="journal")
  2. Pending proposals are listed in the Friday weekly wrap-up email.
  3. You review weekly:  python execution/config_proposals.py list
                         python execution/config_proposals.py approve 3 --note "..."
                         python execution/config_proposals.py reject 4 --note "..."
  4. Approved changes are applied by editing config/strategy_params.yaml in git
     and deploying through deploy/deploy.sh, then marked applied:
                         python execution/config_proposals.py applied 3

Approval is deliberately human — the system proposes, you dispose.
"""

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import settings as cfg_module


def _connect(settings):
    import psycopg2
    return psycopg2.connect(settings.database.url)


def propose(config_key: str, proposed_value: str, rationale: str,
            source: str = "manual", current_value: Optional[str] = None,
            settings=None) -> Optional[int]:
    """File a proposal. Dedups: an identical pending (key, value) is not re-filed."""
    cfg = settings or cfg_module.load()
    if not cfg.database.url:
        print("[PROPOSALS] no DATABASE_URL — proposal not persisted")
        return None
    try:
        with _connect(cfg) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT id FROM proposed_config_changes
                       WHERE config_key=%s AND proposed_value=%s AND status='pending' LIMIT 1""",
                    (config_key, str(proposed_value)),
                )
                existing = cur.fetchone()
                if existing:
                    return existing[0]
                cur.execute(
                    """INSERT INTO proposed_config_changes
                           (source, config_key, current_value, proposed_value, rationale)
                       VALUES (%s, %s, %s, %s, %s) RETURNING id""",
                    (source, config_key, current_value, str(proposed_value), rationale),
                )
                pid = cur.fetchone()[0]
            conn.commit()
        print(f"[PROPOSALS] filed #{pid}: {config_key} -> {proposed_value}")
        return pid
    except Exception as e:
        print(f"[PROPOSALS] propose failed: {e}")
        return None


def list_proposals(status: str = "pending", settings=None) -> list:
    cfg = settings or cfg_module.load()
    if not cfg.database.url:
        return []
    try:
        import psycopg2.extras
        with _connect(cfg) as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """SELECT * FROM proposed_config_changes
                       WHERE status=%s ORDER BY proposed_at ASC""",
                    (status,),
                )
                return [dict(r) for r in cur.fetchall()]
    except Exception as e:
        print(f"[PROPOSALS] list failed: {e}")
        return []


def set_status(proposal_id: int, status: str, note: str = "", settings=None) -> bool:
    cfg = settings or cfg_module.load()
    if not cfg.database.url:
        return False
    try:
        with _connect(cfg) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """UPDATE proposed_config_changes
                       SET status=%s, reviewed_at=%s, review_note=%s WHERE id=%s""",
                    (status, datetime.now(timezone.utc), note, proposal_id),
                )
                updated = cur.rowcount
            conn.commit()
        return updated > 0
    except Exception as e:
        print(f"[PROPOSALS] update failed: {e}")
        return False


def build_pending_section(settings=None) -> str:
    """Markdown block of pending proposals for the weekly wrap-up email."""
    pending = list_proposals("pending", settings=settings)
    if not pending:
        return ""
    lines = [
        "## Pending Config Proposals — weekly review",
        "",
        "Approve/reject with `python execution/config_proposals.py approve|reject <id>`:",
        "",
        "| # | Key | Current | Proposed | Source | Rationale |",
        "|---|-----|---------|----------|--------|-----------|",
    ]
    for p in pending:
        lines.append(
            f"| {p['id']} | `{p['config_key']}` | {p.get('current_value') or '-'} | "
            f"**{p['proposed_value']}** | {p.get('source') or '-'} | "
            f"{(p.get('rationale') or '')[:120]} |"
        )
    return "\n".join(lines)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Config-change proposal review")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_prop = sub.add_parser("propose")
    p_prop.add_argument("key")
    p_prop.add_argument("value")
    p_prop.add_argument("--rationale", required=True)
    p_prop.add_argument("--current", default=None)
    p_prop.add_argument("--source", default="manual")

    p_list = sub.add_parser("list")
    p_list.add_argument("--status", default="pending")

    for name in ("approve", "reject", "applied"):
        p = sub.add_parser(name)
        p.add_argument("id", type=int)
        p.add_argument("--note", default="")

    args = parser.parse_args()

    if args.cmd == "propose":
        propose(args.key, args.value, args.rationale, source=args.source, current_value=args.current)
    elif args.cmd == "list":
        rows = list_proposals(args.status)
        if not rows:
            print(f"(no {args.status} proposals)")
        for r in rows:
            print(f"#{r['id']} [{r['status']}] {r['config_key']}: "
                  f"{r.get('current_value') or '?'} -> {r['proposed_value']}  "
                  f"({r.get('source')}) — {r.get('rationale')}")
    else:
        status = {"approve": "approved", "reject": "rejected", "applied": "applied"}[args.cmd]
        ok = set_status(args.id, status, note=args.note)
        print(f"#{args.id} -> {status}" if ok else f"#{args.id} not updated")
