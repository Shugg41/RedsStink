"""
engine.py — pure scoring / odds / stat math for the Reds prop dashboard.

This module deliberately has NO Streamlit (or network) dependencies so it can be
imported by the app, by the test suite, and by the backtest harness without
launching the UI. All tunable weights live here so they can be swept in a
backtest from one place.
"""

# ============================================================
# SCORING CONFIG — tune weights here
# ============================================================
WEIGHT_CONSISTENCY   = 45   # Max pts: L10 hit game rate
WEIGHT_HRR           = 15   # Max pts: L10 hits+runs+RBI avg
WEIGHT_SPLIT         = 20   # Max pts: OPS vs pitcher hand
WEIGHT_PITCHER       = 10   # Max pts: opponent ERA bonus
WEIGHT_BVP           = 10   # Max pts: batter vs pitcher history
LINEUP_TOP_BONUS     =  5   # Batting 1-3 bonus
LINEUP_BOT_PENALTY   = -5   # Batting 7-9 penalty
TIER1_THRESHOLD      = 75
TIER2_THRESHOLD      = 55

# Scaled BABIP guardrail (used by BOTH engines)
BABIP_THRESHOLD      = 0.340  # regression watch line
BABIP_PER_010        = 1.0    # additive: -1 pt per .010 above threshold
BABIP_ADD_CAP        = -20    # additive penalty floor

# Small-sample gates — below these PA counts the bonus is shrunk toward 0
# (BvP and platoon splits over tiny samples are mostly noise).
BVP_MIN_PA           = 10   # full BvP credit only at/above this many PA
SPLIT_MIN_PA         = 30   # full platoon-split credit only at/above this many PA

# Park factors — shared by the strikeout and multiplicative engines
HITTER_PARKS  = ['Great American Ball Park', 'Coors Field', 'Fenway Park', 'Globe Life Field',
                 'American Family Field', 'Guaranteed Rate Field']
PITCHER_PARKS = ['T-Mobile Park', 'loanDepot park', 'Oracle Park', 'Petco Park',
                 'Kauffman Stadium', 'Truist Park']

# ============================================================
# MULTIPLICATIVE ENGINE CONFIG (side-by-side experiment)
# ============================================================
# Baseline blend (must sum to 1.0) — leaning on stable season quality
MULT_W_SEASON        = 0.50   # OPS+ / ISO anchor (regression-proof)
MULT_W_CONTACT       = 0.25   # K%-based contact floor
MULT_W_RECENT        = 0.25   # L10 involvement (hit-game rate)
# Modifier bands — every modifier clamped to this range so none runs away
MULT_MOD_FLOOR       = 0.80
MULT_MOD_CEIL        = 1.20
# Hot-hand bonus: rewards REAL streaks (hot + sustainable BABIP), ignores mirages
HOT_HAND_RECENT_MIN  = 70     # recent-form sub-score required to qualify as "hot"
HOT_HAND_BABIP_MAX   = 0.340  # BABIP at/below this = streak is real, not luck
HOT_HAND_MAX_BOOST   = 0.15   # max +15% for the hottest legit streaks

# ============================================================
# STRIKEOUT ENGINE WEIGHTS
# ============================================================
SK_K9_WEIGHT         = 3.0  # Base Ks from K/9
SK_SWSTR_BONUS       = 1.0  # SwStr% bonus max
SK_OPP_K_BONUS       = 1.0  # Opponent K% bonus max
SK_FORM_ADJ_MAX      = 1.0  # L5 form adjustment max
SK_WHIP_ADJ          = 0.5  # WHIP penalty/bonus
SK_PARK_K_ADJ        = 0.5  # Park factor adjustment


# ============================================================
# STAT / IP HELPERS
# ============================================================
def calc_ip(ip_str):
    """Parse baseball innings-pitched notation ('5.2' = 5 and 2/3 innings)."""
    try:
        ip = str(ip_str)
        if '.' in ip:
            whole, partial = ip.split('.')
            return int(whole) + (int(partial) / 3.0)
        return int(ip)
    except Exception:
        return 0.0

def calculate_fip(stats):
    """Fielding-independent pitching. Uses the API value when present, else
    computes it from the components with a fixed 3.20 constant."""
    try:
        api_fip = stats.get('fip', stats.get('fieldingIndependentPitching', '0.00'))
        if api_fip not in ('0.00', '-.--'):
            return f"{float(api_fip):.2f}"
        hr  = int(stats.get('homeRuns', 0))
        bb  = int(stats.get('baseOnBalls', 0))
        hbp = int(stats.get('hitBatsmen', stats.get('hitByPitch', 0)))
        k   = int(stats.get('strikeOuts', 0))
        ip  = calc_ip(stats.get('inningsPitched', '0.0'))
        if ip <= 0: return "0.00"
        fip = ((13 * hr) + (3 * (bb + hbp)) - (2 * k)) / ip + 3.20
        return f"{max(0, fip):.2f}"
    except Exception:
        return "0.00"

