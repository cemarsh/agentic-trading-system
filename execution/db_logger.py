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

CREATE TABLE IF NOT EXISTS strategy_analysis (
    id                SERIAL PRIMARY KEY,
    ts                TIMESTAMPTZ DEFAULT NOW(),
    ticker            TEXT,
    regime            TEXT,
    primary_strategy  TEXT,
    conviction        FLOAT,
    recommendation    TEXT,
    reasoning         TEXT,
    entry_plan        TEXT,
    stop_loss_price   FLOAT,
    target_price      FLOAT,
    reward_risk_ratio FLOAT,
    invalidation      TEXT,
    behavioral_check  TEXT
);

CREATE TABLE IF NOT EXISTS strategy_lessons (
    id              SERIAL PRIMARY KEY,
    ts              TIMESTAMPTZ DEFAULT NOW(),
    ticker          TEXT,
    strategy_used   TEXT,
    regime          TEXT,
    entry_price     FLOAT,
    exit_price      FLOAT,
    pnl             FLOAT,
    outcome         TEXT,
    lesson          TEXT
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


def log_strategy_analysis(
    ticker: str,
    regime: str,
    primary_strategy: str,
    conviction: float,
    recommendation: str,
    reasoning: str,
    entry_plan: str = "",
    stop_loss_price: Optional[float] = None,
    target_price: Optional[float] = None,
    reward_risk_ratio: Optional[float] = None,
    invalidation: str = "",
    behavioral_check: str = "",
    settings=None,
) -> int:
    cfg = settings or cfg_module.load()
    with get_connection(cfg) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO strategy_analysis
                    (ticker, regime, primary_strategy, conviction, recommendation,
                     reasoning, entry_plan, stop_loss_price, target_price,
                     reward_risk_ratio, invalidation, behavioral_check)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (ticker, regime, primary_strategy, conviction, recommendation,
                 reasoning, entry_plan, stop_loss_price, target_price,
                 reward_risk_ratio, invalidation, behavioral_check),
            )
            row_id = cur.fetchone()[0]
        conn.commit()
    return row_id


def log_lesson(
    ticker: str,
    strategy_used: str,
    regime: str,
    outcome: str,
    lesson: str,
    entry_price: Optional[float] = None,
    exit_price: Optional[float] = None,
    pnl: Optional[float] = None,
    settings=None,
) -> int:
    cfg = settings or cfg_module.load()
    with get_connection(cfg) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO strategy_lessons
                    (ticker, strategy_used, regime, entry_price, exit_price, pnl, outcome, lesson)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (ticker, strategy_used, regime, entry_price, exit_price, pnl, outcome, lesson),
            )
            row_id = cur.fetchone()[0]
        conn.commit()
    return row_id


def get_lessons(days: int = 7, settings=None) -> list:
    cfg = settings or cfg_module.load()
    with get_connection(cfg) as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT * FROM strategy_lessons
                WHERE ts >= NOW() - INTERVAL '%s days'
                ORDER BY ts DESC
                """,
                (days,),
            )
            return [dict(row) for row in cur.fetchall()]


class DBLogger:
    """Class wrapper around standalone logging functions for use in market_loop."""

    def __init__(self, settings=None):
        self._settings = settings

    def log_decision(self, **kwargs) -> int:
        return log_decision(**kwargs, settings=self._settings)

    def update_status(self, **kwargs):
        return update_status(**kwargs, settings=self._settings)

    def log_strategy_analysis(self, **kwargs) -> int:
        return log_strategy_analysis(**kwargs, settings=self._settings)

    def log_lesson(self, **kwargs) -> int:
        return log_lesson(**kwargs, settings=self._settings)

    def get_lessons(self, days: int = 7) -> list:
        return get_lessons(days=days, settings=self._settings)


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
