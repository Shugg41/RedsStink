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

# SUPABASE CONFIG
try:
    SUPABASE_URL = st.secrets["SUPABASE_URL"]
    SUPABASE_KEY = st.secrets["SUPABASE_KEY"]
    DB_HEADERS = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation"
    }
except:
    SUPABASE_URL = None
    DB_HEADERS = None

# LAZY AUTOMATION
def auto_grade_past_predictions():
    if not SUPABASE_URL: return
    today_str = datetime.now().strftime("%Y-%m-%d")
    
    url = f"{SUPABASE_URL}/rest/v1/predictions?graded=eq.0&date=lt.{today_str}&select=date"
    res = requests.get(url, headers=DB_HEADERS)
    
    if res.status_code != 200 or not res.json(): return
    
    dates_to_grade = list(set([row['date'] for row in res.json()]))

    for d in dates_to_grade:
        sched_url = f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&teamId=113&date={d}"
        try:
            sched = requests.get(sched_url).json()
            if sched['totalGames'] > 0:
                game = sched['dates'][0]['games'][0]
                status = game['status']['statusCode']
                
                if status in ['F', 'O', 'CR']:
                    game_pk = game['gamePk']
                    feed_url = f"https://statsapi.mlb.com/api/v1.1/game/{game_pk}/feed/live"
                    feed = requests.get(feed_url).json()
                    box = feed.get('liveData', {}).get('boxscore', {}).get('teams', {})
                    
                    if feed.get('gameData', {}).get('teams', {}).get('away', {}).get('id') == 113:
                        reds_batters = box.get('away', {}).get('batters', [])
                        players_dict = box.get('away', {}).get('players', {})
                    else:
                        reds_batters = box.get('home', {}).get('batters', [])
                        players_dict = box.get('home', {}).get('players', {})
                    
                    preds_res = requests.get(f"{SUPABASE_URL}/rest/v1/predictions?date=eq.{d}", headers=DB_HEADERS).json()
                    tier_map = {str(p['player_id']): p.get('tier', '') for p in preds_res}
                    
                    requests.patch(f"{SUPABASE_URL}/rest/v1/predictions?date=eq.{d}", 
                                 json={"graded": 1, "win": -1}, headers=DB_HEADERS)
                    
                    for p_id in reds_batters:
                        p_key = f"ID{p_id}"
                        stats = players_dict.get(p_key, {}).get('stats', {}).get('batting', {})
                        pa = stats.get('plateAppearances', 0)
                        
                        if pa > 0:
                            hits = stats.get('hits', 0)
                            runs = stats.get('runs', 0)
                            rbi = stats.get('rbi', 0)
                            hrr = hits + runs + rbi
                            
                            player_tier = tier_map.get(str(p_id), "")
                            if "Tier 3" in player_tier:
                                win = 1 if (hits == 0 and hrr <= 1) else 0
                            else:
                                win = 1 if (hits > 0 or hrr > 1) else 0
                            
                            requests.patch(f"{SUPABASE_URL}/rest/v1/predictions?date=eq.{d}&player_id=eq.{p_id}",
                                         json={"actual_hits": hits, "actual_hrr": hrr, "win": win}, 
                                         headers=DB_HEADERS)
        except:
            pass

auto_grade_past_predictions()

def calc_ip(ip_str):
    try:
        ip = str(ip_str)
        if '.' in ip:
            whole, partial = ip.split('.')
            return int(whole) + (int(partial) / 3.0)
        return int(ip)
    except:
        return 0.0

