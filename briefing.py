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
try:
    import savant
except Exception:
    savant = None

MARKER_PLAYER_ID = 0
MARKER_NAME = "_autorun"
AUTORUN_HOUR_ET = 9   # don't run before 9am ET (probables usually posted by then)

# Closing-line snapshot (CLV): a second, separate marker — same player_id 0
# but game_pk=1 so the (date, player_id, game_pk) unique key keeps them apart.
CLOSE_MARKER_GAME_PK = 1
CLOSE_HOUR_ET = 17    # capture near-close odds on the first visit after 5pm ET

# Pregame safety-net sweep: a third marker (game_pk=2). Within a few hours of
# first pitch it backfills any missing DraftKings lines onto the morning's
# saved picks (they're usually not posted at 10am), and runs the whole morning
# routine if it somehow never happened.
SWEEP_MARKER_GAME_PK = 2
SWEEP_WINDOW_HOURS = 3


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
def _marker_exists(supabase_url, db_headers, date_str, game_pk=0):
    try:
        res = data.http_get(
            f"{supabase_url}/rest/v1/predictions"
            f"?date=eq.{date_str}&player_id=eq.{MARKER_PLAYER_ID}&game_pk=eq.{game_pk}"
            f"&select=player_id&limit=1",
            headers=db_headers)
        return res.status_code == 200 and bool(res.json())
    except Exception:
        return True   # on doubt, do nothing (fail quiet, no spam)

def _claim_marker(supabase_url, db_headers, date_str, game_pk=0, name=MARKER_NAME):
    """Atomically claim a daily job via plain insert (409 = already claimed)."""
    try:
        res = data.http_post(
            f"{supabase_url}/rest/v1/predictions",
            json=[{"date": date_str, "player_id": MARKER_PLAYER_ID,
                   "player_name": name, "game_pk": game_pk,
                   "score": 0, "tier": "", "opp_pitcher": "",
                   "actual_hits": 0, "actual_hrr": 0, "graded": -1, "win": -1}],
            headers=db_headers)
        return res.status_code in (200, 201)
    except Exception:
        return False

def clear_markers(supabase_url, db_headers, date_str):
    """Delete today's job markers (player_id=0 rows) so a forced run can
    re-run daily_autorun / pregame_sweep / closing_snapshot. Used only by the
    manual 'force' path — never on the schedule. Returns True on success."""
    try:
        res = data.http_delete(
            f"{supabase_url}/rest/v1/predictions"
            f"?date=eq.{date_str}&player_id=eq.{MARKER_PLAYER_ID}",
            headers=db_headers)
        return res.status_code in (200, 204)
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

        sv_batters = {}
        if savant is not None:
            try:
                sv_batters = savant.fetch_batter_quality(year)
            except Exception:
                sv_batters = {}

        scan_results = pipeline.score_hitters(
            data, list(hitters.items()), year, split_code, split_label,
            batting_order, ctx['park_name'], pitcher_score, opp_fip_val,
            bullpen_era, live_odds, ctx['opp_pitcher_id'],
            savant_batters=sv_batters)

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


# ============================================================
# CLOSING-LINE SNAPSHOT (CLV groundwork)
# ============================================================
def should_close_snapshot(now_et, close_marker_exists, morning_ran, ctx):
    """Pure gate for the near-close odds capture: evening, still pregame, the
    morning picks exist, and it hasn't run yet today."""
    if now_et.hour < CLOSE_HOUR_ET:
        return False
    if close_marker_exists or not morning_ran:
        return False
    if not ctx or not ctx.get('is_pregame'):
        return False
    return True

