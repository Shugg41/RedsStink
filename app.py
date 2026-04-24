import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timedelta
import plotly.express as px

# --- PAGE CONFIG ---
st.set_page_config(page_title="Reds Prop Dashboard", page_icon="🔴", layout="wide")

# --- CUSTOM CSS ---
st.markdown("""
    <style>
    .big-font { font-size:20px !important; font-weight: bold; }
    .metric-card { background-color: #1E1E1E; padding: 15px; border-radius: 10px; border-left: 5px solid #C6011F; }
    </style>
""", unsafe_allow_html=True)

# --- API HELPERS & CACHING ---
@st.cache_data(ttl=3600)
def get_schedule(date_str):
    url = f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&teamId=113&date={date_str}"
    return requests.get(url).json()

@st.cache_data(ttl=86400)
def get_roster():
    url = "https://statsapi.mlb.com/api/v1/teams/113/roster"
    return requests.get(url).json().get('roster', [])

@st.cache_data(ttl=3600)
def get_season_stats(player_id, group, year):
    url = f"https://statsapi.mlb.com/api/v1/people/{player_id}/stats?stats=season&group={group}&season={year}"
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

# --- SIDEBAR & GLOBAL ---
with st.sidebar:
    st.image("https://upload.wikimedia.org/wikipedia/commons/thumb/0/01/Cincinnati_Reds_Logo.svg/1200px-Cincinnati_Reds_Logo.svg.png", width=100)
    st.title("Settings")
    selected_date = st.date_input("Select Game Date", datetime.now())
    date_str = selected_date.strftime("%Y-%m-%d")
    current_year = selected_date.year

st.title("🔴 Reds Matchup & Prop Engine")
st.markdown("Find your betting edges with real-time MLB API data, BvP matchups, and objective confidence ratings.")

# --- MATCHUP ENGINE ---
data = get_schedule(date_str)

