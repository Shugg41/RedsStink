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

# Headless data + pipeline layer (no Streamlit). The app wraps data.py's
# fetchers with st.cache_data below; the daily auto-run robot uses them raw.
import data
import pipeline
try:
    import briefing
except Exception:  # stale module during a deploy — the robot just skips a day
    briefing = None

# Streamlit ScriptRunContext lets cached fetchers run inside worker threads
# without spamming "missing ScriptRunContext" warnings. Degrade gracefully if
# the internal API moves between Streamlit versions.
try:
    from streamlit.runtime.scriptrunner import add_script_run_ctx, get_script_run_ctx
except Exception:  # pragma: no cover
    add_script_run_ctx = get_script_run_ctx = None

# ============================================================
# TIME / HTTP HELPERS (live in data.py now; re-exported for app code)
# ============================================================
EASTERN      = data.EASTERN
now_eastern  = data.now_eastern
http_get     = data.http_get
http_post    = data.http_post
http_patch   = data.http_patch

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

# Push-notification topic for the morning briefing (ntfy.sh — free, no signup).
# Subscribe to this topic in the ntfy app to get the daily briefing.
try:
    NTFY_TOPIC = st.secrets["NTFY_TOPIC"]
except Exception:
    NTFY_TOPIC = "redsstink-briefing-rk84vq"

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
# AUTO-GRADER
# ============================================================
def auto_grade_worker():
    """Grade past predictions. Pure network + DB — no Streamlit calls — so it
    can run in a background thread without blocking the first render."""
    if not SUPABASE_URL:
        return
    today_str = now_eastern().strftime("%Y-%m-%d")

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
# API HELPERS — cached wrappers around the pure fetchers in data.py
# ============================================================
get_league_hitting   = st.cache_data(ttl=86400)(data.get_league_hitting)
get_schedule         = st.cache_data(ttl=3600)(data.get_schedule)
get_game_starters    = st.cache_data(ttl=300)(data.get_game_starters)
get_live_feed        = st.cache_data(ttl=300)(data.get_live_feed)
get_roster           = st.cache_data(ttl=86400)(data.get_roster)
get_season_stats     = st.cache_data(ttl=3600)(data.get_season_stats)
get_advanced_hitting = st.cache_data(ttl=3600)(data.get_advanced_hitting)
get_advanced_pitching = st.cache_data(ttl=3600)(data.get_advanced_pitching)
get_team_pitching    = st.cache_data(ttl=3600)(data.get_team_pitching)
get_bullpen_fatigue  = st.cache_data(ttl=3600)(data.get_bullpen_fatigue)
get_career_splits    = st.cache_data(ttl=86400)(data.get_career_splits)
get_team_splits      = st.cache_data(ttl=3600)(data.get_team_splits)
get_bvp_stats        = st.cache_data(ttl=3600)(data.get_bvp_stats)
get_game_logs        = st.cache_data(ttl=3600)(data.get_game_logs)
get_pitcher_hand     = st.cache_data(ttl=86400)(data.get_pitcher_hand)
get_league_schedule  = st.cache_data(ttl=1800)(data.get_league_schedule)

class _CachedFetch:
    """Namespace handing the pipeline the CACHED fetchers (interactive path)."""
    get_league_hitting   = staticmethod(lambda *a, **k: get_league_hitting(*a, **k))
    get_schedule         = staticmethod(lambda *a, **k: get_schedule(*a, **k))
    get_game_starters    = staticmethod(lambda *a, **k: get_game_starters(*a, **k))
    get_live_feed        = staticmethod(lambda *a, **k: get_live_feed(*a, **k))
    get_roster           = staticmethod(lambda *a, **k: get_roster(*a, **k))
    get_season_stats     = staticmethod(lambda *a, **k: get_season_stats(*a, **k))
    get_advanced_hitting = staticmethod(lambda *a, **k: get_advanced_hitting(*a, **k))
    get_advanced_pitching = staticmethod(lambda *a, **k: get_advanced_pitching(*a, **k))
    get_team_pitching    = staticmethod(lambda *a, **k: get_team_pitching(*a, **k))
    get_career_splits    = staticmethod(lambda *a, **k: get_career_splits(*a, **k))
    get_team_splits      = staticmethod(lambda *a, **k: get_team_splits(*a, **k))
    get_bvp_stats        = staticmethod(lambda *a, **k: get_bvp_stats(*a, **k))
    get_game_logs        = staticmethod(lambda *a, **k: get_game_logs(*a, **k))
    get_pitcher_hand     = staticmethod(lambda *a, **k: get_pitcher_hand(*a, **k))

    @staticmethod
    def get_pitcher_k_stats(pitcher_id, year):
        adv  = get_advanced_pitching(pitcher_id, year)
        logs = get_game_logs(pitcher_id, year, group="pitching")
        l5   = logs[-5:] if logs else []
        l5_k_list  = [g.get('stat', {}).get('strikeOuts', 0) for g in l5]
        l5_ip_list = [calc_ip(g.get('stat', {}).get('inningsPitched', '0.0')) for g in l5]
        l5_avg_k  = round(sum(l5_k_list) / len(l5_k_list), 1) if l5_k_list else 0.0
        l5_avg_ip = round(sum(l5_ip_list) / len(l5_ip_list), 1) if l5_ip_list else 0.0
        return adv, l5_k_list, l5_avg_k, l5_avg_ip

