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
- **Cover art** — Wikidata first (`P2716`/`P18` image properties), falling back to Steam's public
  store search + CDN (see `scripts/cover_art.py`) when Wikidata has nothing, which is common since
  Commons only hosts freely-licensed images and most official box art isn't. If both come up empty,
  Wikipedia and Fandom are tried as a second fallback (see "How cover art fallback + review works"
  below) but only ever land in a review queue, never shown live without a human approving first.
  Coverage is still incomplete for console-exclusive titles — the UI shows a "No cover art available"
  placeholder when nothing has been approved yet, rather than showing a wrong or unlicensed image.
- **Global "% correct" stat** — stored in Supabase (Postgres). Every guess is inserted as a row in
  `answers`; the client aggregates counts per question. Streaks are **not** stored here — those live
  in the browser's `localStorage` only.
- **Daily Challenge** — 3 questions rotate every day at 12pm PST, picked deterministically client-side
  (see "How the Daily Challenge works" below) so no server/cron is needed for the rotation itself.
- **Weekly update** — `.github/workflows/scrape.yml` runs every Tuesday and commits any new data
  straight to `main`, which GitHub Pages then redeploys automatically.
- **Daily Discord announcement** *(optional)* — `.github/workflows/daily-discord.yml` posts that
  day's 3 prompts (never the answers) to a Discord webhook, if one is configured.

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
   same comment ("I'll take Animal Crossing. Solved! It was New Horizons"), short titles that
   double as common words or coincide with an unrelated game's subtitle ("Dark Souls" is both the
   famous standalone game and the subtitle of the obscure tie-in "Bleach: Dark Souls" — matching is
   held to a higher bar in cases like this), and a franchise+numeral guess with no subtitle ("Starcraft
   2") when only subtitled entries exist for it in `data/games.json` ("StarCraft II: Wings of
   Liberty", "...: Heart of the Swarm", "...: Legacy of the Void" — Wikidata models bare "StarCraft
   II" as a video game *series*, not an instance of "video game", so it's correctly absent from the
   autocomplete source data; `build_numbered_prefix_index()` synthesizes the bare franchise+numeral
   as its own answer candidate in this case rather than falling through to a shorter, differently-
   numbered title).
5. A handful of real game titles are excluded from matching outright because they're also ordinary
   phrases this subreddit's own conversation uses constantly regardless of the actual answer — "The
   Plot", "Deleted"/"Removed" (Reddit's placeholder text for removed content), and "Good Game" (a
   throwaway compliment about literally any game) are all real, obscure titles that would otherwise
   false-positive far more often than anyone actually meaning those games.
6. If nothing confident is found, the post is skipped — better to publish fewer questions than a
   wrong answer.

This is a heuristic over real human conversation, so it won't catch every solved post (particularly
ones where the confirmation is just an emoji, or the actual guess comment is buried deep enough in
the thread that Reddit's RSS view omits it). If you notice a wrong or missing answer after a scrape,
that's the place to look (`resolve_answer()` / `find_title_in_text()` in `scripts/scrape_reddit.py`).

## How cover art fallback + review works

`scripts/cover_art.py`'s two sources (Wikidata, Steam) are both safe to publish automatically —
Wikidata only surfaces freely-licensed Commons images, and Steam art is official first-party store
art. Every new question the scraper resolves that neither source has anything for automatically gets
a second attempt from `scripts/cover_art_fallback.py`, which tries Wikipedia's page image
(`scripts/wikipedia_lookup.py`) and then a guessed Fandom wiki (`scripts/fandom_lookup.py`).

Those two are *not* safe to publish unattended: Wikipedia's box art is almost always a "non-free"
fair-use file whose rationale is scoped to that one article, and Fandom's is fan-uploaded with no
license info at all. So a hit from either one is written to the question as `cover_art_pending`
(`{"source": "wikipedia"|"fandom", "cover_art_url": ...}`) instead of `cover_art_url` — the frontend
only ever reads `cover_art_url`, so a pending suggestion stays completely invisible on the live site
until it's approved.

To review what's queued up:

```
py scripts/review_pending_cover_art.py
```

writes `cover_art_pending_review.html`, a dark-mode image gallery of every pending answer — open it
in a browser to eyeball them. Then:

```
py scripts/review_pending_cover_art.py --approve "Exact Answer" "Another Answer"
py scripts/review_pending_cover_art.py --reject "Wrong Match"
py scripts/review_pending_cover_art.py --approve-all   # once you've spot-checked a sample
```

