"""Tests for the live sweat-tracker helpers."""
import pytest

import live


def _feed(inning=5, half="Top", reds_home=True, reds_runs=3, opp_runs=2,
          status="I", batting=None, pitching=None):
    side, opp = ("home", "away") if reds_home else ("away", "home")
    players = {}
    for pid, (h, r, rbi) in (batting or {}).items():
        players[f"ID{pid}"] = {"person": {"id": pid},
                               "stats": {"batting": {"hits": h, "runs": r, "rbi": rbi,
                                                     "plateAppearances": 3}}}
    pit_players = {}
    for pid, (ks, outs) in (pitching or {}).items():
        pit_players[f"ID{pid}"] = {"person": {"id": pid},
                                   "stats": {"pitching": {"strikeOuts": ks, "outs": outs}}}
    return {
        "gameData": {"status": {"statusCode": status, "abstractGameState": "Live"},
                     "teams": {"home": {"id": 113 if reds_home else 999},
                               "away": {"id": 999 if reds_home else 113}}},
        "liveData": {
            "linescore": {"currentInning": inning, "inningHalf": half,
                          "teams": {side: {"runs": reds_runs}, opp: {"runs": opp_runs}}},
            "boxscore": {"teams": {side: {"players": {**players, **pit_players}},
                                   opp: {"players": pit_players}}},
        },
    }


def test_snapshot_parses_score_and_stats():
    feed = _feed(batting={682829: (2, 1, 1)}, pitching={777: (5, 12)})
    snap = live.live_snapshot(feed)
    assert snap["reds_runs"] == 3 and snap["opp_runs"] == 2
    assert snap["inning"] == 5 and snap["half"] == "top"
    assert snap["batting"][682829]["hits"] == 2
    assert snap["pitching"][777]["ks"] == 5
    assert live.is_live(snap)

def test_snapshot_none_on_garbage():
    assert live.live_snapshot({}) is None
    assert live.live_snapshot(None) is None

def test_remaining_innings_shrinks_as_game_goes():
    early = live.remaining_offense_innings(2, "top", True)
    late  = live.remaining_offense_innings(8, "bottom", True)
    assert early > late
    assert live.remaining_offense_innings(0, "", True) == 9.0

def test_home_team_still_bats_bottom_of_current_inning():
    # Top 9, Reds home -> they still get the bottom 9th
    assert live.remaining_offense_innings(9, "top", True) >= 1.0


def test_hitter_p_clear_already_cleared():
    assert live.hitter_p_clear(2, 1.5, 2.0, 4) == 1.0

def test_hitter_p_clear_decreases_with_less_game_left():
    early = live.hitter_p_clear(0, 1.5, 2.2, innings_left=8)
    late  = live.hitter_p_clear(0, 1.5, 2.2, innings_left=1)
    assert early > late
    assert 0.0 <= late <= 1.0

def test_starter_p_clear_behaviour():
    assert live.starter_p_clear(7, 6.5, 6.8, 6.0, 12) == 1.0        # already over
    mid  = live.starter_p_clear(4, 6.5, 7.0, 6.0, outs_recorded=9)   # 3 IP done
    done = live.starter_p_clear(4, 6.5, 7.0, 6.0, outs_recorded=18)  # pulled at 6
    assert 0 < mid < 1
    assert done < mid   # no innings left -> nearly no chance