FETCH = _CachedFetch()

def _st_thread_hook():
    """Attach Streamlit's ScriptRunContext to pipeline worker threads."""
    if get_script_run_ctx and add_script_run_ctx:
        ctx = _MAIN_CTX
        if ctx:
            add_script_run_ctx(threading.current_thread(), ctx)

_MAIN_CTX = get_script_run_ctx() if get_script_run_ctx else None

def slate_probable_pitchers(sched):
    """Flatten the league schedule into probable-starter dicts."""
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

def _show_odds_msgs(msgs):
    for level, text in msgs or []:
        (st.error if level == "error" else st.warning)(text)

def get_draftkings_odds():
    """Reds batter hits + HRR lines (pure fetch in data.py; messages shown here)."""
    odds, msgs = data.fetch_reds_batter_odds(ODDS_API_KEY)
    _show_odds_msgs(msgs)
    return odds

def get_dk_pitcher_strikeouts(cap=None):
    """League-wide pitcher K lines (pure fetch in data.py; messages shown here)."""
    odds, msgs = data.fetch_pitcher_strikeout_odds(ODDS_API_KEY, cap=cap)
    _show_odds_msgs(msgs)
    return odds

def run_strikeout_engine(pitcher_id, pitcher_name, opp_team_id, opp_team_name, park_name, year):
    """Interactive wrapper over the headless pipeline engine (cached fetchers)."""
    return pipeline.run_strikeout_engine(FETCH, pitcher_id, pitcher_name,
                                         opp_team_id, opp_team_name, park_name, year)


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

    dk_info = row.get('DK_Info', {}) or {}
    badges = []
    if dk_info.get('price') is not None and dk_info.get('line') is not None:
        p = dk_info['price']; ps = f"+{p}" if p > 0 else str(p)
        badges.append(f'<span class="dk-badge">DK Hits: O {dk_info["line"]} ({ps})</span>')
    if dk_info.get('hrr_price') is not None and dk_info.get('hrr_line') is not None:
        hp = dk_info['hrr_price']; hps = f"+{hp}" if hp > 0 else str(hp)
        plus = int(dk_info['hrr_line'] + 0.5)   # O/U line -> "X+" framing (O 1.5 = 2+ HRR)
        badges.append(f'<span class="dk-badge" style="background:#5a2d8a;">DK HRR: {plus}+ ({hps})</span>')
    dk_html = " ".join(badges) if badges else '<span class="dk-badge no-odds">No DK Line</span>'

    bvp_display = f"{row['BVP_Avg']:.3f}" if row['BVP_Avg'] > 0 else "—"

    # Dual-engine display: multiplicative score chip + disagreement flag
    mult_score = row.get('Mult_Score')
    mult_tier  = row.get('Mult_Tier', '')
    mult_chip  = ""
    if mult_score is not None:
        m_emoji = "🟢" if "Tier 1" in mult_tier else ("🟡" if "Tier 2" in mult_tier else "🔴")
        mult_chip = f'<span class="mult-chip">MULT: {mult_score} {m_emoji}</span>'
    disagree_flag = '<span class="disagree-flag">⚠ engines differ</span>' if row.get('Disagree') else ""

    # 🎯 HRR (hits+runs+RBI) readout: projection, model P(2+), and the DK 2+ line
    hrr_html = ""
    if row.get('HRR_Proj') is not None:
        p2 = row.get('HRR_P2')
        p2_str = f"{p2*100:.0f}%" if p2 is not None else "—"
        dk_hrr_bit = ""
        if dk_info.get('hrr_price') is not None and dk_info.get('hrr_line') is not None:
            hp = dk_info['hrr_price']; hps = f"+{hp}" if hp > 0 else str(hp)
            plus = int(dk_info['hrr_line'] + 0.5)
            imp = american_to_implied_prob(hp)
            edge = ""
            if p2 is not None and imp > 0:
                d = (p2 - imp) * 100
                col = "#4caf50" if d > 0 else "#888"
                edge = f' &nbsp;<span style="color:{col};">({d:+.0f} vs book)</span>'
            dk_hrr_bit = f' &nbsp;|&nbsp; <span>DK {plus}+</span>: {hps}{edge}'
        hrr_html = (f'<div class="stat-row" style="margin-top:6px;color:#9b7fff;">'
                    f'<span>🎯 Proj HRR</span>: {row["HRR_Proj"]} &nbsp;|&nbsp; '
                    f'<span>Model P(2+)</span>: {p2_str}{dk_hrr_bit}</div>')

    st.markdown(f"""
    <div class="{card_cls}">
        <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px;">
            <div style="display:flex; align-items:center; gap:12px;">
                <span class="player-score">{row['Score']}</span>
                <div>
                    <p class="player-name">#{idx} {html.escape(str(row['Player']))} {mult_chip}{disagree_flag}</p>
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
        {hrr_html}
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
# EXECUTE AUTO-GRADER — in the background, so it never blocks first paint
# ============================================================
if SUPABASE_URL:
    _now = now_eastern()
    _last = st.session_state.get('last_autograde_time')
    if not _last or (_now - _last).total_seconds() >= 1800:
        st.session_state['last_autograde_time'] = _now
        threading.Thread(target=auto_grade_worker, daemon=True).start()

# ============================================================
# DAILY AUTO-RUN — morning board + briefing, kicked by any visit (incl. the
# keep-awake robot) after 9am ET. Dedup via an atomic marker row, so this is
# safe to fire on every session; it becomes a no-op after the first run.
# ============================================================
if SUPABASE_URL and briefing is not None and not st.session_state.get('autorun_kicked'):
    st.session_state['autorun_kicked'] = True
    threading.Thread(
        target=briefing.daily_autorun,
        kwargs=dict(supabase_url=SUPABASE_URL, db_headers=DB_HEADERS,
                    db_headers_upsert=DB_HEADERS_UPSERT,
                    odds_api_key=ODDS_API_KEY, ntfy_topic=NTFY_TOPIC),
        daemon=True).start()

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
    tab1, tab2, tab3, tab5 = st.tabs([
        "🔥 Offense Top Matchups",
        "⚡ Strikeout Engine",
        "📊 System Tracker",
        "🎯 Lock of the Day"
    ])

    # ----------------------------------------------------------
    # TAB 1 — OFFENSIVE ENGINE
    # ----------------------------------------------------------
    with tab1:
        # --- 📰 Today's Briefing (auto-saved by the morning robot) ---
        if SUPABASE_URL:
            try:
                _b = http_get(f"{SUPABASE_URL}/rest/v1/predictions"
                              f"?date=eq.{date_str}&player_id=gt.0&graded=eq.0"
                              f"&select=player_name,score,tier,odds_price&order=score.desc&limit=3",
                              headers=DB_HEADERS)
                _rows = _b.json() if _b.status_code == 200 else []
                if _rows:
                    _top = " · ".join(f"**{r['player_name']}** {r['score']}" for r in _rows)
                    st.success(f"📰 Today's picks are already saved (auto-run this morning). Top of the board: {_top}")
            except Exception:
                pass

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

                # Opposing starter's FIP is the same for every Reds hitter — compute once.
                opp_fip_val = 4.00
                if adv_stats:
                    try:    opp_fip_val = float(calculate_fip(adv_stats))
                    except Exception: opp_fip_val = 4.00

                # Decide who we actually score (respect "hide bench")
                to_score = []
                for name, p_id in hitters.items():
                    if reds_batting_order and show_starters and p_id not in reds_batting_order:
                        continue
                    to_score.append((name, p_id))

                # Bullpen ERA is the same for every Reds hitter — pull once for HRR.
                try:    bullpen_era = float(opp_bullpen.get('era', 4.0) or 4.0)
                except Exception: bullpen_era = 4.0

                pb = st.progress(0, text=f"Scoring {len(to_score)} hitters...")
                scan_results = pipeline.score_hitters(
                    FETCH, to_score, current_year, split_code, split_label,
                    reds_batting_order, park_name, pitcher_score, opp_fip_val,
                    bullpen_era, live_odds, opp_pitcher_id,
                    progress_cb=lambda frac, nm: pb.progress(frac, text=f"Scoring {nm}..."),
                    thread_hook=_st_thread_hook)
                pb.empty()

                # --- Save to Supabase (UPSERT w/ odds at pick time) ---
                if SUPABASE_URL:
                    if is_pregame:
                        insert_data = pipeline.hitting_payload(
                            scan_results, date_str, game_pk, opp_pitcher_name)
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

                # --- Board (all hitters, ranked) ---
                if scan_results:
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
                    payload = pipeline.pitching_payload(k_projections, date_str, game_pk)
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
                        # Deep analytics (calibration, Brier, tier breakdowns, threshold
                        # sweep) intentionally live OFF-page now: the data is all saved,
                        # and the Export button + backtest.py recompute them on demand.
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
                        auto_grade_worker()   # run synchronously — user wants results now
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
    # TAB 5 — LOCK OF THE DAY (league-wide strikeout edge hunter)
    # ----------------------------------------------------------
    with tab5:
        render_lock_of_the_day(date_str, current_year)

else:
    st.info("🌴 **The Reds are off today** — the Reds-specific boards are hidden, "
            "but the league-wide tools still work.")
    render_lock_of_the_day(date_str, current_year)
