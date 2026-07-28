"""
Scrapes r/ExplainAGamePlotBadly for solved posts and turns them into quiz
questions (data/questions.json).

No Reddit developer app / OAuth / Devvit needed. This uses Reddit's public,
unauthenticated RSS endpoints, which remain open even though Reddit's JSON API
(oauth.reddit.com, *.json) now hard-blocks unauthenticated/datacenter traffic:

  - /new/.rss, /top/.rss, /hot/.rss, /controversial/.rss  -> post listings
  - /comments/<id>/.rss                                    -> a comment thread

Post discovery also uses pullpush.io, a third-party Reddit archive, to reach
further back than Reddit's own ~1000-item listing pagination cap allows - see
discover_all_post_ids() / fetch_pullpush_ids() for details. It's used only to
learn that a post exists; its own content/flair snapshot is stale, so every
discovered post still gets its actual current content and comments straight
from Reddit, same as any other source.

Every post is fetched, not just "Solved"-flaired ones - see fetch_all_posts()
for why (short version: Reddit's search endpoint would be the obvious way to
fetch only solved posts directly, but it hard-caps total results at 250 no
matter how many more actually match, while the general listings used here
aren't subject to that specific cap).

These are rate-limited (roughly one request per 25-35s from a single IP), so
this script paces itself deliberately.

HOW THE ANSWER IS EXTRACTED: in this subreddit, posts almost never state the
answer directly (not even in a "Solved:" line) - it's confirmed conversationally,
e.g. a commenter guesses "Spider-Man ... Miles Morales dlc..." and the OP (post
author) replies "Absolutely Miles." followed by "Solved!", which triggers the
subreddit's flair bot to post "This post has been marked as solved by its
author!". So this script:
  1. Finds that exact bot comment - its presence is what makes a post "solved"
     at all, and it's a far more reliable anchor than scanning for confirm-words
     (a casual "...if your answer is right or wrong..." can false-trigger a
     keyword search, but nothing else produces this exact bot message).
  2. Finds the post author's own comment with the closest timestamp to it
     (Reddit's RSS comment order isn't reliably chronological, so "closest
     comment" isn't the same as "next comment in the feed").
  3. Looks for the longest known game title (from data/games.json, whole-word
     match, with some normalization - see find_title_in_text) in the comment
     right before that one (the guess being confirmed) first, falling back to
     the author's own comment text only if that finds nothing.
  4. If nothing confident is found, the post is skipped rather than guessed.
This is a heuristic over free-form human conversation, so it won't catch every
post (e.g. answers confirmed only by emoji, or referred to by a nickname not in
the games list) - see README for how to report and tighten misses.
"""
import datetime
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(__file__))
from cover_art import find_cover_art  # noqa: E402

SUBREDDIT = "ExplainAGamePlotBadly"
BASE = f"https://www.reddit.com/r/{SUBREDDIT}"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
QUESTIONS_PATH = os.path.join(DATA_DIR, "questions.json")
GAMES_PATH = os.path.join(DATA_DIR, "games.json")

REQUEST_PACING_SECONDS = 30

HINT_LINE_RE = re.compile(r"^\s*\**\s*(?:hint|clue)\s*\**\s*#?\s*[\d.]*\s*[:\-]\s*(.+?)\s*$", re.IGNORECASE)
# Some posts leave the hint section as an unfilled template, e.g. "Hints go here" -
# that's not a real hint or real body text, so it shouldn't end up in the prompt.
PLACEHOLDER_HINT_RE = re.compile(r"^\s*(?:hints?|clues?)\s+(?:will\s+)?go(?:es)?\s+here\.?\s*$", re.IGNORECASE)
# Some posts introduce hints with a heading ("Hints may appear here:") and then
# list them as a plain numbered list (no "Hint" prefix on each line) rather than
# repeating "Hint #N:" every time - HINT_LINE_RE alone misses those entirely.
# A minority of posters use "Clue"/"Clues" as a synonym throughout instead.
HINT_INTRO_RE = re.compile(r"\b(?:hints?|clues?)\b", re.IGNORECASE)
NUMBERED_LINE_RE = re.compile(r"^\s*\(?(\d+)[).:]\s*(.+?)\s*$")
ATOM_ENTRY_RE = re.compile(r"<entry>(.*?)</entry>", re.DOTALL)
TAG_RE = re.compile(r"<[^>]+>")


