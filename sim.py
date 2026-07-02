"""
sim.py — Monte Carlo simulation of the Reds' offensive game (pure, no I/O).

Plays the game thousands of times: each plate appearance rolls weighted dice
from the hitter's real outcome rates (K/BB/1B/2B/3B/HR/out), adjusted for the
opposing starter, the bullpen phase, and the park. Because every outcome comes
from the SAME simulated games, the results are jointly distributed — which is
what makes team totals, F5, per-hitter props, and same-game-parlay correlation
all coherent with each other.
"""
import random

from engine import _safe_float, HITTER_PARKS, PITCHER_PARKS

LEAGUE = {          # league-ish baselines used for opponent scaling
    "k_pct": 0.222, "bb_pct": 0.082,
    "xba": 0.248,
}
DEFAULT_SIMS = 10000


# ============================================================
# PROFILES
# ============================================================
def hitter_profile(season_stat, name="?", player_id=None):
    """Per-PA outcome probabilities from a season counting-stat dict
    (plateAppearances, strikeOuts, baseOnBalls, hitByPitch, hits, doubles,
    triples, homeRuns). Falls back to league-average on thin data."""
    pa = _safe_float(season_stat.get("plateAppearances"), 0)
    if pa < 30:   # too thin — league-average bat
        return {"name": name, "player_id": player_id,
                "k": 0.22, "bb": 0.085, "hr": 0.031,
                "h3": 0.004, "h2": 0.045, "h1": 0.145}
    k   = _safe_float(season_stat.get("strikeOuts"), 0) / pa
    bb  = (_safe_float(season_stat.get("baseOnBalls"), 0)
           + _safe_float(season_stat.get("hitByPitch"), 0)) / pa
    hr  = _safe_float(season_stat.get("homeRuns"), 0) / pa
    h3  = _safe_float(season_stat.get("triples"), 0) / pa
    h2  = _safe_float(season_stat.get("doubles"), 0) / pa
    h1  = max(0.0, (_safe_float(season_stat.get("hits"), 0) / pa) - hr - h3 - h2)
    return {"name": name, "player_id": player_id,
            "k": k, "bb": bb, "hr": hr, "h3": h3, "h2": h2, "h1": h1}

def pitcher_profile(adv_pitching, xba_against=None):
    """Opposing-pitcher adjustment factors from advanced pitching stats."""
    k_pct  = _safe_float(adv_pitching.get("strikeoutsPerPlateAppearance"), LEAGUE["k_pct"])
    bb_pct = _safe_float(adv_pitching.get("walksPerPlateAppearance"), LEAGUE["bb_pct"])
    contact = 1.0
    if xba_against is not None:
        contact = _safe_float(xba_against, LEAGUE["xba"]) / LEAGUE["xba"]
    return {"k_factor":  max(0.5, min(2.0, k_pct / LEAGUE["k_pct"])),
            "bb_factor": max(0.5, min(2.0, bb_pct / LEAGUE["bb_pct"])),
            "contact_factor": max(0.8, min(1.2, contact))}

NEUTRAL_PITCHER = {"k_factor": 1.0, "bb_factor": 1.0, "contact_factor": 1.0}

def bullpen_factor(bullpen_era):
    """Bullpen quality as a contact factor (ERA 4.2 = neutral)."""
    era = _safe_float(bullpen_era, 4.2)
    return max(0.85, min(1.18, 1.0 + (era - 4.2) * 0.035))


# ============================================================
# PER-PA OUTCOME
# ============================================================
def pa_probs(hp, pf, park_hr_mod=1.0, contact_extra=1.0):
    """Blend hitter rates with pitcher factors (square-root scaling so neither
    side dominates) into one per-PA outcome distribution."""
    k  = min(0.60, hp["k"] * (pf["k_factor"] ** 0.5))
    bb = min(0.30, hp["bb"] * (pf["bb_factor"] ** 0.5))
    con = (pf["contact_factor"] ** 0.5) * contact_extra
    hr = min(0.15, hp["hr"] * con * park_hr_mod)
    h3 = hp["h3"] * con
    h2 = hp["h2"] * con
    h1 = hp["h1"] * con
    total_hit = hr + h3 + h2 + h1
    room = max(0.0, 1.0 - k - bb)
    if total_hit > room:                      # renormalize into what's left
        scale = room / total_hit
        hr, h3, h2, h1 = hr*scale, h3*scale, h2*scale, h1*scale
    return {"k": k, "bb": bb, "hr": hr, "h3": h3, "h2": h2, "h1": h1}

def _roll(probs, rng):
    r = rng.random()
    for outcome in ("k", "bb", "hr", "h3", "h2", "h1"):
        r -= probs[outcome]
        if r < 0:
            return outcome
    return "out"


