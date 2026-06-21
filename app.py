import streamlit as st
import requests
import pandas as pd
import html
import json
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import dateutil.parser

# Pure scoring / odds / stat math (no Streamlit) — also used by tests & backtest
from engine import *  # noqa: F401,F403

# Analytics helpers live in backtest.py. Import defensively: during a Streamlit
# Cloud redeploy the new app.py can momentarily run against a cached older
# backtest.py, and a hard `from backtest import ...` would crash the ENTIRE app
# at startup. With this guard, a brief version skew just hides the recap /
# scoreboard (they no-op to None) until the deploy settles, instead of taking
# the whole dashboard down.
try:
    from backtest import (last_game_recap, season_scoreboard, scoreboard_verdict,
                          k_engine_summary, BREAKEVEN_WIN_RATE, MIN_PRICED_FOR_ROI)
except Exception:  # stale/old backtest.py during a deploy
    def last_game_recap(*a, **k): return None
    def season_scoreboard(*a, **k): return None
    def scoreboard_verdict(*a, **k): return None
    def k_engine_summary(*a, **k): return {"n": 0, "avg_miss": 0.0, "bias": 0.0}
    BREAKEVEN_WIN_RATE = 0.524
    MIN_PRICED_FOR_ROI = 20

try:
    from lock import select_locks
except Exception:
    def select_locks(*a, **k): return (None, [])

# Streamlit ScriptRunContext lets cached fetchers run inside worker threads
# without spamming "missing ScriptRunContext" warnings. Degrade gracefully if
# the internal API moves between Streamlit versions.
try:
    from streamlit.runtime.scriptrunner import add_script_run_ctx, get_script_run_ctx
except Exception:  # pragma: no cover
    add_script_run_ctx = get_script_run_ctx = None

# ============================================================
# TIME / HTTP HELPERS
# ============================================================
EASTERN = ZoneInfo("America/New_York")
HTTP_TIMEOUT = 10  # seconds — guard against hung MLB/Supabase/Odds calls

def now_eastern():
    """Current time in US Eastern (handles EST/EDT automatically)."""
    return datetime.now(EASTERN)

def http_get(url, **kwargs):
    kwargs.setdefault("timeout", HTTP_TIMEOUT)
    return requests.get(url, **kwargs)

def http_post(url, **kwargs):
    kwargs.setdefault("timeout", HTTP_TIMEOUT)
    return requests.post(url, **kwargs)

def http_patch(url, **kwargs):
    kwargs.setdefault("timeout", HTTP_TIMEOUT)
    return requests.patch(url, **kwargs)

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

    /* Dual-engine display */
    .mult-chip {
        display: inline-block;
        background: #14233a;
        border: 1px solid #2d4a6b;
        color: #7fb3ff;
        font-family: 'Barlow Condensed', sans-serif;
        font-size: 13px;
        font-weight: 600;
        padding: 2px 10px;
        border-radius: 14px;
        letter-spacing: 0.5px;
        margin-left: 8px;
    }
    .disagree-flag {
        display: inline-block;
        background: #3a2e0a;
        border: 1px solid #e6a817;
        color: #e6a817;
        font-family: 'Barlow Condensed', sans-serif;
        font-size: 11px;
        font-weight: 700;
        padding: 2px 8px;
        border-radius: 14px;
        letter-spacing: 1px;
        text-transform: uppercase;
        margin-left: 8px;
    }
    </style>