def _parse_iso(timestamp):
    return datetime.datetime.fromisoformat(timestamp)


def _fetch(url, retries=4):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/atom+xml"})
    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            if exc.code == 429 and attempt < retries:
                wait = REQUEST_PACING_SECONDS * attempt
                print(f"Rate limited, waiting {wait}s before retry...")
                time.sleep(wait)
                continue
            raise
        except (urllib.error.URLError, TimeoutError) as exc:
            if attempt == retries:
                raise
            time.sleep(10)
    raise RuntimeError(f"Failed to fetch {url}")


def _tag(entry_xml, tag):
    m = re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", entry_xml, re.DOTALL)
    return html.unescape(m.group(1)).strip() if m else ""


def _attr(entry_xml, tag, attr):
    m = re.search(rf'<{tag}[^>]*\s{attr}="([^"]*)"', entry_xml)
    return html.unescape(m.group(1)) if m else ""


def _strip_html(raw):
    # Reddit wraps the real body in SC_OFF/SC_ON HTML comments, then - for posts
    # only, not comments - appends its own "submitted by /u/x [link] [comments]"
    # footer right after SC_ON. Truncating there drops that footer without having
    # to special-case posts vs comments.
    sc_on = raw.find("<!-- SC_ON -->")
    if sc_on != -1:
        raw = raw[:sc_on]
    elif "<!-- SC_OFF -->" not in raw:
        # No SC_OFF/SC_ON wrapper at all means this post has a completely empty
        # selftext (title-only post) - the whole content is just Reddit's footer,
        # not real content, so there's nothing here to keep. (Comments always
        # have this wrapper around their actual text, so this case is post-only.)
        return ""
    text = html.unescape(raw)
    text = TAG_RE.sub("\n", text)
    return "\n".join(line.strip() for line in text.splitlines() if line.strip())


def parse_atom_entries(xml_text):
    entries = []
    for match in ATOM_ENTRY_RE.finditer(xml_text):
        block = match.group(1)
        entries.append(
            {
                "id": _tag(block, "id"),
                "author": _tag(block, "name"),
                "title": _tag(block, "title"),
                "content_html": _tag(block, "content"),
                "link": _attr(block, "link", "href"),
                "published": _tag(block, "published") or _tag(block, "updated"),
            }
        )
    return entries


FEED_PATHS = [
    "/new/.rss",
    "/top/.rss?t=all",
    "/controversial/.rss?t=all",
    "/hot/.rss",
    "/top/.rss?t=year",
]


def _fetch_listing(path):
    """Page through a single Reddit listing (e.g. /new, /top?t=all) with the
    standard `after` cursor until Reddit's pagination limit is hit."""
    posts = []
    after = None
    page = 1
    sep = "&" if "?" in path else "?"
    while True:
        url = f"{BASE}{path}{sep}limit=100"
        if after:
            url += f"&after={after}"
        xml_text = _fetch(url)
        batch = parse_atom_entries(xml_text)
        if not batch:
            break
        posts.extend(batch)
        print(f"    {path} page {page}: {len(batch)} posts (running total {len(posts)})", flush=True)
        if len(batch) < 100:
            break  # short page = last page
        after = batch[-1]["id"]
        page += 1
        time.sleep(REQUEST_PACING_SECONDS)
    return posts