# ============================================================
# GAME SIMULATION
# ============================================================
def simulate_games(lineup, opp_pitcher, bullpen_era=4.2, park_name="",
                   starter_exp_ip=5.5, n_sims=DEFAULT_SIMS, seed=1):
    """Simulate the Reds' offensive halves of n_sims games.

    lineup: list of 9 hitter_profile dicts in batting order.
    Returns joint per-sim results:
      {'team_runs': [...], 'f5_runs': [...],
       'hitters': {player_id: {'H': [...], 'HRR': [...], 'TB': [...]}}}
    """
    rng = random.Random(seed)
    park_hr = 1.12 if park_name in HITTER_PARKS else (0.90 if park_name in PITCHER_PARKS else 1.0)
    bp_con  = bullpen_factor(bullpen_era)
    starter_innings = max(1, min(9, int(round(_safe_float(starter_exp_ip, 5.5)))))

    # Precompute each hitter's outcome table vs starter and vs bullpen
    vs_starter = [pa_probs(h, opp_pitcher, park_hr) for h in lineup]
    vs_bullpen = [pa_probs(h, NEUTRAL_PITCHER, park_hr, contact_extra=bp_con) for h in lineup]

    ids = [h.get("player_id") for h in lineup]
    out = {"team_runs": [], "f5_runs": [],
           "hitters": {pid: {"H": [], "HRR": [], "TB": []} for pid in ids if pid is not None}}

    for _ in range(n_sims):
        H   = [0] * 9
        R   = [0] * 9
        RBI = [0] * 9
        TB  = [0] * 9
        runs = 0
        f5_runs = 0
        batter = 0

        for inning in range(1, 10):
            tables = vs_starter if inning <= starter_innings else vs_bullpen
            outs = 0
            bases = [None, None, None]     # occupant batting-slot index or None

            while outs < 3:
                slot = batter % 9
                res  = _roll(tables[slot], rng)
                batter += 1

                if res == "k" or res == "out":
                    outs += 1
                    continue

                scored = []
                if res == "bb":
                    # force advances only
                    if bases[0] is not None:
                        if bases[1] is not None:
                            if bases[2] is not None:
                                scored.append(bases[2])
                            bases[2] = bases[1]
                        bases[1] = bases[0]
                    bases[0] = slot
                elif res == "hr":
                    for b in (2, 1, 0):
                        if bases[b] is not None:
                            scored.append(bases[b])
                            bases[b] = None
                    scored.append(slot)
                    H[slot] += 1; TB[slot] += 4
                elif res == "h3":
                    for b in (2, 1, 0):
                        if bases[b] is not None:
                            scored.append(bases[b])
                            bases[b] = None
                    bases[2] = slot
                    H[slot] += 1; TB[slot] += 3
                elif res == "h2":
                    if bases[2] is not None: scored.append(bases[2]); bases[2] = None
                    if bases[1] is not None: scored.append(bases[1]); bases[1] = None
                    if bases[0] is not None:
                        # runner from 1st scores on a double ~40% of the time
                        if rng.random() < 0.40:
                            scored.append(bases[0])
                        else:
                            bases[2] = bases[0]
                        bases[0] = None
                    bases[1] = slot
                    H[slot] += 1; TB[slot] += 2
                else:  # single
                    if bases[2] is not None: scored.append(bases[2]); bases[2] = None
                    if bases[1] is not None:
                        # runner from 2nd scores on a single ~62% of the time
                        if rng.random() < 0.62:
                            scored.append(bases[1])
                        else:
                            bases[2] = bases[1]
                        bases[1] = None
                    if bases[0] is not None:
                        # runner from 1st takes 3rd ~28% of the time
                        if bases[2] is None and rng.random() < 0.28:
                            bases[2] = bases[0]
                        else:
                            bases[1] = bases[0]
                        bases[0] = None
                    bases[0] = slot
                    H[slot] += 1; TB[slot] += 1

                for who in scored:
                    R[who] += 1
                    RBI[slot] += 1
                    runs += 1
                    if inning <= 5:
                        f5_runs += 1

        out["team_runs"].append(runs)
        out["f5_runs"].append(f5_runs)
        for i, pid in enumerate(ids):
            if pid is None:
                continue
            rec = out["hitters"][pid]
            rec["H"].append(H[i])
            rec["HRR"].append(H[i] + R[i] + RBI[i])
            rec["TB"].append(TB[i])
    return out


# ============================================================
# SUMMARIES + SGP CORRELATION
# ============================================================
def p_over(dist, line):
    """P(value > line) over a sim distribution (x.5 lines: strictly greater)."""
    if not dist:
        return 0.0
    return sum(1 for v in dist if v > line) / len(dist)

def mean(dist):
    return (sum(dist) / len(dist)) if dist else 0.0

def joint_prob(dist_a, line_a, dist_b, line_b):
    """P(A over AND B over) from paired sim outcomes (same games)."""
    if not dist_a or len(dist_a) != len(dist_b):
        return 0.0
    hits = sum(1 for a, b in zip(dist_a, dist_b) if a > line_a and b > line_b)
    return hits / len(dist_a)

def sgp_edge(dist_a, line_a, dist_b, line_b):
    """Correlation boost for a 2-leg same-game parlay:
    ratio of true joint probability to the independence assumption books
    often price with. > 1.0 means the SGP is worth MORE than the naive price."""
    pa_, pb_ = p_over(dist_a, line_a), p_over(dist_b, line_b)
    indep = pa_ * pb_
    if indep <= 0:
        return None
    return round(joint_prob(dist_a, line_a, dist_b, line_b) / indep, 3)