""", unsafe_allow_html=True)

# Scoring weights, park lists, and engine constants now live in engine.py
# (imported above) so they can be unit-tested and swept in the backtest.

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
except Exception:
    SUPABASE_URL = None
    DB_HEADERS = None
    DB_HEADERS_UPSERT = None

try:
    ODDS_API_KEY = st.secrets["ODDS_API_KEY"]
except Exception:
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
# UTILITY FUNCTIONS (UI-only; the stat/odds math lives in engine.py)
# ============================================================
def color_val(v):
    """Return receipt CSS class based on sign of value."""
    if v > 0:   return "receipt-pos"
    if v < 0:   return "receipt-neg"
    return "receipt-neu"

def signed(v):
    return f"{v:+g}"

# ============================================================
# AUTO-GRADER — 30-min guard
# ============================================================
def auto_grade_past_predictions():
    if not SUPABASE_URL:
        return
    now = now_eastern()
    last = st.session_state.get('last_autograde_time')
    if last and (now - last).total_seconds() < 1800:
        return
    st.session_state['last_autograde_time'] = now

    today_str = now.strftime("%Y-%m-%d")

    dates_to_grade = set()
    for endpoint in ["predictions", "pitcher_predictions"]:
        try:
            res = http_get(f"{SUPABASE_URL}/rest/v1/{endpoint}?graded=eq.0&select=date", headers=DB_HEADERS)
            if res.status_code == 200 and isinstance(res.json(), list):
                dates_to_grade.update([r['date'] for r in res.json()])
        except Exception:
            pass

    for d in dates_to_grade:
        try:
            sched_res = http_get(f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&teamId=113&date={d}")
            if sched_res.status_code != 200:
                continue
            sched = sched_res.json()
            if sched.get('totalGames', 0) == 0:
                _mark_no_game(d)
                continue

            games = sched['dates'][0]['games']
            # A game is gradable when MLB flags it Final — use abstractGameState
            # (robust) and fall back to known final status codes. Relying only on
            # a hardcoded code list mislabeled real finals as "no game".
            def _is_final(g):
                s = g.get('status', {})
                return (s.get('abstractGameState') == 'Final'
                        or s.get('codedGameState') in ('F', 'O')
                        or s.get('statusCode') in ('F', 'O', 'CR', 'FR'))
            final_games = [g for g in games if _is_final(g)]
            all_postponed = all(g['status'].get('statusCode') in ('C', 'P', 'D', 'DI') for g in games)

            if final_games:
                _grade_final_games(final_games, d, today_str)
            elif all_postponed or (d < today_str and not any(g['status'].get('statusCode') in ('I', 'S', 'D', 'DI') for g in games)):
                _mark_no_game(d)
        except Exception:
            pass

def _mark_no_game(d):
    try:
        http_patch(f"{SUPABASE_URL}/rest/v1/predictions?date=eq.{d}&graded=eq.0",
                       json={"graded": 1, "win": -1}, headers=DB_HEADERS)
        http_patch(f"{SUPABASE_URL}/rest/v1/pitcher_predictions?date=eq.{d}&graded=eq.0",
                       json={"actual_ks": 0, "graded": -1}, headers=DB_HEADERS)
    except Exception:
        pass

def _grade_final_games(final_games, d, today_str):
    # Build a per-game lookup: game_pk -> (players_dict, reds_batters)
    # Also build a pooled fallback for legacy rows that have no game_pk.
    per_game = {}
    pooled_players, pooled_batters = {}, []
    for game in final_games:
        gpk = game.get('gamePk')
        try:
            feed = http_get(f"https://statsapi.mlb.com/api/v1.1/game/{game['gamePk']}/feed/live").json()
            box = feed.get('liveData', {}).get('boxscore', {}).get('teams', {})
            players = {**box.get('away', {}).get('players', {}), **box.get('home', {}).get('players', {})}
            if feed.get('gameData', {}).get('teams', {}).get('away', {}).get('id') == 113:
                batters = box.get('away', {}).get('batters', [])
            else:
                batters = box.get('home', {}).get('batters', [])
            per_game[gpk] = (players, batters)
            pooled_players.update(players)
            pooled_batters.extend(batters)
        except Exception:
            pass

    def _grade_hit_row(p_row, players_dict):
        p_id = p_row['player_id']
        tier = p_row.get('tier', '')
        stats = players_dict.get(f"ID{p_id}", {}).get('stats', {}).get('batting', {})
        if int(stats.get('plateAppearances', 0)) > 0:
            hits = stats.get('hits', 0)
            hrr  = hits + stats.get('runs', 0) + stats.get('rbi', 0)
            win  = (1 if (hits == 0 and hrr <= 1) else 0) if "Tier 3" in tier else (1 if (hits > 0 or hrr > 1) else 0)
            return {"actual_hits": hits, "actual_hrr": hrr, "win": win, "graded": 1}
        return None

    # ---- Grade hitting predictions, per game_pk ----
    try:
        preds_res = http_get(f"{SUPABASE_URL}/rest/v1/predictions?date=eq.{d}&graded=eq.0", headers=DB_HEADERS)
        if preds_res.status_code == 200 and preds_res.json():
            rows = preds_res.json()
            # default everything to no-result first (win=-1); real results overwrite
            http_patch(f"{SUPABASE_URL}/rest/v1/predictions?date=eq.{d}&graded=eq.0",
                           json={"graded": 1, "win": -1}, headers=DB_HEADERS)
            for p_row in rows:
                gpk = p_row.get('game_pk')
                # Pick the right box score: this game if tagged, else pooled (legacy)
                if gpk is not None and gpk in per_game:
                    players_dict, _ = per_game[gpk]
                else:
                    players_dict = pooled_players
                patch = _grade_hit_row(p_row, players_dict)
                if patch:
                    # Scope the update to the exact row (date+player+game_pk if present)
                    q = f"date=eq.{d}&player_id=eq.{p_row['player_id']}"
                    if gpk is not None:
                        q += f"&game_pk=eq.{gpk}"
                    http_patch(f"{SUPABASE_URL}/rest/v1/predictions?{q}",
                                   json=patch, headers=DB_HEADERS)
    except Exception:
        pass

    # ---- Grade pitcher predictions (strikeouts), per game_pk ----
    try:
        p_preds_res = http_get(f"{SUPABASE_URL}/rest/v1/pitcher_predictions?date=eq.{d}&graded=eq.0", headers=DB_HEADERS)
        if p_preds_res.status_code == 200 and p_preds_res.json():
            for p_pred in p_preds_res.json():
                if p_pred.get('projected_ks') is None:
                    continue  # legacy outs-only row, skip
                p_id = p_pred['player_id']
                gpk  = p_pred.get('game_pk')
                if gpk is not None and gpk in per_game:
                    players_dict, _ = per_game[gpk]
                else:
                    players_dict = pooled_players
                p_key = f"ID{p_id}"
                k_actual = int(players_dict.get(p_key, {}).get('stats', {}).get('pitching', {}).get('strikeOuts', 0)) if p_key in players_dict else 0
                q = f"player_id=eq.{p_id}&date=eq.{d}"
                if gpk is not None:
                    q += f"&game_pk=eq.{gpk}"
                http_patch(f"{SUPABASE_URL}/rest/v1/pitcher_predictions?{q}",
                               json={"actual_ks": k_actual, "graded": 1}, headers=DB_HEADERS)
    except Exception:
        pass

# ============================================================
# API HELPERS
# ============================================================
@st.cache_data(ttl=86400)
def get_league_hitting(year):
    url = f"https://statsapi.mlb.com/api/v1/sports/1/stats?stats=season&group=hitting&season={year}"
    try:
        return http_get(url).json()['stats'][0]['splits'][0]['stat']
    except Exception:
        return {'obp': '.315', 'slg': '.400'}

@st.cache_data(ttl=3600)
def get_schedule(date_str):
    url = f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&teamId=113&date={date_str}&hydrate=probablePitcher"
    try:
        return http_get(url).json()
    except Exception:
        return {}  # bad/non-JSON response -> app degrades to the OFF DAY screen

@st.cache_data(ttl=300)
def get_game_starters(game_pk):
    url = f"https://statsapi.mlb.com/api/v1.1/game/{game_pk}/feed/live"
    try:
        res = http_get(url).json()
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
    except Exception:
        return {'away': {'id': None, 'name': 'TBD'}, 'home': {'id': None, 'name': 'TBD'}}

@st.cache_data(ttl=300)
def get_live_feed(game_pk):
    """Cached game feed/live pull (used for lineups). Short TTL keeps it fresh
    without re-fetching on every Streamlit rerun."""
    try:
        return http_get(f"https://statsapi.mlb.com/api/v1.1/game/{game_pk}/feed/live").json()
    except Exception:
        return {}

@st.cache_data(ttl=86400)
def get_roster(team_id):
    url = f"https://statsapi.mlb.com/api/v1/teams/{team_id}/roster"
    try:
        return http_get(url).json().get('roster', [])
    except Exception:
        return []

@st.cache_data(ttl=3600)
def get_season_stats(player_id, group, year, split=None):
    if split:
        url = f"https://statsapi.mlb.com/api/v1/people/{player_id}/stats?stats=statSplits&group={group}&season={year}&sitCodes={split}"
    else:
        url = f"https://statsapi.mlb.com/api/v1/people/{player_id}/stats?stats=season&group={group}&season={year}"
    try:
        return http_get(url).json()
    except Exception:
        return {}

@st.cache_data(ttl=3600)
def get_advanced_hitting(player_id, year):
    url = f"https://statsapi.mlb.com/api/v1/people/{player_id}/stats?stats=season,seasonAdvanced&group=hitting&season={year}"
    res = http_get(url).json()
    stats = {}
    try:
        for split in res.get('stats', []):
            if split['type']['displayName'] in ['season', 'seasonAdvanced']:
                stats.update(split['splits'][0]['stat'])
    except Exception:
        pass
    return stats

@st.cache_data(ttl=3600)
def get_advanced_pitching(player_id, year):
    url = f"https://statsapi.mlb.com/api/v1/people/{player_id}/stats?stats=season,seasonAdvanced&group=pitching&season={year}"
    res = http_get(url).json()
    stats = {}
    try:
        for split in res.get('stats', []):
            if split['type']['displayName'] in ['season', 'seasonAdvanced']:
                stats.update(split['splits'][0]['stat'])
    except Exception:
        pass
    return stats

@st.cache_data(ttl=3600)
def get_team_pitching(team_id, year):
    url = f"https://statsapi.mlb.com/api/v1/teams/{team_id}/stats?stats=statSplits&group=pitching&season={year}&sitCodes=rp"
    try:
        return http_get(url).json()['stats'][0]['splits'][0]['stat']
    except Exception:
        return {}

@st.cache_data(ttl=3600)
def get_bullpen_fatigue(team_id):
    today = now_eastern()
    start = (today - timedelta(days=3)).strftime("%Y-%m-%d")
    end   = (today - timedelta(days=1)).strftime("%Y-%m-%d")
    url   = f"https://statsapi.mlb.com/api/v1/teams/{team_id}/stats?stats=byDateRange&group=pitching&startDate={start}&endDate={end}&sitCodes=rp"
    try:
        res = http_get(url).json()
        return calc_ip(res['stats'][0]['splits'][0]['stat'].get('inningsPitched', '0.0'))
    except Exception:
        return 0.0

@st.cache_data(ttl=86400)
def get_career_splits(player_id, group, split_code):
    url = f"https://statsapi.mlb.com/api/v1/people/{player_id}/stats?stats=careerStatSplits&group={group}&sitCodes={split_code}"
    try:
        return http_get(url).json()
    except Exception:
        return {}

@st.cache_data(ttl=3600)
def get_team_splits(team_id, year, split_code):
    url = f"https://statsapi.mlb.com/api/v1/teams/{team_id}/stats?stats=statSplits&group=hitting&season={year}&sitCodes={split_code}"
    try:
        return http_get(url).json()['stats'][0]['splits'][0]['stat']
    except Exception:
        return {}

@st.cache_data(ttl=3600)
def get_bvp_stats(batter_id, pitcher_id):
    if not pitcher_id: return None
    url = f"https://statsapi.mlb.com/api/v1/people/{batter_id}/stats?stats=vsPlayer&opposingPlayerId={pitcher_id}&group=hitting"
    try:
        return http_get(url).json()['stats'][0]['splits'][0]['stat']
    except Exception:
        return None

@st.cache_data(ttl=3600)
def get_game_logs(player_id, year, group="hitting"):
    url = f"https://statsapi.mlb.com/api/v1/people/{player_id}/stats?stats=gameLog&group={group}&season={year}"
    try:
        return http_get(url).json()['stats'][0]['splits']
    except Exception:
        return []

@st.cache_data(ttl=86400)
def get_pitcher_hand(pitcher_id):
    if not pitcher_id: return "R"
    try:
        return http_get(f"https://statsapi.mlb.com/api/v1/people/{pitcher_id}").json()['people'][0]['pitchHand']['code']
    except Exception:
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
# LEAGUE-WIDE SLATE (Lock of the Day)
# ============================================================
@st.cache_data(ttl=1800)
def get_league_schedule(date_str):
    """All MLB games for a date with probable pitchers hydrated."""
    url = f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&date={date_str}&hydrate=probablePitcher"
    try:
        return http_get(url).json()
    except Exception:
        return {}

def slate_probable_pitchers(sched):
    """Flatten the league schedule into a list of probable-starter dicts:
    {pitcher_id, pitcher_name, team_name, opp_team_id, opp_team_name, park_name}."""
    out = []
    for d in sched.get('dates', []):
        for g in d.get('games', []):
            venue = g.get('venue', {}).get('name', 'Unknown')
            teams = g.get('teams', {})
            for side, opp in (('home', 'away'), ('away', 'home')):
                pp = teams.get(side, {}).get('probablePitcher')
                if not pp or not pp.get('id'):
                    continue
                out.append({
                    'pitcher_id':    pp.get('id'),
                    'pitcher_name':  pp.get('fullName', ''),
                    'team_name':     teams.get(side, {}).get('team', {}).get('name', ''),
                    'opp_team_id':   teams.get(opp, {}).get('team', {}).get('id'),
                    'opp_team_name': teams.get(opp, {}).get('team', {}).get('name', ''),
                    'park_name':     venue,
                })
    return out

def get_dk_pitcher_strikeouts(cap=None):
    """League-wide DraftKings pitcher_strikeouts lines, keyed by normalized name:
    {name: {'line', 'over_price', 'under_price'}}. Costs ~1 Odds API credit per
    event, so this is on-demand only."""
    if not ODDS_API_KEY:
        return {}
    base = "https://api.the-odds-api.com/v4/sports/baseball_mlb"
    out = {}
    try:
        ev_res = http_get(f"{base}/events", params={"apiKey": ODDS_API_KEY})
        if ev_res.status_code != 200:
            st.error(f"Odds API (events) failed: {ev_res.text[:160]}")
            return {}
        events = ev_res.json() or []
        if cap:
            events = events[:cap]
        for e in events:
            eid = e.get('id')
            if not eid:
                continue
            r = http_get(f"{base}/events/{eid}/odds", params={
                "apiKey": ODDS_API_KEY, "regions": "us",
                "markets": "pitcher_strikeouts", "bookmakers": "draftkings",
                "oddsFormat": "american",
            })
            if r.status_code != 200:
                continue
            game = r.json()
            for book in game.get('bookmakers', []):
                for market in book.get('markets', []):
                    if market.get('key') != 'pitcher_strikeouts':
                        continue
                    for o in market.get('outcomes', []):
                        nm = normalize_name(o.get('description', ''))
                        if not nm:
                            continue
                        rec = out.setdefault(nm, {'line': o.get('point'),
                                                  'over_price': None, 'under_price': None})
                        if o.get('point') is not None:
                            rec['line'] = o.get('point')
                        if o.get('name') == 'Over':
                            rec['over_price'] = o.get('price')
                        elif o.get('name') == 'Under':
                            rec['under_price'] = o.get('price')
        return out
    except Exception as ex:
        st.error(f"Odds API (pitcher Ks) error: {ex}")
        return {}

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
        ev_res = http_get(f"{base}/events", params={"apiKey": ODDS_API_KEY})
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
        o_res = http_get(
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
    """Returns (projected_ks, receipt_lines, meta). receipt_lines is a list of
    (label, value, description); meta is {'opener': bool}."""
    if not pitcher_id:
        return None, [], {"opener": False, "data_ok": False, "exp_ip": 0.0}

    adv, l5_k_list, l5_avg_k, l5_avg_ip = get_pitcher_k_stats(pitcher_id, year)
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

# ============================================================
# PARALLEL HITTER PREFETCH
# ============================================================
def _prefetch_hitter(p_id, year, split_code, opp_pitcher_id):
    """Pull every API blob one hitter needs in a single call so the whole
    roster can be fetched concurrently. All callees are @st.cache_data, so a
    warm cache short-circuits the network."""
    return {
        'logs':    get_game_logs(p_id, year),
        'ov_data': get_season_stats(p_id, "hitting", year),
        'adv_hit': get_advanced_hitting(p_id, year),
        'sp_data': get_season_stats(p_id, "hitting", year, split=split_code),
        'bvp':     get_bvp_stats(p_id, opp_pitcher_id),
    }

def _parallel_prefetch(player_ids, year, split_code, opp_pitcher_id, max_workers=8):
    """Fetch every hitter's stats in parallel. Returns {player_id: blob|None}.
    Replaces ~6 sequential network calls per hitter with a concurrent sweep."""
    if not player_ids:
        return {}
    ctx = get_script_run_ctx() if get_script_run_ctx else None

    def task(pid):
        if ctx and add_script_run_ctx:
            add_script_run_ctx(threading.current_thread(), ctx)
        try:
            return pid, _prefetch_hitter(pid, year, split_code, opp_pitcher_id)
        except Exception:
            return pid, None

    out = {}
    with ThreadPoolExecutor(max_workers=min(max_workers, len(player_ids))) as ex:
        for pid, blob in ex.map(task, player_ids):
            out[pid] = blob
    return out

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

    # Dual-engine display: multiplicative score chip + disagreement flag
    mult_score = row.get('Mult_Score')
    mult_tier  = row.get('Mult_Tier', '')
    mult_chip  = ""
    if mult_score is not None:
        m_emoji = "🟢" if "Tier 1" in mult_tier else ("🟡" if "Tier 2" in mult_tier else "🔴")
        mult_chip = f'<span class="mult-chip">MULT: {mult_score} {m_emoji}</span>'
    disagree_flag = '<span class="disagree-flag">⚠ engines differ</span>' if row.get('Disagree') else ""

    # 💎 Value badge — model beats the DK price (the only bets worth making)
    val = row.get('Value')
    value_chip = ""
    if val and val.get('is_value'):
        value_chip = (f'<span class="dk-badge" style="background:#1a3a1a;color:#4caf50;">'
                      f'💎 VALUE {val["ev"]*100:+.0f}% EV</span>')

    st.markdown(f"""
    <div class="{card_cls}">
        <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px;">
            <div style="display:flex; align-items:center; gap:12px;">
                <span class="player-score">{row['Score']}</span>
                <div>
                    <p class="player-name">#{idx} {html.escape(str(row['Player']))} {mult_chip}{disagree_flag}{value_chip}</p>
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
    """Render collapsible engine receipt — additive and/or multiplicative."""
    receipt = row.get('Receipt', {})
    mult_receipt = row.get('Mult_Receipt', [])
    if not receipt and not mult_receipt:
        return
    label = "🧾 Engine Receipt"
    if row.get('Disagree'):
        label = "⚠️ Engine Receipt (engines disagree)"
    with st.expander(label):
        lines_html = ""
        if receipt:
            lines_html += '<div class="receipt-line" style="color:#C6011F;font-weight:700;"><span>ADDITIVE ENGINE</span><span></span></div>'
        for label_k, val in receipt.items():
            css = color_val(val)
            lines_html += f"""
            <div class="receipt-line">
                <span>{label_k}</span>
                <span class="{css}">{signed(val)}</span>
            </div>"""
        if receipt:
            lines_html += f"""
            <div class="receipt-total">
                <span>FINAL SCORE (Additive)</span>
                <span>{row['Score']}/100</span>
            </div>"""

        # Multiplicative breakdown (baseline × modifiers)
        if mult_receipt:
            lines_html += '<div style="margin-top:14px;border-top:1px solid #333;padding-top:8px;"></div>'
            lines_html += '<div class="receipt-line" style="color:#7fb3ff;font-weight:700;"><span>MULTIPLICATIVE ENGINE</span><span></span></div>'
            for label, val, detail in mult_receipt:
                if label.startswith("Baseline"):
                    lines_html += f"""
                    <div class="receipt-line">
                        <span>{label} <small style="color:#555;">({detail})</small></span>
                        <span class="receipt-neu">{val}</span>
                    </div>"""
                else:
                    css = "receipt-pos" if val > 1.0 else ("receipt-neg" if val < 1.0 else "receipt-neu")
                    lines_html += f"""
                    <div class="receipt-line">
                        <span>{label} <small style="color:#555;">({detail})</small></span>
                        <span class="{css}">×{val}</span>
                    </div>"""
            lines_html += f"""
            <div class="receipt-total" style="color:#7fb3ff;">
                <span>FINAL SCORE (Mult)</span>
                <span>{row.get('Mult_Score','—')}/100 · {row.get('Mult_Tier','')}</span>
            </div>"""

        st.markdown(f'<div style="background:#111;border-radius:6px;padding:12px 16px;">{lines_html}</div>',
                    unsafe_allow_html=True)

