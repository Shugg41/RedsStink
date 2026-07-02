"""Tests for the all-books odds parsing + line-shopping resolution."""
import pytest

import data


def _game(bookmakers):
    return {"bookmakers": bookmakers}

def _book(key, title, market_key, outcomes):
    return {"key": key, "title": title,
            "markets": [{"key": market_key, "outcomes": outcomes}]}

def _over(name, point, price):
    return {"name": "Over", "description": name, "point": point, "price": price}

def _under(name, point, price):
    return {"name": "Under", "description": name, "point": point, "price": price}


# ------------------------------------------------------------
# batter odds: DK reference + best across books at the same line
# ------------------------------------------------------------
def test_batter_odds_best_price_across_books():
    game = _game([
        _book("draftkings", "DraftKings", "batter_hits",
              [_over("Elly De La Cruz", 0.5, -150)]),
        _book("fanduel", "FanDuel", "batter_hits",
              [_over("Elly De La Cruz", 0.5, -128)]),
        _book("betmgm", "BetMGM", "batter_hits",
              [_over("Elly De La Cruz", 0.5, -145)]),
    ])
    out = data.parse_batter_odds(game)
    rec = out["elly de la cruz"]
    assert rec["line"] == 0.5 and rec["price"] == -150      # DK reference
    assert rec["best_price"] == -128 and rec["best_book"] == "FanDuel"

def test_batter_odds_ignores_other_lines_for_best():
    game = _game([
        _book("draftkings", "DraftKings", "batter_hits",
              [_over("Guy", 0.5, -150)]),
        _book("fanduel", "FanDuel", "batter_hits",
              [_over("Guy", 1.5, +230)]),   # different line — not comparable
    ])
    rec = data.parse_batter_odds(game)["guy"]
    assert rec.get("best_price") == -150    # only DK offered 0.5

def test_batter_odds_hrr_market_parsed_with_best():
    game = _game([
        _book("draftkings", "DraftKings", "batter_hits_runs_rbis",
              [_over("Guy", 1.5, -135)]),
        _book("caesars", "Caesars", "batter_hits_runs_rbis",
              [_over("Guy", 1.5, -118)]),
    ])
    rec = data.parse_batter_odds(game)["guy"]
    assert rec["hrr_line"] == 1.5 and rec["hrr_price"] == -135
    assert rec["hrr_best_price"] == -118 and rec["hrr_best_book"] == "Caesars"

def test_batter_odds_no_dk_falls_back():
    game = _game([
        _book("fanduel", "FanDuel", "batter_hits", [_over("Guy", 0.5, -120)]),
    ])
    rec = data.parse_batter_odds(game)["guy"]
    assert rec["line"] == 0.5 and rec["price"] is None
    assert rec["best_price"] == -120 and rec["best_book"] == "FanDuel"


# ------------------------------------------------------------
# pitcher K odds: over/under best per side
# ------------------------------------------------------------
def test_k_odds_best_per_side():
    game = _game([
        _book("draftkings", "DraftKings", "pitcher_strikeouts",
              [_over("Hunter Greene", 6.5, -120), _under("Hunter Greene", 6.5, -110)]),
        _book("fanduel", "FanDuel", "pitcher_strikeouts",
              [_over("Hunter Greene", 6.5, -105), _under("Hunter Greene", 6.5, -125)]),
    ])
    out = data._resolve_k_best(data.parse_k_odds(game))
    rec = out["hunter greene"]
    assert rec["line"] == 6.5
    assert rec["over_price"] == -120 and rec["under_price"] == -110       # DK ref
    assert rec["over_best_price"] == -105 and rec["over_best_book"] == "FanDuel"
    assert rec["under_best_price"] == -110 and rec["under_best_book"] == "DraftKings"

def test_better_american_comparison():
    assert data._better(-105, -120) == -105
    assert data._better(150, 100) == 150
    assert data._better(None, -110) == -110
    assert data._better(-110, None) == -110