def calculate_fip(stats):
    try:
        api_fip = stats.get('fip', stats.get('fieldingIndependentPitching', '0.00'))
        if api_fip != '0.00' and api_fip != '-.--':
            return f"{float(api_fip):.2f}"
            
        hr = int(stats.get('homeRuns', 0))
        bb = int(stats.get('baseOnBalls', 0))
        hbp = int(stats.get('hitBatsmen', stats.get('hitByPitch', 0)))
        k = int(stats.get('strikeOuts', 0))
        ip = calc_ip(stats.get('inningsPitched', '0.0'))
        
        if ip <= 0: return "0.00"
        fip = ((13 * hr) + (3 * (bb + hbp)) - (2 * k)) / ip + 3.20
        return f"{max(0, fip):.2f}"
    except:
        return "0.00"

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
        if 'away' in probables: starters['away'] = {'id': probables['away']['id'], 'name': probables['away']['fullName']}
        if 'home' in probables: starters['home'] = {'id': probables['home']['id'], 'name': probables['home']['fullName']}
        status = res.get('gameData', {}).get('status', {}).get('statusCode', '')
        if status in ['I', 'F', 'O', 'CR'] or starters['away']['name'] == 'TBD':
            away_p = res.get('liveData', {}).get('boxscore', {}).get('teams', {}).get('away', {}).get('pitchers', [])
            if away_p:
                p_id = away_p[0]
                player = res.get('gameData', {}).get('players', {}).get(f"ID{p_id}", {})
                if player: starters['away'] = {'id': player.get('id'), 'name': player.get('fullName', 'TBD')}
        if status in ['I', 'F', 'O', 'CR'] or starters['home']['name'] == 'TBD':
            home_p = res.get('liveData', {}).get('boxscore', {}).get('teams', {}).get('home', {}).get('pitchers', [])
            if home_p:
                p_id = home_p[0]
                player = res.get('gameData', {}).get('players', {}).get(f"ID{p_id}", {})
                if player: starters['home'] = {'id': player.get('id'), 'name': player.get('fullName', 'TBD')}
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
def get_advanced_hitting(player_id, year):
    url = f"https://statsapi.mlb.com/api/v1/people/{player_id}/stats?stats=season,seasonAdvanced&group=hitting&season={year}"
    res = requests.get(url).json()
    stats = {}
    try:
        for split in res.get('stats', []):
            if split['type']['displayName'] in ['season', 'seasonAdvanced']:
                stats.update(split['splits'][0]['stat'])
        return stats
    except:
        return {}

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

@st.cache_data(ttl=3600)
def get_team_pitching(team_id, year):
    url = f"https://statsapi.mlb.com/api/v1/teams/{team_id}/stats?stats=statSplits&group=pitching&season={year}&sitCodes=rp"
    res = requests.get(url).json()
    try: return res['stats'][0]['splits'][0]['stat']
    except: return {}

@st.cache_data(ttl=86400)
def get_career_splits(player_id, group, split_code):
    url = f"https://statsapi.mlb.com/api/v1/people/{player_id}/stats?stats=careerStatSplits&group={group}&sitCodes={split_code}"
    return requests.get(url).json()

@st.cache_data(ttl=3600)
def get_team_splits(team_id, year, split_code):
    url = f"https://statsapi.mlb.com/api/v1/teams/{team_id}/stats?stats=statSplits&group=hitting&season={year}&sitCodes={split_code}"
    res = requests.get(url).json()
    try: return res['stats'][0]['splits'][0]['stat']
    except: return {}

@st.cache_data(ttl=3600)
def get_bvp_stats(batter_id, pitcher_id):
    if not pitcher_id: return None
    url = f"https://statsapi.mlb.com/api/v1/people/{batter_id}/stats?stats=vsPlayer&opposingPlayerId={pitcher_id}&group=hitting"
    res = requests.get(url).json()
    try: return res['stats'][0]['splits'][0]['stat']
    except: return None

@st.cache_data(ttl=3600)
def get_game_logs(player_id, year, group="hitting"):
    url = f"https://statsapi.mlb.com/api/v1/people/{player_id}/stats?stats=gameLog&group={group}&season={year}"
    res = requests.get(url).json()
    try: return res['stats'][0]['splits']
    except: return []

@st.cache_data(ttl=86400)
def get_pitcher_hand(pitcher_id):
    if not pitcher_id: return "R"
    url = f"https://statsapi.mlb.com/api/v1/people/{pitcher_id}"
    res = requests.get(url).json()
    try: return res['people'][0]['pitchHand']['code']
    except: return "R"

with st.sidebar:
    st.image("https://a.espncdn.com/i/teamlogos/mlb/500/cin.png", width=100)
    st.title("Settings")
    selected_date = st.date_input("Select Game Date", datetime.now())
    date_str = selected_date.strftime("%Y-%m-%d")
    current_year = selected_date.year

st.title("🔴 Reds Matchup & Prop Engine")

data = get_schedule(date_str)
reds_pitcher_name, reds_pitcher_id, opp_pitcher_name, opp_pitcher_id = "TBD", None, "TBD", None
opponent, opp_team_id = "Unknown", None

