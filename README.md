# RedsStink 🔴

Cincinnati Reds prop-betting dashboard — engines, robots, and a simulator.

## What it does (daily flow)

1. **~10am ET, automatically**: a robot fetches DraftKings lines, runs the
   offense board, **saves the picks with odds locked in**, projects both
   starters' strikeouts, and **pushes a morning briefing to your phone**
   (via the free [ntfy](https://ntfy.sh) app — subscribe to the topic below).
2. **~5pm+ ET**: an evening pass captures near-close odds for CLV (needs the
   one-line SQL below).
3. **During the game**: the 📺 Live tab sweats your bets in real time.
4. **After the game**: results auto-grade; the Tracker shows last game +
   season scoreboard for both models.

## Tabs

- **🔥 Offense** — the hitting board (additive + multiplicative models, HRR
  projections with P(2+), Statcast xBA luck tags, DK + best-price lines).
- **⚡ Strikeout Engine** — projected Ks for both starters, opener detection.
- **🎲 Simulator** — plays the game 10,000× (Poisson-free, real outcome dice):
  team total, F5, per-hitter probabilities, same-game-parlay correlation.
- **📺 Live** — score, your board with live hits/HRR and P(clear), starter Ks.
- **📊 System Tracker** — last-game recap, season scoreboard (both models),
  data export, pitching tracker, CLV (once enabled).
- **🎯 Lock of the Day** — league-wide strikeout edge scan (works on off-days).
- **🤖 Ask the app** (sidebar) — optional Claude Q&A over today's board.

## One-time setup

- **Morning briefings**: install the free **ntfy** app on your phone and
  subscribe to the topic `redsstink-briefing-rk84vq` (or set an `NTFY_TOPIC`
  secret and subscribe to that).
- **CLV (optional)**: run once in the Supabase SQL editor:
  ```sql
  alter table predictions add column closing_line real;
  alter table predictions add column closing_price integer;
  ```
- **Ask-the-app (optional)**: add `ANTHROPIC_API_KEY` to the Streamlit secrets.

## Secrets (`.streamlit/secrets.toml` / Streamlit Cloud settings)

`SUPABASE_URL`, `SUPABASE_KEY`, `ODDS_API_KEY` (required for saving/odds);
`NTFY_TOPIC`, `ANTHROPIC_API_KEY` (optional).

## Code layout

| file | what |
|---|---|
| `app.py` | the Streamlit UI |
| `data.py` | all network fetchers (statsapi, Odds API, ntfy) — no Streamlit |
| `pipeline.py` | headless scoring pipelines (offense board, K engine, payloads) |
| `engine.py` | pure scoring/odds/stat math + all tunable weights |
| `sim.py` | 10,000-game Monte Carlo simulator + SGP correlation |
| `savant.py` | Statcast (Baseball Savant) fetchers: xBA/xwOBA, barrels |
| `briefing.py` | morning auto-run + push briefing + closing-odds snapshot |
| `live.py` | in-game sweat-tracker parsing + live P(clear) math |
| `lock.py` | league-wide K-prop lock selection (Poisson + EV) |
| `ai.py` | optional Claude Q&A |
| `backtest.py` | offline analysis of exported picks (threshold sweep, ROI) |
| `.github/workflows/keep-awake.yml` | visits the app every 4h (never sleeps) + triggers the 10am robot |

## Run locally / tests

```bash
pip install -r requirements.txt && streamlit run app.py
pip install -r requirements-dev.txt && pytest -q
```

## Backtest exported data

Tracker → Export → then:
```bash
python backtest.py hitting_predictions_YYYY-MM-DD.json            # additive
python backtest.py --engine mult hitting_predictions_YYYY-MM-DD.json
```