def render_strikeout_panel(pitcher_id, pitcher_name, proj_k, receipt, year):
    """Render the projected-Ks number, the engine receipt, and the L5 starts
    table for one pitcher. Shared by both the Reds and opponent columns."""
    st.markdown(f'<div class="k-label">PROJECTED STRIKEOUTS</div><div class="k-proj">{proj_k}</div>',
                unsafe_allow_html=True)
    st.divider()
    st.markdown(f"#### 🧾 Engine Receipt: {pitcher_name}")
    receipt_html = ""
    for label, val, detail in receipt:
        css = color_val(val)
        receipt_html += f"""
        <div class="receipt-line">
            <span>{label} <small style="color:#555;">({detail})</small></span>
            <span class="{css}">{signed(val)}</span>
        </div>"""
    receipt_html += f"""
    <div class="receipt-total">
        <span>PROJECTED Ks</span>
        <span>{proj_k}</span>
    </div>"""
    st.markdown(f'<div style="background:#111;border-radius:6px;padding:12px 16px;">{receipt_html}</div>',
                unsafe_allow_html=True)

    st.markdown("#### 📋 Last 5 Starts")
    p_logs = get_game_logs(pitcher_id, year, group="pitching")
    if p_logs:
        log_data = [{
            "Date": g.get('date', ''),
            "Opp":  g.get('opponent', {}).get('name', ''),
            "IP":   g.get('stat', {}).get('inningsPitched', '0.0'),
            "K":    g.get('stat', {}).get('strikeOuts', 0),
            "Pitches": g.get('stat', {}).get('numberOfPitches', 0),
        } for g in reversed(p_logs[-5:])]
        st.dataframe(pd.DataFrame(log_data), hide_index=True, use_container_width=True)

