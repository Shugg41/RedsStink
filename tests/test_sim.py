"""Tests for the Monte Carlo game simulator."""
import pytest

import sim


def _stat(pa=600, so=130, bb=50, hbp=5, hits=150, doubles=30, triples=3, hr=20):
    return {"plateAppearances": pa, "strikeOuts": so, "baseOnBalls": bb,
            "hitByPitch": hbp, "hits": hits, "doubles": doubles,
            "triples": triples, "homeRuns": hr}

def _lineup(stat=None, n=9):
    return [sim.hitter_profile(stat or _stat(), name=f"H{i}", player_id=i + 1)
            for i in range(n)]

AVG_PITCHER = sim.pitcher_profile({"strikeoutsPerPlateAppearance": "0.222",
                                   "walksPerPlateAppearance": "0.082"})
ACE = sim.pitcher_profile({"strikeoutsPerPlateAppearance": "0.32",
                           "walksPerPlateAppearance": "0.05"}, xba_against=0.215)
SOFT = sim.pitcher_profile({"strikeoutsPerPlateAppearance": "0.15",
                            "walksPerPlateAppearance": "0.11"}, xba_against=0.285)


# ------------------------------------------------------------
# profiles
# ------------------------------------------------------------
def test_hitter_profile_rates_sane():
    h = sim.hitter_profile(_stat())
    assert h["k"] == pytest.approx(130 / 600)
    assert 0 < h["h1"] < 0.3
    total = h["k"] + h["bb"] + h["hr"] + h["h3"] + h["h2"] + h["h1"]
    assert total < 1.0

def test_hitter_profile_thin_data_falls_back():
    h = sim.hitter_profile({"plateAppearances": 10, "hits": 9})
    assert h["k"] == 0.22   # league fallback, not a .900 hitter

def test_pa_probs_never_exceed_one():
    p = sim.pa_probs(sim.hitter_profile(_stat(hits=250, hr=50)), SOFT, park_hr_mod=1.2)
    assert sum(p.values()) <= 1.0 + 1e-9


# ------------------------------------------------------------
# game simulation sanity
# ------------------------------------------------------------
def test_league_average_run_environment():
    res = sim.simulate_games(_lineup(), AVG_PITCHER, n_sims=3000, seed=7)
    m = sim.mean(res["team_runs"])
    assert 3.2 <= m <= 5.8          # sane MLB team-runs-per-game band

def test_ace_suppresses_runs_vs_soft_arm():
    ace  = sim.mean(sim.simulate_games(_lineup(), ACE,  n_sims=2000, seed=3)["team_runs"])
    soft = sim.mean(sim.simulate_games(_lineup(), SOFT, n_sims=2000, seed=3)["team_runs"])
    assert soft > ace + 0.5

def test_f5_less_than_full_game():
    res = sim.simulate_games(_lineup(), AVG_PITCHER, n_sims=1500, seed=5)
    assert sim.mean(res["f5_runs"]) < sim.mean(res["team_runs"])
    assert all(f <= t for f, t in zip(res["f5_runs"], res["team_runs"]))

def test_per_hitter_hit_probability_sane():
    res = sim.simulate_games(_lineup(), AVG_PITCHER, n_sims=3000, seed=9)
    p1 = sim.p_over(res["hitters"][1]["H"], 0.5)     # leadoff: P(1+ hit)
    assert 0.45 <= p1 <= 0.80

def test_leadoff_gets_more_chances_than_nine_hole():
    res = sim.simulate_games(_lineup(), AVG_PITCHER, n_sims=3000, seed=11)
    assert sim.mean(res["hitters"][1]["HRR"]) > sim.mean(res["hitters"][9]["HRR"])

def test_deterministic_with_seed():
    a = sim.simulate_games(_lineup(), AVG_PITCHER, n_sims=500, seed=42)["team_runs"]
    b = sim.simulate_games(_lineup(), AVG_PITCHER, n_sims=500, seed=42)["team_runs"]
    assert a == b

def test_hitter_park_boosts_offense():
    gabp    = sim.mean(sim.simulate_games(_lineup(), AVG_PITCHER, n_sims=2000, seed=4,
                                          park_name="Great American Ball Park")["team_runs"])
    neutral = sim.mean(sim.simulate_games(_lineup(), AVG_PITCHER, n_sims=2000, seed=4)["team_runs"])
    assert gabp > neutral

def test_gassed_bullpen_leaks_more_runs():
    fresh = sim.mean(sim.simulate_games(_lineup(), AVG_PITCHER, bullpen_era=3.2,
                                        n_sims=2000, seed=6, starter_exp_ip=5)["team_runs"])
    gassed = sim.mean(sim.simulate_games(_lineup(), AVG_PITCHER, bullpen_era=5.6,
                                         n_sims=2000, seed=6, starter_exp_ip=5)["team_runs"])
    assert gassed > fresh


# ------------------------------------------------------------
# summaries + SGP correlation
# ------------------------------------------------------------
def test_p_over_and_mean_basics():
    assert sim.p_over([0, 1, 2, 3], 1.5) == 0.5
    assert sim.mean([2, 4]) == 3.0
    assert sim.p_over([], 0.5) == 0.0

def test_sgp_star_hitter_correlates_with_team_total():
    res = sim.simulate_games(_lineup(), AVG_PITCHER, n_sims=4000, seed=13)
    leadoff_hrr = res["hitters"][1]["HRR"]
    edge = sim.sgp_edge(leadoff_hrr, 1.5, res["team_runs"], 4.5)
    assert edge is not None
    assert edge > 1.05    # 2+ HRR and team-over are genuinely correlated

def test_joint_prob_paired():
    a = [1, 2, 0, 3]
    b = [5, 1, 6, 7]
    # over 0.5 on a AND over 4.5 on b -> games 1 (1,5) and 4 (3,7) => 2/4
    assert sim.joint_prob(a, 0.5, b, 4.5) == 0.5
