"""
Scrapes r/ExplainAGamePlotBadly for posts flaired "Solved" and turns them into
quiz questions (data/questions.json).

Requires a Reddit "script" app (free): https://www.reddit.com/prefs/apps
Set these as environment variables (GitHub Actions secrets in production):
  REDDIT_CLIENT_ID
  REDDIT_CLIENT_SECRET

NOTE ON PARSING: Reddit blocks unauthenticated/datacenter access, which made it
impossible to inspect real "Solved" posts while building this script. The
extraction logic below is a best-effort heuristic (see extract_hints_and_answer)
covering the common ways people mark answers/hints in this kind of subreddit:
explicit "Solved:"/"Answer:"/"Game:" lines, "Hint:" lines, and falling back to
the OP's own comments. If it misses real posts once you have working credentials,
share a couple of example post bodies and the patterns can be tightened.
"""
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
SOLVED_FLAIR = "solved"
USER_AGENT = "python:eagpb-game-scraper:1.0 (by /u/eagpb-game-bot)"
DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
QUESTIONS_PATH = os.path.join(DATA_DIR, "questions.json")
MAX_POSTS = 500

ANSWER_LINE_RE = re.compile(r"^\s*\**\s*(?:solved|answer|game)\s*\**\s*[:\-]\s*(.+?)\s*\**\s*$", re.IGNORECASE)
HINT_LINE_RE = re.compile(r"^\s*\**\s*hint\s*\**\s*\d*\s*[:\-]\s*(.+?)\s*$", re.IGNORECASE)


def get_access_token():
    client_id = os.environ["REDDIT_CLIENT_ID"]
    client_secret = os.environ["REDDIT_CLIENT_SECRET"]
    auth = f"{client_id}:{client_secret}".encode()
    import base64

    body = urllib.parse.urlencode({"grant_type": "client_credentials"}).encode()
    req = urllib.request.Request(
        "https://www.reddit.com/api/v1/access_token",
        data=body,
        headers={
            "Authorization": b"Basic " + base64.b64encode(auth),
            "User-Agent": USER_AGENT,
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)["access_token"]


def api_get(token, path, params=None):
    url = f"https://oauth.reddit.com{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(
        url, headers={"Authorization": f"Bearer {token}", "User-Agent": USER_AGENT}
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def fetch_solved_posts(token):
    posts = []
    after = None
    while len(posts) < MAX_POSTS:
        params = {
            "q": f'flair_name:"{SOLVED_FLAIR}"',
            "restrict_sr": "on",
            "sort": "new",
            "limit": 100,
        }
        if after:
            params["after"] = after
        data = api_get(token, f"/r/{SUBREDDIT}/search", params)
        children = data.get("data", {}).get("children", [])
        if not children:
            break
        for child in children:
            post = child["data"]
            flair = (post.get("link_flair_text") or "").strip().lower()
            if flair != SOLVED_FLAIR:
                continue
            posts.append(post)
        after = data.get("data", {}).get("after")
        if not after:
            break
        time.sleep(1)  # be polite, stay well under rate limits
    return posts


def fetch_op_comments(token, post_id, op_username):
    try:
        data = api_get(token, f"/r/{SUBREDDIT}/comments/{post_id}", {"limit": 50, "depth": 1})
    except (urllib.error.URLError, TimeoutError):
        return []
    if len(data) < 2:
        return []
    comments = []
    for child in data[1].get("data", {}).get("children", []):
        c = child.get("data", {})
        if c.get("author") == op_username and c.get("body"):
            comments.append(c["body"])
    return comments


def extract_hints_and_answer(title, selftext, op_comments):
    """Best-effort heuristic parse. See module docstring for caveats."""
    hints = []
    answer = None
    remaining_lines = []

    for line in selftext.splitlines():
        hint_match = HINT_LINE_RE.match(line)
        answer_match = ANSWER_LINE_RE.match(line)
        if answer_match and not answer:
            answer = answer_match.group(1).strip()
        elif hint_match:
            hints.append(hint_match.group(1).strip())
        else:
            remaining_lines.append(line)

    if not answer:
        for comment in op_comments:
            for line in comment.splitlines():
                answer_match = ANSWER_LINE_RE.match(line)
                if answer_match:
                    answer = answer_match.group(1).strip()
                    break
            if answer:
                break

    body = "\n".join(remaining_lines).strip()
    prompt = title if not body else f"{title}\n\n{body}"
    return prompt, hints, answer


def load_existing():
    if os.path.exists(QUESTIONS_PATH):
        with open(QUESTIONS_PATH, "r", encoding="utf-8") as f:
            return {q["id"]: q for q in json.load(f).get("questions", [])}
    return {}


def main():
    token = get_access_token()
    posts = fetch_solved_posts(token)
    print(f"Fetched {len(posts)} posts flaired '{SOLVED_FLAIR}'")

    existing = load_existing()
    skipped_unresolved = 0

    for post in posts:
        post_id = post["id"]
        op_comments = fetch_op_comments(token, post_id, post.get("author", ""))
        prompt, hints, answer = extract_hints_and_answer(
            post.get("title", ""), post.get("selftext", ""), op_comments
        )

        if not answer:
            skipped_unresolved += 1
            continue

        canonical_name, cover_art_url = find_cover_art(answer)

        existing[post_id] = {
            "id": post_id,
            "prompt": prompt,
            "hints": hints,
            "answer": canonical_name,
            "cover_art_url": cover_art_url,
            "permalink": "https://www.reddit.com" + post.get("permalink", ""),
            "created_utc": post.get("created_utc"),
            "scraped_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        time.sleep(1)

    os.makedirs(DATA_DIR, exist_ok=True)
    questions = sorted(existing.values(), key=lambda q: q.get("created_utc", 0), reverse=True)
    with open(QUESTIONS_PATH, "w", encoding="utf-8") as f:
        json.dump(
            {"updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "count": len(questions), "questions": questions},
            f,
            ensure_ascii=False,
            indent=2,
        )

    print(f"Wrote {len(questions)} questions to {QUESTIONS_PATH}")
    if skipped_unresolved:
        print(f"Skipped {skipped_unresolved} solved posts where no answer could be extracted")


if __name__ == "__main__":
    main()
