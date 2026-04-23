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
tab1, tab2 = st.tabs(["Offensive Props", "Pitcher Props"])

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
    st.info(f"System ready to pull strikeout metrics for {pitcher_name} (ID: {pitcher_id}).")