def fetch_all_posts():
    """Fetch every post in the subreddit (not just solved ones) by combining
    several differently-ordered listings.

    NOTE: this does NOT use Reddit's search endpoint (search.rss?q=flair:...),
    even though that would be the obvious way to fetch only "Solved"-flaired
    posts directly. Confirmed by testing: Reddit's search hard-caps total
    results at exactly 250 for a query like this, no matter how many more
    actually match - paging past post 250 with `after` just returns nothing,
    and the legacy `timestamp:` range operator that could normally work around
    a cap like this by splitting into date windows is no longer functional
    (tested against a known-good date range; also returned nothing).

    The general listings used here aren't subject to that specific cap, but
    each one is still limited by Reddit's ordinary ~1000-item `after`-cursor
    pagination limit - a harder, longstanding, platform-wide constraint that
    applies to any single listing, not something that can be paged around.
    A single listing like /new only reaches back as far as its most recent
    ~1000 posts, which - confirmed by testing on this very active subreddit -
    is as little as a few weeks of history. Since /new, /top, /controversial,
    and /hot each rank posts completely differently, their first ~1000 items
    are largely DIFFERENT posts (e.g. /top?t=all reached back to 2018, nearly
    8 years earlier than /new's window), so fetching all of them and
    deduplicating by post ID meaningfully extends coverage - not to literally
    every post ever made (a post that's both old and never highly-ranked in
    any of these orderings could still fall outside all of them), but well
    beyond what any single listing can reach alone.

    Since none of these listings expose flair, "solved" posts aren't filtered
    here at all - every post gets fetched and passed to resolve_answer(),
    which already only produces an answer when it finds the subreddit's
    flair-bot confirmation comment, so unsolved posts are skipped downstream
    the same way they always were, just at the cost of a comments fetch for
    every post instead of only pre-filtered solved ones.
    """
    seen_ids = set()
    all_posts = []
    for path in FEED_PATHS:
        print(f"  Fetching listing: {path}", flush=True)
        posts = _fetch_listing(path)
        new_posts = [p for p in posts if p["id"] not in seen_ids]
        seen_ids.update(p["id"] for p in new_posts)
        all_posts.extend(new_posts)
        print(
            f"  {path}: {len(posts)} posts, {len(new_posts)} new "
            f"(combined total {len(all_posts)})",
            flush=True,
        )
    return all_posts


PULLPUSH_API = "https://api.pullpush.io/reddit/search/submission/"
PULLPUSH_PAGE_SIZE = 100
PULLPUSH_PACING_SECONDS = 8


def fetch_pullpush_ids():
    """Discover post IDs via pullpush.io (a third-party Reddit archive, the
    successor to the old Pushshift project), to get past Reddit's own ~1000-
    item listing pagination cap - its own `after`/timestamp cursor isn't
    subject to that limit, reaching back to this subreddit's earliest posts
    in 2018 in testing.

    This is used ONLY to discover that a post exists, not for its content:
    pullpush's own crawl of this subreddit is stale (its most recent indexed
    post in testing was over a year old), and critically, its `link_flair_text`
    field reflects flair at crawl time, not now - a post crawled before it got
    solved still shows "Unsolved" there forever, so it can't be used to filter
    for solved posts either. Every discovered ID still goes through the exact
    same live Reddit comments fetch + resolve_answer() as any other source.
    """
    ids = []
    seen = set()
    after = None
    page = 1
    while True:
        params = {
            "subreddit": SUBREDDIT,
            "size": PULLPUSH_PAGE_SIZE,
            "sort": "asc",
            "sort_type": "created_utc",
        }
        if after:
            params["after"] = after
        url = f"{PULLPUSH_API}?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})

        data = None
        max_attempts = 12
        for attempt in range(1, max_attempts + 1):
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    data = json.load(resp)
                break
            except urllib.error.HTTPError as exc:
                if exc.code == 429 and attempt < max_attempts:
                    wait = min(10 * attempt, 90)
                    print(f"  pullpush.io rate limited, waiting {wait}s before retry...", flush=True)
                    time.sleep(wait)
                    continue
                print(f"  pullpush.io request failed, stopping there: {exc}", flush=True)
                break
            except Exception as exc:
                if attempt < max_attempts:
                    time.sleep(10)
                    continue
                print(f"  pullpush.io request failed, stopping there: {exc}", flush=True)
                break

        if data is None:
            break

        batch = data.get("data", [])
        if not batch:
            break

        new_this_page = 0
        for item in batch:
            fullname = f"t3_{item['id']}"
            if fullname not in seen:
                seen.add(fullname)
                ids.append(fullname)
                new_this_page += 1

        print(f"    pullpush.io page {page}: {len(batch)} posts, {new_this_page} new (running total {len(ids)})", flush=True)

        if len(batch) < PULLPUSH_PAGE_SIZE:
            break  # short page = reached the end of pullpush's coverage
        after = max(item["created_utc"] for item in batch)
        page += 1
        time.sleep(PULLPUSH_PACING_SECONDS)
    return ids


