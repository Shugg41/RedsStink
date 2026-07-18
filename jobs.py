"""
jobs.py — headless daily-job runner for the GitHub Actions cron.

Streamlit Community Cloud can't reliably run the briefing in a background
thread (a bot visit only keeps the app alive ~15s, so the work gets killed
mid-run and the day is silently lost). This runs the exact same headless
functions directly from a real cron, to completion, with logging.

Config comes from environment variables (GitHub Actions secrets):
    SUPABASE_URL, SUPABASE_KEY   (required — no-op without them)
    ODDS_API_KEY                 (optional — odds skipped without it)
    NTFY_TOPIC                   (optional — defaults to the app's topic)

Every job is ET-time-gated and marker-guarded inside briefing.py, so running
this on every cron tick is idempotent: each job no-ops unless its window is
open and it hasn't already run today.
"""
import os
import sys

import briefing

DEFAULT_NTFY_TOPIC = "redsstink-briefing-rk84vq"


def _db_headers(supabase_key):
    """Mirror app.py's Supabase header construction."""
    base = {
        "apikey": supabase_key,
        "Authorization": f"Bearer {supabase_key}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }
    upsert = dict(base)
    upsert["Prefer"] = "resolution=merge-duplicates,return=representation"
    return base, upsert


def run(env=None):
    """Run the three daily jobs. Returns a dict of their results (for tests)."""
    env = env if env is not None else os.environ
    supabase_url = env.get("SUPABASE_URL")
    supabase_key = env.get("SUPABASE_KEY")
    odds_api_key = env.get("ODDS_API_KEY")
    ntfy_topic   = env.get("NTFY_TOPIC") or DEFAULT_NTFY_TOPIC

    if not supabase_url or not supabase_key:
        print("jobs: SUPABASE_URL / SUPABASE_KEY not set — nothing to do.")
        return {"skipped": "no supabase config"}

    db_headers, db_headers_upsert = _db_headers(supabase_key)
    common = dict(supabase_url=supabase_url, db_headers=db_headers,
                  db_headers_upsert=db_headers_upsert, odds_api_key=odds_api_key)

    results = {}
    # Morning briefing (board + picks + K projections + push). Gate: >=9am ET,
    # pregame, probables posted, once/day.
    results["daily_autorun"] = briefing.daily_autorun(ntfy_topic=ntfy_topic, **common)
    print(f"jobs: daily_autorun -> {results['daily_autorun']!r}")

    # Pregame safety-net (backfill lines / run engines if morning missed).
    results["pregame_sweep"] = briefing.pregame_sweep(ntfy_topic=ntfy_topic, **common)
    print(f"jobs: pregame_sweep -> {results['pregame_sweep']!r}")

    # Closing-line snapshot for CLV (dormant unless the columns exist).
    results["closing_snapshot"] = briefing.closing_snapshot(**common)
    print(f"jobs: closing_snapshot -> {results['closing_snapshot']!r}")

    return results


if __name__ == "__main__":
    try:
        run()
    except Exception as e:                      # never fail the workflow step
        print(f"jobs: unexpected error: {e}", file=sys.stderr)
    sys.exit(0)
