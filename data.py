"""
data.py — all network fetchers, with NO Streamlit dependencies.

The app wraps these with @st.cache_data for interactive use; the daily
auto-run robot calls them raw from a background thread. Keeping them pure is
what lets the engines run headlessly (briefings, scheduled picks, simulators).
"""
import requests
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from engine import calc_ip, normalize_name

EASTERN = ZoneInfo("America/New_York")
HTTP_TIMEOUT = 10  # seconds — guard against hung MLB/Supabase/Odds calls

STATS = "https://statsapi.mlb.com/api/v1"
STATS11 = "https://statsapi.mlb.com/api/v1.1"
ODDS_BASE = "https://api.the-odds-api.com/v4/sports/baseball_mlb"
REDS_TEAM_ID = 113


def now_eastern():
    """Current time in US Eastern (handles EST/EDT automatically)."""
    return datetime.now(EASTERN)

def http_get(url, **kwargs):
    kwargs.setdefault("timeout", HTTP_TIMEOUT)
    return requests.get(url, **kwargs)

def http_post(url, **kwargs):
    kwargs.setdefault("timeout", HTTP_TIMEOUT)
    return requests.post(url, **kwargs)

def http_patch(url, **kwargs):
    kwargs.setdefault("timeout", HTTP_TIMEOUT)
    return requests.patch(url, **kwargs)

def http_delete(url, **kwargs):
    kwargs.setdefault("timeout", HTTP_TIMEOUT)
    return requests.delete(url, **kwargs)


# ============================================================
# MLB STATSAPI
# ============================================================
def get_league_hitting(year):
    url = f"{STATS}/sports/1/stats?stats=season&group=hitting&season={year}"
    try:
        return http_get(url).json()['stats'][0]['splits'][0]['stat']
    except Exception:
        return {'obp': '.315', 'slg': '.400'}

def get_schedule(date_str):
    url = f"{STATS}/schedule?sportId=1&teamId={REDS_TEAM_ID}&date={date_str}&hydrate=probablePitcher"
    try:
        return http_get(url).json()
    except Exception:
        return {}  # bad/non-JSON response -> app degrades to the OFF DAY screen

def get_game_starters(game_pk):
    url = f"{STATS11}/game/{game_pk}/feed/live"
    try:
        res = http_get(url).json()
        starters = {'away': {'id': None, 'name': 'TBD'}, 'home': {'id': None, 'name': 'TBD'}}
        probables = res.get('gameData', {}).get('probablePitchers', {})
        for side in ('away', 'home'):
            if side in probables:
                starters[side] = {'id': probables[side]['id'], 'name': probables[side]['fullName']}
        status = res.get('gameData', {}).get('status', {}).get('statusCode', '')
        for side in ('away', 'home'):
            if status in ['I', 'F', 'O', 'CR'] or starters[side]['name'] == 'TBD':
                pitchers_list = res.get('liveData', {}).get('boxscore', {}).get('teams', {}).get(side, {}).get('pitchers', [])
                if pitchers_list:
                    p_id   = pitchers_list[0]
                    player = res.get('gameData', {}).get('players', {}).get(f"ID{p_id}", {})
                    if player:
                        starters[side] = {'id': player.get('id'), 'name': player.get('fullName', 'TBD')}
        return starters
    except Exception:
        return {'away': {'id': None, 'name': 'TBD'}, 'home': {'id': None, 'name': 'TBD'}}

def get_live_feed(game_pk):
    """Game feed/live pull (lineups, live score)."""
    try:
        return http_get(f"{STATS11}/game/{game_pk}/feed/live").json()
    except Exception:
        return {}

def get_roster(team_id):
    url = f"{STATS}/teams/{team_id}/roster"
    try:
        return http_get(url).json().get('roster', [])
    except Exception:
        return []

