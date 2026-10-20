"""Credential probes classify a key from the provider's real response shapes
(captured 2026-10-20) and only alarm on a change."""

import io
import sys
import urllib.error
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from execution import credential_health as ch


def _http(status: int, body: str):
    if status == 200:
        resp = io.BytesIO(body.encode())
        resp.status = 200  # type: ignore[attr-defined]
        resp.__enter__ = lambda s: s  # type: ignore[attr-defined]
        resp.__exit__ = lambda s, *a: None  # type: ignore[attr-defined]
        return lambda *a, **k: resp
    err = urllib.error.HTTPError("u", status, "msg", {}, io.BytesIO(body.encode()))
    def raiser(*a, **k):
        raise err
    return raiser


@pytest.mark.parametrize("status,body,expected", [
    (200, '{"data":[]}', ch.OK),
    (401, '{"statusCode":401,"message":"This API key is restricted to only send emails","name":"restricted_api_key"}', ch.OK),
    (400, '{"statusCode":400,"message":"API key is invalid","name":"validation_error"}', ch.INVALID),
    (401, '{"statusCode":401,"message":"Missing API Key","name":"missing_api_key"}', ch.INVALID),
    (503, 'upstream', ch.UNKNOWN),
    # Cloudflare WAF ban (error 1010) on urllib's default User-Agent, seen 2026-10-20:
    # an HTML 403 with no Resend verdict must not read as a dead key.
    (403, '<html><body>error code: 1010</body></html>', ch.UNKNOWN),
])
def test_resend_shapes(status, body, expected):
    with patch.object(ch.urllib.request, "urlopen", _http(status, body)):
        assert ch.probe_resend("re_x")[0] == expected


def test_probe_sends_a_real_user_agent():
    seen = {}
    def capture(req, timeout):
        seen["ua"] = req.get_header("User-agent")
        raise OSError("stop")
    with patch.object(ch.urllib.request, "urlopen", capture):
        ch.probe_resend("re_x")
    assert seen["ua"] == ch._UA


@pytest.mark.parametrize("status,body,expected", [
    (200, '{"data":[]}', ch.OK),
    (401, '{"type":"error","error":{"type":"authentication_error","message":"invalid x-api-key"}}', ch.INVALID),
    (403, '<html>blocked</html>', ch.UNKNOWN),
    (529, 'overloaded', ch.UNKNOWN),
])
def test_anthropic_shapes(status, body, expected):
    with patch.object(ch.urllib.request, "urlopen", _http(status, body)):
        assert ch.probe_anthropic("sk-ant-x")[0] == expected


def test_invalid_detail_carries_the_provider_message():
    body = '{"type":"error","error":{"type":"authentication_error","message":"invalid x-api-key"}}'
    with patch.object(ch.urllib.request, "urlopen", _http(401, body)):
        assert ch.probe_anthropic("sk-ant-x") == (ch.INVALID, "invalid x-api-key")


def test_network_failure_is_unknown_not_invalid():
    def boom(*a, **k):
        raise OSError("Name or service not known")
    with patch.object(ch.urllib.request, "urlopen", boom):
        assert ch.probe_resend("re_x")[0] == ch.UNKNOWN


def test_unset_keys_are_skipped():
    assert ch.probe_resend("")[0] == ch.UNSET
    assert ch.probe_anthropic(None)[0] == ch.UNSET


def test_probe_all_reads_the_settings_shape():
    cfg = SimpleNamespace(notifications=SimpleNamespace(resend_key=""),
                          anthropic=SimpleNamespace(api_key=""))
    health = ch.probe_all(cfg)
    assert set(health) == {"resend", "anthropic"}
    assert all(h["status"] == ch.UNSET for h in health.values())


def test_transitions_report_changes_and_first_run_invalids():
    cur = {"resend": {"status": ch.INVALID}, "anthropic": {"status": ch.OK}}
    assert ch.transitions(None, cur) == [("resend", None, ch.INVALID)]
    prev = {"resend": {"status": ch.OK}, "anthropic": {"status": ch.OK}}
    assert ch.transitions(prev, cur) == [("resend", ch.OK, ch.INVALID)]
    assert ch.transitions(cur, cur) == []
