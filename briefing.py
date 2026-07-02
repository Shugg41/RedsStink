"""
briefing.py — the daily morning briefing: compose + auto-run orchestration.

The auto-run fires from a background thread when the keep-awake robot (or any
visitor) hits the app after 9am ET on a game day. It runs the offense board
and K engine headlessly, saves the picks (odds locked in) exactly as if the
user had tapped the buttons, and pushes a briefing to an ntfy.sh topic.

Cross-session dedup: a marker row (player_id=0, '_autorun') is claimed in the
predictions table with a plain insert — the table's (date, player_id, game_pk)
unique key makes the claim atomic, so two simultaneous visitors can't both run.
"""
import dateutil.parser

import data
import pipeline
from engine import calculate_fip

MARKER_PLAYER_ID = 0
MARKER_NAME = "_autorun"
AUTORUN_HOUR_ET = 9   # don't run before 9am ET (probables usually posted by then)


# ============================================================
# COMPOSE (pure — tested)
# ============================================================
def _fmt_price(p):
    if p is None:
        return ""
    return f" ({'+' if p > 0 else ''}{p})"

def _fmt_time_et(start_utc):
    try:
        t = dateutil.parser.isoparse(start_utc).astimezone(data.EASTERN)
        return t.strftime("%I:%M %p ET").lstrip("0")
    except Exception:
        return "TBD"

def compose_briefing(ctx, scan_results, k_projections, odds_found):
    """Build the plain-text morning briefing. Pure function."""
    lines = []
    lines.append(f"⚾ Reds vs {ctx.get('opponent', '?')} — {_fmt_time_et(ctx.get('start_utc', ''))}, "
                 f"{ctx.get('park_name', '')}")
    opp_p = ctx.get('opp_pitcher_name', 'TBD')
    if opp_p and opp_p != 'TBD':
        lines.append(f"🎯 Facing: {opp_p}")

    ranked = sorted(scan_results or [], key=lambda r: -r.get('Score', 0))
    if ranked:
        top = ranked[:3]
        board = " · ".join(f"{r['Player']} {r['Score']}" for r in top)
        lines.append(f"🔥 Board: {board}")

        best_hrr = max(ranked, key=lambda r: r.get('HRR_P2') or 0)
        if best_hrr.get('HRR_P2'):
            hrr_bits = (f"💪 Best HRR: {best_hrr['Player']} proj {best_hrr['HRR_Proj']} "
                        f"(2+ {best_hrr['HRR_P2']*100:.0f}%")
            dk = best_hrr.get('DK_Info') or {}
            if dk.get('hrr_price') is not None:
                hrr_bits += f", DK{_fmt_price(dk['hrr_price'])}"
            lines.append(hrr_bits + ")")

    for kp in (k_projections or []):
        lines.append(f"⚡ {kp['player_name']}: {kp['projected_ks']} Ks projected")

    lines.append("💾 Picks saved" + (" — odds locked in." if odds_found else
                                     " (no DK lines posted yet)."))
    return "\n".join(lines)


# ============================================================
# AUTO-RUN ORCHESTRATION (background thread; raw data module, no Streamlit)
# ============================================================
def _marker_exists(supabase_url, db_headers, date_str):
    try:
        res = data.http_get(
            f"{supabase_url}/rest/v1/predictions"
            f"?date=eq.{date_str}&player_id=eq.{MARKER_PLAYER_ID}&select=player_id&limit=1",
            headers=db_headers)
        return res.status_code == 200 and bool(res.json())
    except Exception:
        return True   # on doubt, do nothing (fail quiet, no spam)

def _claim_marker(supabase_url, db_headers, date_str):
    """Atomically claim today's auto-run via plain insert (409 = already ran)."""
    try:
        res = data.http_post(
            f"{supabase_url}/rest/v1/predictions",
            json=[{"date": date_str, "player_id": MARKER_PLAYER_ID,
                   "player_name": MARKER_NAME, "game_pk": 0,
                   "score": 0, "tier": "", "opp_pitcher": "",
                   "actual_hits": 0, "actual_hrr": 0, "graded": -1, "win": -1}],
            headers=db_headers)
        return res.status_code in (200, 201)
    except Exception:
        return False

def should_autorun(now_et, marker_exists, ctx):
    """Pure gate: run only after AUTORUN_HOUR_ET, once per day, on a pregame
    game day with a known opposing starter (else retry on a later visit)."""
    if now_et.hour < AUTORUN_HOUR_ET:
        return False
    if marker_exists:
        return False
    if not ctx or not ctx.get('is_pregame'):
        return False
    if not ctx.get('opp_pitcher_id'):
        return False
    return True

