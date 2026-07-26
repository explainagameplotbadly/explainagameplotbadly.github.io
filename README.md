# Explain a Game Plot Badly: The Game

A guessing game built from ["Solved"](https://www.reddit.com/r/ExplainAGamePlotBadly/) posts on
r/ExplainAGamePlotBadly. Players read a badly-worded game plot, optionally reveal hints one at a
time, and guess the game via an autocomplete search box. On reveal, the game shows cover art (when
available), a link to the original post, and what percentage of all players got it right. Streaks
(current / highest / previous) are tracked per-browser.

**Current status:** fully built, tested end-to-end, and running on **real scraped Reddit data**
(see `data/questions.json`). No Reddit developer account, API key, or Devvit app is required —
see "How Reddit scraping works" below for why.

## Architecture

- **Static site** (`index.html` / `style.css` / `app.js`) — hosted on GitHub Pages, no server needed.
- **`data/questions.json`** — the quiz questions, produced by `scripts/scrape_reddit.py`.
- **`data/games.json`** — ~14,000 game titles for autocomplete, pulled from [Wikidata](https://www.wikidata.org/)
  (no API key required). Used instead of Metacritic (no public API / scraping ToS issues) and RAWG
  (account creation was blocked for this account).
- **Cover art** — also from Wikidata (`P2716`/`P18` image properties), resolved per-answer during
  scraping and stored directly in `questions.json`. Coverage is inconsistent (many well-known games
  have no image attached on Wikidata) — the UI shows a "No cover art available" placeholder when
  that happens.
- **Global "% correct" stat** — stored in Supabase (Postgres). Every guess is inserted as a row in
  `answers`; the client aggregates counts per question. Streaks are **not** stored here — those live
  in the browser's `localStorage` only.
- **Weekly update** — `.github/workflows/scrape.yml` runs every Tuesday and commits any new data
  straight to `main`, which GitHub Pages then redeploys automatically.

## How Reddit scraping works (no API key needed)

Reddit's JSON API (`oauth.reddit.com`, `www.reddit.com/*.json`) now hard-blocks unauthenticated and
datacenter traffic, and creating a developer app currently requires accepting Reddit's Responsible
Builder Policy / Devvit onboarding, which isn't practical for a small read-only script. Instead,
`scripts/scrape_reddit.py` uses Reddit's **public, unauthenticated RSS endpoints**, which remain
open:

- `r/ExplainAGamePlotBadly/search.rss?q=flair:"Solved"&restrict_sr=1` — list of solved posts.
- `r/ExplainAGamePlotBadly/comments/<id>/.rss` — a post's comment thread.

These are rate-limited to roughly one request per 25–35 seconds per IP, which the script paces
itself around — completely fine for a once-a-week job.

**Extracting the answer is the hard part.** In this subreddit, the game's name is almost never
stated directly in the post (not even as a "Solved: <game>" line) — it's confirmed conversationally.
For example, a real post's thread looked like this:

> **Commenter:** *"Is it a Spider-Man game... my first guess is Spider-Man for the PS4 or the Miles
> Morales dlc..."*
> **OP:** *"Absolutely Miles. Solved!"*

So the script:
1. Finds the post author's first comment containing a confirmation word (solved / correct / yes /
   absolutely / exactly / got it / that's it / right / bingo / nailed it).
2. Takes that comment plus the comment immediately before it (the guess being confirmed) as context.
3. Searches for the longest known game title (from `data/games.json`) that appears in that context,
   matching whole words — including matching just the subtitle of a series title (e.g. "Miles
   Morales" alone still resolves to "Spider-Man: Miles Morales"). Single-word titles need to be at
   least 6 characters to count, since a short common word (e.g. "Hugo", which really is an obscure
   game) matching by pure coincidence is a real risk in free-form conversation.
4. If nothing confident is found, the post is skipped — better to publish fewer questions than a
   wrong answer. In testing, this correctly skipped a post whose confirming comment referenced a
   guess from a part of the thread the RSS feed didn't include ("Hugo" — a real but obscure game
   title — was almost a false positive here before the length threshold was added).

This is a heuristic over real human conversation, so it won't catch every solved post (particularly
ones where the confirmation is just an emoji, or the actual guess comment is buried deep enough in
the thread that Reddit's RSS view omits it). If you notice a wrong or missing answer after a scrape,
that's the place to look (`resolve_answer()` / `find_title_in_text()` in `scripts/scrape_reddit.py`).

## One-time setup

### 1. Supabase (global stats) — needs the schema applied once

The URL and anon key are already in `config.js` (the anon key is meant to be public — access is
restricted by the Row Level Security policies below, not by hiding the key).

1. Open your Supabase project → **SQL Editor** → **New query**.
2. Paste in the contents of [`supabase_schema.sql`](supabase_schema.sql) and run it.
3. That's it — no further Supabase config needed.

### 2. Push to GitHub and enable Pages

```bash
git add -A
git commit -m "Initial commit"
git push -u origin main
```

Then: repo **Settings → Pages → Source: Deploy from a branch → Branch: main, folder: / (root)**.

No secrets or API keys need to be added to the repo — the weekly workflow needs nothing beyond the
default `GITHUB_TOKEN` (already available automatically) to commit updated data.

### 3. Getting your name/username out of the URL (free, no domain purchase)

Real free `.com`-style domains don't exist anymore (Freenom, which used to offer free `.tk`/`.ml`
domains, was shut down after legal trouble and mass domain seizures — not worth relying on). The
free, reliable fix is to host this under a **GitHub Organization** instead of your personal account,
since the Pages URL is derived from whichever account/org owns the repo:

1. Create a free org: <https://github.com/organizations/new> → choose the **Free** plan → pick a
   neutral name unrelated to you, e.g. `explainagameplotbadly`. (I can't create this for you — it
   needs your GitHub login.)
2. Transfer this repo into it: in the current repo, **Settings → General → Danger Zone → Transfer
   ownership**, and enter the new org as the destination. (Or, if you'd rather start clean: create a
   new repo inside the org and I'll push there instead — just give me the org name.)
3. For the cleanest possible URL with no extra path, name the repo exactly
   `<org-name>.github.io` (e.g. `explainagameplotbadly.github.io`) — GitHub treats a repo with that
   exact name as the org's root site, so it serves directly at `https://explainagameplotbadly.github.io/`
   with nothing after it. A repo with any other name serves at
   `https://explainagameplotbadly.github.io/<repo-name>/` instead, which still works fine.
4. Re-enable Pages under the org's copy of the repo the same way as step 2 above.

If you later decide to buy a real domain after all, the custom-domain setup is simple to add back
(a `CNAME` file plus a DNS record) — just ask.

## Local testing

From the project root:

```bash
py -m http.server 8765
```

Then open `http://localhost:8765/index.html`. (Opening `index.html` directly as a `file://` URL
won't work — the browser blocks the `fetch()` calls to `data/*.json` under that scheme.)

## Running the scrapers manually

```bash
py scripts/fetch_games.py     # refreshes data/games.json from Wikidata
py scripts/scrape_reddit.py   # refreshes data/questions.json from Reddit (~30s per new post, be patient)
```

Both are safe to re-run — they only add new items and never duplicate existing ones (matched by
Reddit post ID / game title).

## Known limitations

- **Reddit answer extraction is a heuristic over real conversation**, not a guaranteed-correct
  parser — see "How Reddit scraping works" above. Expect an occasional post to be skipped rather
  than a wrong answer shown.
- **Cover art coverage is incomplete.** Wikidata doesn't have a box art image for every game (e.g.
  even *Half-Life 2* has none attached). The game itself still works fine — it just shows "No cover
  art available" — but if this matters a lot, revisiting RAWG or IGDB later (once account creation
  works there) would improve coverage.
- **DST**: the Tuesday 1am scrape is pinned to 09:00 UTC, which is 1am PST in winter but 2am PDT in
  summer, since GitHub Actions cron doesn't shift for daylight saving.
- **Streaks are per-browser** (localStorage), not per-account — clearing browser data resets them.
- **Rate limiting**: if Reddit tightens its RSS rate limits further in the future, increase
  `REQUEST_PACING_SECONDS` in `scripts/scrape_reddit.py`.
- **If the weekly Action ever fails with a 403** ("network policy" block) rather than the normal
  429 rate-limit retries: this was tested from a similar cloud/datacenter IP and worked, but if
  Reddit later blocks GitHub Actions' IP ranges specifically for RSS too, the workaround is running
  the scraper from a self-hosted runner or any non-datacenter IP instead.
