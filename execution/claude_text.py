"""
Text out of a Claude Messages API response — the one place that reads `message.content`.

Every synthesis call used to do `message.content[0].text`, which assumes the first block
is text and that there is one. That is not guaranteed: a refusal or an empty turn has
no text block (→ a bare `IndexError: list index out of range` in the logs, which says
nothing about why), and any non-text block ahead of the text (thinking, if it is ever
turned on) raises AttributeError. A reply cut off at max_tokens was also returned as if
it were complete — for the advisor's JSON that meant a parse failure blamed on the model.

`response_text()` joins the text blocks, and turns refusal / no text / (optionally)
truncation into a ClaudeNoText with the stop_reason in the message. Callers already
catch exceptions and fall back to their template, so the behavior is the same — the
log line now says what actually happened.
"""

from typing import Any


class ClaudeNoText(RuntimeError):
    """The response carried no usable text."""


def response_text(message: Any, *, allow_truncated: bool = True, tag: str = "CLAUDE") -> str:
    """Concatenated, stripped text of a Messages API response.

    allow_truncated=False for output that is useless when cut off (JSON); prose that
    hit max_tokens is still returned, with a warning, since most of a report beats none.
    """
    stop = getattr(message, "stop_reason", None)
    if stop == "refusal":
        details = getattr(message, "stop_details", None)
        category = getattr(details, "category", None) if details else None
        raise ClaudeNoText(f"request refused (category={category})")

    text = "".join(
        getattr(block, "text", "") or ""
        for block in (getattr(message, "content", None) or [])
        if getattr(block, "type", None) == "text"
    ).strip()
    if not text:
        raise ClaudeNoText(f"response has no text (stop_reason={stop})")

    if stop == "max_tokens":
        if not allow_truncated:
            raise ClaudeNoText("response truncated at max_tokens — raise max_tokens for this call")
        print(f"[{tag}] response hit max_tokens — output is truncated")
    return text
