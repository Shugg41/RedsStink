"""
savant.py — free Statcast data from Baseball Savant's public leaderboard CSVs.

Two batter feeds, one pitcher feed, all one-request-per-day:
  * expected stats (xBA / xwOBA / xSLG): the honest "deserved" numbers — a far
    sharper luck detector than BABIP
  * exit-velo / barrels: real power quality for the HRR engine
  * pitcher expected stats: contact quality allowed (feeds the simulator)

All parsing is defensive: any failure returns {} and the engines silently run
exactly as they did before Statcast existed.
"""
import csv
import io

import data

SAVANT = "https://baseballsavant.mlb.com/leaderboard"
_HDRS = {"User-Agent": "Mozilla/5.0 (RedsStink dashboard)"}


def _rows_from_csv(url):
    try:
        res = data.http_get(url, headers=_HDRS, timeout=20)
        if res.status_code != 200 or not res.text:
            return []
        return list(csv.DictReader(io.StringIO(res.text)))
    except Exception:
        return []

def _num(row, *keys):
    """First parseable float among fuzzy column-name candidates."""
    for want in keys:
        for col, val in row.items():
            if col and want in col.strip().lower():
                try:
                    return float(val)
                except (TypeError, ValueError):
                    break
    return None

def _pid(row):
    for col in ("player_id", "playerid", "id"):
        for k, v in row.items():
            if k and k.strip().lower() == col:
                try:
                    return int(v)
                except (TypeError, ValueError):
                    return None
    return None


def fetch_batter_xstats(year):
    """{player_id: {'ba', 'xba', 'woba', 'xwoba', 'xslg'}} from expected stats."""
    url = (f"{SAVANT}/expected_statistics?type=batter&year={year}"
           f"&position=&team=&filterType=bip&min=25&csv=true")
    out = {}
    for row in _rows_from_csv(url):
        pid = _pid(row)
        if not pid:
            continue
        rec = {
            "ba":    _num(row, "est_ba_minus") and None or _num(row, "ba"),
            "xba":   _num(row, "est_ba", "xba"),
            "woba":  _num(row, "woba"),
            "xwoba": _num(row, "est_woba", "xwoba"),
            "xslg":  _num(row, "est_slg", "xslg"),
        }
        # 'ba' fuzzy can catch est_ba first — grab the exact column when present
        for k, v in row.items():
            if k and k.strip().lower() == "ba":
                try:
                    rec["ba"] = float(v)
                except (TypeError, ValueError):
                    pass
        if rec.get("xba") is not None:
            out[pid] = rec
    return out

def fetch_batter_power(year):
    """{player_id: {'brl_percent', 'avg_hit_speed'}} from the exit-velo board."""
    url = (f"{SAVANT}/statcast?type=batter&year={year}"
           f"&position=&team=&min=25&csv=true")
    out = {}
    for row in _rows_from_csv(url):
        pid = _pid(row)
        if not pid:
            continue
        rec = {
            "brl_percent":   _num(row, "brl_percent", "barrel"),
            "avg_hit_speed": _num(row, "avg_hit_speed", "exit_velocity"),
        }
        if rec.get("brl_percent") is not None or rec.get("avg_hit_speed") is not None:
            out[pid] = rec
    return out

def fetch_pitcher_xstats(year):
    """{player_id: {'xwoba', 'xba'}} allowed — contact quality against."""
    url = (f"{SAVANT}/expected_statistics?type=pitcher&year={year}"
           f"&position=&team=&filterType=bip&min=25&csv=true")
    out = {}
    for row in _rows_from_csv(url):
        pid = _pid(row)
        if not pid:
            continue
        rec = {"xwoba": _num(row, "est_woba", "xwoba"),
               "xba":   _num(row, "est_ba", "xba")}
        if rec.get("xwoba") is not None:
            out[pid] = rec
    return out

def fetch_batter_quality(year):
    """Merged batter view: xstats + power, keyed by MLB player id."""
    quality = fetch_batter_xstats(year)
    power   = fetch_batter_power(year)
    for pid, rec in power.items():
        quality.setdefault(pid, {}).update(rec)
    return quality
