"""Tests for the strikeout-prop tracking: side selection, O/U grading, payload
patches, the betting-record reducer, and end-to-end grading of a pitcher row."""
import engine
import pipeline
import backtest
import grading
import data


# ------------------------------------------------------------
# engine.k_prop_side / grade_k_prop (pure)
# ------------------------------------------------------------
def test_side_over_under_none():
    assert engine.k_prop_side(6.2, 5.5) == "over"
    assert engine.k_prop_side(4.8, 5.5) == "under"
    assert engine.k_prop_side(5.5, 5.5) is None      # exact lean = no bet
    assert engine.k_prop_side(None, 5.5) is None
    assert engine.k_prop_side(6.0, None) is None


def test_grade_over_win_loss():
    assert engine.grade_k_prop("over", 5.5, 7) == 1
    assert engine.grade_k_prop("over", 5.5, 4) == 0

def test_grade_under_win_loss():
    assert engine.grade_k_prop("under", 5.5, 4) == 1
    assert engine.grade_k_prop("under", 5.5, 7) == 0

def test_grade_integer_line_push_and_missing():
    assert engine.grade_k_prop("over", 6, 6) == -1     # landed on the number
    assert engine.grade_k_prop(None, 5.5, 7) == -1     # no side
    assert engine.grade_k_prop("over", None, 7) == -1  # no line
    assert engine.grade_k_prop("over", 5.5, None) == -1


# ------------------------------------------------------------
# pipeline.k_odds_patches
# ------------------------------------------------------------
def test_k_odds_patches_resolves_side_and_price():
    projs = [{"player_id": 10, "player_name": "Hunter Greene", "projected_ks": 7.1},
             {"player_id": 11, "player_name": "Some Opener", "projected_ks": 3.0}]
    odds = {
        engine.normalize_name("Hunter Greene"): {"line": 6.5, "over_price": -120, "under_price": 100},
        engine.normalize_name("Some Opener"):   {"line": 4.5, "over_price": 110, "under_price": -130},
    }
    out = dict((pid, body) for pid, body in pipeline.k_odds_patches(projs, odds))
    assert out[10] == {"k_line": 6.5, "k_side": "over", "k_price": -120}
    assert out[11] == {"k_line": 4.5, "k_side": "under", "k_price": -130}

def test_k_odds_patches_skips_unpriced_and_unmatched():
    projs = [{"player_id": 10, "player_name": "Hunter Greene", "projected_ks": 7.1},
             {"player_id": 12, "player_name": "No Line Guy", "projected_ks": 5.0}]
    odds = {engine.normalize_name("Hunter Greene"): {"line": None}}  # no line -> skip
    out = list(pipeline.k_odds_patches(projs, odds))
    assert out == []


# ------------------------------------------------------------
# backtest.k_prop_record
# ------------------------------------------------------------
def test_k_prop_record_counts_and_units():
    rows = [
        {"k_win": 1, "k_price": -110},   # win: +0.909u
        {"k_win": 0, "k_price": 100},    # loss: -1u
        {"k_win": 1, "k_price": None},   # win but unpriced (counts record, not units)
        {"k_win": -1, "k_price": -110},  # push/no-bet: ignored
        {"projected_ks": 5},             # ungraded prop: ignored
    ]
    r = backtest.k_prop_record(rows)
    assert r["n"] == 3 and r["wins"] == 2 and r["losses"] == 1
    assert r["n_priced"] == 2
    assert abs(r["units"] - (0.909 - 1.0)) < 0.01

def test_k_prop_record_empty():
    assert backtest.k_prop_record([])["n"] == 0


# ------------------------------------------------------------
# grading._grade_final_games — pitcher row with a stored K prop
# ------------------------------------------------------------
class _Resp:
    def __init__(self, payload, status=200):
        self._p, self.status_code = payload, status
    def json(self):
        return self._p


def test_grading_sets_k_win(monkeypatch):
    # One final game; Hunter Greene (ID10) struck out 8; he was on the OVER 6.5.
    feed = {"liveData": {"boxscore": {"teams": {
        "home": {"players": {"ID10": {"stats": {"pitching": {"strikeOuts": 8}}}}},
        "away": {"players": {}}}}}}
    pitcher_rows = [{"player_id": 10, "game_pk": 777, "projected_ks": 7.1,
                     "k_line": 6.5, "k_side": "over"}]
    patches = []

    def fake_get(url, headers=None, **k):
        if "feed/live" in url:
            return _Resp(feed)
        if "pitcher_predictions" in url:
            return _Resp(pitcher_rows)
        if "predictions" in url:
            return _Resp([])          # no hitters to grade
        return _Resp([])

    def fake_patch(url, json=None, headers=None, **k):
        patches.append((url, json))
        return _Resp(None, status=204)

    monkeypatch.setattr(data, "http_get", fake_get)
    monkeypatch.setattr(data, "http_patch", fake_patch)

    grading._grade_final_games("https://x.co", {}, [{"gamePk": 777}], "2026-07-29")

    kp = [(u, j) for u, j in patches if "pitcher_predictions" in u]
    assert kp, "expected a pitcher_predictions PATCH"
    body = kp[-1][1]
    assert body["actual_ks"] == 8 and body["graded"] == 1 and body["k_win"] == 1


def test_grading_skips_k_win_when_no_line(monkeypatch):
    # Columns absent / no line stored -> row has no k_line -> base patch only.
    feed = {"liveData": {"boxscore": {"teams": {
        "home": {"players": {"ID10": {"stats": {"pitching": {"strikeOuts": 3}}}}},
        "away": {"players": {}}}}}}
    pitcher_rows = [{"player_id": 10, "game_pk": 777, "projected_ks": 5.0}]
    patches = []
    monkeypatch.setattr(data, "http_get", lambda url, headers=None, **k:
                        _Resp(feed) if "feed/live" in url else
                        (_Resp(pitcher_rows) if "pitcher_predictions" in url else _Resp([])))
    monkeypatch.setattr(data, "http_patch", lambda url, json=None, headers=None, **k:
                        patches.append(json) or _Resp(None, 204))
    grading._grade_final_games("https://x.co", {}, [{"gamePk": 777}], "2026-07-29")
    body = [j for j in patches if "actual_ks" in j][-1]
    assert body == {"actual_ks": 3, "graded": 1}     # no k_win key
