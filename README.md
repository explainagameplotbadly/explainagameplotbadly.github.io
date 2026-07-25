# Explain a Game Plot Badly: The Game

A guessing game built from ["Solved"](https://www.reddit.com/r/ExplainAGamePlotBadly/) posts on
r/ExplainAGamePlotBadly. Players read a badly-worded game plot, optionally reveal hints one at a
time, and guess the game via an autocomplete search box. On reveal, the game shows cover art (when
available), a link to the original post, and what percentage of all players got it right. Streaks
(current / highest / previous) are tracked per-browser.

**Current status:** the site is fully built and playable, but `data/questions.json` currently
contains 4 **hand-written sample questions**, not real scraped Reddit data — the automated scraper
is written and ready but blocked on Reddit API credentials (see below). Everything else (front-end,
autocomplete, streaks, global stats, weekly automation) is live and tested.

## Architecture

- **Static site** (`index.html` / `style.css` / `app.js`) — hosted on GitHub Pages, no server needed.
- **`data/questions.json`** — the quiz questions, produced by `scripts/scrape_reddit.py`.
- **`data/games.json`** — ~14,000 game titles for autocomplete, pulled from [Wikidata](https://www.wikidata.org/)
  (no API key required). Used instead of Metacritic (no public API / scraping ToS issues) and RAWG
  (account creation was blocked for this account).
- **Cover art** — also from Wikidata (`P2716`/`P18` image properties), resolved per-answer during
  scraping and stored directly in `questions.json`. Coverage is inconsistent (many well-known games
  have no image attached on Wikidata) — the UI shows a "No cover art available" placeholder when
  that happens. This is a known trade-off of the no-signup approach; see "Known limitations" below.
- **Global "% correct" stat** — stored in Supabase (Postgres). Every guess is inserted as a row in
  `answers`; the client aggregates counts per question. Streaks are **not** stored here — those live
  in the browser's `localStorage` only.
- **Weekly update** — `.github/workflows/scrape.yml` runs every Tuesday and commits any new data
  straight to `main`, which GitHub Pages then redeploys automatically.

## One-time setup

### 1. Supabase (global stats) — done, but needs the schema applied

The URL and anon key are already in `config.js` (the anon key is meant to be public — access is
restricted by the Row Level Security policies below, not by hiding the key).

You still need to create the table:

1. Open your Supabase project → **SQL Editor** → **New query**.
2. Paste in the contents of [`supabase_schema.sql`](supabase_schema.sql) and run it.
3. That's it — no further Supabase config needed.

### 2. Reddit API credentials (required for the real scraper to run)

Reddit blocks unauthenticated/automated requests, so the scraper needs a free "script" app:

1. Go to <https://www.reddit.com/prefs/apps> (or try `old.reddit.com/prefs/apps` if the new UI
   gives you trouble) and click **create another app...**.
2. Choose type **script**, give it any name/description, and set the redirect URI to
   `http://localhost:8080` (unused for this flow, but required by the form).
3. After creating it, copy the **client ID** (the string under the app name) and the **secret**.

If you hit the "Responsible Builder Policy" notice and can't get past it:
- Make sure your Reddit account's email (and phone, if prompted) is verified under Account Settings.
- Try `old.reddit.com/prefs/apps` instead of the redesigned page.
- Look for an "I agree" checkbox or "Continue" control near the notice — on some flows it's an
  acknowledgment step, not a hard rejection.
- Very new or low-karma accounts are sometimes soft-blocked; an older, established account helps.

Once you have the client ID and secret, add them as **GitHub Actions secrets** (not committed to
the repo): repo **Settings → Secrets and variables → Actions → New repository secret**:
- `REDDIT_CLIENT_ID`
- `REDDIT_CLIENT_SECRET`

Then trigger the workflow manually once (**Actions → Weekly Reddit scrape... → Run workflow**) to
do the first real scrape and replace the sample data.

### 3. Push to GitHub and enable Pages

```bash
git add -A
git commit -m "Initial commit"
git push -u origin main
```

Then: repo **Settings → Pages → Source: Deploy from a branch → Branch: main, folder: / (root)**.
The site will be live at `https://jakeevancohen-max.github.io/Explain-a-Game-Plot-Poorly/` a minute
or two later.

## Local testing

From the project root:

```bash
py -m http.server 8765
```

Then open `http://localhost:8765/index.html`. (Opening `index.html` directly as a `file://` URL
won't work — the browser blocks the `fetch()` calls to `data/*.json` under that scheme.)

## Running the scrapers manually

```bash
py scripts/fetch_games.py          # refreshes data/games.json from Wikidata, no credentials needed
REDDIT_CLIENT_ID=xxx REDDIT_CLIENT_SECRET=yyy py scripts/scrape_reddit.py
```

## Known limitations

- **Reddit parsing is a best-effort heuristic, unverified against real posts.** Reddit's bot-blocking
  made it impossible to inspect real "Solved" post formatting while building this. `extract_hints_and_answer()`
  in `scripts/scrape_reddit.py` looks for lines like `Solved: <game>`, `Answer: <game>`, `Hint: <text>`
  in the post body, falling back to the original poster's own comments. Posts where it can't confidently
  find an answer are skipped rather than guessed. Once you run it for real, send a couple of example
  post bodies it got wrong and the patterns can be tightened.
- **Cover art coverage is incomplete.** Wikidata doesn't have a box art image for every game (e.g.
  even *Half-Life 2* has none attached). The game itself still works fine — it just shows "No cover
  art available" — but if this matters a lot, revisiting RAWG or IGDB later (once account creation
  works) would improve coverage.
- **DST**: the Tuesday 1am scrape is pinned to 09:00 UTC, which is 1am PST in winter but 2am PDT in
  summer, since GitHub Actions cron doesn't shift for daylight saving.
- **Streaks are per-browser** (localStorage), not per-account — clearing browser data resets them.
