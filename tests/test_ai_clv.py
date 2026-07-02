"""Tests for the Ask-the-app assistant and the closing-snapshot (CLV) gate."""
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

import ai
import briefing


# ------------------------------------------------------------
# ai.build_context (pure)
# ------------------------------------------------------------
def test_build_context_includes_board_and_ks():
    picks = [{"player_name": "Elly", "score": 88, "tier": "🟢 Tier 1", "odds_price": -150}]
    kproj = [{"player_name": "Greene", "projected_ks": 6.8}]
    sb = {"additive": {"wins": 34, "losses": 19, "win_rate": 0.642},
          "mult": {"wins": 5, "losses": 8, "win_rate": 0.385}}
    ctx = ai.build_context(picks, kproj, sb, "2026-07-04")
    assert "Elly: score 88" in ctx and "DK hits price -150" in ctx
    assert "Greene: 6.8 Ks" in ctx
    assert "34-19" in ctx and "64%" in ctx

def test_build_context_empty_is_safe():
    assert "2026-07-04" in ai.build_context(None, None, None, "2026-07-04")


# ------------------------------------------------------------
# ai.ask (network mocked)
# ------------------------------------------------------------
class FakeRes:
    def __init__(self, code, body): self.status_code, self._b, self.text = code, body, str(body)
    def json(self): return self._b

def test_ask_success(monkeypatch):
    monkeypatch.setattr(ai.data, "http_post", lambda url, **k: FakeRes(200, {
        "content": [{"type": "text", "text": "Lean Elly 2+ HRR tonight."}]}))
    ans, err = ai.ask("key", "Elly?", "ctx")
    assert ans == "Lean Elly 2+ HRR tonight." and err is None

def test_ask_api_error(monkeypatch):
    monkeypatch.setattr(ai.data, "http_post", lambda url, **k: FakeRes(429, {}))
    ans, err = ai.ask("key", "q", "ctx")
    assert ans is None and "429" in err

def test_ask_no_key():
    assert ai.ask(None, "q", "ctx") == (None, "no key")


# ------------------------------------------------------------
# closing-snapshot gate (pure)
# ------------------------------------------------------------
def _et(hour):
    return datetime(2026, 7, 4, hour, 30, tzinfo=ZoneInfo("America/New_York"))

def test_close_gate_rules():
    ctx = {"is_pregame": True}
    assert briefing.should_close_snapshot(_et(18), False, True, ctx) is True
    assert briefing.should_close_snapshot(_et(12), False, True, ctx) is False   # too early
    assert briefing.should_close_snapshot(_et(18), True, True, ctx) is False    # already ran
    assert briefing.should_close_snapshot(_et(18), False, False, ctx) is False  # no morning picks
    assert briefing.should_close_snapshot(_et(18), False, True, None) is False  # off day
    assert briefing.should_close_snapshot(_et(18), False, True, {"is_pregame": False}) is False
