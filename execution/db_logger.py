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

-- NotebookLM trading intelligence bridge tables
CREATE TABLE IF NOT EXISTS research_briefs (
    id              UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    content         TEXT NOT NULL,
    source          VARCHAR(50) DEFAULT 'notebooklm',
    signal_count    INT DEFAULT 0,
    top_conviction  INT DEFAULT 0,
    tickers_mentioned JSONB DEFAULT '[]',
    processed_at    TIMESTAMPTZ DEFAULT NOW(),
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS trading_signals (
    id                  UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    ticker              VARCHAR(10) NOT NULL,
    direction           VARCHAR(10) NOT NULL CHECK (direction IN ('bullish','bearish','neutral')),
    thesis              TEXT NOT NULL,
    source_type         VARCHAR(20) NOT NULL,
    catalysts           JSONB DEFAULT '[]',
    risk_factors        JSONB DEFAULT '[]',
    sector              VARCHAR(50),
    congressional_refs  JSONB DEFAULT '[]',
    timeframe           VARCHAR(10),
    conviction          INT NOT NULL CHECK (conviction BETWEEN 1 AND 10),
    wheel_eligible      BOOLEAN DEFAULT false,
    suggested_strategy  VARCHAR(10),
    premium_environment VARCHAR(10),
    source_brief_id     UUID REFERENCES research_briefs(id),
    status              VARCHAR(20) DEFAULT 'active' CHECK (status IN ('active','acted','expired','dismissed')),
    acted_at            TIMESTAMPTZ,
    notes               TEXT,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_signals_ticker     ON trading_signals(ticker);
CREATE INDEX IF NOT EXISTS idx_signals_conviction ON trading_signals(conviction DESC);
CREATE INDEX IF NOT EXISTS idx_signals_status     ON trading_signals(status);

CREATE TABLE IF NOT EXISTS workflow_runs (
    id                 UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    workflow_name      VARCHAR(100) NOT NULL,
    status             VARCHAR(20) NOT NULL CHECK (status IN ('success','error','partial')),
    input_hash         VARCHAR(64),
    signals_extracted  INT DEFAULT 0,
    signals_upserted   INT DEFAULT 0,
    error_message      TEXT,
    duration_ms        INT,
    created_at         TIMESTAMPTZ DEFAULT NOW()
);

-- IV history for IVR/IVP computation (Account C derivatives gate)
CREATE TABLE IF NOT EXISTS iv_history (
    id              SERIAL PRIMARY KEY,
    ticker          VARCHAR(10) NOT NULL,
    snapshot_date   DATE NOT NULL,
    iv_value        FLOAT NOT NULL,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (ticker, snapshot_date)
);

CREATE INDEX IF NOT EXISTS idx_iv_history_ticker_date ON iv_history(ticker, snapshot_date DESC);

-- Derivatives positions (Account C multi-leg structures)
CREATE TABLE IF NOT EXISTS derivatives_positions (
    id              UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    account         VARCHAR(5) NOT NULL DEFAULT 'C',
    strategy        VARCHAR(20) NOT NULL,  -- BWB, IRON_CONDOR, JADE_LIZARD, VERTICAL, LEAPS, EVENT
    ticker          VARCHAR(10) NOT NULL,
    regime_at_entry VARCHAR(20),
    iv_rank_at_entry FLOAT,
    legs            JSONB NOT NULL,        -- array of {symbol, side, qty, avg_fill}
    net_credit      FLOAT,                 -- positive = credit received, negative = debit paid
    max_profit      FLOAT,
    max_loss        FLOAT,
    dte_at_entry    INT,
    target_close_pct FLOAT DEFAULT 0.50,  -- close at this % of max profit
    status          VARCHAR(20) DEFAULT 'open' CHECK (status IN ('open','closed','rolled','expired')),
    opened_at       TIMESTAMPTZ DEFAULT NOW(),
    closed_at       TIMESTAMPTZ,
    realized_pnl    FLOAT,
    close_reason    TEXT
);

CREATE INDEX IF NOT EXISTS idx_deriv_status  ON derivatives_positions(status);
CREATE INDEX IF NOT EXISTS idx_deriv_ticker  ON derivatives_positions(ticker);
CREATE INDEX IF NOT EXISTS idx_deriv_account ON derivatives_positions(account);

-- Feedback loop: journal lessons become PROPOSED config changes, reviewed weekly
-- (approve/reject via execution/config_proposals.py), so the system doesn't wake
-- up identical every day. A diary logs; a learning system compiles.
CREATE TABLE IF NOT EXISTS proposed_config_changes (
    id           SERIAL PRIMARY KEY,
    proposed_at  TIMESTAMPTZ DEFAULT NOW(),
    source       TEXT,                        -- 'journal', 'weekly_review', 'manual', module name
    config_key   TEXT NOT NULL,               -- e.g. 'wheel.min_iv_rank'
    current_value TEXT,
    proposed_value TEXT NOT NULL,
    rationale    TEXT NOT NULL,
    status       TEXT DEFAULT 'pending' CHECK (status IN ('pending','approved','rejected','applied')),
    reviewed_at  TIMESTAMPTZ,
    review_note  TEXT
);

CREATE INDEX IF NOT EXISTS idx_proposals_status ON proposed_config_changes(status);
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


def log_ipo_scan(ipos: list, watchlist: list, optionable: list, settings=None) -> dict:
    """Persist an IPO scan: one research_brief summary + a trading_signal per
    actionable (new, tradable) name. Dedups against existing active 'ipo' signals."""
    cfg = settings or cfg_module.load()
    Json = psycopg2.extras.Json
    summary = (
        f"IPO scan: {len(ipos)} recent 424B4 filings; {len(watchlist)} new/tradable, "
        f"{len(optionable)} optionable. Watchlist: {', '.join(watchlist[:25]) or '(none)'}"
    )
    by_ticker = {i["ticker"]: i for i in ipos}
    inserted = 0
    with get_connection(cfg) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO research_briefs
                       (content, source, signal_count, top_conviction, tickers_mentioned)
                   VALUES (%s, 'edgar_ipo', %s, %s, %s) RETURNING id""",
                (summary, len(watchlist), 5 if optionable else 4, Json(watchlist)),
            )
            brief_id = cur.fetchone()[0]
            for t in watchlist:
                cur.execute(
                    "SELECT 1 FROM trading_signals "
                    "WHERE ticker=%s AND source_type='ipo' AND status='active' LIMIT 1",
                    (t,),
                )
                if cur.fetchone():
                    continue
                info = by_ticker.get(t, {})
                has_opt = bool(info.get("has_options"))
                cur.execute(
                    """INSERT INTO trading_signals
                           (ticker, direction, thesis, source_type, conviction,
                            wheel_eligible, suggested_strategy, source_brief_id, catalysts)
                       VALUES (%s, 'neutral', %s, 'ipo', %s, %s, %s, %s, %s)""",
                    (
                        t,
                        f"Recent IPO — {info.get('company', '?')} priced {info.get('file_date', '?')}; "
                        f"{'options listed' if has_opt else 'no options yet'}.",
                        5 if has_opt else 4,
                        has_opt,
                        "wheel" if has_opt else None,
                        brief_id,
                        Json(["ipo_pricing"]),
                    ),
                )
                inserted += 1
        conn.commit()
    print(f"[IPO] persisted research_brief + {inserted} new trading_signal(s)")
    return {"brief_id": str(brief_id), "signals_inserted": inserted}


def log_derivatives_signals(rows: list, settings=None) -> int:
    """Persist 'rich premium' (high IV-rank) names as derivatives trading_signals.
    Dedups against existing active derivatives signals per ticker."""
    cfg = settings or cfg_module.load()
    Json = psycopg2.extras.Json
    inserted = 0
    with get_connection(cfg) as conn:
        with conn.cursor() as cur:
            for r in rows:
                t = r["ticker"]
                cur.execute(
                    "SELECT 1 FROM trading_signals "
                    "WHERE ticker=%s AND source_type='derivatives' AND status='active' LIMIT 1",
                    (t,),
                )
                if cur.fetchone():
                    continue
                ivr = r.get("iv_rank") or 0.5
                conviction = min(10, max(1, int(round(ivr * 10))))  # IVR 0.8 -> conviction 8
                cur.execute(
                    """INSERT INTO trading_signals
                           (ticker, direction, thesis, source_type, conviction,
                            wheel_eligible, suggested_strategy, premium_environment, catalysts)
                       VALUES (%s, 'neutral', %s, 'derivatives', %s, true, 'wheel', 'rich', %s)""",
                    (
                        t,
                        f"Rich options premium — IV rank {ivr * 100:.0f}%; favorable for selling CSP/CC.",
                        conviction,
                        Json(["high_iv_rank"]),
                    ),
                )
                inserted += 1
        conn.commit()
    print(f"[DERIV] persisted {inserted} derivatives signal(s)")
    return inserted


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

    def log_ipo_scan(self, ipos: list, watchlist: list, optionable: list) -> dict:
        return log_ipo_scan(ipos, watchlist, optionable, settings=self._settings)

    def log_derivatives_signals(self, rows: list) -> int:
        return log_derivatives_signals(rows, settings=self._settings)


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
