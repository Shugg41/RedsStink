import streamlit as st
import requests
import pandas as pd
from datetime import datetime

st.title("Reds Prop Dashboard")

# Add a date selector
selected_date = st.date_input("Select Game Date", datetime.now())
date_str = selected_date.strftime("%Y-%m-%d")

schedule_url = f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&teamId=113&date={date_str}"

response = requests.get(schedule_url)
data = response.json()

if data['totalGames'] > 0:
    game = data['dates'][0]['games'][0]
    away = game['teams']['away']['team']['name']
    home = game['teams']['home']['team']['name']
    st.subheader(f"Matchup: {away} at {home}")
    
    away_p = game['teams']['away'].get('probablePitcher', {}).get('fullName', 'TBD')
    home_p = game['teams']['home'].get('probablePitcher', {}).get('fullName', 'TBD')
    st.write(f"**Pitchers:** {away_p} vs {home_p}")
else:
    st.write("No Reds game scheduled for this date.")

st.divider()

# Pull live Reds roster with Player IDs
roster_url = "https://statsapi.mlb.com/api/v1/teams/113/roster"
roster_req = requests.get(roster_url).json()

hitters = {}
pitchers = {}
for player in roster_req.get('roster', []):
    name = player['person']['fullName']
    player_id = player['person']['id']
    position = player['position']['abbreviation']
    if position == 'P':
        pitchers[name] = player_id
    else:
        hitters[name] = player_id

hitter_names = sorted(list(hitters.keys()))
pitcher_names = sorted(list(pitchers.keys()))

# Build the app tabs
tab1, tab2, tab3 = st.tabs(["Offensive Props", "Pitcher Props", "System Picks"])

with tab1:
    st.header("Batter Analysis")
    batter_name = st.selectbox("Select Reds Batter", hitter_names)
    batter_id = hitters[batter_name]
    
    # Pull current season stats for the selected batter
    stats_url = f"https://statsapi.mlb.com/api/v1/people/{batter_id}/stats?stats=season&group=hitting"
    stats_req = requests.get(stats_url).json()
    
    if 'stats' in stats_req and stats_req['stats']:
        splits = stats_req['stats'][0]['splits']
        if splits:
            stat_line = splits[0]['stat']
            hits = stat_line.get('hits', 0)
            runs = stat_line.get('runs', 0)
            rbis = stat_line.get('rbi', 0)
            tb = stat_line.get('totalBases', 0)
            games = stat_line.get('gamesPlayed', 1)
            
            hrr = hits + runs + rbis
            hrr_per_game = round(hrr / games, 2)
            
            st.write(f"### 2026 Season Totals for {batter_name}")
            st.write(f"**Games Played:** {games}")
            st.write(f"**Total Bases:** {tb}")
            st.write(f"**Hits + Runs + RBIs (HRR):** {hrr}")
            st.write(f"**HRR per game:** {hrr_per_game}")
        else:
            st.write("No stats available for this player yet.")
    else:
        st.write("Could not retrieve stats.")

with tab2:
    st.header("Pitcher Analysis")
    pitcher_name = st.selectbox("Select Reds Pitcher", pitcher_names)
    pitcher_id = pitchers[pitcher_name]
    
    # Pull current season stats for the selected pitcher
    p_stats_url = f"https://statsapi.mlb.com/api/v1/people/{pitcher_id}/stats?stats=season&group=pitching"
    p_stats_req = requests.get(p_stats_url).json()
    
    if 'stats' in p_stats_req and p_stats_req['stats']:
        p_splits = p_stats_req['stats'][0]['splits']
        if p_splits:
            p_stat = p_splits[0]['stat']
            games_started = p_stat.get('gamesStarted', 0)
            innings = p_stat.get('inningsPitched', '0')
            strikeouts = p_stat.get('strikeOuts', 0)
            walks = p_stat.get('baseOnBalls', 0)
            
            if games_started > 0:
                k_per_start = round(strikeouts / games_started, 2)
            else:
                k_per_start = 0
            
            st.write(f"### 2026 Season Totals for {pitcher_name}")
            st.write(f"**Games Started:** {games_started}")
            st.write(f"**Innings Pitched:** {innings}")
            st.write(f"**Total Strikeouts:** {strikeouts}")
            st.write(f"**Total Walks:** {walks}")
            
            if games_started > 0:
                st.write(f"**Average Strikeouts per Start:** {k_per_start}")
            else:
                st.write("*(Reliever or no starts recorded)*")
        else:
            st.write("No stats available for this pitcher yet.")
    else:
        st.write("Could not retrieve stats.")

with tab3:
    st.header("System Scans")
    st.write("Find the strongest prop candidates based on the last 7 days of live game data.")
    
    if st.button("Scan Hottest Reds Hitters"):
        with st.spinner("Scanning active roster..."):
            target_list = []
            for name, p_id in hitters.items():
                url = f"https://statsapi.mlb.com/api/v1/people/{p_id}/stats?stats=last7Days&group=hitting"
                req = requests.get(url).json()
                if 'stats' in req and req['stats'] and req['stats'][0]['splits']:
                    stat = req['stats'][0]['splits'][0]['stat']
                    hrr = stat.get('hits', 0) + stat.get('runs', 0) + stat.get('rbi', 0)
                    tb = stat.get('totalBases', 0)
                    target_list.append({"Player": name, "HRR": hrr, "Total Bases": tb, "AVG": stat.get('avg', '.000')})
            
            if target_list:
                df = pd.DataFrame(target_list)
                df = df.sort_values(by="HRR", ascending=False).head(5)
                st.write("### Top 5 Offensive Targets")
                st.dataframe(df, hide_index=True)
            else:
                st.write("No recent data found. Team may be coming off a break.")
