"""response_text(): reading Claude's reply without assuming content[0] is text.

The six synthesis calls did `message.content[0].text`. These pin the cases that broke or
hid behind a bare IndexError: no content, a refusal, a non-text block first, and JSON
cut off at max_tokens.
"""

import sys
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from execution.claude_text import ClaudeNoText, response_text


def _msg(*blocks, stop="end_turn", details=None):
    return NS(content=list(blocks), stop_reason=stop, stop_details=details)


def _text(t):
    return NS(type="text", text=t)


def test_joins_text_blocks_and_strips():
    assert response_text(_msg(_text("  Hello "), _text("world  "))) == "Hello world"


def test_skips_non_text_blocks_ahead_of_the_text():
    thinking = NS(type="thinking", thinking="", signature="x")   # has no .text
    assert response_text(_msg(thinking, _text("answer"))) == "answer"


def test_empty_content_names_the_stop_reason():
    with pytest.raises(ClaudeNoText, match="stop_reason=end_turn"):
        response_text(_msg())


def test_refusal_is_reported_as_a_refusal():
    with pytest.raises(ClaudeNoText, match="refused.*cyber"):
        response_text(_msg(_text("partial"), stop="refusal",
                           details=NS(category="cyber", explanation="")))


def test_truncated_prose_is_returned_with_a_warning(capsys):
    out = response_text(_msg(_text("most of a report"), stop="max_tokens"), tag="WEEKLY")
    assert out == "most of a report"
    assert "[WEEKLY] response hit max_tokens" in capsys.readouterr().out


def test_truncated_json_is_refused_when_not_allowed():
    with pytest.raises(ClaudeNoText, match="truncated"):
        response_text(_msg(_text('{"ticker": "CCJ", "recomm'), stop="max_tokens"),
                      allow_truncated=False)
