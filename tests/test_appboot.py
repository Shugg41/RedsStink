"""Boot tests: the app must render BOTH the off-day and game-day paths without
exceptions. The game-day path is the one that caught the data-module shadowing
bug — keep these green."""
import pytest

streamlit = pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest

import data
from tests.test_pipeline import StubFetch


def _boot():
    at = AppTest.from_file("app.py", default_timeout=60)
    at.run()
    return at


def test_offday_boot(monkeypatch):
    monkeypatch.setattr(data, "get_schedule", lambda d: {"totalGames": 0})
    at = _boot()
    assert not at.exception, [repr(e.value) for e in at.exception]


def test_gameday_boot(monkeypatch):
    stub = StubFetch()
    monkeypatch.setattr(data, "get_schedule", stub.get_schedule)
    monkeypatch.setattr(data, "get_game_starters", stub.get_game_starters)
    monkeypatch.setattr(data, "get_pitcher_hand", stub.get_pitcher_hand)
    monkeypatch.setattr(data, "get_advanced_pitching", stub.get_advanced_pitching)
    monkeypatch.setattr(data, "get_league_hitting", stub.get_league_hitting)
    monkeypatch.setattr(data, "get_team_pitching", lambda tid, yr: {"era": "4.30"})
    monkeypatch.setattr(data, "get_live_feed",
                        lambda pk: {"liveData": {"boxscore": {"teams":
                                    {"home": {"battingOrder": []}, "away": {}}}}})
    monkeypatch.setattr(data, "get_roster", lambda tid: [
        {"person": {"fullName": "Test Hitter A", "id": 1}, "position": {"abbreviation": "CF"}},
        {"person": {"fullName": "Reds Arm", "id": 777}, "position": {"abbreviation": "P"}},
    ])
    at = _boot()
    assert not at.exception, [repr(e.value) for e in at.exception]
    # the matchup header proves the game-day branch actually executed
    assert any("Reds vs" in s.value for s in at.subheader)
