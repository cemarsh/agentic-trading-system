"""generate_digest must accept lesson rows straight from Postgres.

db_logger.get_lessons uses RealDictCursor, so `ts` (TIMESTAMPTZ) arrives as a
datetime, not a string. The digest sliced it like a string, which crashed every
weekly and monthly digest with "'datetime.datetime' object is not subscriptable".
"""

import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from execution import strategy_advisor as sa


def _lesson(ts, ticker="GEO"):
    return {
        "ts": ts, "ticker": ticker, "strategy_used": "wheel", "regime": "NEUTRAL",
        "entry_price": 1.0, "exit_price": 0.75, "pnl": -132.0, "outcome": "loss",
        "lesson": "sized too large for the regime",
    }


def test_digest_accepts_datetime_and_string_timestamps():
    cfg = MagicMock()
    cfg.anthropic.api_key = "test-key"
    client = MagicMock()
    client.messages.create.return_value.content = [MagicMock(text="  the digest  ")]
    lessons = [
        _lesson(datetime(2026, 9, 1, 14, 30, tzinfo=timezone.utc)),  # what Postgres returns
        _lesson("2026-09-02T15:00:00+00:00", ticker="CCJ"),          # a pre-formatted string
    ]

    with patch.object(sa.anthropic, "Anthropic", return_value=client):
        out = sa.generate_digest("weekly", lessons, settings=cfg)

    assert out == "the digest"
    prompt = client.messages.create.call_args.kwargs["messages"][0]["content"]
    assert "- 2026-09-01 | GEO |" in prompt
    assert "- 2026-09-02 | CCJ |" in prompt