def render_lock(lock, shortlist, n_scanned):
    """Render the Lock-of-the-Day card: the single best play with deep reasoning,
    plus the top-5 shortlist."""
    if not lock:
        st.warning("No qualifying lock — nothing cleared the edge/confidence guardrails. "
                   "Try again when more DraftKings lines are posted (usually a few hours pre-game).")
        return

    side, conf = lock['side'], lock['confidence']
    emoji  = "🟢" if conf == "HIGH" else ("🟡" if conf == "MEDIUM" else "🔴")
    price  = lock.get('price')
    price_str = (f"+{price}" if isinstance(price, (int, float)) and price > 0 else str(price)) if price is not None else "—"

    st.markdown(f"#### 🎯 Lock of the Day · {emoji} {conf} confidence")
    st.markdown(f"## {lock['pitcher_name']} — {side} {lock['line']} Ks  ({price_str})")
    st.caption(f"{lock.get('team_name','')} vs {lock.get('opp_team_name','')} · "
               f"{lock.get('park_name','')} · scanned {n_scanned} priced starters")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Projection", f"{lock['projection']:.1f} Ks")
    c2.metric("DK Line", f"{lock['line']}")
    if lock.get('implied_prob') is not None:
        c3.metric("Model win prob", f"{lock['model_prob']*100:.0f}%",
                  delta=f"{(lock['model_prob']-lock['implied_prob'])*100:+.0f} pts vs book")
    else:
        c3.metric("Model win prob", f"{lock['model_prob']*100:.0f}%")
    if lock.get('ev') is not None:
        c4.metric("Edge (EV)", f"{lock['ev']*100:+.1f}%", help="Expected value per 1-unit bet")
    else:
        c4.metric("Edge", f"{lock['edge_k']:+.1f} K")

    # Plain-English reasoning
    reason = (f"The engine projects **{lock['projection']:.1f} Ks** against a line of "
              f"**{lock['line']}** — {abs(lock['edge_k']):.1f} K "
              f"{'above' if side=='Over' else 'below'} it. ")
    if lock.get('implied_prob') is not None:
        reason += (f"Modeled with a Poisson distribution, the **{side.lower()}** hits "
                   f"**{lock['model_prob']*100:.0f}%** of the time vs the book's implied "
                   f"**{lock['implied_prob']*100:.0f}%** — a {(lock['model_prob']-lock['implied_prob'])*100:+.0f}-point edge.")
    st.markdown(f"**Why:** {reason}")

    # The factor-by-factor receipt that built the projection
    rec = lock.get('receipt', [])
    if rec:
        rows_html = ""
        for label, val, detail in rec:
            css = color_val(val)
            rows_html += f"""
            <div class="receipt-line">
                <span>{html.escape(str(label))} <small style="color:#555;">({html.escape(str(detail))})</small></span>
                <span class="{css}">{signed(val)}</span>
            </div>"""
        with st.expander("🧾 How the projection was built"):
            st.markdown(f'<div style="background:#111;border-radius:6px;padding:12px 16px;">{rows_html}</div>',
                        unsafe_allow_html=True)

    if len(shortlist) > 1:
        st.markdown("#### 📋 Top 5 edges")
        table = [{
            "Pitcher": c['pitcher_name'],
            "Bet":     f"{c['side']} {c['line']}",
            "Proj":    f"{c['projection']:.1f}",
            "Win %":   f"{c['model_prob']*100:.0f}%",
            "EV":      (f"{c['ev']*100:+.1f}%" if c.get('ev') is not None else "—"),
            "Conf":    c['confidence'],
            "Matchup": f"vs {c.get('opp_team_name','')}",
        } for c in shortlist]
        st.dataframe(pd.DataFrame(table), hide_index=True, use_container_width=True)
    st.caption("⚠️ Single-game strikeouts are noisy — this is the best *edge*, not a guarantee. Bet responsibly.")

