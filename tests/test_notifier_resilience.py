"""Email delivery must never take the loop down, and its failure must reach Slack.

Regression cover for 2026-10-04..20: the Resend key was revoked in an incident
response. Every send raised, the raise counted as an API failure, the loop halted
and respawned ~300 times a day for 16 days, and the Slack fallback in
critical_alert sat *after* the raise so it never fired.
"""

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from execution import notifier as nt


def _settings():
    return SimpleNamespace(notifications=SimpleNamespace(
        resend_key="re_test", alert_email="owner@example.com",
        slack_webhook_url="https://hooks.example/x"))


@pytest.fixture
def n(tmp_path):
    with patch.object(nt, "DEGRADED_PATH", tmp_path / "notifier_degraded.json"), \
         patch.object(nt.resend.Emails, "send") as send, \
         patch.object(nt, "slack_post", return_value=True) as slack:
        yield nt.Notifier(_settings()), send, slack


def test_rejected_send_returns_false_and_does_not_raise(n):
    notifier, send, _ = n
    send.side_effect = Exception("API key is invalid")
    assert notifier.send("subj", "body") is False
    marker = nt.read_degraded()
    assert marker["failures"] == 1 and "API key is invalid" in marker["last_error"]


def test_first_failure_posts_to_slack_once_a_day(n):
    notifier, send, slack = n
    send.side_effect = Exception("API key is invalid")
    notifier.send("a", "b")
    notifier.send("a", "b")
    notifier.send("a", "b")
    assert slack.call_count == 1
    assert nt.read_degraded()["failures"] == 3
    # a day later the reminder fires again
    with patch.object(nt.time, "time", return_value=nt.time.time() + nt.SLACK_REMIND_SECONDS + 1):
        notifier.send("a", "b")
    assert slack.call_count == 2


def test_success_clears_the_marker_and_announces_recovery(n):
    notifier, send, slack = n
    send.side_effect = Exception("API key is invalid")
    notifier.send("a", "b")
    send.side_effect = None
    assert notifier.send("a", "b") is True
    assert nt.read_degraded() is None
    assert "restored" in slack.call_args.args[1]


def test_healthy_send_touches_nothing(n):
    notifier, _, slack = n
    assert notifier.send("a", "b") is True
    assert nt.read_degraded() is None
    slack.assert_not_called()


def test_verify_only_still_sees_the_exception(n):
    notifier, send, _ = n
    send.side_effect = Exception("API key is invalid")
    with pytest.raises(Exception, match="invalid"):
        notifier.send("a", "b", raise_on_error=True)


def test_critical_alert_reaches_slack_when_email_is_dead(n, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # critical_alerts.log lands here, not in the repo
    notifier, send, slack = n
    send.side_effect = Exception("API key is invalid")
    assert notifier.critical_alert("loop halted") is True
    assert slack.call_args_list[0].args[1].startswith(":rotating_light:")


def test_every_email_ends_with_the_dashboard_link(n):
    notifier, send, _ = n
    notifier.send("subj", "body text")
    assert send.call_args.args[0]["text"].endswith(
        "\n\nDashboard: https://trading.cloudmagic.software")
    notifier.send("subj", "<html><body><p>hi</p></body></html>", is_html=True)
    html = send.call_args.args[0]["html"]
    assert 'href="https://trading.cloudmagic.software"' in html and html.endswith("</body></html>")


def test_dashboard_link_is_added_once_and_env_overrides(monkeypatch):
    monkeypatch.setenv("DASHBOARD_URL", "https://dash.example")
    s = _settings()
    s.notifications.dashboard_url = "https://ignored.example"
    with patch.object(nt.resend.Emails, "send") as send:
        notifier = nt.Notifier(s)
        notifier.send("a", "already links https://dash.example here")
        assert send.call_args.args[0]["text"].count("https://dash.example") == 1
        notifier.send("a", "plain")
        assert send.call_args.args[0]["text"].endswith("Dashboard: https://dash.example")


def test_slack_posts_carry_the_link(monkeypatch):
    monkeypatch.setenv("DASHBOARD_URL", "https://dash.example")
    seen = {}

    def capture(req, timeout=0):
        seen["text"] = json.loads(req.data)["text"]

    with patch.object(nt.urllib.request, "urlopen", capture):
        assert nt.slack_post("https://hooks.example/x", ":rotating_light: halted") is True
    assert seen["text"].startswith(":rotating_light: halted")
    assert seen["text"].endswith("Dashboard: https://dash.example")


def test_critical_alert_false_when_no_channel_works(n, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    notifier, send, slack = n
    send.side_effect = Exception("API key is invalid")
    slack.return_value = False
    assert notifier.critical_alert("loop halted") is False
