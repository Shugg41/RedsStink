import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timedelta
import plotly.express as px

# PAGE CONFIG
st.set_page_config(page_title="Reds Prop Dashboard", page_icon="🔴", layout="wide")

# CUSTOM CSS
st.markdown("""
    <style>
    .big-font { font-size:20px !important; font-weight: bold; }
    .metric-card { background-color: #1E1E1E; padding: 15px; border-radius: 10px; border-left: 5px solid #C6011F; }
    </style>
""", unsafe_allow_html=True)

# API HELPERS AND CACHING
@st.cache_data(ttl=3600)
def get_schedule(date_str):
    url = f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&teamId=113&date={date_str}"
    return requests.get(url).json()

@st.cache_data(ttl=86400)
def get_roster(team_id):
    url = f"https://statsapi.mlb.com/api/v1/teams/{team_id}/roster"
    return requests.get(url).json().get('roster', [])

@st.cache_data(ttl=3600)
def get_season_stats(player_id, group, year, split=None):
    url = f"https://statsapi.mlb.com/api/v1/people/{player_id}/stats?stats=season&group={group}&season={year}"
    if split:
        url = f"https://statsapi.mlb.com/api/v1/people/{player_id}/stats?stats=statSplits&group={group}&season={year}&sitCode={split}"
    return requests.get(url).json()

@st.cache_data(ttl=3600)
def get_bvp_stats(batter_id, pitcher_id):
    if not pitcher_id: return None
    url = f"https://statsapi.mlb.com/api/v1/people/{batter_id}/stats?stats=vsPlayer&opposingPlayerId={pitcher_id}&group=hitting"
    res = requests.get(url).json()
    try:
        return res['stats'][0]['splits'][0]['stat']
    except (KeyError, IndexError):
        return None

@st.cache_data(ttl=3600)
def get_pitch_arsenal(pitcher_id, year):
    if not pitcher_id: return []
    url = f"https://statsapi.mlb.com/api/v1/people/{pitcher_id}/stats?stats=pitchArsenal&group=pitching&season={year}"
    res = requests.get(url).json()
    try:
        return res['stats'][0]['splits']
    except (KeyError, IndexError):
        return []

@st.cache_data(ttl=3600)
def get_game_logs(player_id, year):
    url = f"https://statsapi.mlb.com/api/v1/people/{player_id}/stats?stats=gameLog&group=hitting&season={year}"
    res = requests.get(url).json()
    try:
        return res['stats'][0]['splits']
    except (KeyError, IndexError):
        return []

@st.cache_data(ttl=86400)
def get_pitcher_hand(pitcher_id):
    if not pitcher_id: return "R"
    url = f"https://statsapi.mlb.com/api/v1/people/{pitcher_id}"
    res = requests.get(url).json()
    try:
        return res['people'][0]['pitchHand']['code']
    except (KeyError, IndexError):
        return "R"

# SIDEBAR AND GLOBAL
with st.sidebar:
    st.image("https://upload.wikimedia.org/wikipedia/commons/thumb/0/01/Cincinnati_Reds_Logo.svg/1200px-Cincinnati_Reds_Logo.svg.png", width=100)
    st.title("Settings")
    selected_date = st.date_input("Select Game Date", datetime.now())
    date_str = selected_date.strftime("%Y-%m-%d")
    current_year = selected_date.year

st.title("🔴 Reds Matchup & Prop Engine")
st.markdown("Find your betting edges with real-time MLB API data, BvP matchups, and objective confidence ratings.")

# MATCHUP ENGINE
data = get_schedule(date_str)

