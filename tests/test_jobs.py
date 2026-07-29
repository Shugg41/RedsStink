"""Tests for the headless cron runner (jobs.py)."""
import pytest

import jobs
import briefing


def test_db_headers_shape():
    base, upsert = jobs._db_headers("secret-key")
    assert base["apikey"] == "secret-key"
    assert base["Authorization"] == "Bearer secret-key"
    assert base["Prefer"] == "return=representation"
    assert upsert["Prefer"] == "resolution=merge-duplicates,return=representation"
    assert upsert["apikey"] == "secret-key"


def test_run_noop_without_supabase(capsys):
    out = jobs.run(env={})
    assert out == {"skipped": "no supabase config"}
    assert "nothing to do" in capsys.readouterr().out


def test_run_dispatches_all_three_with_correct_args(monkeypatch):
    calls = {}
    def rec(name):
        def _f(**kw):
            calls[name] = kw
            return f"{name}-ran"
        return _f
    monkeypatch.setattr(briefing, "daily_autorun", rec("daily_autorun"))
    monkeypatch.setattr(briefing, "pregame_sweep", rec("pregame_sweep"))
    monkeypatch.setattr(briefing, "closing_snapshot", rec("closing_snapshot"))

    env = {"SUPABASE_URL": "https://x.supabase.co", "SUPABASE_KEY": "k",
           "ODDS_API_KEY": "odds", "NTFY_TOPIC": "my-topic"}
    out = jobs.run(env=env)

    assert out == {"daily_autorun": "daily_autorun-ran",
                   "pregame_sweep": "pregame_sweep-ran",
                   "closing_snapshot": "closing_snapshot-ran"}
    # daily_autorun + pregame_sweep get the ntfy topic; closing_snapshot doesn't
    for name in ("daily_autorun", "pregame_sweep"):
        c = calls[name]
        assert c["supabase_url"] == "https://x.supabase.co"
        assert c["odds_api_key"] == "odds"
        assert c["ntfy_topic"] == "my-topic"
        assert c["db_headers"]["apikey"] == "k"
        assert c["db_headers_upsert"]["Prefer"].startswith("resolution=merge")
    assert "ntfy_topic" not in calls["closing_snapshot"]
    assert calls["closing_snapshot"]["supabase_url"] == "https://x.supabase.co"


def test_force_clears_markers_before_running(monkeypatch):
    cleared = {}
    pings = []
    monkeypatch.setattr(briefing, "clear_markers",
                        lambda url, hdrs, date: cleared.setdefault("url", url) or True)
    monkeypatch.setattr(briefing.data, "ntfy_send",
                        lambda topic, *a, **k: pings.append(topic) or True)
    monkeypatch.setattr(briefing, "daily_autorun", lambda **kw: None)
    monkeypatch.setattr(briefing, "pregame_sweep", lambda **kw: None)
    monkeypatch.setattr(briefing, "closing_snapshot", lambda **kw: None)
    jobs.run(env={"SUPABASE_URL": "https://x.supabase.co", "SUPABASE_KEY": "k",
                  "FORCE": "true"})
    assert cleared["url"] == "https://x.supabase.co"
    # topic defaulted -> exactly one diagnostic ping, to the default topic
    assert pings == [jobs.DEFAULT_NTFY_TOPIC]


def test_force_pings_both_when_topic_differs(monkeypatch):
    pings = []
    monkeypatch.setattr(briefing, "clear_markers", lambda *a, **k: True)
    monkeypatch.setattr(briefing.data, "ntfy_send",
                        lambda topic, *a, **k: pings.append(topic) or True)
    monkeypatch.setattr(briefing, "daily_autorun", lambda **kw: None)
    monkeypatch.setattr(briefing, "pregame_sweep", lambda **kw: None)
    monkeypatch.setattr(briefing, "closing_snapshot", lambda **kw: None)
    jobs.run(env={"SUPABASE_URL": "u", "SUPABASE_KEY": "k",
                  "NTFY_TOPIC": "custom-topic", "FORCE": "1"})
    # resolved topic first, then the default fallback
    assert pings == ["custom-topic", jobs.DEFAULT_NTFY_TOPIC]


def test_no_force_leaves_markers_alone(monkeypatch):
    called = {"clear": False}
    monkeypatch.setattr(briefing, "clear_markers",
                        lambda *a, **k: called.update(clear=True))
    monkeypatch.setattr(briefing, "daily_autorun", lambda **kw: None)
    monkeypatch.setattr(briefing, "pregame_sweep", lambda **kw: None)
    monkeypatch.setattr(briefing, "closing_snapshot", lambda **kw: None)
    jobs.run(env={"SUPABASE_URL": "u", "SUPABASE_KEY": "k"})
    assert called["clear"] is False


def test_run_defaults_ntfy_topic(monkeypatch):
    seen = {}
    monkeypatch.setattr(briefing, "daily_autorun",
                        lambda **kw: seen.update(kw) or None)
    monkeypatch.setattr(briefing, "pregame_sweep", lambda **kw: None)
    monkeypatch.setattr(briefing, "closing_snapshot", lambda **kw: None)
    jobs.run(env={"SUPABASE_URL": "u", "SUPABASE_KEY": "k"})
    assert seen["ntfy_topic"] == jobs.DEFAULT_NTFY_TOPIC
    assert seen["odds_api_key"] is None
