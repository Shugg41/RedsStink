"""Tests for the headless pipeline + briefing composer + autorun gate."""
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

import pipeline
import briefing


# ------------------------------------------------------------
# Stub fetch namespace — realistic-shaped fixture data, no network
# ------------------------------------------------------------
def _split_blob(ops="0.810", pa=120, avg="0.281"):
    return {"stats": [{"splits": [{"stat": {"ops": ops, "plateAppearances": pa,
                                            "avg": avg, "obp": ".350", "slg": ".460"}}]}]}

def _game_log(hits, runs, rbi, ks=1, ip="5.2"):
    return {"stat": {"hits": hits, "runs": runs, "rbi": rbi,
                     "strikeOuts": ks, "inningsPitched": ip}}

class StubFetch:
    def get_league_hitting(self, year):
        return {"obp": ".315", "slg": ".400"}
    def get_game_logs(self, pid, year, group="hitting"):
        if group == "pitching":
            return [_game_log(0, 0, 0, ks=6, ip="5.2") for _ in range(12)]
        return [_game_log(1, 1, 0), _game_log(2, 0, 1), _game_log(0, 0, 0),
                _game_log(1, 2, 2), _game_log(1, 0, 0)] * 4   # 20 games
    def get_season_stats(self, pid, group, year, split=None):
        return _split_blob()
    def get_advanced_hitting(self, pid, year):
        return {"babip": "0.305", "strikeoutsPerPlateAppearance": "0.21", "iso": "0.180"}
    def get_advanced_pitching(self, pid, year):
        return {"strikeoutsPer9Inn": "9.5", "whip": "1.15",
                "strikeoutsPerPlateAppearance": "0.26", "walksPerPlateAppearance": "0.07",
                "gamesStarted": 12, "gamesPlayed": 12, "inningsPitched": "68.0",
                "era": "3.80"}
    def get_career_splits(self, pid, group, split_code):
        return _split_blob()
    def get_team_splits(self, team_id, year, split_code):
        return {"plateAppearances": 2000, "strikeOuts": 500,
                "pitchesPerPlateAppearance": "3.90"}
    def get_bvp_stats(self, batter_id, pitcher_id):
        return {"avg": "0.320", "plateAppearances": 14}
    def get_pitcher_hand(self, pid):
        return "R"
    def get_pitcher_k_stats(self, pid, year):
        logs = self.get_game_logs(pid, year, group="pitching")[-5:]
        ks   = [g["stat"]["strikeOuts"] for g in logs]
        return (self.get_advanced_pitching(pid, year), ks,
                round(sum(ks) / len(ks), 1), 5.7)
    def get_schedule(self, date_str):
        return {"totalGames": 1, "dates": [{"games": [{
            "gamePk": 999, "venue": {"name": "Great American Ball Park"},
            "status": {"statusCode": "S"},
            "gameDate": "2026-07-04T23:10:00Z",
            "teams": {"away": {"team": {"id": 120, "name": "Washington Nationals"}},
                      "home": {"team": {"id": 113, "name": "Cincinnati Reds"}}}}]}]}
    def get_game_starters(self, game_pk):
        return {"away": {"id": 555, "name": "Opp Ace"},
                "home": {"id": 777, "name": "Reds Arm"}}


FETCH = StubFetch()
HITTERS = [("Test Hitter A", 1), ("Test Hitter B", 2)]


# ------------------------------------------------------------
# score_hitters — full offline smoke of the offense board
# ------------------------------------------------------------
def test_score_hitters_produces_full_rows():
    rows = pipeline.score_hitters(
        FETCH, HITTERS, 2026, "vr", "RHP", [1], "Great American Ball Park",
        pitcher_score=5, opp_fip_val=4.2, bullpen_era=4.5,
        live_odds={}, opp_pitcher_id=555)
    assert len(rows) == 2
    r = rows[0]
    for key in ("Player", "Score", "Tier", "Mult_Score", "HRR_Proj", "HRR_P2", "DK_Info"):
        assert key in r
    assert 0 <= r["Score"] <= 100
    assert 0 <= r["HRR_P2"] <= 1

