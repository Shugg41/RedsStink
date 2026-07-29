"""
inspect_data.py — READ-ONLY snapshot of the saved data, printed to the log.

Pulls the `predictions` and `pitcher_predictions` tables from Supabase and runs
them through backtest.py's existing metrics (season scoreboard, win rate, ROI,
calibration, K-engine accuracy) plus a recent-picks table. Writes NOTHING back —
safe to run any time to "look at the data" from a GitHub Action log.

Config (GitHub secrets / env): SUPABASE_URL, SUPABASE_KEY.
"""
import os
import sys

import backtest


def _pull(url, key, table):
    import requests
    headers = {"apikey": key, "Authorization": f"Bearer {key}"}
    res = requests.get(f"{url}/rest/v1/{table}?select=*", headers=headers, timeout=20)
    res.raise_for_status()
    return res.json()


def run(env=None):
    env = env if env is not None else os.environ
    url, key = env.get("SUPABASE_URL"), env.get("SUPABASE_KEY")
    if not url or not key:
        print("inspect: SUPABASE_URL / SUPABASE_KEY not set — nothing to read.")
        return 1

    rows = _pull(url, key, "predictions")
    picks = [r for r in rows if int(r.get("player_id") or 0) > 0]   # drop marker rows
    graded = backtest.graded_rows(picks)
    dates = sorted({r.get("date") for r in picks if r.get("date")})
    print(f"Saved pick rows : {len(picks)}")
    print(f"Graded plays    : {len(graded)}")
    print(f"Game-days       : {len(dates)}"
          + (f"  ({dates[0]} … {dates[-1]})" if dates else ""))
    print()

    sb = backtest.season_scoreboard(picks)
    if sb:
        print("=" * 60)
        print(f"  SEASON SCOREBOARD — {sb['n_games']} games, {sb['n_graded']} graded plays")
        print("  (each model graded on the Tier-1 plays IT recommended)")
        print("=" * 60)
        for label, k in (("Additive", "additive"), ("Multiplicative", "mult")):
            s = sb[k]
            line = (f"  {label:>14}: {s['wins']}-{s['losses']}  "
                    f"({s['win_rate'] * 100:.1f}% win, n={s['n']})")
            if s.get("n_priced"):
                line += f"  |  {s['units']:+.2f}u, {s['roi_pct']:+.1f}% ROI (n_priced={s['n_priced']})"
            if s.get("brier_n"):
                line += f"  |  Brier {s['brier']:.3f}"
            print(line)
        v = backtest.scoreboard_verdict(sb)
        if v:
            names = {"additive": "Additive", "mult": "Multiplicative", "tie": "Tie"}
            print(f"  Leader: {names.get(v['leader'], v['leader'])}  (by {v['basis']})")
        print()

    # Full backtest for each engine (calibration + threshold sweep + best cutoff)
    backtest.summarize(picks, "score", "ADDITIVE (score)")
    backtest.summarize(picks, "mult_score", "MULTIPLICATIVE (mult_score)")

    # Strikeout-engine accuracy
    try:
        pit = _pull(url, key, "pitcher_predictions")
        ks = backtest.k_engine_summary(pit)
        print("=" * 60)
        print("  STRIKEOUT ENGINE")
        print("=" * 60)
        print(f"  Graded projections : {ks['n']}")
        if ks["n"]:
            print(f"  Avg miss           : {ks['avg_miss']} Ks  (|actual - projected|, lower=better)")
            drift = "pitchers K MORE than projected" if ks["bias"] > 0 else "engine runs high"
            print(f"  Bias               : {ks['bias']:+.2f}  ({drift})")
        print()
    except Exception as e:
        print(f"  (pitcher data unavailable: {e})\n")

    # Recent graded picks
    recent = sorted(graded, key=lambda r: (r.get("date") or "",
                                           float(r.get("score") or 0)), reverse=True)[:15]
    if recent:
        print("=" * 60)
        print("  RECENT GRADED PICKS (newest first)")
        print("=" * 60)
        print(f"  {'date':>10}  {'player':<20} {'sc':>4} {'tier':<7} {'H':>2} {'HRR':>3}  result")
        for r in recent:
            res = "WIN " if int(r.get("win") or 0) == 1 else "loss"
            print(f"  {str(r.get('date','')):>10}  {str(r.get('player_name') or '')[:20]:<20} "
                  f"{str(r.get('score','')):>4} {str(r.get('tier') or '')[:7]:<7} "
                  f"{str(r.get('actual_hits','')):>2} {str(r.get('actual_hrr','')):>3}  {res}")
        print()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(run())
    except SystemExit:
        raise
    except Exception as e:
        print(f"inspect: error: {e}", file=sys.stderr)
        raise SystemExit(0)