`--approve` promotes `cover_art_pending` to a live `cover_art_url` for every question sharing that
exact answer; `--reject` just discards the suggestion (leaving no art, so it can surface again on a
future scrape/backfill rather than being permanently blocked). A one-off batch of fallback lookups
(e.g. from `scripts/backfill_fallback_cover_art.py` against a title list) can be merged in the same
way via `scripts/apply_cover_art_results.py <results.json>`, which is also always safe to re-run since
it skips any question that already has `cover_art_url` or `cover_art_pending` set.

## How the Daily Challenge works

Every "gaming day" (noon-to-noon Pacific time, not midnight-to-midnight — so it lines up with the
12pm PST rotation) gets its own 3 questions, picked **deterministically**: `getDailyPeriodKey()` in
`app.js` computes a `"YYYY-MM-DD"` key for the current period, and `pickDailyQuestions()` hashes
`period_key + "|" + question_id` for every question (FNV-1a, see `dailyHash()`), sorting by that hash
and taking the lowest 3. Since this only depends on the period key and the question pool — both the
same for everyone — every visitor computes the identical 3 questions independently, with no
server/cron needed for the rotation itself.

Answers stay hidden while a period is still active: once you guess, you get immediate correct/
incorrect feedback, but the actual game name/cover art aren't shown until the period key changes
(i.e. the next rotation happens). The previous day's questions and answers move to a "Yesterday's
Answers" section, fully revealed, once that happens — otherwise a completed day's results would just
vanish with nowhere to see them again. `scripts/daily_discord.py` re-implements the exact same
`get_daily_period_key()` / `daily_hash()` / `pick_daily_questions()` logic in Python (verified to
produce bit-identical results to the JS version) so the Discord announcement always matches what the
site is actually showing that day.

### Optional: Discord announcements

1. In your Discord server, go to a channel's **Settings → Integrations → Webhooks → New Webhook**,
   name it, and copy its URL.
2. Add it as a GitHub Actions secret: repo **Settings → Secrets and variables → Actions → New
   repository secret**, name `DISCORD_WEBHOOK_URL`, value the URL from step 1.
3. That's it — `.github/workflows/daily-discord.yml` will start posting that day's 3 prompts (never
   the answers) automatically. Trigger it manually once via **Actions → Daily Discord announcement →
   Run workflow** to test it immediately rather than waiting for the schedule.

Without the secret set, the workflow runs and exits quietly without posting — safe to leave enabled.

## Known limitations

- **Reddit answer extraction is a heuristic over real conversation**, not a guaranteed-correct
  parser — see "How Reddit scraping works" above. Expect an occasional post to be skipped rather
  than a wrong answer shown.
- **Cover art coverage depends on manual review** for anything Wikidata + Steam couldn't find —
  mainly console-exclusive titles (Steam only covers PC games) with no free image on Wikidata either.
  The Wikipedia/Fandom fallback usually finds *something* for these, but it sits in
  `cover_art_pending` until approved via `scripts/review_pending_cover_art.py` (see "How cover art
  fallback + review works" above) rather than showing automatically, so a large pending backlog can
  build up between review sessions. The game itself still works fine either way — unapproved/missing
  art just shows the "No cover art available" placeholder rather than a wrong or unlicensed image.
- **DST**: both the weekly scrape and the daily Discord post are pinned to fixed UTC times, which
  shift by an hour relative to Pacific time between PST (winter) and PDT (summer), since GitHub
  Actions cron doesn't shift for daylight saving. The Daily Challenge's own rotation (computed
  client-side from the real `America/Los_Angeles` timezone) is unaffected and always fires at true
  noon Pacific regardless of DST — only the *Discord announcement's* timing drifts by up to an hour.
- **Streaks are per-browser** (localStorage), not per-account — clearing browser data resets them.
- **Rate limiting**: if Reddit tightens its RSS rate limits further in the future, increase
  `REQUEST_PACING_SECONDS` in `scripts/scrape_reddit.py`.
- **If the weekly Action ever fails with a 403** ("network policy" block) rather than the normal
  429 rate-limit retries: this was tested from a similar cloud/datacenter IP and worked, but if
  Reddit later blocks GitHub Actions' IP ranges specifically for RSS too, the workaround is running
  the scraper from a self-hosted runner or any non-datacenter IP instead.
