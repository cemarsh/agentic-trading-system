"""Policy classifier keyword matching — whole-word, not substring."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from execution.policy_monitor import PolicyMonitor, SECTOR_MAP


def _classify(text):
    return PolicyMonitor.__new__(PolicyMonitor)._classify(text)[0]


# ---------------------------------------------------------------------------
# The regressions: two keywords short enough to hide inside ordinary English
# ---------------------------------------------------------------------------

def test_ai_does_not_match_inside_aircraft():
    """'ai' matched 'AIrcraft' — five weekly journals logged this as a mystery."""
    assert "ai_infrastructure" not in _classify(
        "Proclamation on Adjusting Imports of Aircraft Parts")


def test_ai_does_not_match_inside_dairy():
    assert "ai_infrastructure" not in _classify(
        "Canada suspends tariffs on dairy and beverage products")


def test_ai_does_not_match_common_words():
    for text in ("remain vigilant", "the supply chain", "certain imports",
                 "maintain readiness"):
        assert "ai_infrastructure" not in _classify(text), text


def test_ice_does_not_match_inside_price_service_office():
    """'ice' matched prICE, servICE, OffICE, notICE."""
    assert "border_security" not in _classify(
        "Notice on the price of services at the Office of Management")


# ---------------------------------------------------------------------------
# True positives must survive the fix
# ---------------------------------------------------------------------------

def test_ai_still_matches_as_a_word():
    assert "ai_infrastructure" in _classify(
        "Executive Order on Government AI and data center buildout")


def test_ice_still_matches_as_a_word():
    assert "border_security" in _classify("ICE detention facility expansion")


def test_multiword_keywords_still_match():
    assert "nuclear" in _classify("Advancing small modular reactor deployment")
    assert "semiconductors" in _classify("Implementation of the CHIPS Act")


def test_plurals_still_match():
    """Plain \\b would drop 'tariffs' for keyword 'tariff' and lose real signal."""
    assert "domestic_manufacturing" in _classify("New tariffs on steel imports")
    assert "critical_minerals" in _classify("Order on critical minerals and rare earths")
    assert "defense" in _classify("Procurement of drones and missiles")


def test_case_insensitive():
    assert "nuclear" in _classify("URANIUM enrichment expansion")


def test_multiple_sectors_can_match():
    sectors = _classify("Executive Order on nuclear reactors and critical minerals")
    assert "nuclear" in sectors and "critical_minerals" in sectors


def test_unrelated_headline_matches_nothing():
    assert _classify("Presidential remarks at the annual picnic") == []


def test_every_sector_matches_its_own_first_keyword():
    """Guards against a keyword whose \\b + s? form can never fire."""
    for sector, cfg in SECTOR_MAP.items():
        kw = cfg["keywords"][0]
        assert sector in _classify(f"Policy regarding {kw} today"), (sector, kw)
