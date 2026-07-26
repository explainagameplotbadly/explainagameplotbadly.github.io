# Explain a Game Plot Badly: The Game

A guessing game built from ["Solved"](https://www.reddit.com/r/ExplainAGamePlotBadly/) posts on
r/ExplainAGamePlotBadly. Players read a badly-worded game plot, optionally reveal hints one at a
time, and guess the game via an autocomplete search box. On reveal, the game shows cover art (when
available), a link to the original post, and what percentage of all players got it right. Streaks
(current / highest / previous) are tracked per-browser.

**Current status:** fully built, tested end-to-end, and running on **real scraped Reddit data

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
