"""Unit tests for backtest.py pure reducers."""
import math
import pytest

import backtest as bt


def _row(score=80, win=1, graded=1, price=None, mult=None):
    r = {"score": score, "win": win, "graded": graded}
    if price is not None:
        r["odds_price"] = price
    if mult is not None:
        r["mult_score"] = mult
    return r


# ------------------------------------------------------------
# graded_rows — filtering
# ------------------------------------------------------------
def test_graded_rows_drops_no_game_and_ungraded():
    rows = [
        _row(win=1, graded=1),    # keep
        _row(win=0, graded=1),    # keep
        _row(win=-1, graded=1),   # drop: no-game
        _row(win=1, graded=0),    # drop: ungraded
        {"win": "x", "graded": 1},  # drop: garbage
    ]
    assert len(bt.graded_rows(rows)) == 2


# ------------------------------------------------------------
# win_rate
# ------------------------------------------------------------
def test_win_rate():
    rows = [_row(win=1), _row(win=1), _row(win=0), _row(win=0)]
    rate, n = bt.win_rate(rows)
    assert rate == 0.5 and n == 4

def test_win_rate_empty():
    assert bt.win_rate([]) == (0.0, 0)


# ------------------------------------------------------------
# brier
# ------------------------------------------------------------
def test_brier_perfect_prediction_is_zero():
    rows = [_row(score=100, win=1), _row(score=0, win=0)]
    b, n = bt.brier(rows)
    assert b == pytest.approx(0.0) and n == 2

def test_brier_coinflip_is_quarter():
    rows = [_row(score=50, win=1), _row(score=50, win=0)]
    b, _ = bt.brier(rows)
    assert b == pytest.approx(0.25)

def test_brier_supports_mult_score_key():
    rows = [_row(score=10, win=1, mult=100)]
    b, n = bt.brier(rows, score_key="mult_score")
    assert b == pytest.approx(0.0) and n == 1


# ------------------------------------------------------------
# roi
# ------------------------------------------------------------
def test_roi_breakeven_even_money():
    # +100 win (+1u) and +100 loss (-1u) -> 0 units
    rows = [_row(win=1, price=100), _row(win=0, price=100)]
    units, roi_pct, n = bt.roi(rows)
    assert units == pytest.approx(0.0) and roi_pct == pytest.approx(0.0) and n == 2

def test_roi_all_winners_positive():
    rows = [_row(win=1, price=120), _row(win=1, price=120)]
    units, roi_pct, n = bt.roi(rows)
    assert units == pytest.approx(2.4) and roi_pct == pytest.approx(120.0) and n == 2

def test_roi_ignores_unpriced_rows():
    rows = [_row(win=1), _row(win=1, price=100)]   # first has no price
    _, _, n = bt.roi(rows)
    assert n == 1

def test_roi_no_priced_rows():
    assert bt.roi([_row(win=1), _row(win=0)]) == (0.0, 0.0, 0)


# ------------------------------------------------------------
# calibration
# ------------------------------------------------------------
def test_calibration_buckets_and_rates():
    rows = [
        _row(score=50, win=0), _row(score=50, win=0),   # <55 bucket: 0%
        _row(score=80, win=1), _row(score=80, win=1),   # 75-84 bucket: 100%
    ]
    buckets = {b["bucket"]: b for b in bt.calibration(rows)}
    assert buckets["0-54"]["win_rate"] == 0.0
    assert buckets["75-84"]["win_rate"] == 1.0
    assert buckets["75-84"]["n"] == 2


# ------------------------------------------------------------
# threshold_sweep / best_threshold
# ------------------------------------------------------------
def test_threshold_sweep_monotonic_counts():
    rows = [_row(score=s, win=1) for s in (40, 60, 80, 90)]
    sweep = {s["threshold"]: s for s in bt.threshold_sweep(rows)}
    # raising the cutoff can only keep or reduce the number of plays
    counts = [sweep[t]["n"] for t in sorted(sweep)]
    assert counts == sorted(counts, reverse=True)

def test_best_threshold_prefers_higher_roi():
    # Low scores lose, high scores win — best cutoff should sit up high.
    rows = ([_row(score=50, win=0, price=100) for _ in range(20)] +
            [_row(score=90, win=1, price=100) for _ in range(20)])
    best = bt.best_threshold(rows, min_priced=10)
    assert best is not None
    assert best["threshold"] > 50      # excludes the score=50 losers
    assert best["roi_pct"] > 0

def test_best_threshold_none_when_too_few_priced():
    rows = [_row(score=90, win=1, price=100)]
    assert bt.best_threshold(rows, min_priced=10) is None


# ------------------------------------------------------------
# last_game_recap — two-model comparison
# ------------------------------------------------------------
def _drow(date, tier="🟢 Tier 1", mult_tier=None, win=1, score=80, price=None):
    r = {"date": date, "tier": tier,
         "mult_tier": tier if mult_tier is None else mult_tier,
         "win": win, "graded": 1, "score": score, "player_name": f"P{score}"}
    if price is not None:
        r["odds_price"] = price
    return r

def test_recap_none_when_no_graded():
    assert bt.last_game_recap([]) is None
    assert bt.last_game_recap([_drow("2026-06-01", win=-1)]) is None

def test_recap_picks_most_recent_date():
    rows = [_drow("2026-06-01", win=1), _drow("2026-06-04", win=0)]
    recap = bt.last_game_recap(rows)
    assert recap["date"] == "2026-06-04"
    assert recap["additive"]["n"] == 1  # only the latest date is summarized

