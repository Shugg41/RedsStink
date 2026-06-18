"""Unit tests for lock.py — the strikeout Lock-of-the-Day analytics."""
import math
import pytest

import lock as lk


# ------------------------------------------------------------
# Poisson model
# ------------------------------------------------------------
def test_poisson_pmf_sums_to_one():
    lam = 6.0
    total = sum(lk._poisson_pmf(k, lam) for k in range(0, 40))
    assert total == pytest.approx(1.0, abs=1e-6)

def test_poisson_cdf_monotonic():
    lam = 5.5
    vals = [lk.poisson_cdf(k, lam) for k in range(0, 15)]
    assert vals == sorted(vals)
    assert vals[-1] == pytest.approx(1.0, abs=1e-3)

def test_prob_over_higher_projection_more_likely():
    # Same 5.5 line: a 7-K arm clears it more often than a 5-K arm.
    assert lk.prob_over(5.5, 7.0) > lk.prob_over(5.5, 5.0)

def test_prob_over_bounds():
    assert 0.0 <= lk.prob_over(5.5, 6.0) <= 1.0
    assert lk.prob_over(5.5, 0.0) == 0.0      # no expected Ks -> can't clear

def test_prob_over_at_projection_near_line_is_around_half():
    # Projection sitting right at the line -> roughly a coin flip (Poisson skews
    # slightly, so just assert it's in a sane middle band).
    p = lk.prob_over(5.5, 6.0)
    assert 0.45 <= p <= 0.75


# ------------------------------------------------------------
# EV
# ------------------------------------------------------------
def test_ev_positive_when_model_beats_price():
    # Model 60% to hit at +100 (decimal 2.0): EV = .6*1 - .4 = +0.2
    assert lk.ev_per_unit(0.60, 2.0) == pytest.approx(0.20)

def test_ev_negative_when_model_below_breakeven():
    assert lk.ev_per_unit(0.40, 2.0) == pytest.approx(-0.20)

def test_ev_none_without_odds():
    assert lk.ev_per_unit(0.6, None) is None
    assert lk.ev_per_unit(0.6, 1.0) is None


# ------------------------------------------------------------
# confidence
# ------------------------------------------------------------
def test_confidence_labels():
    assert lk.confidence_label(0.70) == "HIGH"
    assert lk.confidence_label(0.60) == "MEDIUM"
    assert lk.confidence_label(0.52) == "LOW"


# ------------------------------------------------------------
# score_candidate
# ------------------------------------------------------------
def _cand(**kw):
    base = {"projection": 6.5, "line": 5.5, "over_price": -110, "under_price": -110,
            "opener": False, "data_ok": True, "pitcher_name": "Test Arm"}
    base.update(kw)
    return base

def test_score_picks_over_when_projection_above_line():
    s = lk.score_candidate(_cand(projection=7.0, line=5.5))
    assert s["side"] == "Over"
    assert s["edge_k"] == pytest.approx(1.5)

def test_score_picks_under_when_projection_below_line():
    s = lk.score_candidate(_cand(projection=3.5, line=5.5))
    assert s["side"] == "Under"
    assert s["edge_k"] == pytest.approx(2.0)

def test_score_unscoreable_returns_none():
    assert lk.score_candidate({"line": 5.5}) is None
    assert lk.score_candidate({"projection": "x", "line": 5.5}) is None

def test_score_respects_sides_filter():
    # Projection well above line, but force Unders-only -> must return Under side.
    s = lk.score_candidate(_cand(projection=8.0, line=5.5), sides="under")
    assert s["side"] == "Under"

def test_score_ev_and_edge_prob_present_with_prices():
    s = lk.score_candidate(_cand(projection=7.5, line=5.5))
    assert s["ev"] is not None
    assert s["edge_prob"] is not None
    assert s["model_prob"] > s["implied_prob"]   # model likes the over more than the book


# ------------------------------------------------------------
# select_locks
# ------------------------------------------------------------
def test_select_ranks_by_ev_and_returns_shortlist():
    cands = [
        _cand(pitcher_name="A", projection=6.0, line=5.5),   # small edge
        _cand(pitcher_name="B", projection=9.0, line=5.5),   # big edge
        _cand(pitcher_name="C", projection=7.0, line=5.5),   # medium edge
    ]
    lock, shortlist = lk.select_locks(cands, guardrails=False, top_n=3)
    assert lock["pitcher_name"] == "B"
    assert [c["pitcher_name"] for c in shortlist] == ["B", "C", "A"]

def test_guardrails_skip_openers_and_thin_data():
    cands = [
        _cand(pitcher_name="Opener", projection=9.0, line=4.5, opener=True),
        _cand(pitcher_name="ThinData", projection=9.0, line=4.5, data_ok=False),
        _cand(pitcher_name="Good", projection=8.0, line=5.5),
    ]
    lock, _ = lk.select_locks(cands, guardrails=True)
    assert lock["pitcher_name"] == "Good"

def test_guardrails_skip_tiny_edges_and_coinflips():
    # Edge below the floor -> filtered out, leaving nothing.
    cands = [_cand(pitcher_name="TooClose", projection=5.6, line=5.5)]
    lock, shortlist = lk.select_locks(cands, guardrails=True)
    assert lock is None and shortlist == []

def test_guardrails_off_keeps_everything():
    cands = [_cand(pitcher_name="Opener", projection=9.0, line=4.5, opener=True)]
    lock, _ = lk.select_locks(cands, guardrails=False)
    assert lock is not None

def test_select_empty():
    assert lk.select_locks([]) == (None, [])
