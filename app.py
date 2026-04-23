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

# --- SIDEBAR & GLOBAL ---
with st.sidebar:
    st.image("https://upload.wikimedia.org/wikipedia/commons/thumb/0/01/Cincinnati_Reds_Logo.svg/1200px-Cincinnati_Reds_Logo.svg.png", width=100)
    st.title("Settings")
    selected_date = st.date_input("Select Game Date", datetime.now())
    date_str = selected_date.strftime("%Y-%m-%d")
    current_year = selected_date.year

st.title("🔴 Reds Matchup & Prop Engine")
st.markdown("Find your betting edges with real-time MLB API data, BvP matchups, and 7-day rolling performance metrics.")

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
        st.warning("Opposing Pitcher: TBD (BvP stats will be unavailable)", icon="⚠️")
    
    st.divider()
    
    # --- PULL ROSTER ---
    roster_res = get_roster()
    hitters = {p['person']['fullName']: p['person']['id'] for p in roster_res if p['position']['abbreviation'] != 'P'}
    pitchers = {p['person']['fullName']: p['person']['id'] for p in roster_res if p['position']['abbreviation'] == 'P'}

    # --- TABS ---
    tab1, tab2, tab3 = st.tabs(["🏏 Offensive Props (Hitters)", "⚾ Pitcher Props", "🔥 System Scans"])

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
            
            st.markdown(f"### {current_year} Season Metrics")
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("AVG", stat.get('avg', '.000'))
            m2.metric("OPS", stat.get('ops', '.000'))
            m3.metric("Total Bases", stat.get('totalBases', 0))
            m4.metric("HRR (Hits+Runs+RBI)", hrr)
        except (KeyError, IndexError):
            st.warning(f"No {current_year} regular season stats found for {batter_name}.")

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
    # TAB 3: SYSTEM SCANS
    # ----------------------------
    with tab3:
        st.markdown("### 🔥 Find the Edge: Hot Hitters (Last 7 Days)")
        st.caption("Scans the entire Reds roster to find the hottest bats based on HRR (Hits + Runs + RBIs) and Total Bases.")
        
        if st.button("Run Prop Scanner", type="primary"):
            progress_bar = st.progress(0, text="Initializing Scan...")
            scan_results = []
            
            start_date = (selected_date - timedelta(days=7)).strftime("%Y-%m-%d")
            end_date = date_str
            
            total_hitters = len(hitters)
            
            for i, (name, p_id) in enumerate(hitters.items()):
                progress_bar.progress((i + 1) / total_hitters, text=f"Querying {name}...")
                
                url = f"https://statsapi.mlb.com/api/v1/people/{p_id}/stats?stats=byDateRange&startDate={start_date}&endDate={end_date}&group=hitting"
                try:
                    res = requests.get(url).json()
                    if 'stats' in res and res['stats'] and res['stats'][0]['splits']:
                        s = res['stats'][0]['splits'][0]['stat']
                        hrr = s.get('hits', 0) + s.get('runs', 0) + s.get('rbi', 0)
                        scan_results.append({
                            "Player": name, 
                            "HRR": hrr, 
                            "Total Bases": s.get('totalBases', 0), 
                            "AVG": float(s.get('avg', '.000')),
                            "OPS": float(s.get('ops', '.000'))
                        })
                except Exception as e:
                    pass # Silently skip players with no data in range
            
            progress_bar.empty()
            
            if scan_results:
                df = pd.DataFrame(scan_results).sort_values(by="HRR", ascending=False).head(8)
                
                # Interactive Chart
                fig = px.bar(
                    df, x='Player', y='HRR', color='Total Bases',
                    title=f"Top Trending Reds (Last 7 Days)",
                    hover_data=['AVG', 'OPS'],
                    color_continuous_scale='Reds',
                    text_auto=True
                )
                fig.update_layout(xaxis_title="", yaxis_title="HRR (Hits + Runs + RBI)", template="plotly_dark")
                st.plotly_chart(fig, use_container_width=True)
                
                # Raw Data Expander
                with st.expander("View Raw Scanner Data"):
                    st.dataframe(df.style.background_gradient(cmap='Reds', subset=['HRR', 'Total Bases']), use_container_width=True)
            else:
                st.info("No active hitter data found for the last 7 days. (Is it the off-season?)")
else:
    st.error(f"No Reds game scheduled for {selected_date.strftime('%b %d, %Y')}. Please pick another date from the sidebar.")
