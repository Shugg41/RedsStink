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

# Pull live Reds roster
roster_url = "https://statsapi.mlb.com/api/v1/teams/113/roster"
roster_req = requests.get(roster_url).json()

hitters = []
pitchers = []
for player in roster_req.get('roster', []):
    name = player['person']['fullName']
    position = player['position']['abbreviation']
    if position == 'P':
        pitchers.append(name)
    else:
        hitters.append(name)

hitters.sort()
pitchers.sort()

# Build the app tabs
tab1, tab2 = st.tabs(["Offensive Props", "Pitcher Props"])

with tab1:
    st.header("Batter Analysis")
    batter = st.selectbox("Select Reds Batter", hitters)
    st.info(f"System ready to pull 7-day rolling data for {batter}.")

with tab2:
    st.header("Pitcher Analysis")
    pitcher = st.selectbox("Select Reds Pitcher", pitchers)
    st.info(f"System ready to pull strikeout metrics for {pitcher}.")