if data['totalGames'] > 0:
    game = data['dates'][0]['games'][0]
    away_team = game['teams']['away']['team']['name']
    home_team = game['teams']['home']['team']['name']
    
    if "Reds" in away_team:
        opponent = home_team
        opp_team_id = game['teams']['home']['team']['id']
        opp_pitcher_data = game['teams']['home'].get('probablePitcher', {})
    else:
        opponent = away_team
        opp_team_id = game['teams']['away']['team']['id']
        opp_pitcher_data = game['teams']['away'].get('probablePitcher', {})

    opp_pitcher_name = opp_pitcher_data.get('fullName', 'TBD')
    opp_pitcher_id = opp_pitcher_data.get('id', None)

    st.subheader(f"🏟️ Matchup: Reds vs {opponent}")
    
    if opp_pitcher_name == 'TBD':
        st.warning("Official lineup card not submitted. Select the starter manually.", icon="⚠️")
        opp_roster = get_roster(opp_team_id)
        opp_pitchers = {p['person']['fullName']: p['person']['id'] for p in opp_roster if p['position']['abbreviation'] == 'P'}
        
        if opp_pitchers:
            manual_pitcher = st.selectbox(f"Select {opponent} Starter:", ["Select..."] + sorted(opp_pitchers.keys()))
            if manual_pitcher != "Select...":
                opp_pitcher_name = manual_pitcher
                opp_pitcher_id = opp_pitchers[manual_pitcher]

    pitcher_hand = get_pitcher_hand(opp_pitcher_id)
    split_code = "vl" if pitcher_hand == "L" else "vr"
    split_label = f"LHP" if pitcher_hand == "L" else f"RHP"

    if opp_pitcher_name != 'TBD' and opp_pitcher_id:
        st.info(f"**Targeting Opposing Starter:** {opp_pitcher_name} ({split_label})", icon="🎯")
    
    st.divider()
    
    roster_res = get_roster(113)
    hitters = {p['person']['fullName']: p['person']['id'] for p in roster_res if p['position']['abbreviation'] != 'P'}
    pitchers = {p['person']['fullName']: p['person']['id'] for p in roster_res if p['position']['abbreviation'] == 'P'}

    tab1, tab2, tab3 = st.tabs(["🏏 Offensive Matchups", "⚾ Pitcher Props", "🎯 The Confidence Engine"])

    # TAB 1 FULL OFFENSE OVERVIEW
    with tab1:
        st.markdown(f"### 🎯 Scouting Report: {opp_pitcher_name}'s Arsenal")
        if opp_pitcher_id:
            arsenal = get_pitch_arsenal(opp_pitcher_id, current_year)
            if arsenal:
                arsenal = sorted(arsenal, key=lambda x: x['stat'].get('percentage', 0), reverse=True)
                
                a1, a2, a3 = st.columns(3)
                cols = [a1, a2, a3]
                
                for i in range(min(len(arsenal), 3)):
                    pitch = arsenal[i]
                    p_name = pitch['stat']['type']['description']
                    p_usage = round(pitch['stat'].get('percentage', 0), 1)
                    p_speed = round(pitch['stat'].get('averageSpeed', 0), 1)
                    cols[i].metric(p_name, f"{p_usage}%", f"{p_speed} mph")
            else:
                st.info("Arsenal data not available.")
        else:
            st.info("Select a pitcher to see arsenal.")

        st.divider()

        st.markdown("### ⚔️ Roster Matchup Matrix")
        st.caption(f"Comparing overall season totals, specific splits vs {split_label}, and last 7 games performance.")

        if st.button("Load Full Team Comparison", type="primary"):
            progress_bar = st.progress(0, text="Calculating splits and recent trends...")
            roster_data = []
            total_hitters = len(hitters)

            for i, (name, p_id) in enumerate(hitters.items()):
                progress_bar.progress((i + 1) / total_hitters, text=f"Analyzing {name}...")

                p_ops = ".000"
                split_ops = ".000"
                l7_hits = 0
                l7_hrr = 0

                s_data = get_season_stats(p_id, "hitting", current_year)
                try:
                    stat = s_data['stats'][0]['splits'][0]['stat']
                    p_ops = f"{float(stat.get('ops', '.000')):.3f}"
                except: pass

                split_data = get_season_stats(p_id, "hitting", current_year, split=split_code)
                try:
                    sp_stat = split_data['stats'][0]['splits'][0]['stat']
                    split_ops = f"{float(sp_stat.get('ops', '.000')):.3f}"
                except: pass

                logs = get_game_logs(p_id, current_year)
                if logs:
                    recent = logs[-7:]
                    l7_hits = sum(g.get('stat', {}).get('hits', 0) for g in recent)
                    l7_hrr = sum((g.get('stat', {}).get('hits', 0) + g.get('stat', {}).get('runs', 0) + g.get('stat', {}).get('rbi', 0)) for g in recent)

                roster_data.append({
                    "Player": name,
                    "Season OPS": p_ops,
                    f"OPS vs {split_label}": split_ops,
                    "L7 Hits": l7_hits,
                    "L7 HRR": l7_hrr
                })

            progress_bar.empty()

            if roster_data:
                df = pd.DataFrame(roster_data).sort_values(by="L7 HRR", ascending=False)
                st.dataframe(df, hide_index=True, use_container_width=True)

    # TAB 2 PITCHERS
    with tab2:
        st.write("Pitcher Analysis placeholder")

    # TAB 3 THE CONFIDENCE ENGINE
    with tab3:
        st.markdown("### 🎯 The Confidence Engine")
        if st.button("Run Algorithm", type="primary", key="engine_btn"):
            if not opp_pitcher_id:
                st.error("Select pitcher first.")
            else:
                scan_results = []
                for name, p_id in hitters.items():
                    points = 0
                    traits = []
                    
                    logs = get_game_logs(p_id, current_year)
                    if logs:
                        hit_games = sum(1 for g in logs[-10:] if g.get('stat', {}).get('hits', 0) > 0)
                        if hit_games >= 7:
                            points += 1
                            traits.append("Consistent")
                    
                    sp_data = get_season_stats(p_id, "hitting", current_year, split=split_code)
                    try:
                        sp_ops = float(sp_data['stats'][0]['splits'][0]['stat'].get('ops', 0))
                        if sp_ops > 0.800:
                            points += 1
                            traits.append(f"Crushes {split_label}")
                    except: pass
                        
                    bvp = get_bvp_stats(p_id, opp_pitcher_id)
                    if bvp and float(bvp.get('avg', 0)) > 0.250:
                        points += 1
                        traits.append("Owns Pitcher")
                            
                    tier = "🟢 Tier 1" if points == 3 else "🟡 Tier 2" if points == 2 else "🔴 Tier 3"
                    scan_results.append({"Player": name, "Tier": tier, "Score": points, "Edge": ", ".join(traits)})
                
                st.dataframe(pd.DataFrame(scan_results).sort_values(by="Score", ascending=False), hide_index=True)

else:
    st.warning("🌴 **OFF DAY:** The Reds are resting today.")
