"""
pipeline.py — the scoring pipelines, decoupled from Streamlit.

Every function takes a `fetch` namespace (any object exposing the data.py
fetcher names). The app passes its @st.cache_data-wrapped versions; the daily
auto-run robot passes the raw `data` module. Same engines, two callers.
"""
import threading
from concurrent.futures import ThreadPoolExecutor

from engine import (
    calc_ip, calculate_fip, calculate_ops_plus, normalize_name,
    split_ops_points, bvp_bonus_points, scaled_babip_penalty,
    run_multiplicative_engine, project_hrr, prob_2plus_hrr,
    ip_per_start, expected_starter_ip, is_likely_opener, base_k_projection,
    WEIGHT_CONSISTENCY, WEIGHT_HRR, LINEUP_TOP_BONUS, LINEUP_BOT_PENALTY,
    TIER1_THRESHOLD, TIER2_THRESHOLD,
    SK_FORM_ADJ_MAX, SK_SWSTR_BONUS, SK_OPP_K_BONUS, SK_WHIP_ADJ, SK_PARK_K_ADJ,
    HITTER_PARKS, PITCHER_PARKS,
)


# ============================================================
# GAME CONTEXT — resolve today's matchup from the schedule
# ============================================================
def game_context(fetch, date_str, game_idx=0):
    """Resolve the Reds game for a date into a context dict, or None if no game.
    Keys: game_pk, park_name, status_code, is_pregame, opponent, opp_team_id,
    reds/opp pitcher name+id, away_team, home_team, start_utc."""
    sched = fetch.get_schedule(date_str)
    if not sched or sched.get('totalGames', 0) == 0:
        return None
    try:
        game = sched['dates'][0]['games'][game_idx]
    except Exception:
        return None
    game_pk  = game.get('gamePk')
    starters = fetch.get_game_starters(game_pk)
    away = game.get('teams', {}).get('away', {}).get('team', {})
    home = game.get('teams', {}).get('home', {}).get('team', {})
    status = game.get('status', {}).get('statusCode', '')
    ctx = {
        'game_pk': game_pk,
        'park_name': game.get('venue', {}).get('name', 'Unknown'),
        'status_code': status,
        'is_pregame': status in ('S', 'P', 'PW'),
        'start_utc': game.get('gameDate', ''),
        'away_team': away.get('name', ''), 'home_team': home.get('name', ''),
        'n_games': sched.get('totalGames', 1),
    }
    if 'Reds' in ctx['away_team']:
        ctx['opponent']         = ctx['home_team']
        ctx['opp_team_id']      = home.get('id')
        ctx['opp_pitcher_name'] = starters['home']['name']
        ctx['opp_pitcher_id']   = starters['home']['id']
        ctx['reds_pitcher_name'] = starters['away']['name']
        ctx['reds_pitcher_id']   = starters['away']['id']
    else:
        ctx['opponent']         = ctx['away_team']
        ctx['opp_team_id']      = away.get('id')
        ctx['opp_pitcher_name'] = starters['away']['name']
        ctx['opp_pitcher_id']   = starters['away']['id']
        ctx['reds_pitcher_name'] = starters['home']['name']
        ctx['reds_pitcher_id']   = starters['home']['id']
    return ctx


# ============================================================
# PARALLEL HITTER PREFETCH
# ============================================================
def prefetch_hitter(fetch, p_id, year, split_code, opp_pitcher_id):
    """Pull every API blob one hitter needs in a single call."""
    return {
        'logs':    fetch.get_game_logs(p_id, year),
        'ov_data': fetch.get_season_stats(p_id, "hitting", year),
        'adv_hit': fetch.get_advanced_hitting(p_id, year),
        'sp_data': fetch.get_season_stats(p_id, "hitting", year, split=split_code),
        'bvp':     fetch.get_bvp_stats(p_id, opp_pitcher_id),
    }