def closing_snapshot(supabase_url, db_headers, db_headers_upsert, odds_api_key):
    """Capture near-close odds onto today's saved picks (closing_line /
    closing_price columns). If the database doesn't have those columns yet,
    this quietly does nothing — see README for the one-line SQL to enable it."""
    try:
        now = data.now_eastern()
        date_str = now.strftime("%Y-%m-%d")
        ctx = pipeline.game_context(data, date_str)
        morning = _marker_exists(supabase_url, db_headers, date_str, game_pk=0)
        closed  = _marker_exists(supabase_url, db_headers, date_str,
                                 game_pk=CLOSE_MARKER_GAME_PK)
        if not should_close_snapshot(now, closed, morning, ctx):
            return False
        if not _claim_marker(supabase_url, db_headers, date_str,
                             game_pk=CLOSE_MARKER_GAME_PK, name="_close"):
            return False

        odds, _msgs = data.fetch_reds_batter_odds(odds_api_key)
        if not odds:
            return False
        # fetch today's saved picks, patch each with its closing line
        res = data.http_get(
            f"{supabase_url}/rest/v1/predictions?date=eq.{date_str}"
            f"&player_id=gt.0&select=player_id,player_name", headers=db_headers)
        rows = res.json() if res.status_code == 200 else []
        from engine import normalize_name
        patched = 0
        for r in rows:
            rec = odds.get(normalize_name(r.get('player_name', '')))
            if not rec or rec.get('price') is None:
                continue
            pr = data.http_patch(
                f"{supabase_url}/rest/v1/predictions"
                f"?date=eq.{date_str}&player_id=eq.{r['player_id']}",
                json={"closing_line": rec.get('line'), "closing_price": rec.get('price')},
                headers=db_headers)
            if pr.status_code in (200, 204):
                patched += 1
            else:
                return False   # columns missing -> dormant until the SQL is run
        return patched > 0
    except Exception:
        return False


# ============================================================
# PREGAME SAFETY-NET SWEEP
# ============================================================
def should_pregame_sweep(now_et, sweep_marker_exists, ctx,
                         window_hours=SWEEP_WINDOW_HOURS):
    """Pure gate: within window_hours of first pitch, still pregame, once/day.
    Unparseable start times fail closed."""
    if sweep_marker_exists:
        return False
    if not ctx or not ctx.get('is_pregame'):
        return False
    try:
        start_et = dateutil.parser.isoparse(ctx.get('start_utc', '')) \
                                  .astimezone(data.EASTERN)
    except Exception:
        return False
    delta_h = (start_et - now_et).total_seconds() / 3600.0
    return 0.0 <= delta_h <= window_hours


def pregame_sweep(supabase_url, db_headers, db_headers_upsert,
                  odds_api_key, ntfy_topic):
    """The safety net: shortly before first pitch, make sure today's data
    exists. If the morning routine never ran, run it now; otherwise backfill
    any picks that were saved before DraftKings posted their lines.
    Returns the number of rows patched (0/None on no-op)."""
    try:
        now = data.now_eastern()
        date_str = now.strftime("%Y-%m-%d")
        ctx = pipeline.game_context(data, date_str)
        swept = _marker_exists(supabase_url, db_headers, date_str,
                               game_pk=SWEEP_MARKER_GAME_PK)
        if not should_pregame_sweep(now, swept, ctx):
            return None

        # Engines never ran today? The existing autorun handles everything
        # (picks + Ks + briefing, with its own once-a-day marker). Don't claim
        # the sweep marker in this path, so a later visit can still top up
        # odds if the lines appear even closer to first pitch.
        morning = _marker_exists(supabase_url, db_headers, date_str, game_pk=0)
        if not morning:
            daily_autorun(supabase_url, db_headers, db_headers_upsert,
                          odds_api_key, ntfy_topic)
            return None

        if not _claim_marker(supabase_url, db_headers, date_str,
                             game_pk=SWEEP_MARKER_GAME_PK, name="_sweep"):
            return None   # another session claimed it this instant

        # Which of today's picks are missing a price?
        res = data.http_get(
            f"{supabase_url}/rest/v1/predictions?date=eq.{date_str}"
            f"&player_id=gt.0&odds_price=is.null&select=player_id,player_name",
            headers=db_headers)
        rows = res.json() if res.status_code == 200 else []
        if not rows:
            return 0

        odds, _msgs = data.fetch_reds_batter_odds(odds_api_key)
        if not odds:
            return 0

        from engine import normalize_name
        patched = 0
        for r in rows:
            rec = odds.get(normalize_name(r.get('player_name', '')))
            if not rec or rec.get('price') is None:
                continue
            pr = data.http_patch(
                f"{supabase_url}/rest/v1/predictions"
                f"?date=eq.{date_str}&player_id=eq.{r['player_id']}",
                json={"odds_line": rec.get('line'), "odds_price": rec.get('price')},
                headers=db_headers)
            if pr.status_code in (200, 204):
                patched += 1

        if patched:
            data.ntfy_send(ntfy_topic, "🔴 Reds",
                           f"🔒 Lines locked: {patched} hitters priced — board's ready")
        return patched
    except Exception:
        return None   # never let the robot take anything down
