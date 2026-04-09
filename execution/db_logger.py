"""
PostgreSQL decision logger.
Writes every trade decision to the decision_logic table.
Usage:
    python execution/db_logger.py --init    # Create table
    python execution/db_logger.py --ping    # Verify connectivity
"""

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

import psycopg2
import psycopg2.extras
from config import settings as cfg_module

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS decision_logic (
    id          SERIAL PRIMARY KEY,
    ts          TIMESTAMPTZ DEFAULT NOW(),
    ticker      TEXT,
    action      TEXT,
    tier        TEXT,
    confidence  FLOAT,
    reasoning   TEXT,
    order_id    TEXT,
    status      TEXT,
    pnl         FLOAT
);
"""


def get_connection(settings=None):
    cfg = settings or cfg_module.load()
    return psycopg2.connect(cfg.database.url)


def init_schema(settings=None):
    with get_connection(settings) as conn:
        with conn.cursor() as cur:
            cur.execute(CREATE_TABLE_SQL)
        conn.commit()
    print("[OK] decision_logic table ready")


def log_decision(
    ticker: str,
    action: str,
    tier: str,
    confidence: float,
    reasoning: str,
    order_id: Optional[str] = None,
    status: str = "pending",
    pnl: Optional[float] = None,
    settings=None,
) -> int:
    cfg = settings or cfg_module.load()
    with get_connection(cfg) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO decision_logic
                    (ticker, action, tier, confidence, reasoning, order_id, status, pnl)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (ticker, action, tier, confidence, reasoning, order_id, status, pnl),
            )
            row_id = cur.fetchone()[0]
        conn.commit()
    return row_id


def update_status(row_id: int, status: str, order_id: str = None, pnl: float = None, settings=None):
    cfg = settings or cfg_module.load()
    with get_connection(cfg) as conn:
        with conn.cursor() as cur:
            fields = ["status = %s"]
            values = [status]
            if order_id:
                fields.append("order_id = %s")
                values.append(order_id)
            if pnl is not None:
                fields.append("pnl = %s")
                values.append(pnl)
            values.append(row_id)
            cur.execute(f"UPDATE decision_logic SET {', '.join(fields)} WHERE id = %s", values)
        conn.commit()


class DBLogger:
    """Class wrapper around standalone logging functions for use in market_loop."""

    def __init__(self, settings=None):
        self._settings = settings

    def log_decision(self, **kwargs) -> int:
        return log_decision(**kwargs, settings=self._settings)

    def update_status(self, **kwargs):
        return update_status(**kwargs, settings=self._settings)


def ping(settings=None) -> bool:
    try:
        with get_connection(settings) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
        print("[OK] PostgreSQL — connected")
        return True
    except Exception as e:
        print(f"[FAIL] PostgreSQL — {e}")
        return False


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--init", action="store_true")
    parser.add_argument("--ping", action="store_true")
    args = parser.parse_args()

    if args.ping:
        ok = ping()
        sys.exit(0 if ok else 1)

    if args.init:
        init_schema()