if data['totalGames'] > 0:
    game = data['dates'][0]['games'][0]
    away_team = game['teams']['away']['team']['name']
    home_team = game['teams']['home']['team']['name']
    
    # Determine Opponent & Pitcher
    if "Reds" in away_team:
        opponent = home_team
        opp_pitcher_data = game['teams']['home'].get('probablePitcher', {})
    else:
        opponent = away_team
        opp_pitcher_data = game['teams']['away'].get('probablePitcher', {})

    opp_pitcher_name = opp_pitcher_data.get('fullName', 'TBD')
    opp_pitcher_id = opp_pitcher_data.get('id', None)

    # Matchup Header
    st.subheader(f"🏟️ Matchup: Reds vs {opponent}")
    if opp_pitcher_name != 'TBD':
        st.info(f"**Targeting Opposing Starter:** {opp_pitcher_name} (ID: {opp_pitcher_id})", icon="🎯")
    else:
        st.warning("Opposing Pitcher: TBD (BvP stats will be unavailable until lineup is submitted)", icon="⚠️")
    
    st.divider()
    
    # --- PULL ROSTER ---
    roster_res = get_roster()
    hitters = {p['person']['fullName']: p['person']['id'] for p in roster_res if p['position']['abbreviation'] != 'P'}
    pitchers = {p['person']['fullName']: p['person']['id'] for p in roster_res if p['position']['abbreviation'] == 'P'}

    # --- TABS ---
    tab1, tab2, tab3 = st.tabs(["🏏 Offensive Props", "⚾ Pitcher Props", "🎯 The Confidence Engine"])

    # ----------------------------
    # TAB 1: BATTERS & BvP
    # ----------------------------
    with tab1:
        col1, col2 = st.columns([1, 2])
        with col1:
            batter_name = st.selectbox("Select Reds Batter", sorted(hitters.keys()))
            b_id = hitters[batter_name]
        
        # Season Stats
        s_data = get_season_stats(b_id, "hitting", current_year)
        try:
            stat = s_data['stats'][0]['splits'][0]['stat']
            hrr = stat.get('hits', 0) + stat.get('runs', 0) + stat.get('rbi', 0)
            ops_val = float(stat.get('ops', '.000'))
            
            st.markdown(f"### {current_year} Season Metrics")
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("AVG", stat.get('avg', '.000'))
            m2.metric("OPS", f"{ops_val:.3f}")
            m3.metric("Total Bases", stat.get('totalBases', 0))
            m4.metric("HRR (Hits+Runs+RBI)", hrr)
                
        except (KeyError, IndexError, ValueError):
            st.warning(f"No {current_year} regular season stats found for {batter_name}.")

        st.divider()

        # Pitch Arsenal Scouting Report
        st.markdown(f"### 🎯 Scouting Report: {opp_pitcher_name}'s Arsenal")
        if opp_pitcher_id:
            arsenal = get_pitch_arsenal(opp_pitcher_id, current_year)
            if arsenal:
                arsenal = sorted(arsenal, key=lambda x: x['stat'].get('usagePercentage', 0), reverse=True)
                
                a1, a2, a3 = st.columns(3)
                cols = [a1, a2, a3]
                
                for i in range(min(len(arsenal), 3)):
                    pitch = arsenal[i]
                    p_name = pitch['stat']['type']['description']
                    p_usage = pitch['stat'].get('usagePercentage', 0)
                    p_speed = pitch['stat'].get('averageSpeed', 0)
                    cols[i].metric(p_name, f"{p_usage}% Usage", f"{p_speed} mph")
            else:
                st.info(f"Pitch arsenal data not yet available for {opp_pitcher_name}.")
        else:
            st.info("Awaiting opposing pitcher announcement for arsenal breakdown.")

        st.divider()

        # BvP Stats (Batter vs Pitcher)
        st.markdown("### ⚔️ Batter vs. Pitcher (BvP) History")
        if opp_pitcher_id:
            bvp = get_bvp_stats(b_id, opp_pitcher_id)
            if bvp:
                st.success(f"Historical Matchup Data vs {opp_pitcher_name} found!")
                b1, b2, b3, b4 = st.columns(4)
                b1.metric("At Bats", bvp.get('atBats', 0))
                b2.metric("Hits", bvp.get('hits', 0))
                b3.metric("Home Runs", bvp.get('homeRuns', 0))
                b4.metric("BvP AVG", bvp.get('avg', '.000'))
            else:
                st.info(f"No historical at-bats for {batter_name} vs {opp_pitcher_name}.")
        else:
            st.info("Awaiting opposing pitcher announcement for BvP stats.")

    # ----------------------------
    # TAB 2: PITCHERS
    # ----------------------------
    with tab2:
        col1, col2 = st.columns([1, 2])
        with col1:
            pitcher_name = st.selectbox("Select Reds Pitcher", sorted(pitchers.keys()))
            p_id = pitchers[pitcher_name]
            
        p_data = get_season_stats(p_id, "pitching", current_year)
        try:
            p_stat = p_data['stats'][0]['splits'][0]['stat']
            
            st.markdown(f"### {current_year} Pitching Metrics")
            pm1, pm2, pm3, pm4 = st.columns(4)
            pm1.metric("ERA", p_stat.get('era', '0.00'))
            pm2.metric("WHIP", p_stat.get('whip', '0.00'))
            pm3.metric("Strikeouts", p_stat.get('strikeOuts', 0))
            pm4.metric("Innings Pitched", p_stat.get('inningsPitched', '0.0'))
        except (KeyError, IndexError):
            st.warning(f"No {current_year} regular season stats found for {pitcher_name}.")

    # ----------------------------
    # TAB 3: THE CONFIDENCE ENGINE
    # ----------------------------
    with tab3:
        st.markdown("### 🎯 The Confidence Engine")
        st.caption("Grades the roster objectively on 3 tests: Consistency (Hits in 7 of last 10 games), Performance (Season OPS > .750), and Matchup History (BvP AVG > .250).")
        
        if st.button("Run Algorithm", type="primary"):
            if not opp_pitcher_id:
                st.error("Cannot run full algorithm. The opposing pitcher is TBD, so we cannot calculate the BvP matchup test. Check back closer to first pitch.")
            else:
                progress_bar = st.progress(0, text="Evaluating roster...")
                scan_results = []
                total_hitters = len(hitters)
                
                for i, (name, p_id) in enumerate(hitters.items()):
                    progress_bar.progress((i + 1) / total_hitters, text=f"Evaluating {name}...")
                    
                    points = 0
                    traits = []
                    
                    # Test 1: Consistency (Hits in 7 of last 10 games)
                    logs = get_game_logs(p_id, current_year)
                    if logs:
                        recent_logs = logs[-10:] # Get up to the last 10 games
                        hit_games = sum(1 for game in recent_logs if game.get('stat', {}).get('hits', 0) > 0)
                        if hit_games >= 7:
                            points += 1
                            traits.append(f"Consistent ({hit_games} of last 10 games with a hit)")
                    
                    # Test 2: Performance (Season OPS > .750)
                    s_data = get_season_stats(p_id, "hitting", current_year)
                    try:
                        ops = float(s_data['stats'][0]['splits'][0]['stat'].get('ops', '.000'))
                        if ops > 0.750:
                            points += 1
                            traits.append(f"Elite Baseline ({ops:.3f} OPS)")
                    except (KeyError, IndexError, ValueError):
                        pass
                        
                    # Test 3: Matchup History (BvP AVG > .250)
                    bvp = get_bvp_stats(p_id, opp_pitcher_id)
                    if bvp:
                        bvp_avg = float(bvp.get('avg', '.000'))
                        if bvp_avg > 0.250:
                            points += 1
                            traits.append(f"Owns Matchup ({bvp_avg:.3f} BvP AVG)")
                            
                    # Map to Tiers
                    if points == 3:
                        tier = "🟢 Tier 1 (Core Play)"
                    elif points == 2:
                        tier = "🟡 Tier 2 (Playable)"
                    else:
                        tier = "🔴 Tier 3 (Fade)"
                        
                    scan_results.append({
                        "Player": name,
                        "Tier": tier,
                        "Score": points,
                        "Edge Identified": ", ".join(traits) if traits else "No edge found"
                    })
                
                progress_bar.empty()
                
                if scan_results:
                    df = pd.DataFrame(scan_results).sort_values(by="Score", ascending=False)
                    # Clean up output table
                    st.dataframe(df[['Player', 'Tier', 'Edge Identified']], hide_index=True, use_container_width=True)
                else:
                    st.info("No data available to process.")

else:
    st.warning("🌴 **OFF DAY:** The Reds are resting today.")
    st.info("Check **Tomorrow (April 24)** in the sidebar to scout the Tigers series. Framber Valdez (LHP) is the projected starter.")
