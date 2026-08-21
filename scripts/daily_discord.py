"""
Posts today's Daily Challenge prompts (never the answers) to a Discord
webhook. Run daily via .github/workflows/daily-discord.yml, timed to fire
shortly after the 1am PST rotation. Requires a DISCORD_WEBHOOK_URL secret -
if unset, this exits quietly without posting, so the workflow is safe to
leave enabled even before a webhook is configured.

The selection logic here MUST exactly match app.js's getDailyPeriodKey() /
dailyHash() / pickDailyQuestions() - the whole point is that the questions
announced in Discord are the same 3 the website is actually showing that day.
"""
import json
import os
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
QUESTIONS_PATH = os.path.join(DATA_DIR, "questions.json")
SITE_URL = "https://explainagameplotbadly.github.io/"


def get_daily_period_key(now=None):
    now = now or datetime.now(timezone.utc)
    la_time = now.astimezone(ZoneInfo("America/Los_Angeles"))
    period_date = la_time.date()
    if la_time.hour < 1:
        period_date = period_date - timedelta(days=1)
    return period_date.isoformat()


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

    period_key = get_daily_period_key()
    daily = pick_daily_questions(questions, period_key)

    lines = [
        f"**\U0001f3ae Daily Challenge — {period_key}**",
        "Guess the game! Answers reveal after today's period ends.",
        "",
    ]
    for i, q in enumerate(daily, 1):
        prompt_preview = q["prompt"].split("\n")[0][:200]
        lines.append(f"**{i}.** {prompt_preview}")
    lines.append("")
    lines.append(f"Play at {SITE_URL}")

    payload = {"content": "\n".join(lines)}
    req = urllib.request.Request(
        webhook_url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            print(f"Discord webhook responded with status {resp.status}")
    except Exception as exc:
        print(f"Failed to post to Discord: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