def get_season_stats(player_id, group, year, split=None):
    if split:
        url = f"{STATS}/people/{player_id}/stats?stats=statSplits&group={group}&season={year}&sitCodes={split}"
    else:
        url = f"{STATS}/people/{player_id}/stats?stats=season&group={group}&season={year}"
    try:
        return http_get(url).json()
    except Exception:
        return {}

def _advanced(player_id, group, year):
    url = f"{STATS}/people/{player_id}/stats?stats=season,seasonAdvanced&group={group}&season={year}"
    stats = {}
    try:
        res = http_get(url).json()
        for split in res.get('stats', []):
            if split['type']['displayName'] in ['season', 'seasonAdvanced']:
                stats.update(split['splits'][0]['stat'])
    except Exception:
        pass
    return stats

def get_advanced_hitting(player_id, year):
    return _advanced(player_id, "hitting", year)

def get_advanced_pitching(player_id, year):
    return _advanced(player_id, "pitching", year)

def get_team_pitching(team_id, year):
    url = f"{STATS}/teams/{team_id}/stats?stats=statSplits&group=pitching&season={year}&sitCodes=rp"
    try:
        return http_get(url).json()['stats'][0]['splits'][0]['stat']
    except Exception:
        return {}

def get_bullpen_fatigue(team_id):
    today = now_eastern()
    start = (today - timedelta(days=3)).strftime("%Y-%m-%d")
    end   = (today - timedelta(days=1)).strftime("%Y-%m-%d")
    url   = f"{STATS}/teams/{team_id}/stats?stats=byDateRange&group=pitching&startDate={start}&endDate={end}&sitCodes=rp"
    try:
        res = http_get(url).json()
        return calc_ip(res['stats'][0]['splits'][0]['stat'].get('inningsPitched', '0.0'))
    except Exception:
        return 0.0

def get_career_splits(player_id, group, split_code):
    url = f"{STATS}/people/{player_id}/stats?stats=careerStatSplits&group={group}&sitCodes={split_code}"
    try:
        return http_get(url).json()
    except Exception:
        return {}

def get_team_splits(team_id, year, split_code):
    url = f"{STATS}/teams/{team_id}/stats?stats=statSplits&group=hitting&season={year}&sitCodes={split_code}"
    try:
        return http_get(url).json()['stats'][0]['splits'][0]['stat']
    except Exception:
        return {}

def get_bvp_stats(batter_id, pitcher_id):
    if not pitcher_id: return None
    url = f"{STATS}/people/{batter_id}/stats?stats=vsPlayer&opposingPlayerId={pitcher_id}&group=hitting"
    try:
        return http_get(url).json()['stats'][0]['splits'][0]['stat']
    except Exception:
        return None

def get_game_logs(player_id, year, group="hitting"):
    url = f"{STATS}/people/{player_id}/stats?stats=gameLog&group={group}&season={year}"
    try:
        return http_get(url).json()['stats'][0]['splits']
    except Exception:
        return []

def get_pitcher_hand(pitcher_id):
    if not pitcher_id: return "R"
    try:
        return http_get(f"{STATS}/people/{pitcher_id}").json()['people'][0]['pitchHand']['code']
    except Exception:
        return "R"

def get_pitcher_k_stats(pitcher_id, year):
    """Pull all K-related metrics for the strikeout engine."""
    adv = get_advanced_pitching(pitcher_id, year)
    logs = get_game_logs(pitcher_id, year, group="pitching")
    l5   = logs[-5:] if logs else []
    l5_k_list = [g.get('stat', {}).get('strikeOuts', 0) for g in l5]
    l5_ip_list = [calc_ip(g.get('stat', {}).get('inningsPitched', '0.0')) for g in l5]
    l5_avg_k  = round(sum(l5_k_list) / len(l5_k_list), 1) if l5_k_list else 0.0
    l5_avg_ip = round(sum(l5_ip_list) / len(l5_ip_list), 1) if l5_ip_list else 0.0
    return adv, l5_k_list, l5_avg_k, l5_avg_ip

