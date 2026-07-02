"""Tests for savant.py CSV parsing (via fixtures) and the xstats engine helpers."""
import pytest

import engine as e
import savant


# ------------------------------------------------------------
# engine xstats helpers
# ------------------------------------------------------------
def test_luck_read_unlucky():
    tag, delta = e.xba_luck_read(0.240, 0.285)
    assert tag == "unlucky" and delta == pytest.approx(0.045)

def test_luck_read_hot_lucky():
    tag, delta = e.xba_luck_read(0.320, 0.270)
    assert tag == "hot-lucky" and delta == pytest.approx(-0.05)

def test_luck_read_fair_and_missing():
    assert e.xba_luck_read(0.260, 0.265)[0] == "fair"
    assert e.xba_luck_read(None, 0.3) is None
    assert e.xba_luck_read("x", 0.3) is None

def test_xstats_modifier_direction_and_clamp():
    assert e.xstats_hit_modifier(0.240, 0.290) > 1.0     # unlucky -> boost
    assert e.xstats_hit_modifier(0.320, 0.260) < 1.0     # lucky -> shave
    assert e.xstats_hit_modifier(0.100, 0.400) == e.XSTAT_MOD_CEIL
    assert e.xstats_hit_modifier(None, None) == 1.0

def test_barrel_boost():
    assert e.barrel_hrr_boost(12.0) > 1.0     # elite power
    assert e.barrel_hrr_boost(2.0) < 1.0      # no pop
    assert e.barrel_hrr_boost(None) == 1.0


# ------------------------------------------------------------
# savant CSV parsing (network mocked with fixture CSVs)
# ------------------------------------------------------------
XSTATS_CSV = '''"last_name, first_name",player_id,year,pa,bip,ba,est_ba,est_ba_minus_ba_diff,slg,est_slg,woba,est_woba
"De La Cruz, Elly",682829,2026,300,210,.264,.291,.027,.480,.512,.350,.372
"Steer, Spencer",668715,2026,280,200,.291,.262,-.029,.440,.410,.340,.318
'''

POWER_CSV = '''"last_name, first_name",player_id,attempts,avg_hit_angle,avg_hit_speed,barrels,brl_percent
"De La Cruz, Elly",682829,210,12.5,92.8,25,11.9
"Steer, Spencer",668715,200,14.1,88.2,9,4.5
'''

class FakeRes:
    def __init__(self, text): self.status_code, self.text = 200, text

def test_fetch_batter_xstats_parses_fixture(monkeypatch):
    monkeypatch.setattr(savant.data, "http_get", lambda url, **k: FakeRes(XSTATS_CSV))
    out = savant.fetch_batter_xstats(2026)
    assert 682829 in out and 668715 in out
    elly = out[682829]
    assert elly["ba"] == pytest.approx(0.264)
    assert elly["xba"] == pytest.approx(0.291)
    assert elly["xwoba"] == pytest.approx(0.372)

def test_fetch_batter_power_parses_fixture(monkeypatch):
    monkeypatch.setattr(savant.data, "http_get", lambda url, **k: FakeRes(POWER_CSV))
    out = savant.fetch_batter_power(2026)
    assert out[682829]["brl_percent"] == pytest.approx(11.9)
    assert out[668715]["avg_hit_speed"] == pytest.approx(88.2)

def test_fetch_batter_quality_merges(monkeypatch):
    calls = {"n": 0}
    def fake_get(url, **k):
        calls["n"] += 1
        return FakeRes(XSTATS_CSV if "expected_statistics" in url else POWER_CSV)
    monkeypatch.setattr(savant.data, "http_get", fake_get)
    out = savant.fetch_batter_quality(2026)
    elly = out[682829]
    assert elly["xba"] == pytest.approx(0.291)       # from xstats
    assert elly["brl_percent"] == pytest.approx(11.9)  # merged from power

def test_fetch_degrades_to_empty_on_failure(monkeypatch):
    def boom(url, **k):
        raise RuntimeError("blocked")
    monkeypatch.setattr(savant.data, "http_get", boom)
    assert savant.fetch_batter_xstats(2026) == {}
    assert savant.fetch_batter_quality(2026) == {}


# ------------------------------------------------------------
# pipeline integration: savant nudges HRR + surfaces luck on the row
# ------------------------------------------------------------
def test_pipeline_uses_savant(monkeypatch):
    import pipeline
    from tests.test_pipeline import StubFetch
    sv = {1: {"ba": 0.240, "xba": 0.295, "brl_percent": 12.0}}   # very unlucky + power
    with_sv = pipeline.score_hitters(StubFetch(), [("A", 1)], 2026, "vr", "RHP",
                                     [], "", 0, 4.0, 4.0, {}, 555,
                                     savant_batters=sv)[0]
    without = pipeline.score_hitters(StubFetch(), [("A", 1)], 2026, "vr", "RHP",
                                     [], "", 0, 4.0, 4.0, {}, 555)[0]
    assert with_sv["xBA"] == pytest.approx(0.295)
    assert with_sv["Luck"] == "unlucky"
    assert with_sv["HRR_Proj"] > without["HRR_Proj"]   # deserved-performance boost
    assert without["xBA"] is None                       # absent -> old behavior
