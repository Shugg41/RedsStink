import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timedelta

st.set_page_config(page_title="Reds Prop Dashboard", layout="wide")
st.title("🔴 Reds Matchup & Prop Engine")

# 1. DATE SELECTION
selected_date = st.date_input("Select Game Date", datetime.now())
date_str = selected_date.strftime("%Y-%m-%d")

# 2. MATCHUP ENGINE
schedule_url = f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&teamId=113&date={date_str}"
data = requests.get(schedule_url).json()

if data['totalGames'] > 0:
    game = data['dates'][0]['games'][0]
    away_team = game['teams']['away']['team']['name']
    home_team = game['teams']['home']['team']['name']
    
    # Identify the OPPOSING pitcher
    if "Reds" in away_team:
        opp_pitcher_name = game['teams']['home'].get('probablePitcher', {}).get('fullName', 'TBD')
        opp_pitcher_id = game['teams']['home'].get('probablePitcher', {}).get('id', None)
        opponent = home_team
    else:
        opp_pitcher_name = game['teams']['away'].get('probablePitcher', {}).get('fullName', 'TBD')
        opp_pitcher_id = game['teams']['away'].get('probablePitcher', {}).get('id', None)
        opponent = away_team

    st.subheader(f"Matchup: Reds vs {opponent}")
    st.write(f"**Targeting Opponent Pitcher:** {opp_pitcher_name}")
    
    st.divider()
    
    # 3. TABS
    tab1, tab2, tab3 = st.tabs(["Offensive Props", "Pitcher Props", "System Scans"])

    # Pull Roster for dropdowns
    roster_url = "https://statsapi.mlb.com/api/v1/teams/113/roster"
    roster_res = requests.get(roster_url).json().get('roster', [])
    hitters = {p['person']['fullName']: p['person']['id'] for p in roster_res if p['position']['abbreviation'] != 'P'}
    pitchers = {p['person']['fullName']: p['person']['id'] for p in roster_res if p['position']['abbreviation'] == 'P'}

    with tab1:
        st.header("Batter Analysis")
        batter_name = st.selectbox("Select Reds Batter", sorted(hitters.keys()))
        b_id = hitters[batter_name]
        
        # Pull 2026 Season Stats
        s_url = f"https://statsapi.mlb.com/api/v1/people/{b_id}/stats?stats=season&group=hitting"
        s_data = requests.get(s_url).json()
        if 'stats' in s_data and s_data['stats']:
            stat = s_data['stats'][0]['splits'][0]['stat']
            st.write(f"**2026 AVG:** {stat.get('avg', '.000')} | **OPS:** {stat.get('ops', '.000')}")
            hrr = stat.get('hits', 0) + stat.get('runs', 0) + stat.get('rbi', 0)
            st.metric("Season HRR", hrr)

    with tab2:
        st.header("Reds Pitcher Analysis")
        pitcher_name = st.selectbox("Select Reds Pitcher", sorted(pitchers.keys()))
        p_id = pitchers[pitcher_name]
        p_url = f"https://statsapi.mlb.com/api/v1/people/{p_id}/stats?stats=season&group=pitching"
        p_data = requests.get(p_url).json()
        if 'stats' in p_data and p_data['stats']:
            p_stat = p_data['stats'][0]['splits'][0]['stat']
            st.write(f"**ERA:** {p_stat.get('era', '0.00')} | **WHIP:** {p_stat.get('whip', '0.00')}")
            st.metric("Total Strikeouts", p_stat.get('strikeOuts', 0))

    with tab3:
        st.header("System Scans")
        if st.button("Scan Hottest Reds Hitters (Last 7 Days)"):
            with st.spinner("Calculating..."):
                scan_results = []
                start_date = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
                end_date = datetime.now().strftime("%Y-%m-%d")
                
                for name, p_id in hitters.items():
                    url = f"https://statsapi.mlb.com/api/v1/people/{p_id}/stats?stats=byDateRange&startDate={start_date}&endDate={end_date}&group=hitting"
                    res = requests.get(url).json()
                    if 'stats' in res and res['stats'] and res['stats'][0]['splits']:
                        s = res['stats'][0]['splits'][0]['stat']
                        hrr = s.get('hits',0) + s.get('runs',0) + s.get('rbi',0)
                        scan_results.append({"Player": name, "HRR": hrr, "TB": s.get('totalBases', 0), "OPS": s.get('ops', '.000')})
                
                if scan_results:
                    df = pd.DataFrame(scan_results).sort_values(by="HRR", ascending=False).head(5)
                    st.table(df)
else:
    st.write("No Reds game scheduled for this date. Select another date to scout.")