def parallel_prefetch(fetch, player_ids, year, split_code, opp_pitcher_id,
                      max_workers=8, thread_hook=None):
    """Fetch every hitter's stats concurrently. thread_hook (optional) is
    called in each worker thread — the app uses it to attach Streamlit's
    ScriptRunContext so cached fetchers don't warn."""
    if not player_ids:
        return {}

    def task(pid):
        if thread_hook:
            try:
                thread_hook()
            except Exception:
                pass
        try:
            return pid, prefetch_hitter(fetch, pid, year, split_code, opp_pitcher_id)
        except Exception:
            return pid, None

    out = {}
    with ThreadPoolExecutor(max_workers=min(max_workers, len(player_ids))) as ex:
        for pid, blob in ex.map(task, player_ids):
            out[pid] = blob
    return out


# ============================================================
# OFFENSE BOARD — score every hitter (the heart of the app)
# ============================================================
def score_hitters(fetch, to_score, year, split_code, split_label,
                  batting_order, park_name, pitcher_score, opp_fip_val,
                  bullpen_era, live_odds, opp_pitcher_id,
                  progress_cb=None, thread_hook=None):
    """Score a list of (name, player_id) hitters. Returns scan_results rows —
    the same dict shape the app renders and saves."""
    league_stats = fetch.get_league_hitting(year)
    prefetched = parallel_prefetch(fetch, [pid for _, pid in to_score], year,
                                   split_code, opp_pitcher_id, thread_hook=thread_hook)
    batting_order = batting_order or []
    live_odds = live_odds or {}
    scan_results = []
    n_score = max(1, len(to_score))

    for i, (name, p_id) in enumerate(to_score):
        if progress_cb:
            try:
                progress_cb((i + 1) / n_score, name)
            except Exception:
                pass
        lineup_score, idx_pos = 0, None
        if batting_order and p_id in batting_order:
            idx_pos      = batting_order.index(p_id)
            lineup_score = LINEUP_TOP_BONUS if idx_pos <= 2 else (LINEUP_BOT_PENALTY if idx_pos >= 6 else 0)

        blob = prefetched.get(p_id) or {}

        # L10 form + season HRR rate
        hit_games, l10_total, l10_h_avg, l10_hrr_avg = 0, 0, 0.0, 0.0
        logs = blob.get('logs') or []
        season_hrr_pg = 0.0
        if logs:
            l10       = logs[-10:]
            l10_total = len(l10)
            hit_games = sum(1 for g in l10 if g.get('stat', {}).get('hits', 0) > 0)
            if l10_total > 0:
                l10_h_avg   = round(sum(g.get('stat', {}).get('hits', 0) for g in l10) / l10_total, 1)
                l10_hrr_avg = round(sum((g['stat'].get('hits', 0) + g['stat'].get('runs', 0) + g['stat'].get('rbi', 0)) for g in l10) / l10_total, 1)
            season_hrr_pg = round(sum((g['stat'].get('hits', 0) + g['stat'].get('runs', 0) + g['stat'].get('rbi', 0)) for g in logs) / len(logs), 2)

        overall_avg, ops_plus, babip = ".000", "N/A", ".000"
        k_pct_val, iso_val = 0.22, 0.140
        ov_data  = blob.get('ov_data') or {}
        adv_hit  = blob.get('adv_hit') or {}
        try:
            psb        = ov_data['stats'][0]['splits'][0]['stat']
            overall_avg = psb.get('avg', '.000')
            ops_plus    = calculate_ops_plus(psb, league_stats)
            babip       = adv_hit.get('babip', '.000')
        except Exception:
            pass
        try:    k_pct_val = float(adv_hit.get('strikeoutsPerPlateAppearance', 0.22) or 0.22)
        except Exception: k_pct_val = 0.22
        try:    iso_val = float(adv_hit.get('iso', 0.140) or 0.140)
        except Exception: iso_val = 0.140

        split_ops, split_pa = 0.0, 0
        sp_data   = blob.get('sp_data') or {}
        try:
            _sp = sp_data['stats'][0]['splits'][0]['stat']
            split_ops = float(_sp.get('ops', 0))
            split_pa  = int(_sp.get('plateAppearances', 0) or 0)
        except Exception:
            try:
                c_data    = fetch.get_career_splits(p_id, "hitting", split_code)
                _sp = c_data['stats'][0]['splits'][0]['stat']
                split_ops = float(_sp.get('ops', 0))
                split_pa  = int(_sp.get('plateAppearances', 0) or 0)
            except Exception:
                pass

        bvp_avg, bvp_pa = 0.0, 0
        bvp = blob.get('bvp')
        if bvp:
            bvp_avg = float(bvp.get('avg', 0) or 0)
            bvp_pa  = int(bvp.get('plateAppearances', bvp.get('atBats', 0)) or 0)

        # --- Scoring (ADDITIVE engine; BvP & splits are sample-gated) ---
        split_score = split_ops_points(split_ops, split_pa)
        bvp_bonus   = bvp_bonus_points(bvp_avg, bvp_pa)
        cons_score  = int((hit_games / 10.0) * WEIGHT_CONSISTENCY) if l10_total > 0 else 0
        hrr_score   = int(min(WEIGHT_HRR, (l10_hrr_avg / 2.5) * WEIGHT_HRR))
        penalty     = scaled_babip_penalty(babip)

        raw_score   = split_score + cons_score + hrr_score + pitcher_score + lineup_score + bvp_bonus + penalty
        total_score = min(100, max(0, raw_score))
        tier        = "🟢 Tier 1" if total_score >= TIER1_THRESHOLD else ("🟡 Tier 2" if total_score >= TIER2_THRESHOLD else "🔴 Tier 3")

        # --- MULTIPLICATIVE engine (side-by-side) ---
        l10_hit_rate = (hit_games / l10_total) if l10_total > 0 else 0.0
        mult_score, mult_tier, mult_baseline, mult_receipt = run_multiplicative_engine({
            'ops_plus': ops_plus, 'iso': iso_val, 'k_pct': k_pct_val,
            'l10_hit_rate': l10_hit_rate, 'opp_fip': opp_fip_val,
            'park_name': park_name, 'lineup_pos': idx_pos, 'babip': babip
        })

        def _tier_rank(t): return 1 if "Tier 1" in t else (2 if "Tier 2" in t else 3)
        tiers_cross   = _tier_rank(tier) != _tier_rank(mult_tier)
        t1_involved   = ("Tier 1" in tier) or ("Tier 1" in mult_tier)
        engines_disagree = tiers_cross and t1_involved

        dk_info = live_odds.get(normalize_name(name), {})

        receipt = {}
        if total_score >= TIER1_THRESHOLD:
            receipt = {
                "Consistency Score (L10 hit rate)":       cons_score,
                "HRR Score (L10 avg HRR)":                hrr_score,
                f"Split OPS vs {split_label} ({split_pa} PA)": split_score,
                "Pitcher ERA Bonus":                      pitcher_score,
                "Lineup Position Bonus":                  lineup_score,
                f"BvP History ({bvp_pa} PA)":             bvp_bonus,
                "BABIP Guardrail (scaled)":               penalty,
            }

        # --- HRR engine: projected hits+runs+RBI and P(2+) ---
        hrr_proj = project_hrr(season_hrr_pg, l10_hrr_avg, idx_pos,
                               opp_fip_val, bullpen_era, park_name)
        hrr_p2   = prob_2plus_hrr(hrr_proj)

        scan_results.append({
            "Player": name, "Player_ID": p_id, "Tier": tier, "Score": total_score,
            "Avg": overall_avg, "Raw_OPS": split_ops, "L10_HRR": l10_hrr_avg,
            "L10_Hits": l10_h_avg, "BVP_Avg": bvp_avg,
            "OPS_Display": f"{split_ops:.3f}", "OPS_Plus": ops_plus,
            "DK_Info": dk_info, "Receipt": receipt,
            "Mult_Score": mult_score, "Mult_Tier": mult_tier,
            "Mult_Baseline": mult_baseline, "Mult_Receipt": mult_receipt,
            "Disagree": engines_disagree,
            "BABIP": babip, "K_Pct": k_pct_val, "ISO": iso_val, "Opp_FIP": opp_fip_val,
            "HRR_Proj": hrr_proj, "HRR_P2": hrr_p2
        })

    return scan_results