def get_league_schedule(date_str):
    """All MLB games for a date with probable pitchers hydrated."""
    url = f"{STATS}/schedule?sportId=1&date={date_str}&hydrate=probablePitcher"
    try:
        return http_get(url).json()
    except Exception:
        return {}


# ============================================================
# ODDS API (pure: returns (result, messages) — the app displays messages)
# ============================================================
def _better(price_a, price_b):
    """American-odds comparison for the bettor: higher number = better payout
    (-105 beats -120; +150 beats +100)."""
    if price_a is None: return price_b
    if price_b is None: return price_a
    return max(price_a, price_b)

def parse_batter_odds(game_json):
    """Parse an event-odds response (ALL books) into per-player records:
    DraftKings as the reference line, plus the best price across books at the
    same line. Pure — unit tested with fixture JSON."""
    odds_dict = {}
    for book in (game_json or {}).get('bookmakers', []):
        bkey  = book.get('key', '')
        btitle = book.get('title', bkey)
        is_dk = (bkey == 'draftkings')
        for market in book.get('markets', []):
            mkey = market.get('key')
            if mkey not in ('batter_hits', 'batter_hits_runs_rbis'):
                continue
            prefix = '' if mkey == 'batter_hits' else 'hrr_'
            for outcome in market.get('outcomes', []):
                if outcome.get('name') != 'Over':
                    continue
                nm  = normalize_name(outcome.get('description', ''))
                if not nm:
                    continue
                rec   = odds_dict.setdefault(nm, {})
                point = outcome.get('point', 0.5)
                price = outcome.get('price', 0)
                if is_dk:
                    rec[prefix + 'line']  = point
                    rec[prefix + 'price'] = price
                # track the best price per (market, point) across all books
                offers = rec.setdefault(prefix + '_offers', {})
                cur = offers.get(point)
                if cur is None or _better(price, cur[0]) == price:
                    offers[point] = (price, btitle)
    # resolve "best at DK's line" (fall back to any line when DK absent)
    for rec in odds_dict.values():
        for prefix in ('', 'hrr_'):
            offers = rec.pop(prefix + '_offers', {})
            if not offers:
                continue
            ref = rec.get(prefix + 'line')
            if ref is None and offers:
                ref = sorted(offers.keys())[0]
                rec[prefix + 'line'] = ref
                rec[prefix + 'price'] = None
            best = offers.get(ref)
            if best:
                rec[prefix + 'best_price'], rec[prefix + 'best_book'] = best
    return odds_dict

def fetch_reds_batter_odds(odds_api_key):
    """DraftKings batter_hits + HRR lines for the Reds game.
    Returns (odds_dict, messages). ~1-2 Odds API credits."""
    msgs = []
    if not odds_api_key:
        return {}, msgs
    try:
        ev_res = http_get(f"{ODDS_BASE}/events", params={"apiKey": odds_api_key})
        if ev_res.status_code != 200:
            msgs.append(("error", f"Odds API (events) failed: {ev_res.text[:200]}"))
            return {}, msgs
        events = ev_res.json()
        if not events:
            msgs.append(("warning", "No MLB events returned by the odds provider right now."))
            return {}, msgs

        reds_event_id = None
        for ev in events:
            if 'Reds' in ev.get('home_team', '') or 'Reds' in ev.get('away_team', ''):
                reds_event_id = ev.get('id')
                break
        if not reds_event_id:
            msgs.append(("warning", "No Reds game found on the odds provider's slate for today."))
            return {}, msgs

        # NOTE: no bookmakers filter — one call returns EVERY US book for the
        # same credit cost, which is what makes line shopping free.
        o_res = http_get(
            f"{ODDS_BASE}/events/{reds_event_id}/odds",
            params={
                "apiKey": odds_api_key,
                "regions": "us",
                "markets": "batter_hits,batter_hits_runs_rbis",
                "oddsFormat": "american",
            }
        )
        if o_res.status_code != 200:
            msgs.append(("error", f"Odds API (Reds event) failed: {o_res.text[:200]}"))
            return {}, msgs

        odds_dict = parse_batter_odds(o_res.json())
        if not odds_dict:
            msgs.append(("warning", "Found the Reds game, but no DraftKings batter lines are "
                                    "posted yet (often not until a few hours before first pitch)."))
        return odds_dict, msgs
    except Exception as e:
        msgs.append(("error", f"Odds API error: {str(e)}"))
        return {}, msgs