if data['totalGames'] > 0:
    game = data['dates'][0]['games'][0]
    game_pk = game['gamePk']
    starters = get_game_starters(game_pk)
    away_team, home_team = game['teams']['away']['team']['name'], game['teams']['home']['team']['name']
    
    if "Reds" in away_team:
        opponent, opp_team_id = home_team, game['teams']['home']['team']['id']
        opp_pitcher_name, opp_pitcher_id = starters['home']['name'], starters['home']['id']
        reds_pitcher_name, reds_pitcher_id = starters['away']['name'], starters['away']['id']
    else:
        opponent, opp_team_id = away_team, game['teams']['away']['team']['id']
        opp_pitcher_name, opp_pitcher_id = starters['away']['name'], starters['away']['id']
        reds_pitcher_name, reds_pitcher_id = starters['home']['name'], starters['home']['id']

    st.subheader(f"🏟️ Matchup: Reds vs {opponent}")
    
    if opp_pitcher_name == 'TBD':
        st.warning("Official lineup card not submitted. Select the starter manually.", icon="⚠️")
        opp_roster = get_roster(opp_team_id)
        opp_pitchers = {p['person']['fullName']: p['person']['id'] for p in opp_roster if p['position']['abbreviation'] == 'P'}
        if opp_pitchers:
            manual_p = st.selectbox(f"Select {opponent} Starter:", ["Select..."] + sorted(opp_pitchers.keys()))
            if manual_p != "Select...":
                opp_pitcher_name, opp_pitcher_id = manual_p, opp_pitchers[manual_p]

    pitcher_hand = get_pitcher_hand(opp_pitcher_id)
    split_code, split_label = ("vl", "LHP") if pitcher_hand == "L" else ("vr", "RHP")

    if opp_pitcher_name != 'TBD' and opp_pitcher_id:
        st.info(f"**Targeting Opposing Starter:** {opp_pitcher_name} ({split_label})", icon="🎯")
    
    st.divider()
    roster_res = get_roster(113)
    hitters = {p['person']['fullName']: p['person']['id'] for p in roster_res if p['position']['abbreviation'] != 'P'}
    pitchers = {p['person']['fullName']: p['person']['id'] for p in roster_res if p['position']['abbreviation'] == 'P'}

    feed_url = f"https://statsapi.mlb.com/api/v1.1/game/{game_pk}/feed/live"
    try:
        live_feed = requests.get(feed_url).json()
        boxscore = live_feed.get('liveData', {}).get('boxscore', {}).get('teams', {})
        if "Reds" in away_team: reds_batting_order = boxscore.get('away', {}).get('battingOrder', [])
        else: reds_batting_order = boxscore.get('home', {}).get('battingOrder', [])
    except: reds_batting_order = []

    tab1, tab2, tab3, tab4 = st.tabs(["🏏 Offense Top Matchups", "⚾ Pitcher Strikeouts", "📊 System Tracker", "🔍 Player Deep Dive"])

    with tab1:
        adv_stats, pitcher_score = {}, 0
        if opp_pitcher_id:
            st.markdown(f"### 🎯 Target Profile: {opp_pitcher_name}")
            adv_stats = get_advanced_pitching(opp_pitcher_id, current_year)
            opp_bullpen = get_team_pitching(opp_team_id, current_year)
            if adv_stats:
                era_val = float(adv_stats.get('era', '3.50'))
                pitcher_score = 10 if era_val >= 4.50 else (5 if era_val >= 3.50 else 0)
                fip_val = calculate_fip(adv_stats)
                c1, c2, c3, c4, c5, c6 = st.columns(6)
                c1.metric("ERA", adv_stats.get('era', '0.00'))
                c2.metric("WHIP", adv_stats.get('whip', '0.00'))
                c3.metric("K/9", adv_stats.get('strikeoutsPer9Inn', '0.00'))
                c4.metric("HR/9", adv_stats.get('homeRunsPer9', '0.00'))
                c5.metric("FIP", fip_val)
                c6.metric("Bullpen ERA", opp_bullpen.get('era', '0.00'))
            else: st.info("Advanced stats unavailable for this pitcher.")
            st.divider()

        st.markdown("### 🏆 Reds Hitting Board (100-Point Scale)")
        st.caption("Graded on Split (45), Form (45), Pitcher (10). BvP is a max +10 bonus.")
        
        lineup_ready = len(reds_batting_order) > 0
        if lineup_ready: st.success("✅ Official Lineup Confirmed")
        else: st.warning("⏳ Waiting on Official Lineup...")
            
        show_starters = st.checkbox("Hide bench players", value=False, disabled=not lineup_ready)

        if st.button("Run Offensive Engine", type="primary"):
            if not opp_pitcher_id: st.error("Select pitcher first.")
            else:
                pb = st.progress(0, text="Evaluating roster...")
                scan_results = []
                for i, (name, p_id) in enumerate(hitters.items()):
                    pb.progress((i+1)/len(hitters), text=f"Analyzing {name}...")
                    lineup_score, in_lineup = 0, False
                    if reds_batting_order:
                        if p_id in reds_batting_order:
                            in_lineup = True
                            idx = reds_batting_order.index(p_id)
                            lineup_score = 5 if idx <= 2 else (-5 if idx >= 6 else 0)
                        if show_starters and not in_lineup: continue
                            
                    hit_games, l10_total, l10_h_avg, l10_hrr_avg = 0, 0, 0.0, 0.0
                    logs = get_game_logs(p_id, current_year)
                    if logs:
                        l10 = logs[-10:]
                        l10_total = len(l10)
                        hit_games = sum(1 for g in l10 if g.get('stat', {}).get('hits', 0) > 0)
                        if l10_total > 0:
                            l10_h_avg = round(sum(g.get('stat', {}).get('hits', 0) for g in l10)/l10_total, 1)
                            l10_hrr_avg = round(sum((g.get('stat', {}).get('hits', 0) + g.get('stat', {}).get('runs', 0) + g.get('stat', {}).get('rbi', 0)) for g in l10)/l10_total, 1)
                    
                    overall_avg = ".000"
                    ov_data = get_season_stats(p_id, "hitting", current_year)
                    try: overall_avg = ov_data['stats'][0]['splits'][0]['stat'].get('avg', '.000')
                    except: pass

                    split_ops = 0.0
                    sp_data = get_season_stats(p_id, "hitting", current_year, split=split_code)
                    try:
                        stat_block = sp_data['stats'][0]['splits'][0]['stat']
                        split_ops = float(stat_block.get('ops', 0))
                    except:
                        c_data = get_career_splits(p_id, "hitting", split_code)
                        try:
                            stat_block = c_data['stats'][0]['splits'][0]['stat']
                            split_ops = float(stat_block.get('ops', 0))
                        except: pass
                        
                    bvp_avg, bvp_bonus = 0.0, 0
                    bvp = get_bvp_stats(p_id, opp_pitcher_id)
                    if bvp:
                        bvp_avg = float(bvp.get('avg', 0))
                        bvp_bonus = 10 if bvp_avg >= .350 else (5 if bvp_avg >= .250 else 0)
                    
                    split_score = int(min(45, max(0, (split_ops - 0.500) * 112)))
                    cons_score = int((hit_games / 10.0) * 22.5) if l10_total > 0 else 0
                    hrr_score = int(min(22.5, (l10_hrr_avg / 2.5) * 22.5))
                    
                    total_score = split_score + cons_score + hrr_score + pitcher_score + lineup_score + bvp_bonus
                    tier = "🟢 Tier 1" if total_score >= 75 else "🟡 Tier 2" if total_score >= 55 else "🔴 Tier 3"
                    
                    scan_results.append({
                        "Player": name, "Player_ID": p_id, "Tier": tier, "Score": total_score, "Avg": overall_avg,
                        "Raw_OPS": split_ops, "L10_HRR": l10_hrr_avg, "L10_Hits": l10_h_avg, "BVP_Avg": bvp_avg,
                        "OPS_Display": f"{split_ops:.3f}"
                    })
                pb.empty()
                
                if SUPABASE_URL:
                    check_url = f"{SUPABASE_URL}/rest/v1/predictions?date=eq.{date_str}&select=date"
                    if not requests.get(check_url, headers=DB_HEADERS).json():
                        insert_data = []
                        for r in scan_results:
                            insert_data.append({
                                "date": date_str, "player_id": r['Player_ID'], "player_name": r['Player'],
                                "score": r['Score'], "tier": r['Tier'], "opp_pitcher": opp_pitcher_name,
                                "actual_hits": 0, "actual_hrr": 0, "graded": 0, "win": 0
                            })
                        requests.post(f"{SUPABASE_URL}/rest/v1/predictions", json=insert_data, headers=DB_HEADERS)
                
                if scan_results:
                    df = pd.DataFrame(scan_results).sort_values(by=['Score', 'Raw_OPS'], ascending=False)
                    for idx, (index, row) in enumerate(df.iterrows()):
                        st.markdown(f"#### {idx + 1}. {row['Player']} - {row['Score']}/100 [{row['Tier']}]")
                        st.markdown(f"**AVG:** {row['Avg']} | **OPS vs {split_label}:** {row['OPS_Display']} | **BvP AVG:** {row['BVP_Avg']:.3f}")
                        st.markdown(f"**L10 HRR/G:** {row['L10_HRR']} | **L10 Hits/G:** {row['L10_Hits']}")
                        st.divider()

    with tab2:
        col1, col2 = st.columns([1, 2])
        r_pitchers = sorted(pitchers.keys())
        def_idx = r_pitchers.index(reds_pitcher_name) if reds_pitcher_name in r_pitchers else 0
        with col1:
            p_name = st.selectbox("Select Reds Pitcher", r_pitchers, index=def_idx)
            p_id = pitchers[p_name]
        
        r_hand = get_pitcher_hand(p_id)
        r_split_code, r_split_label = ("vl", "LHP") if r_hand == "L" else ("vr", "RHP")
        st.markdown(f"### 🎯 Pitcher Form (Last 5 Starts)")
        p_logs = get_game_logs(p_id, current_year, group="pitching")
        avg_k = 0.0
        if p_logs:
            l5 = p_logs[-5:]
            total_k = sum(g.get('stat', {}).get('strikeOuts', 0) for g in l5)
            total_ip = sum(calc_ip(g.get('stat', {}).get('inningsPitched', '0.0')) for g in l5)
            starts = len(l5)
            avg_k, avg_ip = round(total_k/starts, 1), round(total_ip/starts, 1)
            p1, p2, p3 = st.columns(3)
            p1.metric("Avg Strikeouts", avg_k); p2.metric("Avg IP", avg_ip)
        
        st.divider()
        st.markdown(f"### ⚠️ Opponent Target: {opponent} vs {r_split_label}")
        opp_stats = get_team_splits(opp_team_id, current_year, r_split_code)
        if opp_stats:
            pa, so = opp_stats.get('plateAppearances', 0), opp_stats.get('strikeOuts', 0)
            if pa > 0:
                k_rate = round((so/pa)*100, 1)
                proj_k = round(avg_k * (k_rate/22.0), 1)
                m1, m2 = st.columns(2)
                m1.metric("Team K Rate", f"{k_rate}%"); m2.metric("Projected K", proj_k)

    with tab3:
        st.markdown("### 📊 Engine Performance")
        if SUPABASE_URL:
            res = requests.get(f"{SUPABASE_URL}/rest/v1/predictions", headers=DB_HEADERS)
            if res.status_code == 200 and res.json():
                df_track = pd.DataFrame(res.json())
                df_active = df_track[(df_track['graded'] == 1) & (df_track['win'] != -1)].copy()
                
                if not df_active.empty:
                    df_active['date_obj'] = pd.to_datetime(df_active['date'])
                    
                    def calc_points(row):
                        if row['win'] == 1:
                            return 3 if "Tier 1" in row['tier'] else (2 if "Tier 2" in row['tier'] else 1)
                        else:
                            return -3 if "Tier 1" in row['tier'] else (-2 if "Tier 2" in row['tier'] else 0)
                    
                    df_active['points'] = df_active.apply(calc_points, axis=1)
                    
                    total_wins = df_active['win'].sum()
                    win_rate = (total_wins / len(df_active)) * 100
                    sys_score = df_active['points'].sum()
                    
                    # L7 Trend
                    l7_date = df_active['date_obj'].max() - pd.Timedelta(days=7)
                    df_l7 = df_active[df_active['date_obj'] >= l7_date]
                    l7_win_rate = (df_l7['win'].sum() / len(df_l7)) * 100 if not df_l7.empty else 0.0
                    
                    # HRR Quality
                    hrr_wins = df_active[(df_active['win'] == 1) & (df_active['actual_hrr'] > 1)]
                    hrr_win_pct = (len(hrr_wins) / total_wins) * 100 if total_wins > 0 else 0.0
                    
                    # Tier 1 Streak
                    t1_df = df_active[df_active['tier'].str.contains("Tier 1")].sort_values(by='date', ascending=False)
                    streak_str = "None"
                    if not t1_df.empty:
                        current_status = t1_df.iloc[0]['win']
                        streak_count = 0
                        for val in t1_df['win']:
                            if val == current_status:
                                streak_count += 1
                            else:
                                break
                        streak_str = f"W{streak_count}" if current_status == 1 else f"L{streak_count}"
                    
                    c1, c2, c3, c4 = st.columns(4)
                    c1.metric("Overall Win %", f"{win_rate:.1f}%")
                    c2.metric("System Score", f"{sys_score:g}", help="T1=±3, T2=±2, T3=+1/0. Positive = Profit.")
                    c3.metric("L7 Days Win %", f"{l7_win_rate:.1f}%")
                    c4.metric("Tier 1 Streak", streak_str)
                    
                    st.caption(f"🎯 **Win Quality:** {hrr_win_pct:.1f}% of total wins came with >1 HRR.")
                    st.divider()
                    
                    st.markdown("#### Performance by Tier")
                    tier_grp = df_active.groupby('tier')['win'].agg(['count', 'mean']).reset_index()
                    cols = st.columns(len(tier_grp))
                    for i, r in tier_grp.iterrows():
                        cols[i].metric(r['tier'], f"{r['mean']*100:.1f}%", f"{int(r['count'])} plays")
                    
                    st.divider()
                    st.markdown("#### Recent Graded Logs")
                    df_display = df_active[['date', 'player_name', 'score', 'tier', 'opp_pitcher', 'actual_hits', 'actual_hrr', 'win']].sort_values(by='date', ascending=False)
                    df_display['Result'] = df_display['win'].apply(lambda x: "✅ WIN" if x == 1 else "❌ LOSS")
                    st.dataframe(df_display.drop(columns=['win']), hide_index=True, use_container_width=True)

    with tab4:
        st.markdown("### 🔍 Batter Deep Dive")
        red_hitters = sorted(hitters.keys())
        sel_hitter = st.selectbox("Select Reds Batter", red_hitters)
        h_id = hitters[sel_hitter]
        adv_hit = get_advanced_hitting(h_id, current_year)
        if adv_hit:
            st.markdown("#### Advanced Metrics")
            ops_plus, babip, iso = adv_hit.get('opsPlus', 'N/A'), adv_hit.get('babip', '.000'), adv_hit.get('iso', '.000')
            try: k_pct = f"{float(adv_hit.get('strikeoutsPerPlateAppearance', 0))*100:.1f}%"
            except: k_pct = "N/A"
            try: bb_pct = f"{float(adv_hit.get('walksPerPlateAppearance', 0))*100:.1f}%"
            except: bb_pct = "N/A"
            c1, c2, c3, c4, c5 = st.columns(5)
            c1.metric("OPS+", ops_plus); c2.metric("BABIP", babip); c3.metric("ISO", iso); c4.metric("K%", k_pct); c5.metric("BB%", bb_pct)
            st.divider()
        
        c_l, c_r = st.columns(2)
        with c_l:
            st.markdown("#### vs LHP")
            vl = get_season_stats(h_id, "hitting", current_year, split="vl")
            try:
                s = vl['stats'][0]['splits'][0]['stat']
                st.markdown(f"**AVG:** {s.get('avg', '.000')} | **OPS:** {s.get('ops', '.000')} | **HR:** {s.get('homeRuns', 0)}")
            except: st.info("No stats vs LHP.")
        with c_r:
            st.markdown("#### vs RHP")
            vr = get_season_stats(h_id, "hitting", current_year, split="vr")
            try:
                s = vr['stats'][0]['splits'][0]['stat']
                st.markdown(f"**AVG:** {s.get('avg', '.000')} | **OPS:** {s.get('ops', '.000')} | **HR:** {s.get('homeRuns', 0)}")
            except: st.info("No stats vs RHP.")
        
        st.divider()
        st.markdown("#### Last 10 Games")
        logs = get_game_logs(h_id, current_year)
        if logs:
            l10_list = []
            for l in logs[-10:]:
                s = l.get('stat', {})
                l10_list.append({"Date": l.get('date', ''), "Opp": l.get('opponent', {}).get('name', ''), "Hits": s.get('hits', 0), "HR": s.get('homeRuns', 0), "K": s.get('strikeOuts', 0)})
            st.dataframe(pd.DataFrame(l10_list).sort_values(by="Date", ascending=False), hide_index=True, use_container_width=True)

else: st.warning("🌴 **OFF DAY:** The Reds are resting today.")
