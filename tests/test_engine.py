"""
Unit tests for engine.py — the pure scoring / odds / stat math.

Run with:  pytest -q
These lock down the numbers that every bet rides on, so a future tweak to a
weight or formula can't silently change scoring without a test going red.
"""
import math
import pytest

import engine as e


# ------------------------------------------------------------
# calc_ip — baseball innings notation ("5.2" = 5 and 2/3)
# ------------------------------------------------------------
@pytest.mark.parametrize("raw, expected", [
    ("5.2", 5 + 2 / 3),
    ("6.0", 6.0),
    ("6",   6.0),
    ("0.0", 0.0),
    ("7.1", 7 + 1 / 3),
])
def test_calc_ip_valid(raw, expected):
    assert e.calc_ip(raw) == pytest.approx(expected)

def test_calc_ip_garbage_is_zero():
    assert e.calc_ip("nope") == 0.0
    assert e.calc_ip(None) == 0.0


# ------------------------------------------------------------
# Odds math
# ------------------------------------------------------------
@pytest.mark.parametrize("price, expected", [
    (120, 2.2),
    (-110, 1.0 + 100 / 110),
    (100, 2.0),
    (0, 1.0),
    ("bad", 1.0),
])
def test_american_to_decimal(price, expected):
    assert e.american_to_decimal(price) == pytest.approx(expected)

@pytest.mark.parametrize("price, expected", [
    (100, 0.5),
    (-110, 110 / 210),
    (120, 100 / 220),
    (0, 0.0),
])
def test_american_to_implied_prob(price, expected):
    assert e.american_to_implied_prob(price) == pytest.approx(expected)

def test_implied_prob_favorite_higher_than_underdog():
    assert e.american_to_implied_prob(-200) > e.american_to_implied_prob(+200)

def test_units_won():
    assert e.units_won(120, 1) == pytest.approx(1.2)     # win pays +1.2u
    assert e.units_won(-110, 1) == pytest.approx(0.909, abs=1e-3)
    assert e.units_won(-110, 0) == -1.0                  # loss costs the stake
    assert e.units_won(999, 0) == -1.0


# ------------------------------------------------------------
# value_metrics — the Value Filter (+EV detection)
# ------------------------------------------------------------
def test_value_metrics_none_without_price():
    assert e.value_metrics(0.7, None) is None

def test_value_metrics_flags_positive_edge():
    # Model 70% on a +100 line (book implies 50%) -> clear value
    v = e.value_metrics(0.70, 100)
    assert v["is_value"] is True
    assert v["edge"] == pytest.approx(0.20)
    assert v["ev"] > 0

def test_value_metrics_rejects_overpriced_favorite():
    # Model 60% but the book charges -200 (implies 66.7%) -> NOT value
    v = e.value_metrics(0.60, -200)
    assert v["is_value"] is False
    assert v["edge"] < 0
    assert v["ev"] < 0

def test_value_metrics_break_even_is_not_value():
    # Model exactly equals implied -> edge 0, not a value play
    v = e.value_metrics(0.5, 100)
    assert v["edge"] == pytest.approx(0.0)
    assert v["is_value"] is False

def test_value_metrics_garbage_model_prob():
    assert e.value_metrics("x", -110) is None


# ------------------------------------------------------------
# scaled_babip_penalty
# ------------------------------------------------------------
def test_babip_penalty_below_threshold_is_zero():
    assert e.scaled_babip_penalty(".300") == 0
    assert e.scaled_babip_penalty(str(e.BABIP_THRESHOLD)) == 0

def test_babip_penalty_scales_per_010():
    assert e.scaled_babip_penalty(".350") == -1    # .010 over
    assert e.scaled_babip_penalty(".360") == -2    # .020 over

def test_babip_penalty_is_capped():
    assert e.scaled_babip_penalty(".600") == e.BABIP_ADD_CAP
    assert e.scaled_babip_penalty(".700") == e.BABIP_ADD_CAP

def test_babip_penalty_garbage_is_zero():
    assert e.scaled_babip_penalty("--") == 0
    assert e.scaled_babip_penalty(None) == 0


# ------------------------------------------------------------
# sample_weight — small-sample shrink factor
# ------------------------------------------------------------
@pytest.mark.parametrize("pa, min_pa, expected", [
    (0, 10, 0.0),
    (5, 10, 0.5),
    (10, 10, 1.0),
    (50, 10, 1.0),   # clamped to 1.0
    (-3, 10, 0.0),
    (10, 0, 0.0),    # guard against zero min
])
def test_sample_weight(pa, min_pa, expected):
    assert e.sample_weight(pa, min_pa) == pytest.approx(expected)

def test_sample_weight_garbage():
    assert e.sample_weight("x", 10) == 0.0


