"""Tests for the pregame safety-net sweep (gate + orchestration)."""
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

import briefing
import data


def _et(hour, minute=0):
    return datetime(2026, 7, 4, hour, minute, tzinfo=ZoneInfo("America/New_York"))

def _ctx(start_utc="2026-07-04T23:10:00Z", is_pregame=True):
    # 23:10 UTC = 7:10pm ET on 2026-07-04 (EDT)
    return {"is_pregame": is_pregame, "start_utc": start_utc,
            "opponent": "Cubs", "opp_pitcher_id": 1, "game_pk": 999}


# ------------------------------------------------------------
# should_pregame_sweep — pure gate
# ------------------------------------------------------------
def test_gate_true_inside_window():
    assert briefing.should_pregame_sweep(_et(17), False, _ctx()) is True   # 2h10m out
    assert briefing.should_pregame_sweep(_et(18, 30), False, _ctx()) is True

def test_gate_false_too_early():
    assert briefing.should_pregame_sweep(_et(12), False, _ctx()) is False  # 7h out

def test_gate_false_after_first_pitch():
    assert briefing.should_pregame_sweep(_et(19, 30), False, _ctx()) is False

def test_gate_false_marker_exists():
    assert briefing.should_pregame_sweep(_et(17), True, _ctx()) is False

def test_gate_false_game_started_or_offday():
    assert briefing.should_pregame_sweep(_et(17), False, _ctx(is_pregame=False)) is False
    assert briefing.should_pregame_sweep(_et(17), False, None) is False

def test_gate_fails_closed_on_bad_start_time():
    assert briefing.should_pregame_sweep(_et(17), False, _ctx(start_utc="garbage")) is False
    assert briefing.should_pregame_sweep(_et(17), False, _ctx(start_utc="")) is False


# ------------------------------------------------------------
# pregame_sweep — orchestration with mocked network
# ------------------------------------------------------------
class FakeRes:
    def __init__(self, code, body=None):
        self.status_code, self._b, self.text = code, (body if body is not None else []), ""
    def json(self):
        return self._b


def _wire(monkeypatch, morning_exists=True, sweep_exists=False,
          null_odds_rows=None, odds=None, claim_ok=True):
    """Wire briefing/data for a sweep run at 5pm ET on a 7:10pm game day."""
    calls = {"patches": [], "ntfy": [], "autorun": 0}

    monkeypatch.setattr(data, "now_eastern", lambda: _et(17))
    monkeypatch.setattr(briefing.pipeline, "game_context", lambda f, d: _ctx())

    def marker_exists(url, hdrs, d, game_pk=0):
        return morning_exists if game_pk == 0 else (
            sweep_exists if game_pk == briefing.SWEEP_MARKER_GAME_PK else False)
    monkeypatch.setattr(briefing, "_marker_exists", marker_exists)
    monkeypatch.setattr(briefing, "_claim_marker",
                        lambda *a, **k: calls.__setitem__("claimed", True) or claim_ok)
    monkeypatch.setattr(briefing, "daily_autorun",
                        lambda *a, **k: calls.__setitem__("autorun", calls["autorun"] + 1))

    monkeypatch.setattr(data, "http_get",
                        lambda url, **k: FakeRes(200, null_odds_rows or []))
    def fake_patch(url, **k):
        calls["patches"].append((url, k.get("json")))
        return FakeRes(204)
    monkeypatch.setattr(data, "http_patch", fake_patch)
    monkeypatch.setattr(data, "fetch_reds_batter_odds", lambda key: (odds or {}, []))
    monkeypatch.setattr(data, "ntfy_send",
                        lambda t, title, msg, **k: calls["ntfy"].append(msg) or True)
    return calls


def test_sweep_runs_autorun_when_morning_missing(monkeypatch):
    calls = _wire(monkeypatch, morning_exists=False)
    briefing.pregame_sweep("u", {}, {}, "key", "topic")
    assert calls["autorun"] == 1
    assert not calls["patches"]

def test_sweep_backfills_null_odds_and_pushes(monkeypatch):
    rows = [{"player_id": 1, "player_name": "Elly De La Cruz"},
            {"player_id": 2, "player_name": "No Line Guy"}]
    odds = {"elly de la cruz": {"line": 0.5, "price": -145}}
    calls = _wire(monkeypatch, null_odds_rows=rows, odds=odds)
    patched = briefing.pregame_sweep("u", {}, {}, "key", "topic")
    assert patched == 1
    url, body = calls["patches"][0]
    assert "player_id=eq.1" in url
    assert body == {"odds_line": 0.5, "odds_price": -145}
    assert calls["ntfy"] and "Lines locked: 1" in calls["ntfy"][0]

def test_sweep_quiet_when_all_priced(monkeypatch):
    calls = _wire(monkeypatch, null_odds_rows=[])
    assert briefing.pregame_sweep("u", {}, {}, "key", "topic") == 0
    assert not calls["patches"] and not calls["ntfy"]

def test_sweep_quiet_when_no_odds_posted(monkeypatch):
    rows = [{"player_id": 1, "player_name": "Elly De La Cruz"}]
    calls = _wire(monkeypatch, null_odds_rows=rows, odds={})
    assert briefing.pregame_sweep("u", {}, {}, "key", "topic") == 0
    assert not calls["ntfy"]

def test_sweep_noop_when_claim_lost(monkeypatch):
    rows = [{"player_id": 1, "player_name": "Elly De La Cruz"}]
    calls = _wire(monkeypatch, null_odds_rows=rows,
                  odds={"elly de la cruz": {"line": 0.5, "price": -145}},
                  claim_ok=False)
    assert briefing.pregame_sweep("u", {}, {}, "key", "topic") is None
    assert not calls["patches"]

def test_sweep_noop_when_already_swept(monkeypatch):
    calls = _wire(monkeypatch, sweep_exists=True)
    assert briefing.pregame_sweep("u", {}, {}, "key", "topic") is None
    assert calls["autorun"] == 0 and not calls["patches"]


# ------------------------------------------------------------
# clear_markers — the manual force path
# ------------------------------------------------------------
class _Resp:
    def __init__(self, status_code):
        self.status_code = status_code

def test_clear_markers_deletes_player_zero_rows(monkeypatch):
    seen = {}
    def fake_delete(url, headers=None):
        seen["url"] = url
        return _Resp(204)
    monkeypatch.setattr(data, "http_delete", fake_delete)
    assert briefing.clear_markers("https://x.co", {}, "2026-07-29") is True
    assert "player_id=eq.0" in seen["url"]
    assert "date=eq.2026-07-29" in seen["url"]

def test_clear_markers_false_on_error(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("down")
    monkeypatch.setattr(data, "http_delete", boom)
    assert briefing.clear_markers("u", {}, "2026-07-29") is False
