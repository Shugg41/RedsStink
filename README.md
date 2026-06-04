# RedsStink

Cincinnati Reds prop-betting dashboard (Streamlit) — hitting board, strikeout
engine, performance tracker, and player deep-dive.

## Layout

- `app.py` — the Streamlit UI, MLB/odds API calls, and Supabase persistence.
- `engine.py` — pure scoring / odds / stat math (no Streamlit). Imported by the
  app, the tests, and the backtest so the model can be tested in isolation.
- `tests/` — pytest suite over the engine and backtest math.
- `backtest.py` — standalone harness to replay graded predictions.

## Run the app

```bash
pip install -r requirements.txt
streamlit run app.py
```

Secrets (`.streamlit/secrets.toml`): `SUPABASE_URL`, `SUPABASE_KEY`, `ODDS_API_KEY`.

## Tests

```bash
pip install -r requirements-dev.txt
pytest -q
```

## Backtest

Replay graded predictions to measure win rate, Brier score, ROI, calibration,
and to find the score cutoff that would have been most profitable.

```bash
# From a JSON snapshot of the predictions table:
python backtest.py rows.json

# Or pull straight from Supabase:
SUPABASE_URL=... SUPABASE_KEY=... python backtest.py

# Score the multiplicative engine instead of the additive one:
python backtest.py --engine mult rows.json
```