def test_score_hitters_lineup_bonus_applies():
    in_lineup  = pipeline.score_hitters(FETCH, [("A", 1)], 2026, "vr", "RHP",
                                        [1], "", 0, 4.0, 4.0, {}, 555)[0]
    no_lineup  = pipeline.score_hitters(FETCH, [("A", 1)], 2026, "vr", "RHP",
                                        [], "", 0, 4.0, 4.0, {}, 555)[0]
    assert in_lineup["Score"] >= no_lineup["Score"]   # batting leadoff = top bonus

def test_hitting_payload_shape():
    rows = pipeline.score_hitters(FETCH, HITTERS, 2026, "vr", "RHP", [], "",
                                  0, 4.0, 4.0, {}, 555)
    payload = pipeline.hitting_payload(rows, "2026-07-04", 999, "Opp Ace")
    assert len(payload) == 2
    p = payload[0]
    assert p["date"] == "2026-07-04" and p["game_pk"] == 999
    assert p["graded"] == 0 and p["opp_pitcher"] == "Opp Ace"


# ------------------------------------------------------------
# run_strikeout_engine via fetch namespace
# ------------------------------------------------------------
def test_k_engine_headless():
    proj, receipt, meta = pipeline.run_strikeout_engine(
        FETCH, 777, "Reds Arm", 120, "Nationals", "Great American Ball Park", 2026)
    assert proj is not None and 2.0 <= proj <= 12.0
    assert meta["data_ok"] is True and meta["opener"] is False
    assert len(receipt) >= 5

def test_pitching_payload_shape():
    p = pipeline.pitching_payload(
        [{"player_id": 777, "player_name": "Reds Arm", "projected_ks": 6.3}],
        "2026-07-04", 999)[0]
    assert p["projected_ks"] == 6.3 and p["graded"] == 0 and p["game_pk"] == 999


# ------------------------------------------------------------
# game_context
# ------------------------------------------------------------
def test_game_context_resolves_reds_side():
    ctx = pipeline.game_context(FETCH, "2026-07-04")
    assert ctx["opponent"] == "Washington Nationals"
    assert ctx["opp_pitcher_id"] == 555 and ctx["reds_pitcher_id"] == 777
    assert ctx["is_pregame"] is True and ctx["game_pk"] == 999

def test_game_context_none_on_offday():
    class OffDay(StubFetch):
        def get_schedule(self, date_str):
            return {"totalGames": 0}
    assert pipeline.game_context(OffDay(), "2026-07-04") is None


# ------------------------------------------------------------
# briefing compose + autorun gate
# ------------------------------------------------------------
def _ctx():
    return {"opponent": "Cubs", "park_name": "GABP", "start_utc": "2026-07-04T23:10:00Z",
            "opp_pitcher_name": "Some Guy", "opp_pitcher_id": 1,
            "is_pregame": True}

def test_compose_briefing_includes_top_players_and_ks():
    rows = [{"Player": "Elly", "Score": 88, "HRR_Proj": 2.4, "HRR_P2": 0.61,
             "DK_Info": {"hrr_price": -140}},
            {"Player": "Bleday", "Score": 71, "HRR_Proj": 1.9, "HRR_P2": 0.44,
             "DK_Info": {}}]
    ks = [{"player_name": "Greene", "projected_ks": 6.8}]
    text = briefing.compose_briefing(_ctx(), rows, ks, odds_found=True)
    assert "Elly 88" in text and "Greene" in text and "6.8" in text
    assert "odds locked in" in text
    assert "Best HRR: Elly" in text

def test_compose_briefing_handles_empty_board():
    text = briefing.compose_briefing(_ctx(), [], [], odds_found=False)
    assert "Cubs" in text and "no DK lines" in text

def _et(hour):
    return datetime(2026, 7, 4, hour, 30, tzinfo=ZoneInfo("America/New_York"))

def test_autorun_gate_rules():
    ctx = _ctx()
    assert briefing.should_autorun(_et(10), False, ctx) is True
    assert briefing.should_autorun(_et(7),  False, ctx) is False        # too early
    assert briefing.should_autorun(_et(10), True,  ctx) is False        # already ran
    assert briefing.should_autorun(_et(10), False, None) is False       # off day
    late = dict(ctx, is_pregame=False)
    assert briefing.should_autorun(_et(10), False, late) is False       # game started
    tbd = dict(ctx, opp_pitcher_id=None)
    assert briefing.should_autorun(_et(10), False, tbd) is False        # probables not posted
