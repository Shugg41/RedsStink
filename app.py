import streamlit as st
import requests
import pandas as pd
from datetime import datetime

# PAGE CONFIG
st.set_page_config(page_title="Reds Prop Dashboard", page_icon="🔴", layout="wide")

# CUSTOM CSS
st.markdown("""
    <style>
    .big-font { font-size:20px !important; font-weight: bold; }
    .metric-card { background-color: #1E1E1E; padding: 15px; border-radius: 10px; border-left: 5px solid #C6011F; }
    </style>
""", unsafe_allow_html=True)

# MATH HELPERS
def calc_ip(ip_str):
    try:
        ip = str(ip_str)
        if '.' in ip:
            whole, partial = ip.split('.')
            return int(whole) + (int(partial) / 3.0)
        return int(ip)
    except:
        return 0.0

# API HELPERS AND CACHING
@st.cache_data(ttl=3600)
def get_schedule(date_str):
    url = f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&teamId=113&date={date_str}&hydrate=probablePitcher"
    return requests.get(url).json()

@st.cache_data(ttl=300) 
def get_game_starters(game_pk):
    url = f"https://statsapi.mlb.com/api/v1.1/game/{game_pk}/feed/live"
    try:
        res = requests.get(url).json()
        starters = {'away': {'id': None, 'name': 'TBD'}, 'home': {'id': None, 'name': 'TBD'}}
        
        probables = res.get('gameData', {}).get('probablePitchers', {})
        if 'away' in probables:
            starters['away'] = {'id': probables['away']['id'], 'name': probables['away']['fullName']}
        if 'home' in probables:
            starters['home'] = {'id': probables['home']['id'], 'name': probables['home']['fullName']}
            
        status = res.get('gameData', {}).get('status', {}).get('statusCode', '')
        if status in ['I', 'F', 'O', 'CR'] or starters['away']['name'] == 'TBD':
            away_pitchers = res.get('liveData', {}).get('boxscore', {}).get('teams', {}).get('away', {}).get('pitchers', [])
            if away_pitchers:
                p_id = away_pitchers[0]
                player = res.get('gameData', {}).get('players', {}).get(f"ID{p_id}", {})
                if player:
                    starters['away'] = {'id': player.get('id'), 'name': player.get('fullName', 'TBD')}
                    
        if status in ['I', 'F', 'O', 'CR'] or starters['home']['name'] == 'TBD':
            home_pitchers = res.get('liveData', {}).get('boxscore', {}).get('teams', {}).get('home', {}).get('pitchers', [])
            if home_pitchers:
                p_id = home_pitchers[0]
                player = res.get('gameData', {}).get('players', {}).get(f"ID{p_id}", {})
                if player:
                    starters['home'] = {'id': player.get('id'), 'name': player.get('fullName', 'TBD')}
                    
        return starters
    except:
        return {'away': {'id': None, 'name': 'TBD'}, 'home': {'id': None, 'name': 'TBD'}}

@st.cache_data(ttl=86400)
def get_roster(team_id):
    url = f"https://statsapi.mlb.com/api/v1/teams/{team_id}/roster"
    return requests.get(url).json().get('roster', [])

@st.cache_data(ttl=3600)
def get_season_stats(player_id, group, year, split=None):
    url = f"https://statsapi.mlb.com/api/v1/people/{player_id}/stats?stats=season&group={group}&season={year}"
    if split:
        url = f"https://statsapi.mlb.com/api/v1/people/{player_id}/stats?stats=statSplits&group={group}&season={year}&sitCodes={split}"
    return requests.get(url).json()

@st.cache_data(ttl=3600)
def get_advanced_pitching(player_id, year):
    url = f"https://statsapi.mlb.com/api/v1/people/{player_id}/stats?stats=season,seasonAdvanced&group=pitching&season={year}"
    res = requests.get(url).json()
    stats = {}
    try:
        for split in res.get('stats', []):
            if split['type']['displayName'] in ['season', 'seasonAdvanced']:
                stats.update(split['splits'][0]['stat'])
        return stats
    except:
        return {}