def calculate_ops_plus(player_stats, league_stats):
    """OPS+ (100 = league average). Returns 'N/A' for empty samples."""
    try:
        if int(player_stats.get('plateAppearances', 0)) == 0: return "N/A"
        p_obp  = float(player_stats.get('obp', '.000'))
        p_slg  = float(player_stats.get('slg', '.000'))
        lg_obp = float(league_stats.get('obp', '.315'))
        lg_slg = float(league_stats.get('slg', '.400'))
        if lg_obp <= 0 or lg_slg <= 0: return "N/A"
        return str(max(0, int(round(100 * ((p_obp / lg_obp) + (p_slg / lg_slg) - 1)))))
    except Exception:
        return "N/A"

def normalize_name(name):
    """Normalize a player name for fuzzy matching across data sources."""
    return name.lower().replace(".", "").replace(" jr", "").replace(" sr", "").replace("-", " ").strip()


# ============================================================
# ODDS MATH
# ============================================================
def american_to_decimal(price):
    """Convert American odds (e.g. -115, +120) to decimal payout multiplier."""
    try:
        price = float(price)
        if price > 0:
            return 1.0 + (price / 100.0)
        elif price < 0:
            return 1.0 + (100.0 / abs(price))
        return 1.0
    except Exception:
        return 1.0

def american_to_implied_prob(price):
    """Convert American odds to implied win probability (0-1), vig included."""
    try:
        price = float(price)
        if price > 0:
            return 100.0 / (price + 100.0)
        elif price < 0:
            return abs(price) / (abs(price) + 100.0)
        return 0.0
    except Exception:
        return 0.0

def units_won(price, won):
    """Units won/lost on a 1-unit bet given American price and W/L (1/0)."""
    if won == 1:
        return round(american_to_decimal(price) - 1.0, 3)  # net profit on win
    else:
        return -1.0  # lose the staked unit


# ============================================================
# SMALL-SAMPLE GATING
# ============================================================
def sample_weight(pa, min_pa):
    """Linear shrink factor in [0, 1]: 0 PA -> 0 credit, >= min_pa -> full credit.
    Used to fade out BvP / platoon-split bonuses that ride on tiny samples."""
    try:
        pa = float(pa)
    except Exception:
        return 0.0
    if pa <= 0 or min_pa <= 0:
        return 0.0
    return max(0.0, min(1.0, pa / float(min_pa)))


# ============================================================
# SCALED BABIP PENALTY (additive engine)
# ============================================================
def scaled_babip_penalty(babip_str):
    """-1 pt per .010 of BABIP above .340, floored at BABIP_ADD_CAP (-20)."""
    try:
        b = float(babip_str)
    except Exception:
        return 0
    if b <= BABIP_THRESHOLD:
        return 0
    over = b - BABIP_THRESHOLD
    pen  = -(over / 0.010) * BABIP_PER_010
    return int(round(max(BABIP_ADD_CAP, pen)))


# ============================================================
# MULTIPLICATIVE ENGINE
# ============================================================
def _clamp_mod(x):
    return max(MULT_MOD_FLOOR, min(MULT_MOD_CEIL, x))