def render_lock_of_the_day(date_str, current_year):
    """The full Lock-of-the-Day tool. Independent of the Reds schedule, so it
    works on Reds off-days too."""
    st.markdown("### 🎯 Strikeout Lock of the Day")
    st.caption("Scans the full MLB slate, runs every probable starter through the K engine, models "
               "the over/under with a Poisson distribution, and ranks DraftKings lines by edge. "
               "Both sides · full slate · guardrails on (skips openers & thin data).")

    if not ODDS_API_KEY:
        st.warning("Add an `ODDS_API_KEY` to the app secrets to enable the Lock of the Day.")
        return

    st.caption("⚠️ A scan pulls DraftKings strikeout lines for every game (~1 Odds API credit each).")
    if st.button("🔎 Scan the slate for today's lock", type="primary", key="lock_scan"):
        sched = get_league_schedule(date_str)
        slate = slate_probable_pitchers(sched)
        if not slate:
            st.info("No probable pitchers posted for the slate yet — check back closer to game time.")
        else:
            with st.spinner(f"Pulling DraftKings strikeout lines ({len(slate)} probable starters)..."):
                dk = get_dk_pitcher_strikeouts()
            matched = [p for p in slate if normalize_name(p['pitcher_name']) in dk]
            if not matched:
                st.warning(f"Found {len(slate)} probable starters but no DraftKings strikeout lines are "
                           "posted yet (they usually appear a few hours before first pitch).")
            else:
                ctx = get_script_run_ctx() if get_script_run_ctx else None
                def _project(p):
                    if ctx and add_script_run_ctx:
                        add_script_run_ctx(threading.current_thread(), ctx)
                    try:
                        proj, receipt, meta = run_strikeout_engine(
                            p['pitcher_id'], p['pitcher_name'], p['opp_team_id'],
                            p['opp_team_name'], p['park_name'], current_year)
                    except Exception:
                        return None
                    if proj is None:
                        return None
                    dkline = dk.get(normalize_name(p['pitcher_name']), {})
                    return {**p, 'projection': proj, 'line': dkline.get('line'),
                            'over_price': dkline.get('over_price'),
                            'under_price': dkline.get('under_price'),
                            'opener': meta.get('opener', False),
                            'data_ok': meta.get('data_ok', True),
                            'receipt': receipt}

                prog = st.progress(0.0, text="Projecting starters...")
                cands = []
                with ThreadPoolExecutor(max_workers=8) as ex:
                    futs = [ex.submit(_project, p) for p in matched]
                    for i, f in enumerate(as_completed(futs)):
                        prog.progress((i + 1) / len(futs), text=f"Projecting starters... {i+1}/{len(futs)}")
                        r = f.result()
                        if r and r.get('line') is not None:
                            cands.append(r)
                prog.empty()

                lock, shortlist = select_locks(cands, sides="both", guardrails=True, top_n=5)
                st.session_state['lock_result'] = {
                    'lock': lock, 'shortlist': shortlist,
                    'n_scanned': len(cands), 'date': date_str
                }

    res = st.session_state.get('lock_result')
    if res and res.get('date') == date_str:
        st.divider()
        render_lock(res['lock'], res['shortlist'], res['n_scanned'])
    else:
        st.info("Tap **Scan the slate** above to find today's lock.")

def _recap_model_block(label, s):
    """Render one model's last-game line (record / win% / units)."""
    st.markdown(f"**{label}**")
    if s.get('n', 0) == 0:
        st.caption("No plays")
        return
    wins, losses = s.get('wins', 0), s.get('losses', 0)
    won = wins >= losses
    c1, c2, c3 = st.columns(3)
    c1.metric("Record", f"{wins}–{losses}",
              delta="WIN ✅" if won else "LOSS ❌",
              delta_color="normal" if won else "inverse")
    c2.metric("Win %", f"{s.get('win_rate', 0)*100:.0f}%")
    c3.metric("Units", f"{s.get('units', 0):+.2f}u" if s.get('n_priced') else "—")

def render_last_game_recap(recap):
    """Top-of-analytics card comparing the two models on the last game."""
    head = f"#### 📅 Last Game — {recap.get('date', '')}"
    if recap.get('opp_pitcher'):
        head += f"  ·  vs {recap['opp_pitcher']}"
    st.markdown(head)

    a = recap.get('additive') or {}
    m = recap.get('mult') or {}
    if a.get('n', 0) == 0 and m.get('n', 0) == 0:
        st.caption("Neither model had a play on that date.")
        return

    col_a, col_m = st.columns(2)
    with col_a: _recap_model_block("🅰️ Additive model", a)
    with col_m: _recap_model_block("✖️ Multiplicative model", m)

    # Which model was on each player, and how it turned out
    table = [{
        "Player":   p.get('player_name', '?'),
        "Additive": "🟢" if "Tier 1" in str(p.get('tier', '')) else "·",
        "Mult":     "🟢" if "Tier 1" in str(p.get('mult_tier', '')) else "·",
        "Hits":     p.get('actual_hits'),
        "Result":   "✅ WIN" if int(p['win']) == 1 else "❌ LOSS",
    } for p in recap['picks']]
    if table:
        st.dataframe(pd.DataFrame(table), hide_index=True, use_container_width=True)

def _brier_grade(b):
    if   b <= 0.17: return "A"
    elif b <= 0.21: return "B"
    elif b <= 0.25: return "C"
    return "D"

def _scoreboard_model_block(label, s):
    """One model's season column: plays, record, win% vs break-even, units, grade."""
    st.markdown(f"**{label}**")
    n = s.get('n', 0)
    if n == 0:
        st.caption("No Tier 1 plays yet")
        return
    wins, losses = s.get('wins', 0), s.get('losses', 0)
    rate = s.get('win_rate', 0.0)
    c1, c2 = st.columns(2)
    c1.metric("Record", f"{wins}–{losses}", help=f"{n} Tier 1 plays")
    # Win % shown against the ~52.4% break-even line (green = beating the juice)
    c2.metric("Win %", f"{rate*100:.1f}%",
              delta=f"{(rate - BREAKEVEN_WIN_RATE)*100:+.1f} vs break-even",
              delta_color="normal")
    c3, c4 = st.columns(2)
    if s.get('n_priced'):
        c3.metric("Units", f"{s.get('units', 0):+.2f}u")
        c4.metric("ROI", f"{s.get('roi_pct', 0):+.1f}%")
        st.caption(f"⚠️ units/ROI on just **{s['n_priced']}** priced bet(s) — "
                   "small sample, trust the win rate for now"
                   if s['n_priced'] < MIN_PRICED_FOR_ROI
                   else f"units/ROI on {s['n_priced']} priced bets")
    else:
        c3.metric("Units", "—", help="no stored odds yet")
        c4.metric("ROI", "—")
    if s.get('brier_n'):
        st.caption(f"Calibration grade **{_brier_grade(s['brier'])}** "
                   f"(Brier {s['brier']:.3f}, 0.25 = coin flip)")