def daily_autorun(supabase_url, db_headers, db_headers_upsert,
                  odds_api_key, ntfy_topic, year=None):
    """The whole morning routine, headless. Safe to call often — it no-ops
    unless the gate opens, and the marker claim makes it once-per-day."""
    try:
        now = data.now_eastern()
        date_str = now.strftime("%Y-%m-%d")
        year = year or now.year

        ctx = pipeline.game_context(data, date_str)
        if not should_autorun(now, _marker_exists(supabase_url, db_headers, date_str), ctx):
            return None
        if not _claim_marker(supabase_url, db_headers, date_str):
            return None   # someone else claimed it in the same instant

        # --- Odds (locked in at pick time) ---
        live_odds, _msgs = data.fetch_reds_batter_odds(odds_api_key)

        # --- Offense board ---
        roster  = data.get_roster(data.REDS_TEAM_ID)
        hitters = {p['person']['fullName']: p['person']['id']
                   for p in roster if p['position']['abbreviation'] != 'P'}
        p_hand = data.get_pitcher_hand(ctx['opp_pitcher_id'])
        split_code, split_label = ("vl", "LHP") if p_hand == "L" else ("vr", "RHP")

        adv_stats = data.get_advanced_pitching(ctx['opp_pitcher_id'], year)
        try:
            era_val = float(adv_stats.get('era', '3.50'))
        except Exception:
            era_val = 3.50
        pitcher_score = 10 if era_val >= 4.50 else (5 if era_val >= 3.50 else 0)
        try:
            opp_fip_val = float(calculate_fip(adv_stats)) if adv_stats else 4.00
        except Exception:
            opp_fip_val = 4.00
        opp_bullpen = data.get_team_pitching(ctx['opp_team_id'], year)
        try:
            bullpen_era = float(opp_bullpen.get('era', 4.0) or 4.0)
        except Exception:
            bullpen_era = 4.0

        feed = data.get_live_feed(ctx['game_pk'])
        box  = feed.get('liveData', {}).get('boxscore', {}).get('teams', {})
        side = 'away' if 'Reds' in ctx.get('away_team', '') else 'home'
        batting_order = box.get(side, {}).get('battingOrder', []) or []

        scan_results = pipeline.score_hitters(
            data, list(hitters.items()), year, split_code, split_label,
            batting_order, ctx['park_name'], pitcher_score, opp_fip_val,
            bullpen_era, live_odds, ctx['opp_pitcher_id'])

        if scan_results:
            data.http_post(
                f"{supabase_url}/rest/v1/predictions?on_conflict=date,player_id,game_pk",
                json=pipeline.hitting_payload(scan_results, date_str, ctx['game_pk'],
                                              ctx['opp_pitcher_name']),
                headers=db_headers_upsert)

        # --- Strikeout projections for both starters ---
        k_projections = []
        if ctx.get('reds_pitcher_id'):
            proj, _r, _m = pipeline.run_strikeout_engine(
                data, ctx['reds_pitcher_id'], ctx['reds_pitcher_name'],
                ctx['opp_team_id'], ctx['opponent'], ctx['park_name'], year)
            if proj is not None:
                k_projections.append({"player_id": ctx['reds_pitcher_id'],
                                      "player_name": ctx['reds_pitcher_name'],
                                      "projected_ks": proj})
        if ctx.get('opp_pitcher_id'):
            proj, _r, _m = pipeline.run_strikeout_engine(
                data, ctx['opp_pitcher_id'], ctx['opp_pitcher_name'],
                data.REDS_TEAM_ID, "Cincinnati Reds", ctx['park_name'], year)
            if proj is not None:
                k_projections.append({"player_id": ctx['opp_pitcher_id'],
                                      "player_name": ctx['opp_pitcher_name'],
                                      "projected_ks": proj})
        if k_projections:
            data.http_post(
                f"{supabase_url}/rest/v1/pitcher_predictions?on_conflict=date,player_id,game_pk",
                json=pipeline.pitching_payload(k_projections, date_str, ctx['game_pk']),
                headers=db_headers_upsert)

        # --- Push the briefing ---
        text = compose_briefing(ctx, scan_results, k_projections, bool(live_odds))
        data.ntfy_send(ntfy_topic, "🔴 Reds Daily Briefing", text)
        return text
    except Exception:
        return None   # never let the robot take anything down