def run_multiplicative_engine(inputs):
    """
    inputs: dict with keys
      ops_plus (str/N/A), iso (str), k_pct (float 0-1), l10_hit_rate (0-1),
      opp_fip (float), park_name (str), lineup_pos (int or None),
      babip (str)
    Returns (mult_score int 0-100, mult_tier str, baseline int, receipt list[(label,val,detail)]).
    Receipt vals: baseline is a 0-100 int; modifiers are multipliers (e.g. 0.88).
    """
    receipt = []

    # ---- BASELINE: blend of season quality / contact / recent involvement ----
    # Season quality from OPS+ (100 = league avg -> ~60 baseline pts), ISO nudges.
    try:
        opsp = float(inputs.get('ops_plus')) if inputs.get('ops_plus') not in (None, "N/A") else 100.0
    except Exception:
        opsp = 100.0
    # Map OPS+ ~ [60,160] -> [30,90]; 100 -> 60
    season_sub = max(0, min(100, 60 + (opsp - 100) * 0.5))
    try:
        iso = float(inputs.get('iso', 0) or 0)
        season_sub = min(100, season_sub + (iso - 0.140) * 40)  # ISO above .140 nudges up
    except Exception:
        pass

    # Contact floor from K%: 12% -> ~85, 22% -> ~60, 32% -> ~35
    try:
        kp = float(inputs.get('k_pct', 0.22) or 0.22)
    except Exception:
        kp = 0.22
    contact_sub = max(0, min(100, 60 + (0.22 - kp) * 250))

    # Recent involvement from L10 hit-game rate (0-1)
    try:
        rate = float(inputs.get('l10_hit_rate', 0.0) or 0.0)
    except Exception:
        rate = 0.0
    recent_sub = max(0, min(100, rate * 100))

    baseline = (MULT_W_SEASON * season_sub +
                MULT_W_CONTACT * contact_sub +
                MULT_W_RECENT * recent_sub)
    baseline = int(round(max(0, min(100, baseline))))
    receipt.append(("Baseline (blend)", baseline,
                    f"season {int(season_sub)} / contact {int(contact_sub)} / recent {int(recent_sub)}"))

    # ---- MATCHUP MODIFIER: starter FIP + park ----
    try:
        fip = float(inputs.get('opp_fip', 4.00) or 4.00)
    except Exception:
        fip = 4.00
    # Lower FIP (better pitcher) -> modifier below 1.0. 4.00 neutral.
    fip_mod = 1.0 + (fip - 4.00) * 0.06  # each run of FIP = 6% swing
    park = inputs.get('park_name', '')
    park_mod = 1.05 if park in HITTER_PARKS else (0.95 if park in PITCHER_PARKS else 1.0)
    matchup_mod = _clamp_mod(fip_mod * park_mod)
    receipt.append(("Matchup (FIP × park)", round(matchup_mod, 3),
                    f"opp FIP {fip:.2f}, park {'hitter' if park in HITTER_PARKS else ('pitcher' if park in PITCHER_PARKS else 'neutral')}"))

    # ---- LUCK MODIFIER: BABIP regression ----
    try:
        b = float(inputs.get('babip', 0) or 0)
    except Exception:
        b = 0.0
    if b > BABIP_THRESHOLD:
        luck_mod = _clamp_mod(1.0 - (b - BABIP_THRESHOLD) * 2.0)  # .420 -> ~0.84
    else:
        luck_mod = 1.0
    receipt.append(("Luck / BABIP regression", round(luck_mod, 3), f"BABIP {b:.3f}"))

    # ---- LINEUP MODIFIER ----
    pos = inputs.get('lineup_pos')
    if pos is None:
        lineup_mod = 1.0
        lp_detail = "no confirmed lineup"
    elif pos <= 2:
        lineup_mod = 1.05; lp_detail = f"batting {pos+1} (top)"
    elif pos >= 6:
        lineup_mod = 0.92; lp_detail = f"batting {pos+1} (bottom)"
    else:
        lineup_mod = 1.0;  lp_detail = f"batting {pos+1}"
    lineup_mod = _clamp_mod(lineup_mod)
    receipt.append(("Lineup spot", round(lineup_mod, 3), lp_detail))

    # ---- HOT-HAND MODIFIER: reward REAL streaks, not lucky ones ----
    # Fires only when the hitter is genuinely hot (recent form high) AND the
    # streak is sustainable (BABIP not luck-inflated). Lucky-hot guys get no
    # boost here and still eat the luck/BABIP tax above.
    if recent_sub >= HOT_HAND_RECENT_MIN and b <= HOT_HAND_BABIP_MAX:
        hot_boost = 1.0 + min(HOT_HAND_MAX_BOOST, (recent_sub - 60) / 100.0)
        hot_mod   = _clamp_mod(hot_boost)
        hot_detail = f"hot (recent {int(recent_sub)}) + sustainable BABIP {b:.3f}"
    else:
        hot_mod = 1.0
        if recent_sub >= HOT_HAND_RECENT_MIN and b > HOT_HAND_BABIP_MAX:
            hot_detail = f"hot but BABIP {b:.3f} too high — no boost (likely luck)"
        else:
            hot_detail = "not on a qualifying streak"
    receipt.append(("Hot Hand", round(hot_mod, 3), hot_detail))

    # ---- FINAL ----
    final = baseline * matchup_mod * luck_mod * lineup_mod * hot_mod
    mult_score = int(round(max(0, min(100, final))))
    mult_tier  = ("🟢 Tier 1" if mult_score >= TIER1_THRESHOLD
                  else "🟡 Tier 2" if mult_score >= TIER2_THRESHOLD
                  else "🔴 Tier 3")
    return mult_score, mult_tier, baseline, receipt


def tier_for_score(score):
    """Map a 0-100 score to its tier label (shared by both engines)."""
    return ("🟢 Tier 1" if score >= TIER1_THRESHOLD
            else "🟡 Tier 2" if score >= TIER2_THRESHOLD
            else "🔴 Tier 3")