def parse_k_odds(game_json, out=None):
    """Parse one event's pitcher_strikeouts markets (ALL books) into per-pitcher
    records: DK reference line/prices + best over/under across books at the
    same line. Pure — unit tested with fixture JSON."""
    out = out if out is not None else {}
    for book in (game_json or {}).get('bookmakers', []):
        is_dk  = (book.get('key') == 'draftkings')
        btitle = book.get('title', book.get('key', ''))
        for market in book.get('markets', []):
            if market.get('key') != 'pitcher_strikeouts':
                continue
            for o in market.get('outcomes', []):
                nm = normalize_name(o.get('description', ''))
                if not nm:
                    continue
                rec   = out.setdefault(nm, {'line': None,
                                            'over_price': None, 'under_price': None})
                point = o.get('point')
                price = o.get('price')
                side  = 'over' if o.get('name') == 'Over' else 'under'
                if is_dk:
                    if point is not None:
                        rec['line'] = point
                    rec[f'{side}_price'] = price
                offers = rec.setdefault(f'_{side}_offers', {})
                cur = offers.get(point)
                if cur is None or _better(price, cur[0]) == price:
                    offers[point] = (price, btitle)
    return out

def _resolve_k_best(out):
    for rec in out.values():
        ref = rec.get('line')
        for side in ('over', 'under'):
            offers = rec.pop(f'_{side}_offers', {})
            if not offers:
                continue
            if ref is None:
                ref = sorted(k for k in offers.keys() if k is not None)[0] if offers else None
                rec['line'] = ref
            best = offers.get(ref)
            if best:
                rec[f'{side}_best_price'], rec[f'{side}_best_book'] = best
    return out

def fetch_pitcher_strikeout_odds(odds_api_key, cap=None):
    """League-wide pitcher_strikeouts lines (all US books; DK as reference)
    keyed by normalized name. Returns (dict, messages). ~1 credit per event."""
    msgs = []
    if not odds_api_key:
        return {}, msgs
    out = {}
    try:
        ev_res = http_get(f"{ODDS_BASE}/events", params={"apiKey": odds_api_key})
        if ev_res.status_code != 200:
            msgs.append(("error", f"Odds API (events) failed: {ev_res.text[:160]}"))
            return {}, msgs
        events = ev_res.json() or []
        if cap:
            events = events[:cap]
        for e in events:
            eid = e.get('id')
            if not eid:
                continue
            r = http_get(f"{ODDS_BASE}/events/{eid}/odds", params={
                "apiKey": odds_api_key, "regions": "us",
                "markets": "pitcher_strikeouts",
                "oddsFormat": "american",
            })
            if r.status_code != 200:
                continue
            parse_k_odds(r.json(), out)
        return _resolve_k_best(out), msgs
    except Exception as ex:
        msgs.append(("error", f"Odds API (pitcher Ks) error: {ex}"))
        return _resolve_k_best(out), msgs


# ============================================================
# NOTIFICATIONS (ntfy.sh — free push, no signup)
# ============================================================
def ntfy_send(topic, title, message, tags="baseball"):
    """Publish a push notification to an ntfy.sh topic. Returns True on success."""
    if not topic:
        return False
    try:
        res = http_post(f"https://ntfy.sh/{topic}",
                        data=message.encode("utf-8"),
                        headers={"Title": title, "Tags": tags, "Priority": "default"})
        return res.status_code in (200, 202)
    except Exception:
        return False
