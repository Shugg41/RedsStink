import streamlit as st
import requests
from datetime import datetime

st.title("Reds Prop Dashboard")

# Get today's date
today = datetime.now().strftime("%Y-%m-%d")

# MLB Stats API URL for the Reds (Team ID 113)
url = f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&teamId=113&date={today}"

response = requests.get(url)
data = response.json()

if data['totalGames'] > 0:
    game = data['dates'][0]['games'][0]
    away_team = game['teams']['away']['team']['name']
    home_team = game['teams']['home']['team']['name']
    
    st.subheader(f"Today's Matchup: {away_team} at {home_team}")
    
    # Extract probable pitchers
    away_pitcher = game['teams']['away'].get('probablePitcher', {}).get('fullName', 'TBD')
    home_pitcher = game['teams']['home'].get('probablePitcher', {}).get('fullName', 'TBD')
    
    st.write(f"**Pitching Matchup:** {away_pitcher} vs {home_pitcher}")
else:
    st.write("The Reds do not play today or the schedule is not posted.")
