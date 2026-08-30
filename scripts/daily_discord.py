"""
Posts today's Daily Challenge questions to a Discord Forum channel, one
thread per question, and reveals the previous day's answers by posting a
follow-up into each of those threads. Run daily via
.github/workflows/daily-discord.yml, timed to fire shortly after the 1am
PST rotation - by then "today" has both its own 3 new questions AND
yesterday's answers ready to reveal, matching the website's own timing (see
"How the Daily Challenge works" in README.md).

Requires DISCORD_WEBHOOK_URL to point at a webhook whose target channel is a
Discord Forum (or Media) channel - that's what makes the `thread_name` field
create a new thread per post, with no bot/bot-token needed. If unset, exits
quietly so the workflow is safe to leave enabled even before a webhook is
configured.

Thread IDs are persisted in data/discord_threads.json (period key -> list of
{question_id, thread_id, revealed}) so the *next* day's run can find and
post the answer into the right threads. This file gets committed back to
the repo by the workflow, same as data/questions.json.

The period-key/question-selection logic here MUST exactly match app.js's
getDailyPeriodKey() / dailyHash() / pickDailyQuestions() - the whole point
is that the questions threaded in Discord are the same 3 the website is
actually showing that day.
"""
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
QUESTIONS_PATH = os.path.join(DATA_DIR, "questions.json")
THREADS_PATH = os.path.join(DATA_DIR, "discord_threads.json")
SITE_URL = "https://explainagameplotbadly.github.io/"
REQUEST_PACING_SECONDS = 2  # be polite to Discord's per-webhook rate limit
PRUNE_AFTER_DAYS = 7  # safety net so a permanently-stuck period can't grow this file forever
# Discord's edge (Cloudflare) hard-blocks the default Python-urllib/x.y User-
# Agent with an HTTP 403 "error code: 1010" before the request ever reaches
# Discord's own API - a real browser-like UA is required, same as
# scrape_reddit.py's USER_AGENT for the same reason against Reddit.
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"


def get_daily_period_key(now=None):
    now = now or datetime.now(timezone.utc)
    la_time = now.astimezone(ZoneInfo("America/Los_Angeles"))
    period_date = la_time.date()
    if la_time.hour < 1:
        period_date = period_date - timedelta(days=1)
    return period_date.isoformat()


def get_previous_period_key(period_key):
    d = datetime.strptime(period_key, "%Y-%m-%d").date()
    return (d - timedelta(days=1)).isoformat()


def daily_hash(s):
    """FNV-1a over 32 bits - must match app.js's dailyHash() bit-for-bit."""
    h = 2166136261
    for ch in s:
        h ^= ord(ch)
        h = (h * 16777619) & 0xFFFFFFFF
    return h


def pick_daily_questions(questions, period_key, count=3):
    scored = sorted(questions, key=lambda q: daily_hash(f"{period_key}|{q['id']}"))
    return scored[:count]


def load_threads():
    if os.path.exists(THREADS_PATH):
        with open(THREADS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_threads(threads):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(THREADS_PATH, "w", encoding="utf-8") as f:
        json.dump(threads, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")


def prune_threads(threads, today_key):
    """Drop period keys that are fully revealed, or old enough
    (PRUNE_AFTER_DAYS) that they're never coming back regardless of revealed
    status - keeps this file from growing forever if a thread permanently
    fails to reveal (e.g. someone deleted it in Discord)."""
    today = datetime.strptime(today_key, "%Y-%m-%d").date()
    kept = {}
    for period_key, entries in threads.items():
        if entries and all(e.get("revealed") for e in entries):
            continue
        try:
            age = (today - datetime.strptime(period_key, "%Y-%m-%d").date()).days
        except ValueError:
            age = 0
        if age > PRUNE_AFTER_DAYS:
            continue
        kept[period_key] = entries
    return kept


def discord_post(webhook_url, payload, thread_id=None):
    """POST to the webhook, optionally into an existing thread. Returns the
    parsed message JSON (requires wait=true to get anything back) or None on
    failure."""
    params = {"wait": "true"}
    if thread_id:
        params["thread_id"] = thread_id
    url = webhook_url + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": USER_AGENT},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read()
            return json.loads(body) if body else None
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        print(f"Discord webhook POST failed: HTTP {exc.code} - {detail}")
        return None
    except Exception as exc:
        print(f"Discord webhook POST failed: {exc}")
        return None


def reveal_previous_day(webhook_url, questions_by_id, threads, previous_period_key):
    entries = threads.get(previous_period_key)
    if not entries:
        print(f"No threads recorded for {previous_period_key}, nothing to reveal.")
        return

    for i, entry in enumerate(entries, 1):
        if entry.get("revealed"):
            continue
        question = questions_by_id.get(entry["question_id"])
        if not question:
            print(f"Question {entry['question_id']} not found, skipping reveal.")
            continue

        lines = [f"✅ **Answer: {question['answer']}**"]
        if question.get("permalink"):
            lines.append(f"[Original post]({question['permalink']})")
        payload = {"content": "\n".join(lines)}
        if question.get("cover_art_url"):
            payload["embeds"] = [{"image": {"url": question["cover_art_url"]}}]

        result = discord_post(webhook_url, payload, thread_id=entry["thread_id"])
        if result is not None:
            entry["revealed"] = True
            print(f"Revealed answer for question {i} in thread {entry['thread_id']}.")
        else:
            print(f"Failed to reveal answer for question {i}, will retry next run.")
        time.sleep(REQUEST_PACING_SECONDS)


def post_today(webhook_url, daily_questions, threads, period_key):
    if period_key in threads:
        print(f"Threads already posted for {period_key}, skipping.")
        return

    entries = []
    for i, q in enumerate(daily_questions, 1):
        prompt_preview = q["prompt"].split("\n")[0][:200]
        thread_name = f"Q{i} — {period_key}"[:100]
        payload = {
            "thread_name": thread_name,
            "content": (
                f"**Question {i} of {len(daily_questions)}**\n{prompt_preview}\n\n"
                f"Guess at {SITE_URL}#daily-section"
            ),
        }
        result = discord_post(webhook_url, payload)
        if result is not None:
            thread_id = result.get("channel_id")
            entries.append({"question_id": q["id"], "thread_id": thread_id, "revealed": False})
            print(f"Posted question {i} as thread {thread_id}.")
        else:
            print(f"Failed to post question {i}, it won't get a thread this run.")
        time.sleep(REQUEST_PACING_SECONDS)

    if entries:
        threads[period_key] = entries


def main():
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        print("DISCORD_WEBHOOK_URL not set, skipping Discord announcement.")
        return

    with open(QUESTIONS_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    questions = data.get("questions", [])
    if not questions:
        print("No questions available, skipping.")
        return
    questions_by_id = {q["id"]: q for q in questions}

    period_key = get_daily_period_key()
    previous_period_key = get_previous_period_key(period_key)
    daily_questions = pick_daily_questions(questions, period_key)

    threads = load_threads()

    # Reveal yesterday's answers first, so a later failure posting today's
    # questions can never cause a reveal to be skipped.
    reveal_previous_day(webhook_url, questions_by_id, threads, previous_period_key)
    post_today(webhook_url, daily_questions, threads, period_key)

    threads = prune_threads(threads, period_key)
    save_threads(threads)


if __name__ == "__main__":
    main()
