"""
backtest.py — replay graded predictions to measure (and tune) the engine.

This is a standalone harness: NO Streamlit. It answers questions the live
"proof layer" can't, like "what score cutoff would actually have made money?".

Usage
-----
  # Pull graded rows straight from Supabase (reads env vars):
  SUPABASE_URL=https://xxx.supabase.co SUPABASE_KEY=... python backtest.py

  # Or replay an offline snapshot (a JSON list of prediction rows):
  python backtest.py rows.json

  # Score the multiplicative engine instead of the additive one:
  python backtest.py --engine mult            [rows.json]

Each prediction row is expected to look like the `predictions` table:
  score, mult_score, tier, mult_tier, win (1/0/-1), graded (1/0/-1),
  odds_price, odds_line, player_name, date, ...

Only graded straight bets (graded == 1, win in {0, 1}) are counted; no-game
rows (win == -1) and ungraded rows are ignored.
"""
import os
import sys
import json

from engine import units_won, TIER1_THRESHOLD, TIER2_THRESHOLD


# ============================================================
# LOADING
# ============================================================
def load_rows_from_file(path):
    with open(path) as f:
        data = json.load(f)
    if isinstance(data, dict) and "rows" in data:
        data = data["rows"]
    if not isinstance(data, list):
        raise ValueError("Expected a JSON list of prediction rows")
    return data

def load_rows_from_supabase(url, key):
    import requests  # lazy: offline mode shouldn't require it
    headers = {"apikey": key, "Authorization": f"Bearer {key}"}
    res = requests.get(f"{url}/rest/v1/predictions?select=*", headers=headers, timeout=20)
    res.raise_for_status()
    return res.json()


# ============================================================
# PURE METRIC REDUCERS (unit-tested)
# ============================================================
def graded_rows(rows):
    """Keep only graded straight bets with a real win/loss (drops no-game and
    ungraded rows)."""
    out = []
    for r in rows:
        try:
            if int(r.get("graded", 0)) == 1 and int(r.get("win", -1)) in (0, 1):
                out.append(r)
        except (TypeError, ValueError):
            continue
    return out

def _wins(rows):
    return [int(r["win"]) for r in rows]

def win_rate(rows):
    """Return (rate_0_to_1, n). Empty -> (0.0, 0)."""
    w = _wins(rows)
    return (sum(w) / len(w), len(w)) if w else (0.0, 0)

def brier(rows, score_key="score"):
    """Mean Brier score using model_prob = score/100. Lower is better; 0.25 is
    a coin flip. Returns (brier, n) over rows that have a usable score."""
    terms = []
    for r in rows:
        try:
            p = float(r[score_key]) / 100.0
            terms.append((p - int(r["win"])) ** 2)
        except (KeyError, TypeError, ValueError):
            continue
    return (sum(terms) / len(terms), len(terms)) if terms else (0.0, 0)

def roi(rows):
    """Units and ROI over rows that carry a price. 1u flat stake.
    Returns (total_units, roi_pct, n_priced)."""
    priced = [r for r in rows if r.get("odds_price") not in (None, "")]
    if not priced:
        return (0.0, 0.0, 0)
    units = sum(units_won(r["odds_price"], int(r["win"])) for r in priced)
    return (round(units, 3), round(units / len(priced) * 100, 2), len(priced))

def calibration(rows, score_key="score", edges=(0, 55, 65, 75, 85, 101)):
    """Bucket rows by score and report hit rate per bucket. Returns a list of
    dicts: {bucket, lo, hi, n, win_rate}."""
    buckets = []
    for lo, hi in zip(edges, edges[1:]):
        sub = []
        for r in rows:
            try:
                s = float(r[score_key])
            except (KeyError, TypeError, ValueError):
                continue
            if lo <= s < hi:
                sub.append(r)
        rate, n = win_rate(sub)
        buckets.append({"bucket": f"{lo}-{hi-1}", "lo": lo, "hi": hi,
                        "n": n, "win_rate": rate})
    return buckets

def threshold_sweep(rows, score_key="score", lo=40, hi=95, step=5):
    """For each candidate cutoff, treat score >= cutoff as a bet and report how
    that slice would have done. This is the 'where should Tier 1 start?' tool.
    Returns a list of dicts: {threshold, n, win_rate, units, roi_pct, n_priced}."""
    results = []
    for thr in range(lo, hi + 1, step):
        slice_ = []
        for r in rows:
            try:
                if float(r[score_key]) >= thr:
                    slice_.append(r)
            except (KeyError, TypeError, ValueError):
                continue
        rate, n = win_rate(slice_)
        units, roi_pct, n_priced = roi(slice_)
        results.append({"threshold": thr, "n": n, "win_rate": rate,
                        "units": units, "roi_pct": roi_pct, "n_priced": n_priced})
    return results

def best_threshold(rows, score_key="score", min_priced=10, **kw):
    """Pick the cutoff with the best ROI among options that have enough priced
    bets to be meaningful. Returns the winning sweep dict, or None."""
    candidates = [s for s in threshold_sweep(rows, score_key, **kw)
                  if s["n_priced"] >= min_priced]
    if not candidates:
        return None
    return max(candidates, key=lambda s: s["roi_pct"])