def discover_all_post_ids():
    """Combine every post-discovery source into one deduplicated ID list."""
    reddit_posts = fetch_all_posts()
    ids = [p["id"] for p in reddit_posts]
    seen = set(ids)

    print("  Fetching listing: pullpush.io (historical archive)", flush=True)
    pullpush_ids = fetch_pullpush_ids()
    new_from_pullpush = [i for i in pullpush_ids if i not in seen]
    seen.update(new_from_pullpush)
    ids.extend(new_from_pullpush)
    print(
        f"  pullpush.io: {len(pullpush_ids)} posts, {len(new_from_pullpush)} new "
        f"(combined total {len(ids)})",
        flush=True,
    )
    return ids


def fetch_comments(post_id36):
    time.sleep(REQUEST_PACING_SECONDS)
    url = f"{BASE}/comments/{post_id36}/.rss"
    xml_text = _fetch(url)
    return parse_atom_entries(xml_text)


def _is_hint_intro_line(line):
    """A short heading-like line that mentions "hint(s)", e.g. "Hints may
    appear here:" - deliberately requires brevity so an incidental mention of
    "hint" inside a longer plot-description sentence doesn't false-trigger."""
    return bool(HINT_INTRO_RE.search(line)) and len(line.split()) <= 8


def extract_body_and_hints(content_html):
    """Split a post's body into (extra_body_text, hints).

    extra_body_text is whatever plot description appears before the hints
    (e.g. a post that opens with a paragraph and only lists hints further
    down) - unfilled template placeholders like "Hints go here" are dropped
    rather than treated as real body text.

    Hints are recognized in two formats: explicit "Hint #N: ..." lines
    anywhere in the body, or a short "Hints ..." heading followed by a plain
    numbered list ("1) ...", "2. ...") - real posts use both styles.
    """
    body = _strip_html(content_html)
    hints = []
    body_lines = []
    seen_hint = False
    numbered_mode = False

    for line in body.splitlines():
        m = HINT_LINE_RE.match(line)
        if m:
            hints.append(m.group(1).strip())
            seen_hint = True
            numbered_mode = False
            continue

        if PLACEHOLDER_HINT_RE.match(line):
            continue

        if numbered_mode:
            nm = NUMBERED_LINE_RE.match(line)
            if nm:
                hints.append(nm.group(2).strip())
                seen_hint = True
                continue
            numbered_mode = False  # a non-numbered line ends the list

        if not seen_hint and _is_hint_intro_line(line):
            numbered_mode = True
            continue  # the heading itself isn't body text or a hint

        if not seen_hint and not numbered_mode:
            body_lines.append(line)

    extra_body = "\n".join(body_lines).strip()
    return extra_body, hints


def load_game_titles():
    titles = set()
    if os.path.exists(GAMES_PATH):
        with open(GAMES_PATH, "r", encoding="utf-8") as f:
            titles.update(json.load(f).get("games", []))
    if os.path.exists(QUESTIONS_PATH):
        with open(QUESTIONS_PATH, "r", encoding="utf-8") as f:
            for q in json.load(f).get("questions", []):
                titles.add(q["answer"])
    # Longest first, so "Portal 2" is preferred over "Portal" when both match.
    return sorted(titles, key=len, reverse=True)


def build_unique_subtitle_index(sorted_titles):
    """Map subtitle (lowercase, e.g. "new horizons") -> title, but only for
    subtitles that belong to exactly one title AND don't collide with some
    other, unrelated standalone title. Two collision patterns get excluded:
    different franchises reusing the same subtitle (e.g. "New Horizons" is
    both Animal Crossing's and Uncharted Waters II's), and a subtitle that
    happens to equal a real, independent, unrelated game's full title (e.g.
    "Dark Souls" is both the famous standalone game and the subtitle of the
    obscure "Bleach: Dark Souls" tie-in - someone saying "Dark Souls" is
    overwhelmingly more likely to mean the standalone game). Either way,
    matching on the subtitle alone would be a coin flip, not a real ID."""
    standalone_titles = {t.lower() for t in sorted_titles}
    candidates = {}
    ambiguous = set()
    for title in sorted_titles:
        if ":" not in title:
            continue
        subtitle = title.split(":", 1)[1].strip().lower()
        if len(subtitle.split()) < 2:
            continue
        if subtitle in standalone_titles:
            ambiguous.add(subtitle)
        if subtitle in candidates and candidates[subtitle] != title:
            ambiguous.add(subtitle)
        candidates[subtitle] = title
    return {k: v for k, v in candidates.items() if k not in ambiguous}


