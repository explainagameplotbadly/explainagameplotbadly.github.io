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

- `r/ExplainAGamePlotBadly/new/.rss` — every post in the subreddit, newest first.
- `r/ExplainAGamePlotBadly/comments/<id>/.rss` — a post's comment thread.

**Every post gets fetched, not just "Solved"-flaired ones.** The obvious approach would be Reddit's
search endpoint (`search.rss?q=flair:"Solved"`), but testing found it hard-caps total results at
exactly 250 no matter how many more actually match — paging past post 250 returns nothing further,
and the legacy `timestamp:` range operator that could normally split a query into date windows to
work around a cap like that is no longer functional either (confirmed empty even against a date
range with known results). The general listing isn't subject to that cap, so it's used instead, at
the cost of a comments fetch for every post rather than only pre-filtered solved ones - genuinely
unsolved posts are tracked in `data/checked_posts.json` so they aren't redundantly re-fetched on
every future weekly run, only the first time each is seen.

**Extracting the answer is the hard part.** In this subreddit, the game's name is almost never
stated directly in the post (not even as a "Solved: <game>" line) — it's confirmed conversationally.
For example, a real post's thread looked like this:

> **Commenter:** *"Is it a Spider-Man game... my first guess is Spider-Man for the PS4 or the Miles
> Morales dlc..."*
> **OP:** *"Absolutely Miles. Solved!"*

...which triggers the subreddit's flair bot to post "This post has been marked as solved by its
author!". So the script:
1. Finds that exact bot comment — its presence is what makes a post "solved" at all, and it's a far
   more reliable anchor than scanning for confirm-words (a casual "...if your answer is right or
   wrong..." can false-trigger a keyword search, but nothing else produces this exact bot message).
2. Finds the post author's own comment with the closest timestamp to it (Reddit's RSS comment order
   isn't reliably chronological, so "closest by time" isn't the same as "next in the feed").
3. Searches for the longest known game title (from `data/games.json`) in the comment right before
   that one (the guess being confirmed) first, falling back to the author's own comment text only if
   that finds nothing — in every case seen during testing, matching the author's own reaction text
   ("Yes!", "You got it marine", "It was indeed Pandora's Box that was opened") produced a false
   positive (a title-shaped phrase mentioned incidentally), never a correct answer.
4. Matching handles some real-world variation: colons dropped ("Animal Crossing New Horizons" still
   matches "Animal Crossing: New Horizons"), roman numerals written as digits ("Kingdom Hearts 3"
   still matches "Kingdom Hearts III"), a franchise name and its subtitle mentioned separately in the
   same comment ("I'll take Animal Crossing. Solved! It was New Horizons"), and short titles that
   double as common words or coincide with an unrelated game's subtitle ("Dark Souls" is both the
   famous standalone game and the subtitle of the obscure tie-in "Bleach: Dark Souls" — matching is
   held to a higher bar in cases like this).
5. If nothing confident is found, the post is skipped — better to publish fewer questions than a
   wrong answer.

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