def hitting_payload(scan_results, date_str, game_pk, opp_pitcher_name):
    """Build the Supabase predictions upsert payload from scan results.
    Shared by the app's save button and the daily auto-run."""
    return [{
        "date": date_str, "player_id": r['Player_ID'], "player_name": r['Player'],
        "game_pk": int(game_pk or 0),
        "score": r['Score'], "tier": r['Tier'], "opp_pitcher": opp_pitcher_name,
        "actual_hits": 0, "actual_hrr": 0, "graded": 0, "win": 0,
        "odds_line":  r['DK_Info'].get('line')  if r['DK_Info'] else None,
        "odds_price": r['DK_Info'].get('price') if r['DK_Info'] else None,
        "mult_score": r['Mult_Score'], "mult_tier": r['Mult_Tier'],
        "mult_baseline": r['Mult_Baseline'],
        "babip":   (float(r['BABIP']) if r['BABIP'] not in (None, '.000', '') else None),
        "k_pct":   r['K_Pct'], "iso": r['ISO'], "opp_fip": r['Opp_FIP']
    } for r in scan_results]


# ============================================================
# STRIKEOUT ENGINE — projected Ks for one pitcher
# ============================================================
def run_strikeout_engine(fetch, pitcher_id, pitcher_name, opp_team_id,
                         opp_team_name, park_name, year):
    """Returns (projected_ks, receipt_lines, meta). receipt_lines is a list of
    (label, value, description); meta is {'opener', 'data_ok', 'exp_ip'}."""
    if not pitcher_id:
        return None, [], {"opener": False, "data_ok": False, "exp_ip": 0.0}

    adv, l5_k_list, l5_avg_k, l5_avg_ip = fetch.get_pitcher_k_stats(pitcher_id, year)
    receipt = []

    # --- BASE: K/9 × stable expected innings (anchored on season IP/start) ---
    try:
        k9 = float(adv.get('strikeoutsPer9Inn', adv.get('k9', '7.5')))
    except Exception:
        k9 = 7.5
    season_gs  = adv.get('gamesStarted', 0)
    season_gp  = adv.get('gamesPlayed', 0)
    season_ip  = calc_ip(adv.get('inningsPitched', '0.0'))
    season_ips = ip_per_start(season_ip, season_gs)
    exp_ip     = expected_starter_ip(season_ip, season_gs, l5_avg_ip)
    opener     = is_likely_opener(season_ip, season_gs, season_gp)
    base_ks    = base_k_projection(k9, exp_ip)
    receipt.append(("Base K Projection (K/9 × Exp IP)", base_ks,
                    f"K/9 {k9:.1f} × Exp IP {exp_ip:.1f} (season {season_ips:.1f}/start, L5 {l5_avg_ip})"))
    if opener:
        receipt.append(("⚠ Likely opener", 0.0,
                        f"~{season_ips:.1f} IP/start — projection unreliable; the bulk pitcher gets the Ks"))

    # --- FORM: L5 trend vs K/9 baseline ---
    if l5_k_list:
        l5_k_trend = round(sum(l5_k_list) / len(l5_k_list), 1)
        form_diff  = l5_k_trend - base_ks
        form_adj   = round(max(-SK_FORM_ADJ_MAX, min(SK_FORM_ADJ_MAX, form_diff * 0.4)), 1)
        receipt.append(("L5 Form Trend", form_adj, f"L5 Avg Ks: {l5_k_trend} vs projected {base_ks}"))
    else:
        form_adj = 0.0
        receipt.append(("L5 Form Trend", 0.0, "No recent data"))

    # --- SwStr% / Swing-and-miss proxy using BB% and K% ---
    try:
        k_pct  = float(adv.get('strikeoutsPerPlateAppearance', adv.get('kPct', '0.22')))
        bb_pct = float(adv.get('walksPerPlateAppearance', adv.get('bbPct', '0.08')))
        if k_pct >= 0.28:   swstr_adj = SK_SWSTR_BONUS
        elif k_pct >= 0.24: swstr_adj = SK_SWSTR_BONUS * 0.5
        elif k_pct <= 0.17: swstr_adj = -SK_SWSTR_BONUS
        else:               swstr_adj = 0.0
        if bb_pct > 0.12:   swstr_adj -= 0.25
        receipt.append(("K% / Swing-Miss Profile", round(swstr_adj, 2), f"K%: {k_pct*100:.1f}%, BB%: {bb_pct*100:.1f}%"))
    except Exception:
        swstr_adj = 0.0
        receipt.append(("K% / Swing-Miss Profile", 0.0, "Unavailable"))

    # --- Opponent K% vs pitcher hand ---
    p_hand = fetch.get_pitcher_hand(pitcher_id)
    split_code = "vl" if p_hand == "L" else "vr"
    split_label = "LHP" if p_hand == "L" else "RHP"
    opp_splits = fetch.get_team_splits(opp_team_id, year, split_code)
    try:
        pa = int(opp_splits.get('plateAppearances', 0))
        so = int(opp_splits.get('strikeOuts', 0))
        opp_k_pct = (so / pa) if pa > 0 else 0.22
        if opp_k_pct >= 0.27:   opp_k_adj = SK_OPP_K_BONUS
        elif opp_k_pct >= 0.24: opp_k_adj = SK_OPP_K_BONUS * 0.5
        elif opp_k_pct <= 0.18: opp_k_adj = -SK_OPP_K_BONUS
        else:                    opp_k_adj = 0.0
        receipt.append((f"{opp_team_name} K% vs {split_label}", round(opp_k_adj, 2),
                         f"{opp_k_pct*100:.1f}% K rate"))
    except Exception:
        opp_k_adj = 0.0
        receipt.append((f"{opp_team_name} K% vs {split_label}", 0.0, "Unavailable"))

    # --- Opp P/PA (patient lineup = fewer Ks) ---
    try:
        opp_ppa = float(opp_splits.get('pitchesPerPlateAppearance', '3.85'))
        ppa_adj = -0.4 if opp_ppa > 4.1 else (-0.2 if opp_ppa > 3.95 else (0.3 if opp_ppa < 3.70 else 0.0))
        receipt.append((f"{opp_team_name} P/PA", round(ppa_adj, 2), f"{opp_ppa:.2f} pitches/PA"))
    except Exception:
        ppa_adj = 0.0
        receipt.append((f"{opp_team_name} P/PA", 0.0, "Unavailable"))

    # --- WHIP (command) ---
    try:
        whip = float(adv.get('whip', '1.25'))
        whip_adj = -SK_WHIP_ADJ if whip > 1.45 else (-0.25 if whip > 1.30 else (SK_WHIP_ADJ if whip < 1.10 else 0.0))
        receipt.append(("Command / WHIP", round(whip_adj, 2), f"WHIP: {whip:.2f}"))
    except Exception:
        whip_adj = 0.0
        receipt.append(("Command / WHIP", 0.0, "Unavailable"))

    # --- Park factor ---
    if park_name in HITTER_PARKS:
        park_k_adj = -SK_PARK_K_ADJ
    elif park_name in PITCHER_PARKS:
        park_k_adj = SK_PARK_K_ADJ
    else:
        park_k_adj = 0.0
    receipt.append((f"Park Factor ({park_name})", round(park_k_adj, 2), "Hitter/Pitcher park adjustment"))

    # --- FINAL ---
    total_adj   = form_adj + swstr_adj + opp_k_adj + ppa_adj + whip_adj + park_k_adj
    projected_k = round(max(0.0, base_ks + total_adj), 1)

    meta = {"opener": opener, "data_ok": (season_ip > 0 or l5_avg_ip > 0), "exp_ip": exp_ip}
    return projected_k, receipt, meta


def pitching_payload(k_projections, date_str, game_pk):
    """Build the Supabase pitcher_predictions upsert payload."""
    return [{
        "date": date_str,
        "player_id": kp["player_id"],
        "player_name": kp["player_name"],
        "game_pk": int(game_pk or 0),
        "projected_ks": kp["projected_ks"],
        "actual_ks": 0,
        "graded": 0
    } for kp in k_projections]
