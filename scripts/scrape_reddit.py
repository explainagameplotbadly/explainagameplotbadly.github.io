"""
Scrapes r/ExplainAGamePlotBadly for posts flaired "Solved" and turns them into
quiz questions (data/questions.json).

No Reddit developer app / OAuth / Devvit needed. This uses Reddit's public,
unauthenticated RSS endpoints, which remain open even though Reddit's JSON API
(oauth.reddit.com, *.json) now hard-blocks unauthenticated/datacenter traffic:

  - search.rss  with q=flair:"Solved"  -> list of solved posts
  - /comments/<id>/.rss                -> a post's comment thread

These are rate-limited (roughly one request per 25-35s from a single IP), so
this script paces itself deliberately. A weekly run comfortably fits Reddit's
limits and GitHub Actions' time budget.

HOW THE ANSWER IS EXTRACTED: in this subreddit, posts almost never state the
answer directly (not even in a "Solved:" line) - it's confirmed conversationally,
e.g. a commenter guesses "Spider-Man ... Miles Morales dlc..." and the OP (post
author) replies "Absolutely Miles." followed by "Solved!". So this script:
  1. Finds the first comment by the post's own author containing a confirmation
     word (solved/correct/yes/yep/absolutely/right/exactly/got it/that's it).
  2. Takes that comment's text plus the comment immediately before it (the guess
     being confirmed) as "context text".
  3. Looks for the longest known game title (from data/games.json, whole-word
     match) that appears in that context text - preferring a match inside the
     OP's own confirmation text over the guesser's text.
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
from wikidata_lookup import find_cover_art  # noqa: E402

SUBREDDIT = "ExplainAGamePlotBadly"
BASE = f"https://www.reddit.com/r/{SUBREDDIT}"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
QUESTIONS_PATH = os.path.join(DATA_DIR, "questions.json")
GAMES_PATH = os.path.join(DATA_DIR, "games.json")

REQUEST_PACING_SECONDS = 30

HINT_LINE_RE = re.compile(r"^\s*\**\s*hint\s*\**\s*#?\s*[\d.]*\s*[:\-]\s*(.+?)\s*$", re.IGNORECASE)
# Some posts leave the hint section as an unfilled template, e.g. "Hints go here" -
# that's not a real hint or real body text, so it shouldn't end up in the prompt.
PLACEHOLDER_HINT_RE = re.compile(r"^\s*hints?\s+(?:will\s+)?go(?:es)?\s+here\.?\s*$", re.IGNORECASE)
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


def fetch_solved_posts():
    """Fetch every "Solved"-flaired post, paging through with the standard
    Reddit listing `after` cursor (100 posts per page, the endpoint's max)."""
    query = urllib.parse.quote('flair:"Solved"')
    all_posts = []
    after = None
    page = 1
    while True:
        url = f"{BASE}/search.rss?q={query}&restrict_sr=1&sort=new&limit=100"
        if after:
            url += f"&after={after}"
        xml_text = _fetch(url)
        posts = parse_atom_entries(xml_text)
        if not posts:
            break
        all_posts.extend(posts)
        print(f"  Search page {page}: {len(posts)} posts (running total {len(all_posts)})", flush=True)
        if len(posts) < 100:
            break  # short page = last page
        after = posts[-1]["id"]
        page += 1
        time.sleep(REQUEST_PACING_SECONDS)
    return all_posts


def fetch_comments(post_id36):
    time.sleep(REQUEST_PACING_SECONDS)
    url = f"{BASE}/comments/{post_id36}/.rss"
    xml_text = _fetch(url)
    return parse_atom_entries(xml_text)


def extract_body_and_hints(content_html):
    """Split a post's body into (extra_body_text, hints).

    extra_body_text is whatever plot description appears before the first
    "Hint" line (e.g. a post that opens with a paragraph and only lists hints
    further down) - unfilled template placeholders like "Hints go here" are
    dropped rather than treated as real body text.
    """
    body = _strip_html(content_html)
    hints = []
    body_lines = []
    seen_hint = False

    for line in body.splitlines():
        m = HINT_LINE_RE.match(line)
        if m:
            hints.append(m.group(1).strip())
            seen_hint = True
            continue
        if PLACEHOLDER_HINT_RE.match(line):
            continue
        if not seen_hint:
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
    subtitles that belong to exactly one title. Different franchises reusing
    the same subtitle is common (e.g. "New Horizons" is both Animal Crossing's
    and Uncharted Waters II's) - matching on a shared subtitle is a coin flip,
    not a real identification, so those are deliberately excluded here."""
    candidates = {}
    ambiguous = set()
    for title in sorted_titles:
        if ":" not in title:
            continue
        subtitle = title.split(":", 1)[1].strip().lower()
        if len(subtitle.split()) < 2:
            continue
        if subtitle in candidates and candidates[subtitle] != title:
            ambiguous.add(subtitle)
        candidates[subtitle] = title
    return {k: v for k, v in candidates.items() if k not in ambiguous}


def _contains_whole(lowered_text, phrase):
    return re.search(r"\b" + re.escape(phrase) + r"\b", lowered_text) is not None


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
    """
    lowered = text.lower()
    is_short_text = len(text.split()) <= 2
    best_title = None
    best_len = 0

    for title in sorted_titles:
        is_single_word = " " not in title
        if is_single_word and (len(title) < 6 or not is_short_text):
            continue
        if len(title) < 3:
            continue
        matched = False
        if _contains_whole(lowered, title.lower()):
            matched = True
        elif ":" in title and _contains_whole(lowered, re.sub(r":\s*", " ", title.lower()).strip()):
            matched = True
        if matched and len(title) > best_len:
            best_title = title
            best_len = len(title)

    for subtitle, title in unique_subtitles.items():
        if _contains_whole(lowered, subtitle) and len(title) > best_len:
            best_title = title
            best_len = len(title)

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


def load_existing():
    if os.path.exists(QUESTIONS_PATH):
        with open(QUESTIONS_PATH, "r", encoding="utf-8") as f:
            return {q["id"]: q for q in json.load(f).get("questions", [])}
    return {}


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
    posts = fetch_solved_posts()
    print(f"Found {len(posts)} posts flaired 'Solved'", flush=True)

    existing = load_existing()
    skipped_unresolved = 0
    new_count = 0

    for i, post in enumerate(posts, 1):
        post_id = post["id"].split("_")[-1]  # "t3_1v6iv64" -> "1v6iv64"
        if f"t3_{post_id}" in existing:
            continue  # already scraped in a previous run

        print(f"[{i}/{len(posts)}] fetching comments for {post_id}...", flush=True)
        try:
            comment_entries = fetch_comments(post_id)
        except Exception as exc:
            print(f"  Failed to fetch comments for {post_id}: {exc}", flush=True)
            continue

        answer = resolve_answer(post["author"], comment_entries[1:], sorted_titles, unique_subtitles)
        if not answer:
            skipped_unresolved += 1
            print("  No confident answer found, skipping", flush=True)
            continue

        extra_body, hints = extract_body_and_hints(post["content_html"])
        prompt = f"{post['title']}\n\n{extra_body}" if extra_body else post["title"]
        canonical_name, cover_art_url = find_cover_art(answer)

        existing[f"t3_{post_id}"] = {
            "id": f"t3_{post_id}",
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
        print(f"Skipped {skipped_unresolved} solved posts where no confident answer could be resolved", flush=True)


if __name__ == "__main__":
    main()
