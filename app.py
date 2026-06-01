import streamlit as st
import requests
import pandas as pd
import statistics
from datetime import datetime, timedelta
import dateutil.parser

# ============================================================
# PAGE CONFIG
# ============================================================
st.set_page_config(page_title="Reds Prop Dashboard", page_icon="🔴", layout="wide")

# ============================================================
# CUSTOM CSS — Dark industrial theme, red accents
# ============================================================
st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@400;600;700&family=Barlow:wght@400;500&display=swap');

    html, body, [class*="css"] {
        font-family: 'Barlow', sans-serif;
    }
    h1, h2, h3, h4 {
        font-family: 'Barlow Condensed', sans-serif;
        letter-spacing: 0.5px;
    }

    /* Player cards */
    .player-card {
        background: linear-gradient(135deg, #1a1a1a 0%, #212121 100%);
        border: 1px solid #2e2e2e;
        border-left: 5px solid #4caf50;
        border-radius: 8px;
        padding: 16px 20px;
        margin-bottom: 12px;
        position: relative;
    }
    .player-card.tier2 { border-left-color: #e6a817; }
    .player-card.tier3 { border-left-color: #C6011F; }

    .player-name {
        font-family: 'Barlow Condensed', sans-serif;
        font-size: 22px;
        font-weight: 700;
        color: #f0f0f0;
        margin: 0;
    }
    .player-score {
        font-family: 'Barlow Condensed', sans-serif;
        font-size: 28px;
        font-weight: 700;
        color: #C6011F;
    }
    .tier-badge {
        display: inline-block;
        padding: 2px 10px;
        border-radius: 20px;
        font-size: 12px;
        font-weight: 600;
        font-family: 'Barlow Condensed', sans-serif;
        letter-spacing: 1px;
        text-transform: uppercase;
    }
    .tier1-badge { background: #1a3a1a; color: #4caf50; border: 1px solid #4caf50; }
    .tier2-badge { background: #3a2e0a; color: #e6a817; border: 1px solid #e6a817; }
    .tier3-badge { background: #2a1a1a; color: #888; border: 1px solid #555; }

    .dk-badge {
        display: inline-block;
        background: #00378a;
        color: #fff;
        font-family: 'Barlow Condensed', sans-serif;
        font-size: 15px;
        font-weight: 700;
        padding: 4px 14px;
        border-radius: 5px;
        letter-spacing: 0.5px;
        margin-left: 8px;
    }
    .dk-badge.no-odds {
        background: #2e2e2e;
        color: #666;
        font-size: 12px;
    }
    .stat-row {
        font-size: 13px;
        color: #aaa;
        margin-top: 6px;
    }
    .stat-row span {
        color: #ddd;
        font-weight: 500;
    }

    /* Receipt */
    .receipt-line {
        display: flex;
        justify-content: space-between;
        font-size: 13px;
        color: #bbb;
        padding: 3px 0;
        border-bottom: 1px solid #2a2a2a;
    }
    .receipt-total {
        display: flex;
        justify-content: space-between;
        font-size: 15px;
        font-weight: 700;
        color: #C6011F;
        padding: 6px 0 0 0;
        font-family: 'Barlow Condensed', sans-serif;
    }
    .receipt-pos { color: #4caf50; }
    .receipt-neg { color: #C6011F; }
    .receipt-neu { color: #888; }

    /* Fetch button styling override */
    div[data-testid="stButton"] button[kind="primary"] {
        background-color: #C6011F !important;
        border: none !important;
        font-family: 'Barlow Condensed', sans-serif !important;
        font-size: 18px !important;
        font-weight: 700 !important;
        letter-spacing: 1px !important;
        padding: 12px 24px !important;
        width: 100% !important;
    }
    div[data-testid="stButton"] button[kind="primary"]:hover {
        background-color: #a50019 !important;
    }

    .odds-status-ok {
        background: #1a3a1a;
        border: 1px solid #4caf50;
        border-radius: 6px;
        padding: 8px 14px;
        color: #4caf50;
        font-size: 13px;
        font-family: 'Barlow Condensed', sans-serif;
        letter-spacing: 0.5px;
    }
    .odds-status-none {
        background: #2a2a2a;
        border: 1px solid #444;
        border-radius: 6px;
        padding: 8px 14px;
        color: #888;
        font-size: 13px;
        font-family: 'Barlow Condensed', sans-serif;
    }

    /* Strikeout engine */
    .k-proj {
        font-family: 'Barlow Condensed', sans-serif;
        font-size: 42px;
        font-weight: 700;
        color: #C6011F;
        line-height: 1;
    }
    .k-label {
        font-family: 'Barlow Condensed', sans-serif;
        font-size: 14px;
        color: #888;
        text-transform: uppercase;
        letter-spacing: 1px;
    }

    /* Calibration / proof layer */
    .proof-card {
        background: linear-gradient(135deg, #1a1a1a 0%, #212121 100%);
        border: 1px solid #2e2e2e;
        border-radius: 8px;
        padding: 16px 20px;
        margin-bottom: 12px;
    }
    .proof-big {
        font-family: 'Barlow Condensed', sans-serif;
        font-size: 34px;
        font-weight: 700;
        line-height: 1;
    }
    .proof-label {
        font-family: 'Barlow Condensed', sans-serif;
        font-size: 13px;
        color: #888;
        text-transform: uppercase;
        letter-spacing: 1px;
    }
    .grade-a { color: #4caf50; }
    .grade-b { color: #9acd32; }
    .grade-c { color: #e6a817; }
    .grade-d { color: #C6011F; }
    </style>
""", unsafe_allow_html=True)

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
BABIP_PENALTY        = -8   # High BABIP + hot streak guardrail
TIER1_THRESHOLD      = 75
TIER2_THRESHOLD      = 55

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
# SECRETS CONFIG
# ============================================================
try:
    SUPABASE_URL = st.secrets["SUPABASE_URL"]
    SUPABASE_KEY = st.secrets["SUPABASE_KEY"]
    DB_HEADERS = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation"
    }
    # Upsert variant: merge duplicates on conflict instead of erroring
    DB_HEADERS_UPSERT = dict(DB_HEADERS)
    DB_HEADERS_UPSERT["Prefer"] = "resolution=merge-duplicates,return=representation"
except:
    SUPABASE_URL = None
    DB_HEADERS = None
    DB_HEADERS_UPSERT = None

try:
    ODDS_API_KEY = st.secrets["ODDS_API_KEY"]
except:
    ODDS_API_KEY = None

# ============================================================
# SESSION STATE INIT
# ============================================================
if 'last_autograde_time' not in st.session_state:
    st.session_state['last_autograde_time'] = None
if 'dk_odds' not in st.session_state:
    st.session_state['dk_odds'] = {}
if 'dk_odds_date' not in st.session_state:
    st.session_state['dk_odds_date'] = None

# ============================================================
# UTILITY FUNCTIONS
# ============================================================
def calc_ip(ip_str):
    try:
        ip = str(ip_str)
        if '.' in ip:
            whole, partial = ip.split('.')
            return int(whole) + (int(partial) / 3.0)
        return int(ip)
    except:
        return 0.0

def calculate_fip(stats):
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
    except:
        return "0.00"

def normalize_name(name):
    return name.lower().replace(".", "").replace(" jr", "").replace(" sr", "").replace("-", " ").strip()

def color_val(v):
    """Return receipt CSS class based on sign of value."""
    if v > 0:   return "receipt-pos"
    if v < 0:   return "receipt-neg"
    return "receipt-neu"

def signed(v):
    return f"{v:+g}"

def american_to_decimal(price):
    """Convert American odds (e.g. -115, +120) to decimal payout multiplier."""
    try:
        price = float(price)
        if price > 0:
            return 1.0 + (price / 100.0)
        elif price < 0:
            return 1.0 + (100.0 / abs(price))
        return 1.0
    except:
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
    except:
        return 0.0

def units_won(price, won):
    """Units won/lost on a 1-unit bet given American price and W/L (1/0)."""
    if won == 1:
        return round(american_to_decimal(price) - 1.0, 3)  # net profit on win
    else:
        return -1.0  # lose the staked unit

# ============================================================
# AUTO-GRADER — 30-min guard
# ============================================================
def auto_grade_past_predictions():
    if not SUPABASE_URL:
        return
    now = datetime.now()
    last = st.session_state.get('last_autograde_time')
    if last and (now - last).total_seconds() < 1800:
        return
    st.session_state['last_autograde_time'] = now

    today_str = now.strftime("%Y-%m-%d")

    dates_to_grade = set()
    for endpoint in ["predictions", "pitcher_predictions"]:
        try:
            res = requests.get(f"{SUPABASE_URL}/rest/v1/{endpoint}?graded=eq.0&select=date", headers=DB_HEADERS)
            if res.status_code == 200 and isinstance(res.json(), list):
                dates_to_grade.update([r['date'] for r in res.json()])
        except:
            pass

    for d in dates_to_grade:
        try:
            sched_res = requests.get(f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&teamId=113&date={d}")
            if sched_res.status_code != 200:
                continue
            sched = sched_res.json()
            if sched.get('totalGames', 0) == 0:
                _mark_no_game(d)
                continue

            games = sched['dates'][0]['games']
            final_games = [g for g in games if g['status']['statusCode'] in ['F', 'O', 'CR', 'FR']]
            all_postponed = all(g['status']['statusCode'] in ['C', 'P', 'D', 'DI'] for g in games)

            if final_games:
                _grade_final_games(final_games, d, today_str)
            elif all_postponed or (d < today_str and not any(g['status']['statusCode'] in ['I', 'S', 'D', 'DI'] for g in games)):
                _mark_no_game(d)
        except:
            pass

def _mark_no_game(d):
    try:
        requests.patch(f"{SUPABASE_URL}/rest/v1/predictions?date=eq.{d}&graded=eq.0",
                       json={"graded": 1, "win": -1}, headers=DB_HEADERS)
        requests.patch(f"{SUPABASE_URL}/rest/v1/pitcher_predictions?date=eq.{d}&graded=eq.0",
                       json={"actual_ks": 0, "graded": -1}, headers=DB_HEADERS)
    except:
        pass

def _grade_final_games(final_games, d, today_str):
    all_players_dict, reds_batters_all = {}, []
    for game in final_games:
        try:
            feed = requests.get(f"https://statsapi.mlb.com/api/v1.1/game/{game['gamePk']}/feed/live").json()
            box = feed.get('liveData', {}).get('boxscore', {}).get('teams', {})
            all_players_dict.update({**box.get('away', {}).get('players', {}), **box.get('home', {}).get('players', {})})
            if feed.get('gameData', {}).get('teams', {}).get('away', {}).get('id') == 113:
                reds_batters_all.extend(box.get('away', {}).get('batters', []))
            else:
                reds_batters_all.extend(box.get('home', {}).get('batters', []))
        except:
            pass

    # Grade hitting predictions
    try:
        preds_res = requests.get(f"{SUPABASE_URL}/rest/v1/predictions?date=eq.{d}&graded=eq.0", headers=DB_HEADERS)
        if preds_res.status_code == 200 and preds_res.json():
            tier_map = {str(p['player_id']): p.get('tier', '') for p in preds_res.json()}
            requests.patch(f"{SUPABASE_URL}/rest/v1/predictions?date=eq.{d}",
                           json={"graded": 1, "win": -1}, headers=DB_HEADERS)
            for p_id in reds_batters_all:
                stats = all_players_dict.get(f"ID{p_id}", {}).get('stats', {}).get('batting', {})
                if int(stats.get('plateAppearances', 0)) > 0:
                    hits = stats.get('hits', 0)
                    hrr  = hits + stats.get('runs', 0) + stats.get('rbi', 0)
                    tier = tier_map.get(str(p_id), "")
                    win  = (1 if (hits == 0 and hrr <= 1) else 0) if "Tier 3" in tier else (1 if (hits > 0 or hrr > 1) else 0)
                    requests.patch(f"{SUPABASE_URL}/rest/v1/predictions?date=eq.{d}&player_id=eq.{p_id}",
                                   json={"actual_hits": hits, "actual_hrr": hrr, "win": win}, headers=DB_HEADERS)
    except:
        pass

    # Grade pitcher predictions — STRIKEOUTS (new K engine)
    # Legacy rows that only have projected_outs (no projected_ks) are left untouched.
    try:
        p_preds_res = requests.get(f"{SUPABASE_URL}/rest/v1/pitcher_predictions?date=eq.{d}&graded=eq.0", headers=DB_HEADERS)
        if p_preds_res.status_code == 200 and p_preds_res.json():
            for p_pred in p_preds_res.json():
                # Skip legacy outs-only rows (no K projection) — clean break
                if p_pred.get('projected_ks') is None:
                    continue
                p_id  = p_pred['player_id']
                p_key = f"ID{p_id}"
                if p_key in all_players_dict:
                    k_actual = int(all_players_dict[p_key].get('stats', {}).get('pitching', {}).get('strikeOuts', 0))
                    requests.patch(f"{SUPABASE_URL}/rest/v1/pitcher_predictions?player_id=eq.{p_id}&date=eq.{d}",
                                   json={"actual_ks": k_actual, "graded": 1}, headers=DB_HEADERS)
                else:
                    requests.patch(f"{SUPABASE_URL}/rest/v1/pitcher_predictions?player_id=eq.{p_id}&date=eq.{d}",
                                   json={"actual_ks": 0, "graded": 1}, headers=DB_HEADERS)
    except:
        pass

# ============================================================
# API HELPERS
# ============================================================
@st.cache_data(ttl=86400)
def get_league_hitting(year):
    url = f"https://statsapi.mlb.com/api/v1/sports/1/stats?stats=season&group=hitting&season={year}"
    try:
        return requests.get(url).json()['stats'][0]['splits'][0]['stat']
    except:
        return {'obp': '.315', 'slg': '.400'}

def calculate_ops_plus(player_stats, league_stats):
    try:
        if int(player_stats.get('plateAppearances', 0)) == 0: return "N/A"
        p_obp  = float(player_stats.get('obp', '.000'))
        p_slg  = float(player_stats.get('slg', '.000'))
        lg_obp = float(league_stats.get('obp', '.315'))
        lg_slg = float(league_stats.get('slg', '.400'))
        if lg_obp <= 0 or lg_slg <= 0: return "N/A"
        return str(max(0, int(round(100 * ((p_obp / lg_obp) + (p_slg / lg_slg) - 1)))))
    except:
        return "N/A"

@st.cache_data(ttl=3600)
def get_schedule(date_str):
    url = f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&teamId=113&date={date_str}&hydrate=probablePitcher"
    return requests.get(url).json()

@st.cache_data(ttl=300)
def get_game_starters(game_pk):
    url = f"https://statsapi.mlb.com/api/v1.1/game/{game_pk}/feed/live"
    try:
        res = requests.get(url).json()
        starters = {'away': {'id': None, 'name': 'TBD'}, 'home': {'id': None, 'name': 'TBD'}}
        probables = res.get('gameData', {}).get('probablePitchers', {})
        for side in ('away', 'home'):
            if side in probables:
                starters[side] = {'id': probables[side]['id'], 'name': probables[side]['fullName']}
        status = res.get('gameData', {}).get('status', {}).get('statusCode', '')
        for side in ('away', 'home'):
            if status in ['I', 'F', 'O', 'CR'] or starters[side]['name'] == 'TBD':
                pitchers_list = res.get('liveData', {}).get('boxscore', {}).get('teams', {}).get(side, {}).get('pitchers', [])
                if pitchers_list:
                    p_id   = pitchers_list[0]
                    player = res.get('gameData', {}).get('players', {}).get(f"ID{p_id}", {})
                    if player:
                        starters[side] = {'id': player.get('id'), 'name': player.get('fullName', 'TBD')}
        return starters
    except:
        return {'away': {'id': None, 'name': 'TBD'}, 'home': {'id': None, 'name': 'TBD'}}

@st.cache_data(ttl=86400)
def get_roster(team_id):
    url = f"https://statsapi.mlb.com/api/v1/teams/{team_id}/roster"
    return requests.get(url).json().get('roster', [])

@st.cache_data(ttl=3600)
def get_season_stats(player_id, group, year, split=None):
    if split:
        url = f"https://statsapi.mlb.com/api/v1/people/{player_id}/stats?stats=statSplits&group={group}&season={year}&sitCodes={split}"
    else:
        url = f"https://statsapi.mlb.com/api/v1/people/{player_id}/stats?stats=season&group={group}&season={year}"
    return requests.get(url).json()

@st.cache_data(ttl=3600)
def get_advanced_hitting(player_id, year):
    url = f"https://statsapi.mlb.com/api/v1/people/{player_id}/stats?stats=season,seasonAdvanced&group=hitting&season={year}"
    res = requests.get(url).json()
    stats = {}
    try:
        for split in res.get('stats', []):
            if split['type']['displayName'] in ['season', 'seasonAdvanced']:
                stats.update(split['splits'][0]['stat'])
    except:
        pass
    return stats

@st.cache_data(ttl=3600)
def get_advanced_pitching(player_id, year):
    url = f"https://statsapi.mlb.com/api/v1/people/{player_id}/stats?stats=season,seasonAdvanced&group=pitching&season={year}"
    res = requests.get(url).json()
    stats = {}
    try:
        for split in res.get('stats', []):
            if split['type']['displayName'] in ['season', 'seasonAdvanced']:
                stats.update(split['splits'][0]['stat'])
    except:
        pass
    return stats

@st.cache_data(ttl=3600)
def get_team_pitching(team_id, year):
    url = f"https://statsapi.mlb.com/api/v1/teams/{team_id}/stats?stats=statSplits&group=pitching&season={year}&sitCodes=rp"
    try:
        return requests.get(url).json()['stats'][0]['splits'][0]['stat']
    except:
        return {}

@st.cache_data(ttl=3600)
def get_bullpen_fatigue(team_id):
    today = datetime.now()
    start = (today - timedelta(days=3)).strftime("%Y-%m-%d")
    end   = (today - timedelta(days=1)).strftime("%Y-%m-%d")
    url   = f"https://statsapi.mlb.com/api/v1/teams/{team_id}/stats?stats=byDateRange&group=pitching&startDate={start}&endDate={end}&sitCodes=rp"
    try:
        res = requests.get(url).json()
        return calc_ip(res['stats'][0]['splits'][0]['stat'].get('inningsPitched', '0.0'))
    except:
        return 0.0

@st.cache_data(ttl=86400)
def get_career_splits(player_id, group, split_code):
    url = f"https://statsapi.mlb.com/api/v1/people/{player_id}/stats?stats=careerStatSplits&group={group}&sitCodes={split_code}"
    return requests.get(url).json()

@st.cache_data(ttl=3600)
def get_team_splits(team_id, year, split_code):
    url = f"https://statsapi.mlb.com/api/v1/teams/{team_id}/stats?stats=statSplits&group=hitting&season={year}&sitCodes={split_code}"
    try:
        return requests.get(url).json()['stats'][0]['splits'][0]['stat']
    except:
        return {}

@st.cache_data(ttl=3600)
def get_bvp_stats(batter_id, pitcher_id):
    if not pitcher_id: return None
    url = f"https://statsapi.mlb.com/api/v1/people/{batter_id}/stats?stats=vsPlayer&opposingPlayerId={pitcher_id}&group=hitting"
    try:
        return requests.get(url).json()['stats'][0]['splits'][0]['stat']
    except:
        return None

@st.cache_data(ttl=3600)
def get_game_logs(player_id, year, group="hitting"):
    url = f"https://statsapi.mlb.com/api/v1/people/{player_id}/stats?stats=gameLog&group={group}&season={year}"
    try:
        return requests.get(url).json()['stats'][0]['splits']
    except:
        return []

@st.cache_data(ttl=86400)
def get_pitcher_hand(pitcher_id):
    if not pitcher_id: return "R"
    try:
        return requests.get(f"https://statsapi.mlb.com/api/v1/people/{pitcher_id}").json()['people'][0]['pitchHand']['code']
    except:
        return "R"

@st.cache_data(ttl=3600)
def get_pitcher_k_stats(pitcher_id, year):
    """Pull all K-related metrics for strikeout engine."""
    adv = get_advanced_pitching(pitcher_id, year)
    logs = get_game_logs(pitcher_id, year, group="pitching")
    l5   = logs[-5:] if logs else []
    l5_k_list = [g.get('stat', {}).get('strikeOuts', 0) for g in l5]
    l5_ip_list = [calc_ip(g.get('stat', {}).get('inningsPitched', '0.0')) for g in l5]
    l5_avg_k  = round(sum(l5_k_list) / len(l5_k_list), 1) if l5_k_list else 0.0
    l5_avg_ip = round(sum(l5_ip_list) / len(l5_ip_list), 1) if l5_ip_list else 0.0
    return adv, l5_k_list, l5_avg_k, l5_avg_ip

# ============================================================
# ODDS API
# ============================================================
def get_draftkings_odds():
    """Fetch DraftKings batter_hits props for the REDS game only.

    Free-tier friendly: lists events (cheap), finds the Reds matchup, then
    pulls batter_hits for that ONE event. ~1 credit per fetch instead of one
    per game on the slate. Market key is 'batter_hits' (no 'player_' prefix);
    player props are only served via /events/{id}/odds, not the slate /odds.
    """
    if not ODDS_API_KEY:
        return {}

    base = "https://api.the-odds-api.com/v4/sports/baseball_mlb"
    try:
        # --- Step 1: list events (cheap, no markets) ---
        ev_res = requests.get(f"{base}/events", params={"apiKey": ODDS_API_KEY})
        if ev_res.status_code != 200:
            st.error(f"Odds API (events) failed: {ev_res.text[:200]}")
            return {}
        events = ev_res.json()
        if not events:
            st.warning("No MLB events returned by the odds provider right now.")
            return {}

        # --- Find the Reds event only ---
        reds_event_id = None
        for ev in events:
            home = ev.get('home_team', '')
            away = ev.get('away_team', '')
            if 'Reds' in home or 'Reds' in away:
                reds_event_id = ev.get('id')
                break

        if not reds_event_id:
            st.warning("No Reds game found on the odds provider's slate for today.")
            return {}

        # --- Step 2: pull batter_hits for the Reds event (1 credit) ---
        o_res = requests.get(
            f"{base}/events/{reds_event_id}/odds",
            params={
                "apiKey": ODDS_API_KEY,
                "regions": "us",
                "markets": "batter_hits",
                "bookmakers": "draftkings",
                "oddsFormat": "american",
            }
        )
        if o_res.status_code != 200:
            st.error(f"Odds API (Reds event) failed: {o_res.text[:200]}")
            return {}

        odds_dict = {}
        game = o_res.json()
        for book in game.get('bookmakers', []):
            for market in book.get('markets', []):
                if market['key'] == 'batter_hits':
                    for outcome in market.get('outcomes', []):
                        if outcome.get('name') == 'Over':
                            odds_dict[normalize_name(outcome.get('description', ''))] = {
                                'line':  outcome.get('point', 0.5),
                                'price': outcome.get('price', 0)
                            }
        if not odds_dict:
            st.warning("Found the Reds game, but no DraftKings batter-hits lines are posted yet (often not until a few hours before first pitch).")
        return odds_dict
    except Exception as e:
        st.error(f"Odds API error: {str(e)}")
        return {}

# ============================================================
# STRIKEOUT ENGINE — projected Ks for one pitcher
# ============================================================
def run_strikeout_engine(pitcher_id, pitcher_name, opp_team_id, opp_team_name, park_name, year):
    """Returns (projected_ks, receipt_lines) where receipt_lines is list of (label, value, description)."""
    if not pitcher_id:
        return None, []

    adv, l5_k_list, l5_avg_k, l5_avg_ip = get_pitcher_k_stats(pitcher_id, year)
    receipt = []

    # --- BASE: K/9 projection ---
    try:
        k9 = float(adv.get('strikeoutsPer9Inn', adv.get('k9', '7.5')))
    except:
        k9 = 7.5
    base_ks = round((k9 / 9.0) * l5_avg_ip, 1) if l5_avg_ip > 0 else round(k9 / 9.0 * 5.5, 1)
    receipt.append(("Base K Projection (K/9 × Avg IP)", base_ks, f"K/9: {k9:.1f}, Avg IP L5: {l5_avg_ip}"))

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
    except:
        swstr_adj = 0.0
        receipt.append(("K% / Swing-Miss Profile", 0.0, "Unavailable"))

    # --- Opponent K% vs pitcher hand ---
    p_hand = get_pitcher_hand(pitcher_id)
    split_code = "vl" if p_hand == "L" else "vr"
    split_label = "LHP" if p_hand == "L" else "RHP"
    opp_splits = get_team_splits(opp_team_id, year, split_code)
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
    except:
        opp_k_adj = 0.0
        receipt.append((f"{opp_team_name} K% vs {split_label}", 0.0, "Unavailable"))

    # --- Opp P/PA (patient lineup = fewer Ks) ---
    try:
        opp_ppa = float(opp_splits.get('pitchesPerPlateAppearance', '3.85'))
        ppa_adj = -0.4 if opp_ppa > 4.1 else (-0.2 if opp_ppa > 3.95 else (0.3 if opp_ppa < 3.70 else 0.0))
        receipt.append((f"{opp_team_name} P/PA", round(ppa_adj, 2), f"{opp_ppa:.2f} pitches/PA"))
    except:
        ppa_adj = 0.0
        receipt.append((f"{opp_team_name} P/PA", 0.0, "Unavailable"))

    # --- WHIP (command) ---
    try:
        whip = float(adv.get('whip', '1.25'))
        whip_adj = -SK_WHIP_ADJ if whip > 1.45 else (-0.25 if whip > 1.30 else (SK_WHIP_ADJ if whip < 1.10 else 0.0))
        receipt.append(("Command / WHIP", round(whip_adj, 2), f"WHIP: {whip:.2f}"))
    except:
        whip_adj = 0.0
        receipt.append(("Command / WHIP", 0.0, "Unavailable"))

    # --- Park factor ---
    hitter_parks  = ['Great American Ball Park', 'Coors Field', 'Fenway Park', 'Globe Life Field',
                     'American Family Field', 'Guaranteed Rate Field']
    pitcher_parks = ['T-Mobile Park', 'loanDepot park', 'Oracle Park', 'Petco Park',
                     'Kauffman Stadium', 'Truist Park']
    if park_name in hitter_parks:
        park_k_adj = -SK_PARK_K_ADJ
    elif park_name in pitcher_parks:
        park_k_adj = SK_PARK_K_ADJ
    else:
        park_k_adj = 0.0
    receipt.append((f"Park Factor ({park_name})", round(park_k_adj, 2), "Hitter/Pitcher park adjustment"))

    # --- FINAL ---
    total_adj   = form_adj + swstr_adj + opp_k_adj + ppa_adj + whip_adj + park_k_adj
    projected_k = round(max(0.0, base_ks + total_adj), 1)

    return projected_k, receipt

# ============================================================
# PLAYER CARD HTML
# ============================================================
def render_player_card(row, split_label, idx):
    tier_str = row['Tier']
    if "Tier 1" in tier_str:
        card_cls   = "player-card"
        badge_cls  = "tier1-badge"
        badge_text = "TIER 1 ✅"
    elif "Tier 2" in tier_str:
        card_cls   = "player-card tier2"
        badge_cls  = "tier2-badge"
        badge_text = "TIER 2 🟡"
    else:
        card_cls   = "player-card tier3"
        badge_cls  = "tier3-badge"
        badge_text = "TIER 3 🔴"

    dk_info = row.get('DK_Info', {})
    if dk_info:
        price_str = f"+{dk_info['price']}" if dk_info['price'] > 0 else str(dk_info['price'])
        dk_html = f'<span class="dk-badge">DK: O {dk_info["line"]} ({price_str})</span>'
    else:
        dk_html = '<span class="dk-badge no-odds">No DK Line</span>'

    bvp_display = f"{row['BVP_Avg']:.3f}" if row['BVP_Avg'] > 0 else "—"

    st.markdown(f"""
    <div class="{card_cls}">
        <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px;">
            <div style="display:flex; align-items:center; gap:12px;">
                <span class="player-score">{row['Score']}</span>
                <div>
                    <p class="player-name">#{idx} {row['Player']}</p>
                    <span class="tier-badge {badge_cls}">{badge_text}</span>
                </div>
            </div>
            <div>{dk_html}</div>
        </div>
        <div class="stat-row" style="margin-top:10px;">
            <span>OPS+</span>: {row['OPS_Plus']} &nbsp;|&nbsp;
            <span>AVG</span>: {row['Avg']} &nbsp;|&nbsp;
            <span>OPS vs {split_label}</span>: {row['OPS_Display']} &nbsp;|&nbsp;
            <span>BvP</span>: {bvp_display} &nbsp;|&nbsp;
            <span>L10 Hits/G</span>: {row['L10_Hits']} &nbsp;|&nbsp;
            <span>L10 HRR/G</span>: {row['L10_HRR']}
        </div>
    </div>
    """, unsafe_allow_html=True)

def render_receipt(row):
    """Render collapsible engine receipt for Tier 1 players."""
    receipt = row.get('Receipt', {})
    if not receipt:
        return
    with st.expander("🧾 Engine Receipt"):
        lines_html = ""
        for label, val in receipt.items():
            css = color_val(val)
            lines_html += f"""
            <div class="receipt-line">
                <span>{label}</span>
                <span class="{css}">{signed(val)}</span>
            </div>"""
        lines_html += f"""
        <div class="receipt-total">
            <span>FINAL SCORE</span>
            <span>{row['Score']}/100</span>
        </div>"""
        st.markdown(f'<div style="background:#111;border-radius:6px;padding:12px 16px;">{lines_html}</div>',
                    unsafe_allow_html=True)

# ============================================================
# EXECUTE AUTO-GRADER
# ============================================================
auto_grade_past_predictions()

# ============================================================
# SIDEBAR
# ============================================================
with st.sidebar:
    st.image("https://a.espncdn.com/i/teamlogos/mlb/500/cin.png", width=100)
    st.title("Settings")
    selected_date = st.date_input("Select Game Date", datetime.now())
    date_str      = selected_date.strftime("%Y-%m-%d")
    current_year  = selected_date.year

    data     = get_schedule(date_str)
    game_idx = 0
    if data and data.get('totalGames', 0) > 1:
        st.warning("⚾ Doubleheader Detected!")
        games_list   = data['dates'][0]['games']
        game_choices = [f"Game {i+1}" for i in range(len(games_list))]
        sel_game     = st.selectbox("Select Matchup", game_choices)
        game_idx     = game_choices.index(sel_game)

# ============================================================
# MAIN
# ============================================================
st.title("🔴 Reds Matchup & Prop Engine")

reds_pitcher_name  = "TBD"
reds_pitcher_id    = None
opp_pitcher_name   = "TBD"
opp_pitcher_id     = None
opponent           = "Unknown"
opp_team_id        = None
park_name          = "Unknown"
start_time_est     = "TBD"
is_pregame         = False

roster_res = get_roster(113)
hitters    = {p['person']['fullName']: p['person']['id'] for p in roster_res if p['position']['abbreviation'] != 'P'}
pitchers   = {p['person']['fullName']: p['person']['id'] for p in roster_res if p['position']['abbreviation'] == 'P'}

if data and data.get('totalGames', 0) > 0:
    game     = data['dates'][0]['games'][game_idx]
    game_pk  = game['gamePk']
    park_name = game.get('venue', {}).get('name', 'Unknown')

    raw_time = game.get('gameDate', '')
    if raw_time:
        try:
            utc_time       = dateutil.parser.isoparse(raw_time)
            est_time       = utc_time - timedelta(hours=4)
            start_time_est = est_time.strftime("%I:%M %p EST")
        except:
            pass

    game_status = game['status']['statusCode']
    is_pregame  = game_status in ['S', 'P', 'PW']
    starters    = get_game_starters(game_pk)
    away_team   = game['teams']['away']['team']['name']
    home_team   = game['teams']['home']['team']['name']

    if "Reds" in away_team:
        opponent, opp_team_id    = home_team, game['teams']['home']['team']['id']
        opp_pitcher_name, opp_pitcher_id   = starters['home']['name'], starters['home']['id']
        reds_pitcher_name, reds_pitcher_id = starters['away']['name'], starters['away']['id']
    else:
        opponent, opp_team_id    = away_team, game['teams']['away']['team']['id']
        opp_pitcher_name, opp_pitcher_id   = starters['away']['name'], starters['away']['id']
        reds_pitcher_name, reds_pitcher_id = starters['home']['name'], starters['home']['id']

    st.subheader(f"🏟️ Reds vs {opponent} | Venue: {park_name} | ⏰ First Pitch: {start_time_est}")

    c1, c2 = st.columns(2)
    with c1:
        if opp_pitcher_name == 'TBD':
            opp_roster   = get_roster(opp_team_id)
            opp_pitchers = {p['person']['fullName']: p['person']['id'] for p in opp_roster if p['position']['abbreviation'] == 'P'}
            if opp_pitchers:
                manual_p = st.selectbox(f"Select {opponent} Starter:", ["Select..."] + sorted(opp_pitchers.keys()))
                if manual_p != "Select...":
                    opp_pitcher_name, opp_pitcher_id = manual_p, opp_pitchers[manual_p]
    with c2:
        if reds_pitcher_name == 'TBD':
            manual_r = st.selectbox("Select Reds Starter:", ["Select..."] + sorted(pitchers.keys()))
            if manual_r != "Select...":
                reds_pitcher_name, reds_pitcher_id = manual_r, pitchers[manual_r]

    pitcher_hand        = get_pitcher_hand(opp_pitcher_id)
    split_code, split_label = ("vl", "LHP") if pitcher_hand == "L" else ("vr", "RHP")

    if opp_pitcher_name != 'TBD' and opp_pitcher_id:
        st.info(f"**Targeting Opposing Starter:** {opp_pitcher_name} ({split_label})", icon="🎯")

    st.divider()

    # --- Batting order ---
    try:
        live_feed = requests.get(f"https://statsapi.mlb.com/api/v1.1/game/{game_pk}/feed/live").json()
        boxscore  = live_feed.get('liveData', {}).get('boxscore', {}).get('teams', {})
        reds_batting_order = boxscore.get('away' if "Reds" in away_team else 'home', {}).get('battingOrder', [])
    except:
        reds_batting_order = []

    # ============================================================
    # TABS
    # ============================================================
    tab1, tab2, tab3, tab4 = st.tabs([
        "🔥 Offense Top Matchups",
        "⚡ Strikeout Engine",
        "📊 System Tracker",
        "🔍 Player Deep Dive"
    ])

    # ----------------------------------------------------------
    # TAB 1 — OFFENSIVE ENGINE
    # ----------------------------------------------------------
    with tab1:
        # --- DraftKings Fetch Button (prominent, top of tab) ---
        fetch_col, status_col = st.columns([1, 2])
        with fetch_col:
            fetch_odds = st.button("🎰 FETCH DRAFTKINGS LINES", type="primary", use_container_width=True)
        with status_col:
            if fetch_odds:
                with st.spinner("Pulling DraftKings lines..."):
                    fetched = get_draftkings_odds()
                    if fetched:
                        st.session_state['dk_odds']      = fetched
                        st.session_state['dk_odds_date'] = date_str
            dk_date = st.session_state.get('dk_odds_date')
            if dk_date == date_str and st.session_state['dk_odds']:
                st.markdown(f'<div class="odds-status-ok">✅ DraftKings lines loaded for {date_str} ({len(st.session_state["dk_odds"])} players)</div>', unsafe_allow_html=True)
            else:
                st.markdown('<div class="odds-status-none">No lines loaded — click Fetch to pull</div>', unsafe_allow_html=True)

        live_odds = st.session_state['dk_odds'] if st.session_state.get('dk_odds_date') == date_str else {}

        st.divider()

        # --- Opposing pitcher profile ---
        adv_stats, pitcher_score = {}, 0
        if opp_pitcher_id:
            st.markdown(f"### 🎯 Target Profile: {opp_pitcher_name}")
            adv_stats   = get_advanced_pitching(opp_pitcher_id, current_year)
            opp_bullpen = get_team_pitching(opp_team_id, current_year)
            if adv_stats:
                era_val      = float(adv_stats.get('era', '3.50'))
                pitcher_score = 10 if era_val >= 4.50 else (5 if era_val >= 3.50 else 0)
                fip_val      = calculate_fip(adv_stats)
                c1, c2, c3, c4, c5, c6 = st.columns(6)
                c1.metric("ERA",        adv_stats.get('era', '0.00'))
                c2.metric("WHIP",       adv_stats.get('whip', '0.00'))
                c3.metric("K/9",        adv_stats.get('strikeoutsPer9Inn', '0.00'))
                c4.metric("HR/9",       adv_stats.get('homeRunsPer9', '0.00'))
                c5.metric("FIP",        fip_val)
                c6.metric("Bullpen ERA", opp_bullpen.get('era', '0.00'))
            else:
                st.info("Advanced stats unavailable for this pitcher.")
            st.divider()

        st.markdown("### 🏆 Reds Hitting Board (100-Point Scale)")
        st.caption(f"Weights: Consistency {WEIGHT_CONSISTENCY} | HRR {WEIGHT_HRR} | Split {WEIGHT_SPLIT} | Pitcher {WEIGHT_PITCHER} | BvP {WEIGHT_BVP}")

        lineup_ready = len(reds_batting_order) > 0
        if lineup_ready: st.success("✅ Official Lineup Confirmed")
        else:            st.warning("⏳ Waiting on Official Lineup...")

        show_starters = st.checkbox("Hide bench players", value=False, disabled=not lineup_ready)

        if st.button("▶ Run Offensive Engine", type="primary"):
            if not opp_pitcher_id:
                st.error("Select pitcher first.")
            else:
                # --- Auto-fetch odds if not already loaded for this date ---
                # Guarantees fresh odds are present at save time even after a reload,
                # but reuses session odds if already fetched today (0 extra credits).
                if not (st.session_state.get('dk_odds_date') == date_str and st.session_state.get('dk_odds')):
                    with st.spinner("Auto-fetching DraftKings lines..."):
                        auto_fetched = get_draftkings_odds()
                        if auto_fetched:
                            st.session_state['dk_odds']      = auto_fetched
                            st.session_state['dk_odds_date'] = date_str
                # refresh local handle after potential auto-fetch
                live_odds = st.session_state['dk_odds'] if st.session_state.get('dk_odds_date') == date_str else {}

                pb           = st.progress(0, text="Evaluating roster...")
                scan_results = []
                league_stats = get_league_hitting(current_year)

                for i, (name, p_id) in enumerate(hitters.items()):
                    pb.progress((i + 1) / len(hitters), text=f"Analyzing {name}...")
                    lineup_score, in_lineup = 0, False
                    if reds_batting_order:
                        if p_id in reds_batting_order:
                            in_lineup    = True
                            idx_pos      = reds_batting_order.index(p_id)
                            lineup_score = LINEUP_TOP_BONUS if idx_pos <= 2 else (LINEUP_BOT_PENALTY if idx_pos >= 6 else 0)
                        if show_starters and not in_lineup:
                            continue

                    # L10 form
                    hit_games, l10_total, l10_h_avg, l10_hrr_avg = 0, 0, 0.0, 0.0
                    logs = get_game_logs(p_id, current_year)
                    if logs:
                        l10       = logs[-10:]
                        l10_total = len(l10)
                        hit_games = sum(1 for g in l10 if g.get('stat', {}).get('hits', 0) > 0)
                        if l10_total > 0:
                            l10_h_avg   = round(sum(g.get('stat', {}).get('hits', 0) for g in l10) / l10_total, 1)
                            l10_hrr_avg = round(sum((g['stat'].get('hits', 0) + g['stat'].get('runs', 0) + g['stat'].get('rbi', 0)) for g in l10) / l10_total, 1)

                    overall_avg, ops_plus, babip = ".000", "N/A", ".000"
                    ov_data  = get_season_stats(p_id, "hitting", current_year)
                    adv_hit  = get_advanced_hitting(p_id, current_year)
                    try:
                        psb        = ov_data['stats'][0]['splits'][0]['stat']
                        overall_avg = psb.get('avg', '.000')
                        ops_plus    = calculate_ops_plus(psb, league_stats)
                        babip       = adv_hit.get('babip', '.000')
                    except:
                        pass

                    split_ops = 0.0
                    sp_data   = get_season_stats(p_id, "hitting", current_year, split=split_code)
                    try:
                        split_ops = float(sp_data['stats'][0]['splits'][0]['stat'].get('ops', 0))
                    except:
                        try:
                            c_data    = get_career_splits(p_id, "hitting", split_code)
                            split_ops = float(c_data['stats'][0]['splits'][0]['stat'].get('ops', 0))
                        except:
                            pass

                    bvp_avg, bvp_bonus = 0.0, 0
                    bvp = get_bvp_stats(p_id, opp_pitcher_id)
                    if bvp:
                        bvp_avg   = float(bvp.get('avg', 0))
                        bvp_bonus = 10 if bvp_avg >= .350 else (5 if bvp_avg >= .250 else 0)

                    # --- Scoring ---
                    split_score = int(min(WEIGHT_SPLIT,      max(0, (split_ops - 0.500) * 50)))
                    cons_score  = int((hit_games / 10.0) * WEIGHT_CONSISTENCY) if l10_total > 0 else 0
                    hrr_score   = int(min(WEIGHT_HRR, (l10_hrr_avg / 2.5) * WEIGHT_HRR))
                    penalty     = 0
                    try:
                        if float(babip) > .350 and hit_games >= 6:
                            penalty = BABIP_PENALTY
                    except:
                        pass

                    raw_score   = split_score + cons_score + hrr_score + pitcher_score + lineup_score + bvp_bonus + penalty
                    total_score = min(100, max(0, raw_score))
                    tier        = "🟢 Tier 1" if total_score >= TIER1_THRESHOLD else ("🟡 Tier 2" if total_score >= TIER2_THRESHOLD else "🔴 Tier 3")

                    dk_info = live_odds.get(normalize_name(name), {})

                    # Build receipt dict for Tier 1
                    receipt = {}
                    if total_score >= TIER1_THRESHOLD:
                        receipt = {
                            f"Consistency Score (L10 hit rate)":       cons_score,
                            f"HRR Score (L10 avg HRR)":                hrr_score,
                            f"Split OPS vs {split_label}":             split_score,
                            f"Pitcher ERA Bonus":                      pitcher_score,
                            f"Lineup Position Bonus":                  lineup_score,
                            f"BvP History":                            bvp_bonus,
                            f"BABIP Guardrail":                        penalty,
                        }

                    scan_results.append({
                        "Player": name, "Player_ID": p_id, "Tier": tier, "Score": total_score,
                        "Avg": overall_avg, "Raw_OPS": split_ops, "L10_HRR": l10_hrr_avg,
                        "L10_Hits": l10_h_avg, "BVP_Avg": bvp_avg,
                        "OPS_Display": f"{split_ops:.3f}", "OPS_Plus": ops_plus,
                        "DK_Info": dk_info, "Receipt": receipt
                    })

                pb.empty()

                # --- Save to Supabase (UPSERT w/ odds at pick time) ---
                if SUPABASE_URL:
                    if is_pregame:
                        insert_data = [{
                            "date": date_str, "player_id": r['Player_ID'], "player_name": r['Player'],
                            "score": r['Score'], "tier": r['Tier'], "opp_pitcher": opp_pitcher_name,
                            "actual_hits": 0, "actual_hrr": 0, "graded": 0, "win": 0,
                            "odds_line":  r['DK_Info'].get('line')  if r['DK_Info'] else None,
                            "odds_price": r['DK_Info'].get('price') if r['DK_Info'] else None
                        } for r in scan_results]
                        # merge-duplicates upsert relies on UNIQUE (date, player_id)
                        save_res = requests.post(
                            f"{SUPABASE_URL}/rest/v1/predictions?on_conflict=date,player_id",
                            json=insert_data, headers=DB_HEADERS_UPSERT
                        )
                        if save_res.status_code in (200, 201):
                            odds_count = sum(1 for r in scan_results if r['DK_Info'])
                            st.success(f"💾 Saved {len(insert_data)} predictions ({odds_count} with DK odds locked in).")
                        else:
                            st.warning(f"⚠️ Save issue: {save_res.status_code} — {save_res.text[:140]}")
                    else:
                        st.warning("⚠️ Game has already started. Predictions not saved.")

                # --- Render cards ---
                if scan_results:
                    df = pd.DataFrame(scan_results).sort_values(by=['Score', 'Raw_OPS'], ascending=False)
                    for idx_c, (_, row) in enumerate(df.iterrows(), start=1):
                        render_player_card(row, split_label, idx_c)
                        if "Tier 1" in row['Tier']:
                            render_receipt(row)

    # ----------------------------------------------------------
    # TAB 2 — STRIKEOUT ENGINE
    # ----------------------------------------------------------
    with tab2:
        st.markdown("### ⚡ Strikeout Engine")
        st.caption("Projected Ks for both starters. Analytics: K/9 × IP projection, L5 trend, K%/SwStr proxy, opp K%, P/PA, WHIP, park factor.")

        r_pitchers = sorted(pitchers.keys())
        def_idx    = r_pitchers.index(reds_pitcher_name) if reds_pitcher_name in r_pitchers else 0

        k_c1, k_c2 = st.columns(2)

        with k_c1:
            st.markdown(f"#### 🔴 Reds Starter")
            reds_k_pitcher = st.selectbox("Select Reds Pitcher", r_pitchers, index=def_idx, key="k_reds_sel")
            reds_k_id      = pitchers[reds_k_pitcher]

        with k_c2:
            st.markdown(f"#### ⚪ {opponent} Starter")
            if opp_pitcher_name != 'TBD' and opp_pitcher_id:
                st.info(f"**{opp_pitcher_name}** (auto-loaded)")
                opp_k_name = opp_pitcher_name
                opp_k_id   = opp_pitcher_id
            else:
                opp_roster_k   = get_roster(opp_team_id) if opp_team_id else []
                opp_pitchers_k = {p['person']['fullName']: p['person']['id'] for p in opp_roster_k if p['position']['abbreviation'] == 'P'}
                if opp_pitchers_k:
                    manual_opp_k = st.selectbox(f"Select {opponent} Pitcher", ["Select..."] + sorted(opp_pitchers_k.keys()), key="k_opp_sel")
                    opp_k_name   = manual_opp_k if manual_opp_k != "Select..." else "TBD"
                    opp_k_id     = opp_pitchers_k.get(manual_opp_k) if manual_opp_k != "Select..." else None
                else:
                    opp_k_name, opp_k_id = "TBD", None

        st.divider()

        if st.button("▶ Run Strikeout Engine", type="primary"):
            col_reds, col_opp = st.columns(2)
            k_projections = []  # collect for Supabase save

            with col_reds:
                with st.spinner(f"Projecting {reds_k_pitcher}..."):
                    r_proj_k, r_receipt = run_strikeout_engine(
                        reds_k_id, reds_k_pitcher, opp_team_id, opponent, park_name, current_year
                    )
                if r_proj_k is not None:
                    st.markdown(f'<div class="k-label">PROJECTED STRIKEOUTS</div><div class="k-proj">{r_proj_k}</div>', unsafe_allow_html=True)
                    st.divider()
                    st.markdown(f"#### 🧾 Engine Receipt: {reds_k_pitcher}")
                    receipt_html = ""
                    for label, val, detail in r_receipt:
                        css = color_val(val)
                        receipt_html += f"""
                        <div class="receipt-line">
                            <span>{label} <small style="color:#555;">({detail})</small></span>
                            <span class="{css}">{signed(val)}</span>
                        </div>"""
                    receipt_html += f"""
                    <div class="receipt-total">
                        <span>PROJECTED Ks</span>
                        <span>{r_proj_k}</span>
                    </div>"""
                    st.markdown(f'<div style="background:#111;border-radius:6px;padding:12px 16px;">{receipt_html}</div>', unsafe_allow_html=True)

                    k_projections.append({"player_id": reds_k_id, "player_name": reds_k_pitcher, "projected_ks": r_proj_k})

                    # L5 log
                    st.markdown("#### 📋 Last 5 Starts")
                    p_logs = get_game_logs(reds_k_id, current_year, group="pitching")
                    if p_logs:
                        log_data = []
                        for g in reversed(p_logs[-5:]):
                            s = g.get('stat', {})
                            log_data.append({
                                "Date": g.get('date', ''),
                                "Opp":  g.get('opponent', {}).get('name', ''),
                                "IP":   s.get('inningsPitched', '0.0'),
                                "K":    s.get('strikeOuts', 0),
                                "Pitches": s.get('numberOfPitches', 0)
                            })
                        st.dataframe(pd.DataFrame(log_data), hide_index=True, use_container_width=True)
                else:
                    st.info("No data available.")

            with col_opp:
                if opp_k_id:
                    with st.spinner(f"Projecting {opp_k_name}..."):
                        o_proj_k, o_receipt = run_strikeout_engine(
                            opp_k_id, opp_k_name, 113, "Cincinnati Reds", park_name, current_year
                        )
                    if o_proj_k is not None:
                        st.markdown(f'<div class="k-label">PROJECTED STRIKEOUTS</div><div class="k-proj">{o_proj_k}</div>', unsafe_allow_html=True)
                        st.divider()
                        st.markdown(f"#### 🧾 Engine Receipt: {opp_k_name}")
                        receipt_html = ""
                        for label, val, detail in o_receipt:
                            css = color_val(val)
                            receipt_html += f"""
                            <div class="receipt-line">
                                <span>{label} <small style="color:#555;">({detail})</small></span>
                                <span class="{css}">{signed(val)}</span>
                            </div>"""
                        receipt_html += f"""
                        <div class="receipt-total">
                            <span>PROJECTED Ks</span>
                            <span>{o_proj_k}</span>
                        </div>"""
                        st.markdown(f'<div style="background:#111;border-radius:6px;padding:12px 16px;">{receipt_html}</div>', unsafe_allow_html=True)

                        k_projections.append({"player_id": opp_k_id, "player_name": opp_k_name, "projected_ks": o_proj_k})

                        st.markdown("#### 📋 Last 5 Starts")
                        p_logs_opp = get_game_logs(opp_k_id, current_year, group="pitching")
                        if p_logs_opp:
                            log_data_opp = []
                            for g in reversed(p_logs_opp[-5:]):
                                s = g.get('stat', {})
                                log_data_opp.append({
                                    "Date": g.get('date', ''),
                                    "Opp":  g.get('opponent', {}).get('name', ''),
                                    "IP":   s.get('inningsPitched', '0.0'),
                                    "K":    s.get('strikeOuts', 0),
                                    "Pitches": s.get('numberOfPitches', 0)
                                })
                            st.dataframe(pd.DataFrame(log_data_opp), hide_index=True, use_container_width=True)
                else:
                    st.info(f"Select {opponent} pitcher to run engine.")

            # --- Save K projections to Supabase (pregame only) ---
            if SUPABASE_URL and k_projections:
                if is_pregame:
                    payload = [{
                        "date": date_str,
                        "player_id": kp["player_id"],
                        "player_name": kp["player_name"],
                        "projected_ks": kp["projected_ks"],
                        "actual_ks": 0,
                        "graded": 0
                    } for kp in k_projections]
                    ksave = requests.post(
                        f"{SUPABASE_URL}/rest/v1/pitcher_predictions?on_conflict=date,player_id",
                        json=payload, headers=DB_HEADERS_UPSERT
                    )
                    if ksave.status_code in (200, 201):
                        st.success(f"💾 Saved {len(payload)} K projection(s) — will auto-grade after the game.")
                    else:
                        st.warning(f"⚠️ K save issue: {ksave.status_code} — {ksave.text[:140]}")
                else:
                    st.info("ℹ️ Game already started — K projections shown but not saved.")

    # ----------------------------------------------------------
    # TAB 3 — SYSTEM TRACKER (+ Proof Layer: Calibration, Brier, ROI)
    # ----------------------------------------------------------
    with tab3:
        st.markdown("### 📊 Engine Performance")
        hit_tab, pitch_tab = st.tabs(["🔥 Hitting Tracker", "⚾ Pitching Tracker"])

        if SUPABASE_URL:
            with hit_tab:
                @st.cache_data(ttl=300)
                def load_hitting_predictions():
                    res = requests.get(f"{SUPABASE_URL}/rest/v1/predictions", headers=DB_HEADERS)
                    return res.json() if res.status_code == 200 else []

                raw = load_hitting_predictions()
                if raw:
                    df_track  = pd.DataFrame(raw)
                    df_active = df_track[(df_track['graded'] == 1) & (df_track['win'] != -1)].copy()

                    if not df_active.empty:
                        df_active['date_obj'] = pd.to_datetime(df_active['date'])

                        def calc_points(row):
                            if row['win'] == 1:
                                return 3 if "Tier 1" in row['tier'] else (2 if "Tier 2" in row['tier'] else 1)
                            else:
                                return -3 if "Tier 1" in row['tier'] else (-2 if "Tier 2" in row['tier'] else 0)

                        df_active['points']  = df_active.apply(calc_points, axis=1)
                        total_wins  = df_active['win'].sum()
                        win_rate    = (total_wins / len(df_active)) * 100
                        sys_score   = df_active['points'].sum()

                        # ============================================
                        # PROOF LAYER — Tier 1 only (the bets actually placed)
                        # ============================================
                        st.markdown("#### 🔬 Engine Proof Layer")
                        st.caption("Measured on TIER 1 plays only — the tier you actually bet.")

                        df_t1 = df_active[df_active['tier'].str.contains("Tier 1", na=False)].copy()

                        # --- Brier score (Tier 1, straight bets: model_prob = score/100) ---
                        if not df_t1.empty:
                            df_t1['model_prob'] = df_t1['score'] / 100.0
                            df_t1['brier']      = (df_t1['model_prob'] - df_t1['win']) ** 2
                            brier = df_t1['brier'].mean()
                            if   brier <= 0.17: b_grade, b_cls = "A", "grade-a"
                            elif brier <= 0.21: b_grade, b_cls = "B", "grade-b"
                            elif brier <= 0.25: b_grade, b_cls = "C", "grade-c"
                            else:               b_grade, b_cls = "D", "grade-d"
                            brier_sub = f"{brier:.3f} &nbsp; (0.25 = coin flip) · {len(df_t1)} T1 plays"
                        else:
                            b_grade, b_cls, brier_sub = "—", "receipt-neu", "No graded Tier 1 plays yet"

                        # --- ROI / units (Tier 1 with stored odds) ---
                        roi_txt, units_txt = "N/A (no odds yet)", "—"
                        t1_odds = df_t1.dropna(subset=['odds_price']) if ('odds_price' in df_t1.columns and not df_t1.empty) else pd.DataFrame()
                        if not t1_odds.empty:
                            t1_odds = t1_odds.copy()
                            t1_odds['units'] = t1_odds.apply(lambda r: units_won(r['odds_price'], r['win']), axis=1)
                            total_units = t1_odds['units'].sum()
                            roi_pct     = (total_units / len(t1_odds)) * 100
                            units_txt   = f"{total_units:+.2f} U"
                            roi_txt     = f"{roi_pct:+.1f}%"

                        pc1, pc2, pc3 = st.columns(3)
                        with pc1:
                            st.markdown(f'<div class="proof-card"><div class="proof-label">T1 Calibration Grade (Brier)</div>'
                                        f'<div class="proof-big {b_cls}">{b_grade}</div>'
                                        f'<div class="proof-label">{brier_sub}</div></div>',
                                        unsafe_allow_html=True)
                        with pc2:
                            st.markdown(f'<div class="proof-card"><div class="proof-label">T1 ROI (graded, w/ odds)</div>'
                                        f'<div class="proof-big">{roi_txt}</div>'
                                        f'<div class="proof-label">{len(t1_odds)} priced T1 bets</div></div>',
                                        unsafe_allow_html=True)
                        with pc3:
                            st.markdown(f'<div class="proof-card"><div class="proof-label">T1 Net Units</div>'
                                        f'<div class="proof-big">{units_txt}</div>'
                                        f'<div class="proof-label">1U flat stake</div></div>',
                                        unsafe_allow_html=True)

                        st.divider()

                        # --- CALIBRATION CHART: score bucket vs actual hit rate (straight tiers) ---
                        st.markdown("#### 🎯 Calibration: Predicted Score vs Actual Hit Rate")
                        st.caption("All straight tiers (1 & 2), bucketed by score. If the engine works, hit rate should climb as score climbs.")
                        df_straight = df_active[~df_active['tier'].str.contains("Tier 3", na=False)].copy()
                        if not df_straight.empty:
                            bins   = [0, 55, 65, 75, 85, 101]
                            labels = ["<55", "55-64", "65-74", "75-84", "85+"]
                            df_straight['bucket'] = pd.cut(df_straight['score'], bins=bins, labels=labels, right=False)
                            calib = df_straight.groupby('bucket', observed=True)['win'].agg(['mean', 'count']).reset_index()
                            calib['Hit Rate %'] = (calib['mean'] * 100).round(1)
                            calib = calib.rename(columns={'bucket': 'Score Bucket', 'count': 'Plays'})
                            st.bar_chart(calib.set_index('Score Bucket')['Hit Rate %'])
                            st.dataframe(calib[['Score Bucket', 'Hit Rate %', 'Plays']], hide_index=True, use_container_width=True)
                        else:
                            st.info("Need graded Tier 1/2 plays to build calibration.")

                        st.divider()

                        # --- Tier metrics ---
                        st.markdown("#### 🏅 Tier Performance & Units")
                        t1_active = df_active[df_active['tier'].str.contains("Tier 1")]
                        t1_units  = t1_active['win'].apply(lambda x: 1 if x == 1 else -1).sum() if not t1_active.empty else 0
                        tier_grp  = df_active.groupby('tier')['win'].agg(['count', 'mean']).reset_index()
                        top_cols  = st.columns(len(tier_grp) + 1)
                        top_cols[0].metric("🥇 T1 Units", f"{t1_units:+g} U")
                        for i, r in tier_grp.iterrows():
                            top_cols[i + 1].metric(r['tier'], f"{r['mean']*100:.1f}%", f"{int(r['count'])} plays")

                        st.divider()

                        # --- Win % Chart ---
                        st.markdown("#### 📈 Rolling Win % Over Time")
                        df_chart = (
                            df_active.sort_values('date_obj')
                            .groupby('date_obj')['win']
                            .mean()
                            .reset_index()
                        )
                        df_chart.columns = ['Date', 'Win %']
                        df_chart['Win %'] = (df_chart['Win %'] * 100).round(1)
                        df_chart['Rolling Win %'] = df_chart['Win %'].rolling(window=5, min_periods=1).mean().round(1)
                        st.line_chart(df_chart.set_index('Date')[['Win %', 'Rolling Win %']])

                        st.divider()

                        l7_date     = df_active['date_obj'].max() - pd.Timedelta(days=7)
                        df_l7       = df_active[df_active['date_obj'] >= l7_date]
                        l7_win_rate = (df_l7['win'].sum() / len(df_l7)) * 100 if not df_l7.empty else 0.0
                        with st.expander("📊 Overall System Metrics"):
                            c1, c2, c3 = st.columns(3)
                            c1.metric("Overall Win %", f"{win_rate:.1f}%")
                            c2.metric("L7 Win %",      f"{l7_win_rate:.1f}%")
                            c3.metric("System Score",  f"{sys_score:g}")

                        st.markdown("#### Recent Graded Logs")
                        cols_show = ['date', 'player_name', 'score', 'tier', 'opp_pitcher', 'actual_hits', 'win']
                        if 'odds_line' in df_active.columns:
                            cols_show.insert(4, 'odds_line')
                        df_display = df_active[cols_show].sort_values(by='date', ascending=False).copy()
                        df_display['Result'] = df_display['win'].apply(lambda x: "✅ WIN" if x == 1 else "❌ LOSS")
                        st.dataframe(df_display.drop(columns=['win']), hide_index=True, use_container_width=True)
                    else:
                        st.info("No graded hitting predictions yet.")

            with pitch_tab:
                @st.cache_data(ttl=300)
                def load_pitching_predictions():
                    res = requests.get(f"{SUPABASE_URL}/rest/v1/pitcher_predictions", headers=DB_HEADERS)
                    return res.json() if res.status_code == 200 else []

                p_raw = load_pitching_predictions()
                if p_raw:
                    df_ptrack  = pd.DataFrame(p_raw)
                    # Only K-engine rows (have projected_ks); legacy outs rows ignored
                    if 'projected_ks' in df_ptrack.columns:
                        df_ptrack = df_ptrack[df_ptrack['projected_ks'].notna()]
                    df_pactive = df_ptrack[df_ptrack['graded'] == 1].copy() if not df_ptrack.empty else pd.DataFrame()
                    df_pending = df_ptrack[df_ptrack['graded'] == 0].copy() if not df_ptrack.empty else pd.DataFrame()

                    if not df_pactive.empty:
                        df_pactive['delta']    = df_pactive['actual_ks'] - df_pactive['projected_ks']
                        df_pactive['abs_miss'] = df_pactive['delta'].abs()
                        m1, m2 = st.columns(2)
                        m1.metric("Avg Miss", f"{df_pactive['abs_miss'].mean():.1f} Ks")
                        m2.metric("Bias", f"{df_pactive['delta'].mean():+.1f} Ks",
                                  help="Positive = pitchers strike out more than projected (engine runs low)")
                        st.divider()
                        df_pdisplay = df_pactive[['date', 'player_name', 'projected_ks', 'actual_ks', 'delta']].sort_values(by='date', ascending=False).copy()
                        df_pdisplay['delta'] = df_pdisplay['delta'].apply(lambda x: f"{x:+.1f}")
                        st.dataframe(df_pdisplay, hide_index=True, use_container_width=True)
                    else:
                        st.info("No graded K projections yet.")

                    if not df_pending.empty:
                        st.markdown("#### ⏳ Pending K Projections")
                        st.dataframe(df_pending[['date', 'player_name', 'projected_ks']], hide_index=True, use_container_width=True)
                else:
                    st.info("No pitcher predictions yet.")

    # ----------------------------------------------------------
    # TAB 4 — DEEP DIVE (unchanged)
    # ----------------------------------------------------------
    with tab4:
        st.markdown("### 🔍 Batter Deep Dive")
        red_hitters = sorted(hitters.keys())
        sel_hitter  = st.selectbox("Select Reds Batter", red_hitters)
        h_id        = hitters[sel_hitter]
        adv_hit     = get_advanced_hitting(h_id, current_year)
        ov_hit      = get_season_stats(h_id, "hitting", current_year)
        league_stats = get_league_hitting(current_year)

        ops_plus = "N/A"
        try:
            ops_plus = calculate_ops_plus(ov_hit['stats'][0]['splits'][0]['stat'], league_stats)
        except:
            pass

        if adv_hit:
            st.markdown("#### Advanced Metrics")
            c1, c2, c3, c4, c5 = st.columns(5)
            c1.metric("OPS+",  ops_plus)
            c2.metric("BABIP", adv_hit.get('babip', '.000'))
            c3.metric("ISO",   adv_hit.get('iso', '.000'))
            try:    c4.metric("K%",  f"{float(adv_hit.get('strikeoutsPerPlateAppearance', 0))*100:.1f}%")
            except: c4.metric("K%",  "N/A")
            try:    c5.metric("BB%", f"{float(adv_hit.get('walksPerPlateAppearance', 0))*100:.1f}%")
            except: c5.metric("BB%", "N/A")
            st.divider()

        c_l, c_r = st.columns(2)
        with c_l:
            st.markdown("#### vs LHP")
            try:
                s = get_season_stats(h_id, "hitting", current_year, split="vl")['stats'][0]['splits'][0]['stat']
                st.markdown(f"**AVG:** {s.get('avg', '.000')} | **OPS:** {s.get('ops', '.000')} | **HR:** {s.get('homeRuns', 0)}")
            except:
                st.info("No stats vs LHP.")
        with c_r:
            st.markdown("#### vs RHP")
            try:
                s = get_season_stats(h_id, "hitting", current_year, split="vr")['stats'][0]['splits'][0]['stat']
                st.markdown(f"**AVG:** {s.get('avg', '.000')} | **OPS:** {s.get('ops', '.000')} | **HR:** {s.get('homeRuns', 0)}")
            except:
                st.info("No stats vs RHP.")

        st.divider()
        st.markdown("#### Last 10 Games")
        logs = get_game_logs(h_id, current_year)
        if logs:
            l10_list = []
            for l in logs[-10:]:
                s = l.get('stat', {})
                l10_list.append({
                    "Date": l.get('date', ''),
                    "Opp":  l.get('opponent', {}).get('name', ''),
                    "Hits": s.get('hits', 0),
                    "HR":   s.get('homeRuns', 0),
                    "K":    s.get('strikeOuts', 0)
                })
            st.dataframe(pd.DataFrame(l10_list).sort_values(by="Date", ascending=False),
                         hide_index=True, use_container_width=True)

else:
    st.warning("🌴 **OFF DAY:** The Reds are resting today.")