@st.cache_data(ttl=86400)
def get_career_splits(player_id, group, split_code):
    url = f"https://statsapi.mlb.com/api/v1/people/{player_id}/stats?stats=careerStatSplits&group={group}&sitCodes={split_code}"
    return requests.get(url).json()

@st.cache_data(ttl=3600)
def get_team_splits(team_id, year, split_code):
    url = f"https://statsapi.mlb.com/api/v1/teams/{team_id}/stats?stats=statSplits&group=hitting&season={year}&sitCodes={split_code}"
    res = requests.get(url).json()
    try:
        return res['stats'][0]['splits'][0]['stat']
    except (KeyError, IndexError):
        return {}

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
def get_game_logs(player_id, year, group="hitting"):
    url = f"https://statsapi.mlb.com/api/v1/people/{player_id}/stats?stats=gameLog&group={group}&season={year}"
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
    st.image("https://a.espncdn.com/i/teamlogos/mlb/500/cin.png", width=100)
    st.title("Settings")
    selected_date = st.date_input("Select Game Date", datetime.now())
    date_str = selected_date.strftime("%Y-%m-%d")
    current_year = selected_date.year

st.title("🔴 Reds Matchup & Prop Engine")

# MATCHUP ENGINE
data = get_schedule(date_str)

reds_pitcher_name = "TBD"
reds_pitcher_id = None
opp_pitcher_name = "TBD"
opp_pitcher_id = None
opponent = "Unknown"
opp_team_id = None