def _contains_whole(lowered_text, phrase):
    return re.search(r"\b" + re.escape(phrase) + r"\b", lowered_text) is not None


TRAILING_PUNCT_RE = re.compile(r"[!?.]+$")


# I-XX covers virtually every real sequel number in practice.
ROMAN_NUMERALS = {
    "I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6, "VII": 7, "VIII": 8,
    "IX": 9, "X": 10, "XI": 11, "XII": 12, "XIII": 13, "XIV": 14, "XV": 15,
    "XVI": 16, "XVII": 17, "XVIII": 18, "XIX": 19, "XX": 20,
}


def _arabic_numeral_variant(title):
    """If `title` ends in a whole-word roman numeral (e.g. "Kingdom Hearts III"),
    return it with that numeral swapped for the arabic digit ("Kingdom Hearts 3")
    - real conversation almost always uses the digit, not the roman numeral, so
    without this the correctly-numbered title never matches literally and a
    shorter, wrong, unnumbered title (a real, different, earlier game) wins
    instead."""
    words = title.split()
    if not words:
        return None
    last = words[-1].upper()
    if last in ROMAN_NUMERALS:
        return " ".join(words[:-1] + [str(ROMAN_NUMERALS[last])])
    return None


def find_title_in_text(text, sorted_titles, unique_subtitles):
    """Return the best-matching known title found in `text`.

    Considers both the full title (e.g. "Spider-Man: Miles Morales") and, for
    series titles, the subtitle alone when it unambiguously identifies one
    title (e.g. "Miles Morales", since real conversation often drops the
    series prefix - but NOT "New Horizons", which is shared by two different
    franchises and would be a guess, not an identification). Among all
    matches, prefers the one whose matched title string is longest/most
    specific, rather than stopping at the first (possibly more generic) hit.

    Single-word titles (e.g. "Portal", "Combat") are much easier to match by
    pure coincidence, so they're only accepted when the word makes up most of
    `text` (e.g. a comment that's just "Legendary") - not when it's one word
    buried in a longer sentence (e.g. "Combat" inside "Halo Combat Evolved",
    where the real answer, "Halo: Combat Evolved", just isn't in our list).

    Titles with a colon (e.g. "Animal Crossing: New Horizons") are also checked
    without it ("Animal Crossing New Horizons"), since casual conversation
    routinely drops the punctuation. Without this, the full correct title never
    matches literally, while its own shorter prefix ("Animal Crossing", also a
    real, different game) still does - and being shorter, should never win.

    Titles ending in a roman numeral (e.g. "Kingdom Hearts III") are also
    checked with it swapped for the arabic digit ("Kingdom Hearts 3"), since
    that's how people actually type it - without this, "Kingdom Hearts" (the
    first, different game) matches instead, being the only literal match.

    Titles with stylized trailing punctuation (e.g. "Date Everything!") are
    also checked with it stripped ("Date Everything"), since casual replies
    routinely drop or swap it (e.g. "Date everything?") - without this, the
    full title never matches literally, while its own shorter, unrelated
    standalone-title prefix ("Everything", a real different game) still does.

    Titles with embedded abbreviation periods (e.g. "The Simpsons: Bart vs.
    the Space Mutants") are also checked with colons and periods stripped
    entirely ("the simpsons bart vs the space mutants"), since that's how
    people actually type "vs." in a casual reply - without this, only the
    shorter, different "The Simpsons" prefix matches.

    Titles with an ampersand (e.g. "The Simpsons Hit & Run") are also checked
    with it swapped for "and" or the casual "n" ("...Hit and Run", "...Hit n
    Run"), a common colloquial substitution (cf. "rock n roll") - without
    this, the full title never matches literally.

    Titles with a comma (e.g. "Papers, Please") are also checked with it
    dropped ("Papers Please"), since casual replies routinely drop internal
    punctuation - without this, only a shorter, unrelated single-word title
    matches instead.

    A handful of real but generic-sounding titles are excluded outright
    regardless of length/word-count, because they're also ordinary words used
    constantly in THIS subreddit's own conversation (every post is about a
    "plot" being explained badly) - "The Plot" is a real, if obscure, game,
    but matching on it is essentially guaranteed to be a false positive here.
    Likewise "Deleted" and "Removed" are real, obscure games, but Reddit's own
    placeholder text for a removed comment/account ("[deleted]", "[removed]")
    is far more common in this data than anyone actually meaning those games.
    """
    SUBREDDIT_CONTEXT_STOPWORDS = {
        "plot", "the plot", "game", "the game", "solved",
        "deleted", "removed", "[deleted]", "[removed]",
    }

    lowered = text.lower()
    is_short_text = len(text.split()) <= 2
    best_title = None
    best_len = 0

    for title in sorted_titles:
        if title.lower() in SUBREDDIT_CONTEXT_STOPWORDS:
            continue
        is_single_word = " " not in title
        if is_single_word and (len(title) < 6 or not is_short_text):
            continue
        if len(title) < 3:
            continue
        candidates = {title.lower()}
        if ":" in title:
            candidates.add(re.sub(r":\s*", " ", title.lower()).strip())
        numeral_variant = _arabic_numeral_variant(title)
        if numeral_variant:
            candidates.add(numeral_variant.lower())
        stripped_punct = TRAILING_PUNCT_RE.sub("", title).strip()
        if stripped_punct:
            candidates.add(stripped_punct.lower())
        if "." in title:
            loose = re.sub(r"\s+", " ", re.sub(r"[:.]", " ", title.lower())).strip()
            candidates.add(loose)
        if "&" in title:
            candidates.add(re.sub(r"\s*&\s*", " and ", title.lower()))
            candidates.add(re.sub(r"\s*&\s*", " n ", title.lower()))
        if "," in title:
            candidates.add(re.sub(r"\s*,\s*", " ", title.lower()).strip())
        matched = any(_contains_whole(lowered, c) for c in candidates)
        if matched and len(title) > best_len:
            best_title = title
            best_len = len(title)

    for subtitle, title in unique_subtitles.items():
        if _contains_whole(lowered, subtitle) and len(title) > best_len:
            best_title = title
            best_len = len(title)

    # If the best match is a plain prefix of a longer franchise entry, and that
    # entry's own subtitle ALSO appears somewhere else in the same text, prefer
    # the more specific title - even for an otherwise-ambiguous subtitle like
    # "New Horizons", since the franchise name being present too resolves it.
    # This catches real phrasing like "I'll take Animal Crossing. Solved! It
    # was New Horizons", where the two pieces aren't adjacent so the checks
    # above can't bridge them, but both being present together is unambiguous.
    if best_title:
        prefix = best_title.lower() + ":"
        upgrades = []
        for title in sorted_titles:
            if not title.lower().startswith(prefix):
                continue
            subtitle = title.split(":", 1)[1].strip().lower()
            if len(subtitle.split()) >= 2 and _contains_whole(lowered, subtitle):
                upgrades.append(title)
        if len(upgrades) == 1:
            best_title = upgrades[0]

    return best_title