def last_game_recap(rows):
    """Quick 'how did we do last game?' summary of the most recent graded date.

    Counts the straight bets (Tier 1 & 2 — Tier 3 are fades, not plays) and
    returns wins/losses, win rate, Tier-1 units, the opponent, and the per-pick
    list sorted best-first. Returns None if there are no graded plays yet.
    """
    g = [r for r in graded_rows(rows) if r.get("date")]
    if not g:
        return None
    last_date = max(r["date"] for r in g)
    day = [r for r in g if r["date"] == last_date]

    def _tier(r):
        return str(r.get("tier", ""))

    straight = [r for r in day if "Tier 3" not in _tier(r)]   # 1 & 2 = the bets
    wins   = sum(1 for r in straight if int(r["win"]) == 1)
    losses = sum(1 for r in straight if int(r["win"]) == 0)
    rate, n = win_rate(straight)
    units, roi_pct, n_priced = roi([r for r in straight if "Tier 1" in _tier(r)])
    opp = next((r.get("opp_pitcher") for r in day if r.get("opp_pitcher")), None)
    picks = sorted(straight,
                   key=lambda r: (0 if "Tier 1" in _tier(r) else 1,
                                  -float(r.get("score", 0) or 0)))
    return {
        "date": last_date, "opp_pitcher": opp,
        "wins": wins, "losses": losses, "n": n, "win_rate": rate,
        "units": units, "roi_pct": roi_pct, "n_priced": n_priced,
        "picks": picks,
    }


# ============================================================
# REPORT
# ============================================================
def _bar(rate, width=20):
    filled = int(round(rate * width))
    return "█" * filled + "·" * (width - filled)

def summarize(rows, score_key="score", engine_label="ADDITIVE (score)"):
    g = graded_rows(rows)
    print("=" * 60)
    print(f"  BACKTEST — {engine_label}")
    print("=" * 60)
    if not g:
        print("  No graded straight bets found. Nothing to backtest yet.")
        return

    rate, n = win_rate(g)
    b, bn = brier(g, score_key)
    units, roi_pct, n_priced = roi(g)
    print(f"  Graded plays      : {n}")
    print(f"  Win rate          : {rate*100:.1f}%   {_bar(rate)}")
    print(f"  Brier ({score_key:<5})     : {b:.3f}  (0.25 = coin flip, n={bn})")
    if n_priced:
        print(f"  ROI (priced bets) : {roi_pct:+.1f}%  over {n_priced} bets")
        print(f"  Net units         : {units:+.2f}u  (1u flat)")
    else:
        print("  ROI               : n/a (no stored odds)")

    print("\n  Calibration (hit rate should climb with score):")
    for row in calibration(g, score_key):
        if row["n"]:
            print(f"    {row['bucket']:>7} | {row['win_rate']*100:5.1f}%  "
                  f"{_bar(row['win_rate'])}  (n={row['n']})")

    print("\n  Threshold sweep (score >= cutoff):")
    print(f"    {'cut':>4} {'plays':>6} {'win%':>6} {'ROI%':>7} {'units':>7} {'priced':>7}")
    for s in threshold_sweep(g, score_key):
        if s["n"]:
            print(f"    {s['threshold']:>4} {s['n']:>6} {s['win_rate']*100:>5.1f}% "
                  f"{s['roi_pct']:>6.1f}% {s['units']:>+7.2f} {s['n_priced']:>7}")

    best = best_threshold(g, score_key)
    if best:
        print(f"\n  Best ROI cutoff (>= {best['n_priced']} priced bets): "
              f"score >= {best['threshold']}  ->  {best['roi_pct']:+.1f}% ROI "
              f"({best['win_rate']*100:.1f}% win, {best['units']:+.2f}u)")
        print(f"  (current Tier 1 starts at {TIER1_THRESHOLD})")
    print()


# ============================================================
# CLI
# ============================================================
def _parse_args(argv):
    engine = "score"
    path = None
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--engine":
            i += 1
            choice = argv[i] if i < len(argv) else "additive"
            engine = "mult_score" if choice.startswith("mult") else "score"
        else:
            path = a
        i += 1
    return engine, path

def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    score_key, path = _parse_args(argv)
    label = "MULTIPLICATIVE (mult_score)" if score_key == "mult_score" else "ADDITIVE (score)"

    if path:
        rows = load_rows_from_file(path)
        print(f"Loaded {len(rows)} rows from {path}")
    else:
        url = os.environ.get("SUPABASE_URL")
        key = os.environ.get("SUPABASE_KEY")
        if not url or not key:
            print("No file given and SUPABASE_URL / SUPABASE_KEY not set.\n"
                  "  Pass a JSON snapshot:  python backtest.py rows.json\n"
                  "  Or export the env vars to pull from Supabase.")
            return 1
        rows = load_rows_from_supabase(url, key)
        print(f"Loaded {len(rows)} rows from Supabase")

    summarize(rows, score_key=score_key, engine_label=label)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
