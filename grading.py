"""
grading.py — headless auto-grader (no Streamlit).

Grades past predictions from box scores: hitters (hits / HRR win) and pitchers
(actual strikeouts, plus the strikeout-prop over/under win when a line was
stored). Pure network + DB, parameterized on (supabase_url, db_headers), so it
runs both in the Streamlit app AND in the GitHub cron (jobs.py) — grading no
longer depends on anyone opening the app.

Idempotent and marker-free: it only touches rows with graded=0, so firing it on
every cron tick is safe.
"""
import data
from engine import grade_k_prop


def _is_final(g):
    s = g.get('status', {})
    return (s.get('abstractGameState') == 'Final'
            or s.get('codedGameState') in ('F', 'O')
            or s.get('statusCode') in ('F', 'O', 'CR', 'FR'))


def _mark_no_game(supabase_url, db_headers, d):
    try:
        data.http_patch(f"{supabase_url}/rest/v1/predictions?date=eq.{d}&graded=eq.0",
                        json={"graded": 1, "win": -1}, headers=db_headers)
        data.http_patch(f"{supabase_url}/rest/v1/pitcher_predictions?date=eq.{d}&graded=eq.0",
                        json={"actual_ks": 0, "graded": -1}, headers=db_headers)
    except Exception:
        pass


def _grade_hit_row(p_row, players_dict):
    p_id = p_row['player_id']
    tier = p_row.get('tier', '')
    stats = players_dict.get(f"ID{p_id}", {}).get('stats', {}).get('batting', {})
    if int(stats.get('plateAppearances', 0)) > 0:
        hits = stats.get('hits', 0)
        hrr  = hits + stats.get('runs', 0) + stats.get('rbi', 0)
        win  = (1 if (hits == 0 and hrr <= 1) else 0) if "Tier 3" in tier else (1 if (hits > 0 or hrr > 1) else 0)
        return {"actual_hits": hits, "actual_hrr": hrr, "win": win, "graded": 1}
    return None


def _grade_final_games(supabase_url, db_headers, final_games, d):
    # Per-game box-score lookup, plus a pooled fallback for legacy rows w/o game_pk.
    per_game = {}
    pooled_players = {}
    for game in final_games:
        gpk = game.get('gamePk')
        try:
            feed = data.http_get(
                f"https://statsapi.mlb.com/api/v1.1/game/{game['gamePk']}/feed/live").json()
            box = feed.get('liveData', {}).get('boxscore', {}).get('teams', {})
            players = {**box.get('away', {}).get('players', {}),
                       **box.get('home', {}).get('players', {})}
            per_game[gpk] = players
            pooled_players.update(players)
        except Exception:
            pass

    # ---- Hitting ----
    try:
        preds_res = data.http_get(
            f"{supabase_url}/rest/v1/predictions?date=eq.{d}&graded=eq.0", headers=db_headers)
        if preds_res.status_code == 200 and preds_res.json():
            rows = preds_res.json()
            # default to no-result first (win=-1); real results overwrite below
            data.http_patch(f"{supabase_url}/rest/v1/predictions?date=eq.{d}&graded=eq.0",
                            json={"graded": 1, "win": -1}, headers=db_headers)
            for p_row in rows:
                gpk = p_row.get('game_pk')
                players_dict = per_game.get(gpk, pooled_players)
                patch = _grade_hit_row(p_row, players_dict)
                if patch:
                    q = f"date=eq.{d}&player_id=eq.{p_row['player_id']}"
                    if gpk is not None:
                        q += f"&game_pk=eq.{gpk}"
                    data.http_patch(f"{supabase_url}/rest/v1/predictions?{q}",
                                    json=patch, headers=db_headers)
    except Exception:
        pass

    # ---- Pitching (strikeouts + K-prop over/under) ----
    try:
        p_preds_res = data.http_get(
            f"{supabase_url}/rest/v1/pitcher_predictions?date=eq.{d}&graded=eq.0",
            headers=db_headers)
        if p_preds_res.status_code == 200 and p_preds_res.json():
            for p_pred in p_preds_res.json():
                if p_pred.get('projected_ks') is None:
                    continue  # legacy outs-only row
                p_id = p_pred['player_id']
                gpk  = p_pred.get('game_pk')
                players_dict = per_game.get(gpk, pooled_players)
                p_key = f"ID{p_id}"
                k_actual = int(players_dict.get(p_key, {})
                               .get('stats', {}).get('pitching', {}).get('strikeOuts', 0)) \
                    if p_key in players_dict else 0
                patch = {"actual_ks": k_actual, "graded": 1}
                # Grade the prop only when a line was stored (columns exist +
                # odds were posted). If the k_* columns don't exist yet, the row
                # has no k_line key and we skip k_win, so the base patch still
                # succeeds — dormant until the one-time SQL is run.
                if p_pred.get('k_line') is not None:
                    patch["k_win"] = grade_k_prop(p_pred.get('k_side'),
                                                  p_pred.get('k_line'), k_actual)
                q = f"player_id=eq.{p_id}&date=eq.{d}"
                if gpk is not None:
                    q += f"&game_pk=eq.{gpk}"
                r = data.http_patch(f"{supabase_url}/rest/v1/pitcher_predictions?{q}",
                                    json=patch, headers=db_headers)
                # If k_win made the patch fail (column missing on a partially-set
                # DB), retry with the base fields so actual_ks/graded still land.
                if "k_win" in patch and getattr(r, "status_code", 0) not in (200, 204):
                    data.http_patch(f"{supabase_url}/rest/v1/pitcher_predictions?{q}",
                                    json={"actual_ks": k_actual, "graded": 1},
                                    headers=db_headers)
    except Exception:
        pass


def grade_all(supabase_url, db_headers):
    """Grade every ungraded prediction whose game has finished. Returns the
    number of dates it looked at (for logging). Safe to call repeatedly."""
    if not supabase_url:
        return 0
    today_str = data.now_eastern().strftime("%Y-%m-%d")

    dates_to_grade = set()
    for endpoint in ("predictions", "pitcher_predictions"):
        try:
            res = data.http_get(
                f"{supabase_url}/rest/v1/{endpoint}?graded=eq.0&select=date",
                headers=db_headers)
            if res.status_code == 200 and isinstance(res.json(), list):
                dates_to_grade.update(r['date'] for r in res.json())
        except Exception:
            pass

    for d in dates_to_grade:
        try:
            sched_res = data.http_get(
                f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&teamId=113&date={d}")
            if sched_res.status_code != 200:
                continue
            sched = sched_res.json()
            if sched.get('totalGames', 0) == 0:
                _mark_no_game(supabase_url, db_headers, d)
                continue
            games = sched['dates'][0]['games']
            final_games = [g for g in games if _is_final(g)]
            all_postponed = all(
                g['status'].get('statusCode') in ('C', 'P', 'D', 'DI') for g in games)
            if final_games:
                _grade_final_games(supabase_url, db_headers, final_games, d)
            elif all_postponed or (d < today_str and not any(
                    g['status'].get('statusCode') in ('I', 'S', 'D', 'DI') for g in games)):
                _mark_no_game(supabase_url, db_headers, d)
        except Exception:
            pass

    return len(dates_to_grade)