if data['totalGames'] > 0:
    game = data['dates'][0]['games'][0]
    game_pk = game['gamePk']
    
    starters = get_game_starters(game_pk)
    
    away_team = game['teams']['away']['team']['name']
    home_team = game['teams']['home']['team']['name']
    
    if "Reds" in away_team:
        opponent = home_team
        opp_team_id = game['teams']['home']['team']['id']
        opp_pitcher_name = starters['home']['name']
        opp_pitcher_id = starters['home']['id']
        
        reds_pitcher_name = starters['away']['name']
        reds_pitcher_id = starters['away']['id']
    else:
        opponent = away_team
        opp_team_id = game['teams']['away']['team']['id']
        opp_pitcher_name = starters['away']['name']
        opp_pitcher_id = starters['away']['id']
        
        reds_pitcher_name = starters['home']['name']
        reds_pitcher_id = starters['home']['id']

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

    tab1, tab2 = st.tabs(["🏏 Offense Top Matchups", "⚾ Pitcher Strikeouts"])

    # TAB 1: OFFENSE MATCHUPS
    with tab1:
        adv_stats = {}
        pitcher_era_val = 3.50
        pitcher_score = 0
        
        # TARGET PROFILE SECTION
        if opp_pitcher_id:
            st.markdown(f"### 🎯 Target Profile: {opp_pitcher_name}")
            adv_stats = get_advanced_pitching(opp_pitcher_id, current_year)
            if adv_stats:
                try:
                    pitcher_era_val = float(adv_stats.get('era', '3.50'))
                except:
                    pitcher_era_val = 3.50
                    
                pitcher_score = 10 if pitcher_era_val >= 4.50 else (5 if pitcher_era_val >= 3.50 else 0)
                
                fip_val = adv_stats.get('fip', adv_stats.get('fieldingIndependentPitching', '0.00'))
                
                col_a, col_b, col_c, col_d, col_e = st.columns(5)
                col_a.metric("ERA", adv_stats.get('era', '0.00'))
                col_b.metric("WHIP", adv_stats.get('whip', '0.00'))
                col_c.metric("K/9", adv_stats.get('strikeoutsPer9Inn', '0.00'))
                col_d.metric("HR/9", adv_stats.get('homeRunsPer9', '0.00'))
                col_e.metric("FIP", fip_val, help="Fielding Independent Pitching. Lower is better. Exposes luck.")
            else:
                st.info("Advanced stats currently unavailable for this pitcher.")
            st.divider()

        st.markdown("### 🏆 Reds Hitting Board (100-Point Scale)")
        st.caption(f"Graded on Split Advantage (40), Form (40), Pitcher Vulnerability (10), and BvP History (10).")

        if st.button("Run Offensive Engine", type="primary"):
            if not opp_pitcher_id:
                st.error("Select pitcher first.")
            else:
                pb = st.progress(0, text="Evaluating roster...")
                scan_results = []
                total_hitters = len(hitters)

                for i, (name, p_id) in enumerate(hitters.items()):
                    pb.progress((i + 1) / total_hitters, text=f"Analyzing {name}...")
                    
                    # Test 1: Recent Form Averages
                    hit_games = 0
                    l10_total = 0
                    l10_h_avg = 0.0
                    l10_hrr_avg = 0.0
                    
                    logs = get_game_logs(p_id, current_year)
                    if logs:
                        l10_logs = logs[-10:]
                        l10_total = len(l10_logs)
                        hit_games = sum(1 for g in l10_logs if g.get('stat', {}).get('hits', 0) > 0)
                        
                        if l10_total > 0:
                            l10_h = sum(g.get('stat', {}).get('hits', 0) for g in l10_logs)
                            l10_h_avg = round(l10_h / l10_total, 1)

                            l10_hrr = sum((g.get('stat', {}).get('hits', 0) + g.get('stat', {}).get('runs', 0) + g.get('stat', {}).get('rbi', 0)) for g in l10_logs)
                            l10_hrr_avg = round(l10_hrr / l10_total, 1)
                    
                    # Test 2: vs LHP/RHP Performance
                    best_split_ops = 0.0
                    sp_data = get_season_stats(p_id, "hitting", current_year, split=split_code)
                    try:
                        best_split_ops = float(sp_data['stats'][0]['splits'][0]['stat'].get('ops', 0))
                    except: pass
                    
                    if best_split_ops == 0.0:
                        c_data = get_career_splits(p_id, "hitting", split_code)
                        try:
                            best_split_ops = float(c_data['stats'][0]['splits'][0]['stat'].get('ops', 0))
                        except: pass
                        
                    # Test 3: History (BvP)
                    bvp_avg = 0.0
                    bvp = get_bvp_stats(p_id, opp_pitcher_id)
                    if bvp:
                        bvp_avg = float(bvp.get('avg', 0))
                    
                    # MATH: 100-Point Scale
                    split_score = int(min(40, max(0, (best_split_ops - 0.500) * 100)))
                    
                    consistency_score = int((hit_games / 10.0) * 20) if l10_total > 0 else 0
                    hrr_score = int(min(20, (l10_hrr_avg / 2.5) * 20))
                    
                    bvp_score = 10 if bvp_avg >= 0.300 else (5 if bvp_avg >= 0.200 else 0)
                    
                    total_score = split_score + consistency_score + hrr_score + pitcher_score + bvp_score
                    
                    tier = "🟢 Tier 1" if total_score >= 80 else "🟡 Tier 2" if total_score >= 60 else "🔴 Tier 3"
                    
                    scan_results.append({
                        "Player": name, 
                        "Tier": tier, 
                        "Score": total_score,
                        "Raw_OPS": best_split_ops,
                        "L10_HRR": l10_hrr_avg,
                        "L10_Hits": l10_h_avg,
                        "BVP_Avg": bvp_avg,
                        "OPS_Display": f"{best_split_ops:.3f}"
                    })
                
                pb.empty()
                
                if scan_results:
                    df = pd.DataFrame(scan_results)
                    df = df.sort_values(by=['Score', 'Raw_OPS', 'L10_HRR'], ascending=[False, False, False])
                    
                    for idx, (index, row) in enumerate(df.iterrows()):
                        st.markdown(f"#### {idx + 1}. {row['Player']} - {row['Score']}/100 [{row['Tier']}]")
                        
                        m1, m2, m3, m4 = st.columns(4)
                        m1.metric(f"OPS vs {split_label}", row['OPS_Display'])
                        m2.metric("L10 HRR/G", row['L10_HRR'])
                        m3.metric("L10 Hits/G", row['L10_Hits'])
                        m4.metric("BvP AVG", f"{row['BVP_Avg']:.3f}")
                        
                        st.divider()

    # TAB 2: PITCHER STRIKEOUTS
    with tab2:
        col1, col2 = st.columns([1, 2])
        
        reds_pitchers_list = sorted(pitchers.keys())
        default_idx = 0
        if reds_pitcher_name in reds_pitchers_list:
            default_idx = reds_pitchers_list.index(reds_pitcher_name)
            
        with col1:
            pitcher_name = st.selectbox("Select Reds Pitcher", reds_pitchers_list, index=default_idx)
            p_id = pitchers[pitcher_name]
        
        reds_pitcher_hand = get_pitcher_hand(p_id)
        r_split_code = "vl" if reds_pitcher_hand == "L" else "vr"
        r_split_label = "LHP" if reds_pitcher_hand == "L" else "RHP"

        st.markdown(f"### 🎯 Pitcher Form (Last 5 Starts)")
        p_logs = get_game_logs(p_id, current_year, group="pitching")
        avg_k = 0.0
        if p_logs:
            l5_p = p_logs[-5:]
            total_k = sum(g.get('stat', {}).get('strikeOuts', 0) for g in l5_p)
            total_ip = sum(calc_ip(g.get('stat', {}).get('inningsPitched', '0.0')) for g in l5_p)
            total_pitches = sum(g.get('stat', {}).get('numberOfPitches', 0) for g in l5_p)
            starts = len(l5_p)
            
            avg_k = round(total_k / starts, 1)
            avg_ip = round(total_ip / starts, 1)
            
            p1, p2, p3 = st.columns(3)
            p1.metric("Avg Strikeouts", avg_k)
            p2.metric("Avg Innings Pitched", avg_ip)
            p3.metric("Avg Pitch Count", int(total_pitches / starts))
        else:
            st.info(f"No 2026 pitching logs found for {pitcher_name}.")

        st.divider()

        st.markdown(f"### ⚠️ Opponent Target: {opponent} vs {r_split_label}")
        opp_stats = get_team_splits(opp_team_id, current_year, r_split_code)
        if opp_stats:
            pa = opp_stats.get('plateAppearances', 0)
            so = opp_stats.get('strikeOuts', 0)
            if pa > 0:
                team_k_rate = round((so / pa) * 100, 1)
                
                league_avg_k_rate = 22.0
                matchup_multiplier = team_k_rate / league_avg_k_rate
                projected_k = round(avg_k * matchup_multiplier, 1)
                
                m1, m2 = st.columns(2)
                m1.metric("Team Strikeout Rate", f"{team_k_rate}%")
                m2.metric("Projected Strikeouts", projected_k, help="Pitcher's L5 Avg scaled by Opponent K-Rate compared to League Avg (22%).")
                
                if team_k_rate > 24.0:
                    st.success("High strikeout target. Matchup upgrades baseline expectations.")
                elif team_k_rate < 20.0:
                    st.error("Low strikeout target. Matchup downgrades baseline expectations.")
            else:
                st.info("Insufficient team data vs this handedness.")
        else:
            st.info("Team split data unavailable.")

        st.divider()

        st.markdown("### ⚔️ BvP Strikeout Hit List")
        st.caption(f"Historical strikeout rates for {opponent} hitters vs {pitcher_name}.")
        
        if st.button("Scan Opponent Lineup"):
            pb = st.progress(0, text="Scanning opponent history...")
            opp_roster_data = get_roster(opp_team_id)
            opp_hitters = {p['person']['fullName']: p['person']['id'] for p in opp_roster_data if p['position']['abbreviation'] != 'P'}
            
            hit_list = []
            for i, (name, ob_id) in enumerate(opp_hitters.items()):
                pb.progress((i + 1) / len(opp_hitters), text=f"Checking {name}...")
                bvp = get_bvp_stats(ob_id, p_id)
                if bvp:
                    pa = bvp.get('plateAppearances', 0)
                    if pa > 0:
                        so = bvp.get('strikeOuts', 0)
                        k_pct = round((so / pa) * 100, 1)
                        hit_list.append({"Batter": name, "Plate Appearances": pa, "Strikeouts": so, "K%": k_pct})
            
            pb.empty()
            
            if hit_list:
                df_hit = pd.DataFrame(hit_list).sort_values(by="K%", ascending=False)
                st.dataframe(df_hit, hide_index=True, use_container_width=True)
            else:
                st.info(f"No historical at-bats for {opponent} vs {pitcher_name}.")

else:
    st.warning("🌴 **OFF DAY:** The Reds are resting today.")