# ------------------------------------------------------------
# split_ops_points — platoon split, sample-gated
# ------------------------------------------------------------
def test_split_points_full_sample_matches_legacy_formula():
    # At/above SPLIT_MIN_PA the old formula is preserved: int((ops-.5)*50), capped.
    assert e.split_ops_points(0.800, e.SPLIT_MIN_PA) == 15
    assert e.split_ops_points(0.500, e.SPLIT_MIN_PA) == 0
    assert e.split_ops_points(1.500, e.SPLIT_MIN_PA) == e.WEIGHT_SPLIT  # capped

def test_split_points_small_sample_is_shrunk():
    full = e.split_ops_points(0.800, e.SPLIT_MIN_PA)
    half = e.split_ops_points(0.800, e.SPLIT_MIN_PA // 2)
    assert 0 < half < full

def test_split_points_zero_pa_is_zero():
    assert e.split_ops_points(0.900, 0) == 0

def test_split_points_garbage_is_zero():
    assert e.split_ops_points("x", e.SPLIT_MIN_PA) == 0


# ------------------------------------------------------------
# bvp_bonus_points — batter vs pitcher, sample-gated
# ------------------------------------------------------------
def test_bvp_full_sample_tiers():
    assert e.bvp_bonus_points(0.360, e.BVP_MIN_PA) == e.WEIGHT_BVP
    assert e.bvp_bonus_points(0.300, e.BVP_MIN_PA) == e.WEIGHT_BVP * 0.5
    assert e.bvp_bonus_points(0.200, e.BVP_MIN_PA) == 0

def test_bvp_small_sample_is_shrunk():
    full = e.bvp_bonus_points(0.360, e.BVP_MIN_PA)
    tiny = e.bvp_bonus_points(0.360, 2)
    assert 0 <= tiny < full

def test_bvp_zero_pa_is_zero():
    assert e.bvp_bonus_points(0.500, 0) == 0

def test_bvp_garbage_is_zero():
    assert e.bvp_bonus_points("x", e.BVP_MIN_PA) == 0


# ------------------------------------------------------------
# calculate_fip
# ------------------------------------------------------------
def test_fip_uses_api_value_when_present():
    assert e.calculate_fip({"fip": "3.51"}) == "3.51"

def test_fip_computes_from_components_when_missing():
    # ((13*1)+(3*2)-(2*8))/6 + 3.20 = (13+6-16)/6 + 3.20 = 0.5 + 3.20 = 3.70
    val = e.calculate_fip({"homeRuns": 1, "baseOnBalls": 2,
                           "strikeOuts": 8, "inningsPitched": "6.0"})
    assert val == "3.70"

def test_fip_zero_ip_is_safe():
    assert e.calculate_fip({"inningsPitched": "0.0"}) == "0.00"

def test_fip_garbage_is_safe():
    assert e.calculate_fip({"fip": "abc"}) == "0.00"


# ------------------------------------------------------------
# calculate_ops_plus
# ------------------------------------------------------------
def test_ops_plus_empty_sample_is_na():
    assert e.calculate_ops_plus({"plateAppearances": 0}, {"obp": ".315", "slg": ".400"}) == "N/A"

def test_ops_plus_league_average_is_100():
    lg = {"obp": ".315", "slg": ".400"}
    player = {"plateAppearances": 100, "obp": ".315", "slg": ".400"}
    assert e.calculate_ops_plus(player, lg) == "100"

def test_ops_plus_better_than_league_exceeds_100():
    lg = {"obp": ".315", "slg": ".400"}
    player = {"plateAppearances": 100, "obp": ".400", "slg": ".550"}
    assert int(e.calculate_ops_plus(player, lg)) > 100


# ------------------------------------------------------------
# normalize_name
# ------------------------------------------------------------
def test_normalize_name_strips_punct_and_suffix():
    assert e.normalize_name("A.J. Pollock Jr.") == "aj pollock"
    assert e.normalize_name("Hunter Greene-Smith") == "hunter greene smith"

def test_normalize_name_is_idempotent():
    once = e.normalize_name("T.J. Friedl")
    assert e.normalize_name(once) == once


# ------------------------------------------------------------
# tier_for_score
# ------------------------------------------------------------
def test_tier_for_score_boundaries():
    assert "Tier 1" in e.tier_for_score(e.TIER1_THRESHOLD)
    assert "Tier 2" in e.tier_for_score(e.TIER2_THRESHOLD)
    assert "Tier 2" in e.tier_for_score(e.TIER1_THRESHOLD - 1)
    assert "Tier 3" in e.tier_for_score(e.TIER2_THRESHOLD - 1)


# ------------------------------------------------------------
# Strikeout projection — stable IP + opener detection
# ------------------------------------------------------------
def test_ip_per_start():
    assert e.ip_per_start(60.0, 10) == pytest.approx(6.0)
    assert e.ip_per_start(60.0, 0) == 0.0      # no starts -> 0, no divide error
    assert e.ip_per_start("bad", 10) == 0.0

def test_is_likely_opener_true_for_short_starts():
    # 12 starts, 18 IP -> 1.5 IP/start = classic opener
    assert e.is_likely_opener(18.0, 12) is True

def test_is_likely_opener_false_for_real_starter():
    # 10 starts, 58 IP -> 5.8 IP/start
    assert e.is_likely_opener(58.0, 10) is False

def test_is_likely_opener_false_without_starts():
    assert e.is_likely_opener(40.0, 0) is False  # pure reliever / no data -> don't flag

def test_is_likely_opener_mostly_relief():
    # 4 starts of 12 appearances, ~4 IP/start (mostly relieves) -> bulk/opener usage
    assert e.is_likely_opener(16.0, 4, games_played=12) is True

def test_expected_ip_clamps_real_starter_and_ignores_fragile_recent():
    # Season 5.8 IP/start but a couple short recent outings (L5 avg 2.0).
    # Old code used 2.0 and under-projected; now it stays near the season anchor.
    exp = e.expected_starter_ip(58.0, 10, 2.0)
    assert exp >= e.STARTER_IP_FLOOR
    assert 4.0 <= exp <= 6.5

def test_expected_ip_opener_stays_low():
    exp = e.expected_starter_ip(18.0, 12, 1.5)   # opener
    assert exp < e.STARTER_IP_FLOOR              # not floored up to a starter's innings

def test_expected_ip_thin_data_falls_back():
    assert e.expected_starter_ip(0, 0, 0) == pytest.approx(e.DEFAULT_STARTER_IP)

def test_base_k_projection():
    # 9.0 K/9 over 6 IP -> 6.0 Ks
    assert e.base_k_projection(9.0, 6.0) == pytest.approx(6.0)
    assert e.base_k_projection("bad", 6.0) == pytest.approx(5.0)  # default K/9 7.5 -> 5.0

def test_stable_ip_fixes_underprojection():
    # The live bug: K/9 ~8, season 5.8 IP/start, but L5 avg IP cratered to 2.0.
    old_base = round((8.0 / 9.0) * 2.0, 1)               # = 1.8 (broken)
    new_base = e.base_k_projection(8.0, e.expected_starter_ip(58.0, 10, 2.0))
    assert new_base > old_base + 1.5                     # materially higher, no longer absurd


# ------------------------------------------------------------
# run_multiplicative_engine
# ------------------------------------------------------------
def _base_inputs(**over):
    inp = {
        "ops_plus": "100", "iso": "0.140", "k_pct": 0.22,
        "l10_hit_rate": 0.5, "opp_fip": 4.00, "park_name": "",
        "lineup_pos": None, "babip": "0.300",
    }
    inp.update(over)
    return inp

def test_mult_returns_well_formed_tuple():
    score, tier, baseline, receipt = e.run_multiplicative_engine(_base_inputs())
    assert isinstance(score, int) and 0 <= score <= 100
    assert "Tier" in tier
    assert isinstance(baseline, int) and 0 <= baseline <= 100
    assert isinstance(receipt, list) and len(receipt) >= 5

def test_mult_handles_empty_and_garbage_inputs():
    for bad in ({}, {"ops_plus": "N/A", "iso": None, "k_pct": "x", "babip": "--"}):
        score, tier, baseline, receipt = e.run_multiplicative_engine(bad)
        assert 0 <= score <= 100

def test_mult_high_babip_luck_tax_lowers_score():
    lucky = e.run_multiplicative_engine(_base_inputs(babip="0.430"))[0]
    normal = e.run_multiplicative_engine(_base_inputs(babip="0.300"))[0]
    assert lucky < normal

def test_mult_hot_hand_boosts_sustainable_streak():
    hot = e.run_multiplicative_engine(_base_inputs(l10_hit_rate=0.9, babip="0.320"))[0]
    cold = e.run_multiplicative_engine(_base_inputs(l10_hit_rate=0.2, babip="0.320"))[0]
    assert hot > cold

def test_mult_tough_pitcher_lowers_score():
    ace = e.run_multiplicative_engine(_base_inputs(opp_fip=2.50))[0]
    batting_practice = e.run_multiplicative_engine(_base_inputs(opp_fip=5.50))[0]
    assert ace < batting_practice

def test_mult_top_of_order_beats_bottom():
    top = e.run_multiplicative_engine(_base_inputs(lineup_pos=0))[0]
    bottom = e.run_multiplicative_engine(_base_inputs(lineup_pos=7))[0]
    assert top > bottom

def test_mult_elite_profile_reaches_tier1():
    elite = _base_inputs(ops_plus="170", iso="0.280", k_pct=0.12,
                         l10_hit_rate=0.9, opp_fip=5.50,
                         park_name="Great American Ball Park", lineup_pos=1, babip="0.320")
    score, tier, _, _ = e.run_multiplicative_engine(elite)
    assert "Tier 1" in tier


# ------------------------------------------------------------
# Config sanity
# ------------------------------------------------------------
def test_baseline_blend_weights_sum_to_one():
    assert e.MULT_W_SEASON + e.MULT_W_CONTACT + e.MULT_W_RECENT == pytest.approx(1.0)

def test_modifier_band_is_sane():
    assert e.MULT_MOD_FLOOR < 1.0 < e.MULT_MOD_CEIL
