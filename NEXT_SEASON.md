# Before next season — RedsStink loose ends

Short checklist to run through before Opening Day. The system went dormant in
the 2026 offseason (expected); these are the things to fix/verify so it comes
back clean.

## 1. Fix the `NTFY_TOPIC` repo secret (so briefings reach the phone)

During debugging, the cron pushed a **"RedsStink (default topic)"** diagnostic.
That message only fires when the `NTFY_TOPIC` GitHub secret is set to something
**other** than the app's default topic `redsstink-briefing-rk84vq`. The phone is
subscribed to the default, so a mis-set secret means real briefings would be
sent to a topic nobody is watching.

Fix: repo → Settings → Secrets and variables → Actions → `NTFY_TOPIC` → set it
to exactly `redsstink-briefing-rk84vq` (or whatever topic the ntfy app is
subscribed to — the two must match).

## 2. Re-arm the GitHub Actions cron

GitHub automatically idles scheduled workflows in a repo that has gone inactive.
The `Daily jobs` and `Keep app awake` crons stopped firing on 2026-09-28 for
this reason. Any push to `main` re-enables them. After pushing, confirm a
**scheduled** (not manually dispatched) `Daily jobs` run appears on a game day.

## 3. One stuck, harmless run

Run #677 (a manual `DIAG_SAVE` dispatch from 2026-10-01) is wedged in GitHub's
queue and the API refuses to cancel it ("not been queued yet"). It sends **no**
notifications — `DIAG_SAVE` only writes a throwaway DB row and deletes it — so
it is inert whether it ever runs or not. If it bothers you, delete it from the
Actions UI; otherwise ignore it.

## 4. Capture the August save-failure root cause (optional)

The 2026 season's back third saved few boards because `daily_autorun`'s board
save returned a non-2xx from Supabase that the code ignored. That's now fixed
(the save checks its status, logs the error, and pushes a `⚠️ save failed`
alert — see `briefing.py`). To learn the *exact* error, run the `Daily jobs`
workflow once with the `diag_save` input checked and read the log line
`jobs: DIAG_SAVE upsert status=...` — most likely a Supabase free-tier write
limit that resets monthly.

## 5. Optional carry-overs from last season

- **CLV** and **strikeout-prop O/U** tracking were never enabled (the one-time
  SQL in the README was not run). Enable if you want those records.
- **Tuning pass**: come back at ~150+ priced bets for a real ROI tune. The 2026
  book was dense Apr 30–early Aug (additive greens went 42–23, +19.6% ROI).
