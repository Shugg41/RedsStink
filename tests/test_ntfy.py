"""Tests for ntfy_send — the push path that silently ate every briefing.

The bug: the title was sent as an HTTP `Title:` header, but header values are
latin-1 only, so an emoji title raised UnicodeEncodeError before the request
went out and ntfy_send returned False. The fix publishes via ntfy's JSON API
(everything in the UTF-8 body), so emoji titles work.
"""
import data


class _Resp:
    def __init__(self, status_code=200):
        self.status_code = status_code


def test_emoji_title_is_sent_not_swallowed(monkeypatch):
    sent = {}
    def fake_post(url, **kw):
        sent["url"] = url
        sent["json"] = kw.get("json")
        return _Resp(200)
    monkeypatch.setattr(data, "http_post", fake_post)

    ok = data.ntfy_send("redsstink-briefing-rk84vq",
                        "🔴 Reds Daily Briefing", "⚾ Reds vs Guardians")
    assert ok is True
    # JSON publishing API: topic/title/message live in the body, not headers.
    assert sent["url"] == "https://ntfy.sh"
    assert sent["json"]["topic"] == "redsstink-briefing-rk84vq"
    assert sent["json"]["title"] == "🔴 Reds Daily Briefing"
    assert sent["json"]["message"] == "⚾ Reds vs Guardians"
    assert sent["json"]["tags"] == ["baseball"]


def test_tags_string_splits_to_list(monkeypatch):
    sent = {}
    monkeypatch.setattr(data, "http_post",
                        lambda url, **kw: sent.update(kw) or _Resp(200))
    data.ntfy_send("t", "title", "msg", tags="warning,cd")
    assert sent["json"]["tags"] == ["warning", "cd"]


def test_no_topic_is_noop(monkeypatch):
    called = {"n": 0}
    monkeypatch.setattr(data, "http_post",
                        lambda *a, **k: called.update(n=called["n"] + 1) or _Resp(200))
    assert data.ntfy_send("", "title", "msg") is False
    assert called["n"] == 0


def test_non_2xx_returns_false(monkeypatch):
    monkeypatch.setattr(data, "http_post", lambda url, **kw: _Resp(429))
    assert data.ntfy_send("t", "title", "msg") is False
