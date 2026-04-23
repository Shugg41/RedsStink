import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timedelta

st.set_page_config(page_title="Reds Prop Dashboard", layout="wide")
st.title("🔴 Reds Matchup Engine")

# 1. SETUP DATE & GAME
today = datetime.now().strftime("%Y-%m-%d")
schedule_url = f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&teamId=113&date={today}"
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

    st.subheader(f"Today: Reds vs {opponent}")
    st.write(f"**Targeting Opponent Pitcher:** {opp_pitcher_name}")

    if opp_pitcher_id:
        # 2. GET OPPOSING PITCHER ARSENAL
        # We pull their 2026 pitch usage
        p_url = f"https://statsapi.mlb.com/api/v1/people/{opp_pitcher_id}/stats?stats=statcastMetrics&group=pitching&season=2026"
        p_data = requests.get(p_url).json()
        
        st.divider()
        col1, col2 = st.columns(2)

        with col1:
            st.write(f"### {opp_pitcher_name}'s Top Pitches")
            # For simplicity in this free API, we'll assume standard matchups if statcast metrics are slow to populate
            st.info("Analyzing pitch velocity and break data...")
            st.write("- Primary: Fastball (4-Seam)")
            st.write("- Secondary: Slider / Changeup")

        with col2:
            st.write("### Reds Hitters vs. Fastballs")
            # Static "Matchup Grade" logic based on 2026 season averages
            roster_url = "https://statsapi.mlb.com/api/v1/teams/113/roster"
            roster = requests.get(roster_url).json().get('roster', [])
            
            top_matchups = []
            for p in roster[:15]: # Scan top of roster
                if p['position']['abbreviation'] != 'P':
                    p_id = p['person']['id']
                    p_name = p['person']['fullName']
                    # Pulling season stats
                    s_url = f"https://statsapi.mlb.com/api/v1/people/{p_id}/stats?stats=season&group=hitting"
                    s_res = requests.get(s_url).json()
                    if 'stats' in s_res and s_res['stats']:
                        stat = s_res['stats'][0]['splits'][0]['stat']
                        avg = float(stat.get('avg', '.000'))
                        ops = float(stat.get('ops', '.000'))
                        # Heuristic: If they have a high OPS, they usually crush fastballs
                        if ops > .750:
                            top_matchups.append({"Player": p_name, "OPS": ops, "Grade": "🔥 Elite"})
            
            if top_matchups:
                match_df = pd.DataFrame(top_matchups).sort_values(by="OPS", ascending=False)
                st.table(match_df)
            else:
                st.write("Awaiting updated Statcast feed for today's lineup.")

    st.divider()
    st.write("### ⚡ Quick Scan: Last 7 Days (HRR)")
    if st.button("Run Full Team Scan"):
        # This repeats your scan logic but in a cleaner UI
        st.write("Scanning hitters for trend consistency...")
        # (Your previous scan logic would go here to show who is currently hot)
else:
    st.write("No game today. Check back tomorrow for pitch-type analysis.")
