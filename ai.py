"""
ai.py — "Ask the app": a small Claude-powered Q&A over today's board and your
season results. Entirely optional: it only activates when an ANTHROPIC_API_KEY
secret is present (costs pennies per question, paid to Anthropic).
"""
import json

import data

API_URL = "https://api.anthropic.com/v1/messages"
MODEL = "claude-sonnet-4-5"

SYSTEM = (
    "You are the analyst inside a Cincinnati Reds prop-betting dashboard. "
    "Answer the user's question using ONLY the context provided (today's model "
    "board, strikeout projections, and season track record). Be direct and "
    "plain-spoken, 2-5 sentences. Give a lean when asked, but be honest about "
    "uncertainty — these are small edges, not locks. Never invent stats that "
    "aren't in the context."
)


def build_context(picks=None, k_projs=None, scoreboard=None, date_str=""):
    """Assemble a compact plain-text context block from app data. Pure."""
    parts = [f"Date: {date_str}"]
    if picks:
        parts.append("Today's board (model score 0-100, higher = better spot):")
        for p in picks[:12]:
            bits = f"  {p.get('player_name', '?')}: score {p.get('score', '?')} {p.get('tier', '')}"
            if p.get('odds_price') is not None:
                bits += f", DK hits price {p['odds_price']}"
            parts.append(bits)
    if k_projs:
        parts.append("Strikeout projections:")
        for k in k_projs[:4]:
            parts.append(f"  {k.get('player_name', '?')}: {k.get('projected_ks', '?')} Ks projected")
    if scoreboard:
        a, m = scoreboard.get('additive', {}), scoreboard.get('mult', {})
        parts.append(
            f"Season record — additive model: {a.get('wins', 0)}-{a.get('losses', 0)} "
            f"({a.get('win_rate', 0)*100:.0f}% win); multiplicative: "
            f"{m.get('wins', 0)}-{m.get('losses', 0)} ({m.get('win_rate', 0)*100:.0f}%).")
    return "\n".join(parts)


def ask(api_key, question, context):
    """One-shot question against the Messages API. Returns (answer, error)."""
    if not api_key:
        return None, "no key"
    try:
        res = data.http_post(
            API_URL,
            headers={"x-api-key": api_key,
                     "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            json={"model": MODEL, "max_tokens": 400,
                  "system": SYSTEM,
                  "messages": [{"role": "user",
                                "content": f"CONTEXT:\n{context}\n\nQUESTION: {question}"}]},
            timeout=30)
        if res.status_code != 200:
            return None, f"API error {res.status_code}: {res.text[:120]}"
        body = res.json()
        text = "".join(b.get("text", "") for b in body.get("content", [])
                       if b.get("type") == "text").strip()
        return (text or None), (None if text else "empty response")
    except Exception as e:
        return None, str(e)