def render_season_scoreboard(sb):
    """All-time two-model scoreboard for the top of the analytics page."""
    st.markdown(f"#### 🏆 Season Scoreboard — {sb.get('n_games', 0)} games")
    st.caption("Each model graded on the Tier 1 plays IT recommended, all-time. "
               "Win % is vs the ~52.4% break-even at standard −110 juice.")
    a = sb.get('additive') or {}
    m = sb.get('mult') or {}
    col_a, col_m = st.columns(2)
    with col_a: _scoreboard_model_block("🅰️ Additive model", a)
    with col_m: _scoreboard_model_block("✖️ Multiplicative model", m)

    # Plain-English verdict: who's ahead. Uses win rate (the big, reliable
    # sample) until there are enough priced bets for ROI to mean anything.
    v = scoreboard_verdict(sb)
    if v:
        names = {"additive": "🅰️ Additive", "mult": "✖️ Multiplicative", "tie": "Both models"}
        name = names[v['leader']]
        if v['basis'] == 'roi':
            st.info(f"📈 **{name}** is ahead this season "
                    f"(ROI {v['a']:+.1f}% vs {v['m']:+.1f}%).")
        elif v['leader'] == 'tie':
            st.info(f"📈 The two models are dead even on win rate "
                    f"({v['a']*100:.1f}%).")
        else:
            st.info(f"📈 **{name}** is ahead this season "
                    f"(win rate {v['a']*100:.1f}% vs {v['m']*100:.1f}%). "
                    f"Not enough priced bets yet for a reliable ROI read.")

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
    selected_date = st.date_input("Select Game Date", now_eastern())
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
            est_time       = utc_time.astimezone(EASTERN)
            start_time_est = est_time.strftime("%I:%M %p %Z")
        except Exception:
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
        live_feed = get_live_feed(game_pk)
        boxscore  = live_feed.get('liveData', {}).get('boxscore', {}).get('teams', {})
        reds_batting_order = boxscore.get('away' if "Reds" in away_team else 'home', {}).get('battingOrder', [])
    except Exception:
        reds_batting_order = []

    # ============================================================
    # TABS
    # ============================================================
    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "🔥 Offense Top Matchups",
        "⚡ Strikeout Engine",
        "📊 System Tracker",
        "🔍 Player Deep Dive",
        "🎯 Lock of the Day"
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
                if is_likely_opener(calc_ip(adv_stats.get('inningsPitched', '0.0')),
                                    adv_stats.get('gamesStarted', 0),
                                    adv_stats.get('gamesPlayed', 0)):
                    st.warning("⚠️ This 'starter' looks like an **opener** — your hitters face the bulk "
                               "pitcher for most of the game, so the splits/FIP above may not reflect the "
                               "real matchup.")
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

                scan_results = []
                league_stats = get_league_hitting(current_year)

                # Opposing starter's FIP is the same for every Reds hitter — compute once.
                opp_fip_val = 4.00
                if adv_stats:
                    try:    opp_fip_val = float(calculate_fip(adv_stats))
                    except Exception: opp_fip_val = 4.00

                # Decide who we actually score (respect "hide bench"), then fetch
                # all of their stats concurrently instead of one hitter at a time.
                to_score = []
                for name, p_id in hitters.items():
                    if reds_batting_order and show_starters and p_id not in reds_batting_order:
                        continue
                    to_score.append((name, p_id))

                with st.spinner(f"Fetching stats for {len(to_score)} hitters in parallel..."):
                    prefetched = _parallel_prefetch(
                        [pid for _, pid in to_score], current_year, split_code, opp_pitcher_id
                    )

                pb = st.progress(0, text="Scoring roster...")
                n_score = max(1, len(to_score))
                for i, (name, p_id) in enumerate(to_score):
                    pb.progress((i + 1) / n_score, text=f"Scoring {name}...")
                    lineup_score, in_lineup, idx_pos = 0, False, None
                    if reds_batting_order and p_id in reds_batting_order:
                        in_lineup    = True
                        idx_pos      = reds_batting_order.index(p_id)
                        lineup_score = LINEUP_TOP_BONUS if idx_pos <= 2 else (LINEUP_BOT_PENALTY if idx_pos >= 6 else 0)

                    blob = prefetched.get(p_id) or {}

                    # L10 form
                    hit_games, l10_total, l10_h_avg, l10_hrr_avg = 0, 0, 0.0, 0.0
                    logs = blob.get('logs') or []
                    if logs:
                        l10       = logs[-10:]
                        l10_total = len(l10)
                        hit_games = sum(1 for g in l10 if g.get('stat', {}).get('hits', 0) > 0)
                        if l10_total > 0:
                            l10_h_avg   = round(sum(g.get('stat', {}).get('hits', 0) for g in l10) / l10_total, 1)
                            l10_hrr_avg = round(sum((g['stat'].get('hits', 0) + g['stat'].get('runs', 0) + g['stat'].get('rbi', 0)) for g in l10) / l10_total, 1)

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
                            c_data    = get_career_splits(p_id, "hitting", split_code)
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
                    split_score = split_ops_points(split_ops, split_pa)   # shrinks below SPLIT_MIN_PA
                    bvp_bonus   = bvp_bonus_points(bvp_avg, bvp_pa)        # shrinks below BVP_MIN_PA
                    cons_score  = int((hit_games / 10.0) * WEIGHT_CONSISTENCY) if l10_total > 0 else 0
                    hrr_score   = int(min(WEIGHT_HRR, (l10_hrr_avg / 2.5) * WEIGHT_HRR))
                    penalty     = scaled_babip_penalty(babip)  # scaled, -1/.010 over .340, cap -20

                    raw_score   = split_score + cons_score + hrr_score + pitcher_score + lineup_score + bvp_bonus + penalty
                    total_score = min(100, max(0, raw_score))
                    tier        = "🟢 Tier 1" if total_score >= TIER1_THRESHOLD else ("🟡 Tier 2" if total_score >= TIER2_THRESHOLD else "🔴 Tier 3")

                    # --- MULTIPLICATIVE engine (side-by-side) ---
                    lineup_pos_val = idx_pos
                    l10_hit_rate   = (hit_games / l10_total) if l10_total > 0 else 0.0
                    mult_score, mult_tier, mult_baseline, mult_receipt = run_multiplicative_engine({
                        'ops_plus': ops_plus, 'iso': iso_val, 'k_pct': k_pct_val,
                        'l10_hit_rate': l10_hit_rate, 'opp_fip': opp_fip_val,
                        'park_name': park_name, 'lineup_pos': lineup_pos_val, 'babip': babip
                    })

                    # Disagreement flag: only fire when TIER 1 is involved on either
                    # engine — that's the only disagreement that affects a real bet.
                    def _tier_rank(t): return 1 if "Tier 1" in t else (2 if "Tier 2" in t else 3)
                    tiers_cross   = _tier_rank(tier) != _tier_rank(mult_tier)
                    t1_involved   = ("Tier 1" in tier) or ("Tier 1" in mult_tier)
                    engines_disagree = tiers_cross and t1_involved

                    dk_info = live_odds.get(normalize_name(name), {})

                    # --- VALUE FILTER: does the model beat the DK price? ---
                    # Model win prob = score/100; bet only when that exceeds the
                    # book's implied prob (a +EV edge). This is the filter that
                    # turned a losing card into a winner in the backtest.
                    dk_price = dk_info.get('price') if dk_info else None
                    value = value_metrics(total_score / 100.0, dk_price)

                    # Build receipt dict for Tier 1
                    receipt = {}
                    if total_score >= TIER1_THRESHOLD:
                        receipt = {
                            f"Consistency Score (L10 hit rate)":       cons_score,
                            f"HRR Score (L10 avg HRR)":                hrr_score,
                            f"Split OPS vs {split_label} ({split_pa} PA)": split_score,
                            f"Pitcher ERA Bonus":                      pitcher_score,
                            f"Lineup Position Bonus":                  lineup_score,
                            f"BvP History ({bvp_pa} PA)":              bvp_bonus,
                            f"BABIP Guardrail (scaled)":               penalty,
                        }

                    scan_results.append({
                        "Player": name, "Player_ID": p_id, "Tier": tier, "Score": total_score,
                        "Avg": overall_avg, "Raw_OPS": split_ops, "L10_HRR": l10_hrr_avg,
                        "L10_Hits": l10_h_avg, "BVP_Avg": bvp_avg,
                        "OPS_Display": f"{split_ops:.3f}", "OPS_Plus": ops_plus,
                        "DK_Info": dk_info, "Receipt": receipt,
                        # multiplicative + diagnostics
                        "Mult_Score": mult_score, "Mult_Tier": mult_tier,
                        "Mult_Baseline": mult_baseline, "Mult_Receipt": mult_receipt,
                        "Disagree": engines_disagree,
                        "BABIP": babip, "K_Pct": k_pct_val, "ISO": iso_val, "Opp_FIP": opp_fip_val,
                        "Value": value
                    })

                pb.empty()

                # --- Save to Supabase (UPSERT w/ odds at pick time) ---
                if SUPABASE_URL:
                    if is_pregame:
                        insert_data = [{
                            "date": date_str, "player_id": r['Player_ID'], "player_name": r['Player'],
                            "game_pk": int(game_pk),
                            "score": r['Score'], "tier": r['Tier'], "opp_pitcher": opp_pitcher_name,
                            "actual_hits": 0, "actual_hrr": 0, "graded": 0, "win": 0,
                            "odds_line":  r['DK_Info'].get('line')  if r['DK_Info'] else None,
                            "odds_price": r['DK_Info'].get('price') if r['DK_Info'] else None,
                            "mult_score": r['Mult_Score'], "mult_tier": r['Mult_Tier'],
                            "mult_baseline": r['Mult_Baseline'],
                            "babip":   (float(r['BABIP']) if r['BABIP'] not in (None, '.000', '') else None),
                            "k_pct":   r['K_Pct'], "iso": r['ISO'], "opp_fip": r['Opp_FIP']
                        } for r in scan_results]
                        # merge-duplicates upsert keyed on (date, player_id, game_pk)
                        # so doubleheaders (same date+player, different game) stay separate
                        save_res = http_post(
                            f"{SUPABASE_URL}/rest/v1/predictions?on_conflict=date,player_id,game_pk",
                            json=insert_data, headers=DB_HEADERS_UPSERT
                        )
                        if save_res.status_code in (200, 201):
                            odds_count = sum(1 for r in scan_results if r['DK_Info'])
                            st.success(f"💾 Saved {len(insert_data)} predictions ({odds_count} with DK odds locked in).")
                        else:
                            st.warning(f"⚠️ Save issue: {save_res.status_code} — {save_res.text[:140]}")
                    else:
                        st.warning("⚠️ Game has already started. Predictions not saved.")

                # --- 💎 VALUE PLAYS: only where the model beats the DK price ---
                value_plays = sorted(
                    [r for r in scan_results if r.get('Value') and r['Value']['is_value']],
                    key=lambda r: r['Value']['ev'], reverse=True)
                st.markdown("### 💎 Value Plays")
                st.caption("The only bets where **your model's win % beats the DraftKings price** (positive "
                           "expected value). In the backtest, betting *only* these returned +27% ROI vs −12% "
                           "betting everything. If a hitter isn't here, the line is too juiced — pass.")
                if value_plays:
                    vrows = []
                    for r in value_plays:
                        v = r['Value']
                        price = r['DK_Info'].get('price')
                        price_str = f"+{price}" if isinstance(price, (int, float)) and price > 0 else str(price)
                        vrows.append({
                            "Player":   r['Player'],
                            "Bet":      f"O {r['DK_Info'].get('line', 0.5)} ({price_str})",
                            "Your win %":  f"{r['Score']}%",
                            "Book implied": f"{v['implied_prob']*100:.0f}%",
                            "Edge":     f"{v['edge']*100:+.0f} pts",
                            "EV":       f"{v['ev']*100:+.1f}%",
                        })
                    st.dataframe(pd.DataFrame(vrows), hide_index=True, use_container_width=True)
                    st.success(f"✅ {len(value_plays)} value play(s) found — these are the bets with a real edge.")
                else:
                    st.info("No value plays today — every posted line is priced above the model's number. "
                            "The disciplined move is to **pass** (or fetch DK lines if you haven't).")
                st.divider()

                # --- Full board (all hitters, ranked) ---
                if scan_results:
                    st.markdown("### 🏆 Full Board")
                    df = pd.DataFrame(scan_results).sort_values(by=['Score', 'Raw_OPS'], ascending=False)
                    for idx_c, (_, row) in enumerate(df.iterrows(), start=1):
                        render_player_card(row, split_label, idx_c)
                        # Show receipt if either engine flags Tier 1 (disagreements now
                        # only flag when T1 is involved, so this covers them too)
                        if ("Tier 1" in row['Tier']) or ("Tier 1" in str(row.get('Mult_Tier',''))):
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
                    r_proj_k, r_receipt, r_meta = run_strikeout_engine(
                        reds_k_id, reds_k_pitcher, opp_team_id, opponent, park_name, current_year
                    )
                if r_proj_k is not None:
                    if r_meta.get('opener'):
                        st.warning("⚠️ Looks like an **opener** (very few innings per start) — "
                                   "this projection is unreliable; the bulk reliever behind them gets the Ks.")
                    render_strikeout_panel(reds_k_id, reds_k_pitcher, r_proj_k, r_receipt, current_year)
                    k_projections.append({"player_id": reds_k_id, "player_name": reds_k_pitcher, "projected_ks": r_proj_k})
                else:
                    st.info("No data available.")

            with col_opp:
                if opp_k_id:
                    with st.spinner(f"Projecting {opp_k_name}..."):
                        o_proj_k, o_receipt, o_meta = run_strikeout_engine(
                            opp_k_id, opp_k_name, 113, "Cincinnati Reds", park_name, current_year
                        )
                    if o_proj_k is not None:
                        if o_meta.get('opener'):
                            st.warning("⚠️ Looks like an **opener** (very few innings per start) — "
                                       "this projection is unreliable; the bulk reliever behind them gets the Ks.")
                        render_strikeout_panel(opp_k_id, opp_k_name, o_proj_k, o_receipt, current_year)
                        k_projections.append({"player_id": opp_k_id, "player_name": opp_k_name, "projected_ks": o_proj_k})
                else:
                    st.info(f"Select {opponent} pitcher to run engine.")

            # --- Save K projections to Supabase (pregame only) ---
            if SUPABASE_URL and k_projections:
                if is_pregame:
                    payload = [{
                        "date": date_str,
                        "player_id": kp["player_id"],
                        "player_name": kp["player_name"],
                        "game_pk": int(game_pk),
                        "projected_ks": kp["projected_ks"],
                        "actual_ks": 0,
                        "graded": 0
                    } for kp in k_projections]
                    ksave = http_post(
                        f"{SUPABASE_URL}/rest/v1/pitcher_predictions?on_conflict=date,player_id,game_pk",
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

        if SUPABASE_URL:
            @st.cache_data(ttl=300)
            def load_hitting_predictions():
                res = http_get(f"{SUPABASE_URL}/rest/v1/predictions", headers=DB_HEADERS)
                return res.json() if res.status_code == 200 else []

            @st.cache_data(ttl=300)
            def load_pitching_predictions():
                res = http_get(f"{SUPABASE_URL}/rest/v1/pitcher_predictions", headers=DB_HEADERS)
                return res.json() if res.status_code == 200 else []

            raw = load_hitting_predictions()

            # Quick "how did we do last game?" recap, shown above everything
            # else. Wrapped so it can never take down the analytics page (e.g.
            # if a deploy briefly serves mismatched module versions).
            try:
                recap = last_game_recap(raw) if raw else None
                if recap:
                    render_last_game_recap(recap)
                    st.divider()
            except Exception:
                pass

            # Season-long two-model scoreboard (same defensive wrapping)
            try:
                sb = season_scoreboard(raw) if raw else None
                if sb:
                    render_season_scoreboard(sb)
                    st.divider()
            except Exception:
                pass

            # ---- Export your data (offline backtest / backup) ----
            with st.expander("⬇️ Export your data (for a full backtest or backup)"):
                st.caption("Download your saved picks as JSON. Send the hitting file to get a full "
                           "backtest report (threshold sweep, per-model ROI), or just keep it as a backup.")
                ec1, ec2 = st.columns(2)
                ec1.download_button(
                    "⬇️ Hitting picks (JSON)",
                    data=json.dumps(raw or [], indent=2, default=str),
                    file_name=f"hitting_predictions_{date_str}.json",
                    mime="application/json", use_container_width=True)
                ec2.download_button(
                    "⬇️ Pitching projections (JSON)",
                    data=json.dumps(load_pitching_predictions() or [], indent=2, default=str),
                    file_name=f"pitching_predictions_{date_str}.json",
                    mime="application/json", use_container_width=True)
            st.divider()

            hit_tab, pitch_tab = st.tabs(["🔥 Hitting Tracker", "⚾ Pitching Tracker"])
            with hit_tab:
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
                # Manual re-grade — covers auto-grader timing, and un-sticks any
                # rows wrongly marked "no-result" so they get re-evaluated.
                if st.button("🔄 Grade / re-check K projections now"):
                    with st.spinner("Re-grading..."):
                        try:
                            http_patch(f"{SUPABASE_URL}/rest/v1/pitcher_predictions?graded=eq.-1",
                                       json={"graded": 0, "actual_ks": 0}, headers=DB_HEADERS)
                        except Exception:
                            pass
                        st.session_state['last_autograde_time'] = None  # bypass 30-min guard
                        auto_grade_past_predictions()
                        load_pitching_predictions.clear()
                    st.rerun()

                p_raw = load_pitching_predictions()
                if p_raw:
                    df_ptrack  = pd.DataFrame(p_raw)
                    # Coerce numeric columns: some DB setups return these as text,
                    # which silently broke the graded/pending filters (== 1 never
                    # matched a string "1"), so graded rows looked like they vanished.
                    for col in ('graded', 'projected_ks', 'actual_ks'):
                        if col in df_ptrack.columns:
                            df_ptrack[col] = pd.to_numeric(df_ptrack[col], errors='coerce')
                    # Only K-engine rows (have projected_ks); legacy outs rows ignored
                    if 'projected_ks' in df_ptrack.columns:
                        df_ptrack = df_ptrack[df_ptrack['projected_ks'].notna()]
                    df_pactive = df_ptrack[df_ptrack['graded'] == 1].copy() if not df_ptrack.empty else pd.DataFrame()
                    df_pending = df_ptrack[df_ptrack['graded'] == 0].copy() if not df_ptrack.empty else pd.DataFrame()
                    df_nogame  = df_ptrack[df_ptrack['graded'] == -1].copy() if not df_ptrack.empty else pd.DataFrame()

                    st.caption(f"{len(df_ptrack)} K projections · {len(df_pactive)} graded · "
                               f"{len(df_pending)} pending · {len(df_nogame)} no-result")

                    if not df_pactive.empty:
                        df_pactive['delta'] = df_pactive['actual_ks'] - df_pactive['projected_ks']
                        ks = k_engine_summary(df_pactive.to_dict('records'))
                        m1, m2 = st.columns(2)
                        m1.metric("Avg Miss", f"{ks['avg_miss']:.1f} Ks", help=f"{ks['n']} graded starts")
                        m2.metric("Bias", f"{ks['bias']:+.1f} Ks",
                                  help="Positive = pitchers strike out more than projected (engine runs low)")
                        st.divider()
                        df_pdisplay = df_pactive[['date', 'player_name', 'projected_ks', 'actual_ks', 'delta']].sort_values(by='date', ascending=False).copy()
                        df_pdisplay['delta'] = df_pdisplay['delta'].apply(lambda x: f"{x:+.1f}")
                        st.dataframe(df_pdisplay, hide_index=True, use_container_width=True)
                    else:
                        st.info("No graded K projections yet.")

                    if not df_pending.empty:
                        st.markdown("#### ⏳ Pending K Projections")
                        st.dataframe(df_pending[['date', 'player_name', 'projected_ks']].sort_values(by='date', ascending=False),
                                     hide_index=True, use_container_width=True)
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
        except Exception:
            pass

        if adv_hit:
            st.markdown("#### Advanced Metrics")
            c1, c2, c3, c4, c5 = st.columns(5)
            c1.metric("OPS+",  ops_plus)
            c2.metric("BABIP", adv_hit.get('babip', '.000'))
            c3.metric("ISO",   adv_hit.get('iso', '.000'))
            try:    c4.metric("K%",  f"{float(adv_hit.get('strikeoutsPerPlateAppearance', 0))*100:.1f}%")
            except Exception: c4.metric("K%",  "N/A")
            try:    c5.metric("BB%", f"{float(adv_hit.get('walksPerPlateAppearance', 0))*100:.1f}%")
            except Exception: c5.metric("BB%", "N/A")
            st.divider()

        c_l, c_r = st.columns(2)
        with c_l:
            st.markdown("#### vs LHP")
            try:
                s = get_season_stats(h_id, "hitting", current_year, split="vl")['stats'][0]['splits'][0]['stat']
                st.markdown(f"**AVG:** {s.get('avg', '.000')} | **OPS:** {s.get('ops', '.000')} | **HR:** {s.get('homeRuns', 0)}")
            except Exception:
                st.info("No stats vs LHP.")
        with c_r:
            st.markdown("#### vs RHP")
            try:
                s = get_season_stats(h_id, "hitting", current_year, split="vr")['stats'][0]['splits'][0]['stat']
                st.markdown(f"**AVG:** {s.get('avg', '.000')} | **OPS:** {s.get('ops', '.000')} | **HR:** {s.get('homeRuns', 0)}")
            except Exception:
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

    # ----------------------------------------------------------
    # TAB 5 — LOCK OF THE DAY (league-wide strikeout edge hunter)
    # ----------------------------------------------------------
    with tab5:
        render_lock_of_the_day(date_str, current_year)

else:
    st.info("🌴 **The Reds are off today** — the Reds-specific boards are hidden, "
            "but the league-wide tools still work.")
    render_lock_of_the_day(date_str, current_year)
