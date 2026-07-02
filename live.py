"""
live.py — in-game "sweat tracker" helpers (pure parsing + math, no I/O).

Parses the MLB live feed into a snapshot, estimates each hitter's remaining
opportunity, and gives a live P(clear) for the bets saved this morning.
"""
from engine import _safe_float, poisson_at_least

LIVE_CODES  = ("I", "IR", "IH", "MA", "MC")   # in progress / delayed-ish
FINAL_CODES = ("F", "O", "CR", "FR")

TEAM_PA_PER_INNING = 4.25   # league-average plate appearances per team inning


def reds_is_home(feed):
    try:
        return feed["gameData"]["teams"]["home"]["id"] == 113
    except Exception:
        return True

def live_snapshot(feed):
    """Flatten the live feed into what the sweat tracker needs. Returns None
    when the feed is empty/unusable."""
    if not feed:
        return None
    try:
        gd = feed.get("gameData", {})
        ld = feed.get("liveData", {})
        lines = ld.get("linescore", {})
        home = reds_is_home(feed)
        side, opp_side = ("home", "away") if home else ("away", "home")
        box = ld.get("boxscore", {}).get("teams", {})

        batting, pitching = {}, {}
        for pkey, pdata in (box.get(side, {}).get("players", {}) or {}).items():
            stats = pdata.get("stats", {})
            bat = stats.get("batting", {})
            if bat:
                pid = pdata.get("person", {}).get("id")
                batting[pid] = {"hits": int(bat.get("hits", 0) or 0),
                                "runs": int(bat.get("runs", 0) or 0),
                                "rbi":  int(bat.get("rbi", 0) or 0),
                                "pa":   int(bat.get("plateAppearances", 0) or 0)}
        # both sides' pitchers (we track Reds starter AND the opponent's)
        for s in ("home", "away"):
            for pkey, pdata in (box.get(s, {}).get("players", {}) or {}).items():
                pit = pdata.get("stats", {}).get("pitching", {})
                if pit:
                    pid = pdata.get("person", {}).get("id")
                    pitching[pid] = {"ks": int(pit.get("strikeOuts", 0) or 0),
                                     "outs": int(pit.get("outs", 0) or 0)}

        return {
            "status_code": gd.get("status", {}).get("statusCode", ""),
            "abstract":    gd.get("status", {}).get("abstractGameState", ""),
            "inning":      int(lines.get("currentInning", 0) or 0),
            "half":        (lines.get("inningHalf", "") or "").lower(),
            "reds_runs":   int(lines.get("teams", {}).get(side, {}).get("runs", 0) or 0),
            "opp_runs":    int(lines.get("teams", {}).get(opp_side, {}).get("runs", 0) or 0),
            "reds_home":   home,
            "batting":     batting,
            "pitching":    pitching,
        }
    except Exception:
        return None

def is_live(snap):
    return bool(snap) and (snap.get("status_code") in LIVE_CODES
                           or snap.get("abstract") == "Live")

def remaining_offense_innings(inning, half, reds_home):
    """How many more innings the Reds are expected to bat (fractional game
    remaining, capped at 9 — ignores extras/walk-off truncation)."""
    if inning <= 0:
        return 9.0
    if reds_home:
        # Reds bat in the bottom half
        done = (inning - 1) + (0.0 if half in ("top", "middle", "mid") else
                               (1.0 if half in ("bottom", "end") else 0.0))
        # treat 'end' of inning N as N bottoms complete
        if half in ("end",):
            done = inning
    else:
        done = (inning - 1) + (1.0 if half in ("bottom", "end", "middle", "mid") else 0.5)
        if half == "top":
            done = inning - 0.5
    return max(0.0, 9.0 - done)

def hitter_p_clear(current, line, rate_per_game, innings_left):
    """Live P(finishing over the line): current + Poisson(remaining share of
    the game at the pregame rate)."""
    needed = int(line) + 1 - int(current)   # x.5 line -> need floor(line)+1 total
    if needed <= 0:
        return 1.0
    lam = _safe_float(rate_per_game) * max(0.0, min(1.0, innings_left / 9.0))
    return round(poisson_at_least(needed, lam), 4)

def starter_p_clear(current_ks, line, projected_ks, exp_ip, outs_recorded):
    """Live P(starter clears his K line) given outs already recorded."""
    needed = int(line) + 1 - int(current_ks)
    if needed <= 0:
        return 1.0
    ip_done = _safe_float(outs_recorded) / 3.0
    ip_left = max(0.0, _safe_float(exp_ip, 5.5) - ip_done)
    if _safe_float(exp_ip, 5.5) <= 0:
        return 0.0
    lam = _safe_float(projected_ks) * (ip_left / _safe_float(exp_ip, 5.5))
    return round(poisson_at_least(needed, lam), 4)