AUTOMOD_SOLVED_MARKER = "marked as solved by its author"


def resolve_answer(post_author, comment_entries, sorted_titles, unique_subtitles):
    # NOTE: deliberately NOT re-sorted by timestamp for adjacency purposes below.
    # Reddit's RSS feed order isn't strictly chronological, but it tracks genuine
    # reply-adjacency ("the comment right before this one" = the guess actually
    # being replied to) better than a flat chronological sort does.
    plain_comments = [
        {**c, "text": _strip_html(c["content_html"])} for c in comment_entries if c["id"].startswith("t1_")
    ]

    # The subreddit's flair bot posts "marked as solved by its author" within about
    # a second of the post author's real confirming comment - every time, no matter
    # where either lands in the feed. That's a far more reliable anchor than
    # scanning for confirm-words: a casual "...if your answer is right or wrong..."
    # can false-trigger a keyword search, but nothing else produces this exact bot
    # message. Find it, then find the author's own comment closest to its timestamp.
    automod_comment = next(
        (c for c in plain_comments if AUTOMOD_SOLVED_MARKER in c["text"]),
        None,
    )
    if automod_comment is None:
        return None  # can't confidently locate the solve moment at all - skip

    author_comments = [c for c in plain_comments if c["author"] == post_author]
    if not author_comments:
        return None

    confirmation = min(
        author_comments,
        key=lambda c: abs(_parse_iso(c["published"]) - _parse_iso(automod_comment["published"])),
    )

    # Check the guess being confirmed FIRST, not the author's own reaction text.
    # In every real case tested, the confirming comment is a reaction/description
    # ("Yes!", "You got it marine", "It was indeed Pandora's Box that was opened")
    # rather than a restatement of the title, and matching against it has only ever
    # produced false positives (a title-shaped phrase mentioned incidentally). The
    # comment being confirmed is a real guess, almost always just the title itself.
    i = plain_comments.index(confirmation)
    if i > 0:
        match = find_title_in_text(plain_comments[i - 1]["text"], sorted_titles, unique_subtitles)
        if match:
            return match

    match = find_title_in_text(confirmation["text"], sorted_titles, unique_subtitles)
    if match:
        return match

    return None


