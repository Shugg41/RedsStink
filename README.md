# RedsStink 🔴

Cincinnati Reds prop-betting dashboard — engines, robots, and a simulator.

## What it does (daily flow)

These jobs run from a **GitHub Actions cron** (`.github/workflows/daily-jobs.yml`
→ `jobs.py`), which reliably runs the headless engines to completion —
independent of whether the Streamlit app happens to be awake/visited. Requires
the four repo secrets listed under Setup.

1. **~10am ET, automatically**: a robot fetches DraftKings lines, runs the
   offense board, **saves the picks with odds locked in**, projects both
   starters' strikeouts, and **pushes a morning briefing to your phone**
   (via the free [ntfy](https://ntfy.sh) app — subscribe to the topic below).
2. **~1–3h before first pitch**: a pregame safety-net sweep runs the engines
   if they somehow never ran, and **backfills any DraftKings lines** that
   weren't posted yet at 10am onto the saved picks (pushes a "🔒 Lines locked"
   note when it does).
3. **~5pm+ ET**: an evening pass captures near-close odds for CLV (needs the
   one-line SQL below).
4. **During the game**: the 📺 Live tab sweats your bets in real time.
5. **After the game**: the robot auto-grades finished games on its next cron
   tick (hitters, pitcher Ks, and the K-prop over/under) — no app visit needed —
   and the Tracker shows last game + season scoreboard for both models.

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

- **The daily robot (REQUIRED for briefings)**: add four **GitHub repo secrets**
  (repo → Settings → Secrets and variables → Actions → New repository secret) —
  the same values already in the Streamlit app: `SUPABASE_URL`, `SUPABASE_KEY`,
  `ODDS_API_KEY`, `NTFY_TOPIC`. The `Daily jobs` workflow needs these to reach
  the database and send pushes. (Encrypted; never printed in logs.)
- **Morning briefings**: install the free **ntfy** app on your phone and
  subscribe to the topic `redsstink-briefing-rk84vq` (or set `NTFY_TOPIC` to
  your own topic in both the GitHub secret and the app, and subscribe to that).
- **CLV (optional)**: run once in the Supabase SQL editor:
  ```sql
  alter table predictions add column closing_line real;
  alter table predictions add column closing_price integer;
  ```
- **Strikeout-prop tracking (optional)**: gives the K engine a real win/loss +
  ROI record (over/under vs the posted line). Run once in the Supabase SQL editor:
  ```sql
  alter table pitcher_predictions add column k_line real;
  alter table pitcher_predictions add column k_side text;
  alter table pitcher_predictions add column k_price integer;
  alter table pitcher_predictions add column k_win integer;
  ```
  After that the daily robot stores each starter's line/side/price and grades the
  over/under automatically — no manual runs. Until the columns exist it stays
  dormant (the engine still projects Ks; it just won't grade the prop).
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
| `grading.py` | headless auto-grader (hitters + pitcher Ks + K-prop O/U) — runs in-app AND in the cron |
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