def test_recap_separates_the_two_models():
    # One player only the additive model likes, one only the mult model likes.
    rows = [
        _drow("2026-06-04", tier="🟢 Tier 1", mult_tier="🔴 Tier 3", win=1),  # additive only
        _drow("2026-06-04", tier="🔴 Tier 3", mult_tier="🟢 Tier 1", win=0),  # mult only
    ]
    recap = bt.last_game_recap(rows)
    assert (recap["additive"]["wins"], recap["additive"]["losses"]) == (1, 0)
    assert (recap["mult"]["wins"], recap["mult"]["losses"]) == (0, 1)
    assert len(recap["picks"]) == 2  # union of both models' Tier 1

def test_recap_units_per_model():
    rows = [
        _drow("2026-06-04", tier="🟢 Tier 1", mult_tier="🔴 Tier 3", win=1, price=100),
        _drow("2026-06-04", tier="🟢 Tier 1", mult_tier="🔴 Tier 3", win=0, price=100),
    ]
    recap = bt.last_game_recap(rows)
    assert recap["additive"]["units"] == pytest.approx(0.0)
    assert recap["additive"]["n_priced"] == 2
    assert recap["mult"]["n"] == 0   # mult liked nobody that day

def test_recap_ignores_tier3_only_players():
    rows = [_drow("2026-06-04", tier="🔴 Tier 3", mult_tier="🔴 Tier 3", win=1)]
    recap = bt.last_game_recap(rows)
    assert recap["additive"]["n"] == 0 and recap["mult"]["n"] == 0
    assert recap["picks"] == []


# ------------------------------------------------------------
# season_scoreboard
# ------------------------------------------------------------
def test_scoreboard_none_when_no_graded():
    assert bt.season_scoreboard([]) is None

def test_scoreboard_counts_games_and_both_models():
    rows = [
        _drow("2026-06-03", tier="🟢 Tier 1", mult_tier="🔴 Tier 3", win=1, score=85),
        _drow("2026-06-04", tier="🔴 Tier 3", mult_tier="🟢 Tier 1", win=0),
        _drow("2026-06-04", tier="🟢 Tier 1", mult_tier="🟢 Tier 1", win=1, score=90),
    ]
    sb = bt.season_scoreboard(rows)
    assert sb["n_games"] == 2          # two distinct dates
    assert sb["n_graded"] == 3
    # additive Tier 1: rows 1 & 3 -> 2-0 ; mult Tier 1: rows 2 & 3 -> 1-1
    assert (sb["additive"]["wins"], sb["additive"]["losses"]) == (2, 0)
    assert (sb["mult"]["wins"], sb["mult"]["losses"]) == (1, 1)

def test_scoreboard_brier_uses_each_models_own_score():
    # Additive nails it (score 100, win); mult would use mult_score.
    rows = [_drow("2026-06-04", tier="🟢 Tier 1", mult_tier="🔴 Tier 3", win=1, score=100)]
    sb = bt.season_scoreboard(rows)
    assert sb["additive"]["brier"] == pytest.approx(0.0)
    assert sb["additive"]["brier_n"] == 1
    assert sb["mult"]["n"] == 0


# ------------------------------------------------------------
# scoreboard_verdict — ranks by win rate until ROI has a real sample
# ------------------------------------------------------------
def _sb(a_wins, a_losses, m_wins, m_losses, a_priced=0, m_priced=0,
        a_roi=0.0, m_roi=0.0):
    def model(w, l, priced, roi):
        n = w + l
        return {"n": n, "wins": w, "losses": l,
                "win_rate": (w / n) if n else 0.0,
                "n_priced": priced, "roi_pct": roi, "units": 0.0,
                "brier": 0.0, "brier_n": n}
    return {"additive": model(a_wins, a_losses, a_priced, a_roi),
            "mult": model(m_wins, m_losses, m_priced, m_roi)}

def test_verdict_uses_win_rate_when_few_priced():
    # The exact case from the live app: additive wins way more, but ROI (on a
    # tiny priced sample) favors mult. Win rate must win the verdict.
    sb = _sb(34, 19, 5, 8, a_priced=5, m_priced=5, a_roi=-41.6, m_roi=-27.6)
    v = bt.scoreboard_verdict(sb)
    assert v["leader"] == "additive"
    assert v["basis"] == "win_rate"

def test_verdict_uses_roi_when_both_have_enough_priced():
    sb = _sb(30, 20, 30, 20, a_priced=40, m_priced=40, a_roi=2.0, m_roi=8.0)
    v = bt.scoreboard_verdict(sb)
    assert v["leader"] == "mult" and v["basis"] == "roi"

def test_verdict_none_when_a_model_has_no_plays():
    sb = _sb(10, 5, 0, 0)
    assert bt.scoreboard_verdict(sb) is None

def test_verdict_tie_on_win_rate():
    sb = _sb(5, 5, 5, 5)
    v = bt.scoreboard_verdict(sb)
    assert v["leader"] == "tie"


# ------------------------------------------------------------
# loader
# ------------------------------------------------------------
def test_load_rows_from_file(tmp_path):
    import json
    p = tmp_path / "rows.json"
    p.write_text(json.dumps([_row(), _row(win=0)]))
    assert len(bt.load_rows_from_file(str(p))) == 2

def test_load_rows_from_file_accepts_wrapped(tmp_path):
    import json
    p = tmp_path / "rows.json"
    p.write_text(json.dumps({"rows": [_row()]}))
    assert len(bt.load_rows_from_file(str(p))) == 1