CHECKED_PATH = os.path.join(DATA_DIR, "checked_posts.json")


def load_existing():
    if os.path.exists(QUESTIONS_PATH):
        with open(QUESTIONS_PATH, "r", encoding="utf-8") as f:
            return {q["id"]: q for q in json.load(f).get("questions", [])}
    return {}


def load_checked():
    """IDs of every post already checked, resolved or not. Since every post
    gets fetched now (not just pre-filtered solved ones - see fetch_all_posts),
    without this a post that's genuinely never been solved would get re-checked
    on every single future weekly run forever."""
    if os.path.exists(CHECKED_PATH):
        with open(CHECKED_PATH, "r", encoding="utf-8") as f:
            return set(json.load(f))
    return set()


def save_checked(checked_ids):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(CHECKED_PATH, "w", encoding="utf-8") as f:
        json.dump(sorted(checked_ids), f)


def save_questions(existing):
    os.makedirs(DATA_DIR, exist_ok=True)
    questions = sorted(existing.values(), key=lambda q: q.get("created_utc", ""), reverse=True)
    with open(QUESTIONS_PATH, "w", encoding="utf-8") as f:
        json.dump(
            {
                "source": "reddit",
                "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "count": len(questions),
                "questions": questions,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )
    return len(questions)


def main():
    sorted_titles = load_game_titles()
    unique_subtitles = build_unique_subtitle_index(sorted_titles)
    post_ids = discover_all_post_ids()
    print(f"Found {len(post_ids)} total posts to check for a solved confirmation", flush=True)

    existing = load_existing()
    checked = load_checked() | set(existing.keys())
    skipped_unresolved = 0
    new_count = 0

    for i, fullname in enumerate(post_ids, 1):  # fullname e.g. "t3_1v6iv64"
        post_id = fullname.split("_")[-1]
        if fullname in checked:
            continue  # already checked in a previous run, solved or not

        print(f"[{i}/{len(post_ids)}] fetching comments for {post_id}...", flush=True)
        try:
            comment_entries = fetch_comments(post_id)
        except Exception as exc:
            print(f"  Failed to fetch comments for {post_id}: {exc}", flush=True)
            continue  # transient failure - don't mark checked, retry next run

        checked.add(fullname)
        save_checked(checked)

        if not comment_entries:
            continue  # post deleted/removed, nothing there anymore

        post = comment_entries[0]  # the post itself is always the first entry
        answer = resolve_answer(post["author"], comment_entries[1:], sorted_titles, unique_subtitles)
        if not answer:
            skipped_unresolved += 1
            print("  Not solved / no confident answer found, skipping", flush=True)
            continue

        extra_body, hints = extract_body_and_hints(post["content_html"])
        prompt = f"{post['title']}\n\n{extra_body}" if extra_body else post["title"]
        canonical_name, cover_art_url = find_cover_art(answer)

        existing[fullname] = {
            "id": fullname,
            "prompt": prompt,
            "hints": hints,
            "answer": canonical_name,
            "cover_art_url": cover_art_url,
            "permalink": post["link"],
            "created_utc": post["published"],
            "scraped_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        new_count += 1
        total = save_questions(existing)
        print(f"  Resolved: {canonical_name!r} (saved, {total} questions total)", flush=True)

    print(f"Done. Added {new_count} new questions this run.", flush=True)
    if skipped_unresolved:
        print(f"Checked {skipped_unresolved} posts with no solved confirmation found", flush=True)


if __name__ == "__main__":
    main()
