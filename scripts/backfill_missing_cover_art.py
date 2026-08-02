"""
Fills in cover_art_url for questions that don't have one yet, without
re-querying Wikidata/Steam for games that already resolved successfully
elsewhere. Groups questions by answer first, so every instance of the same
game gets the exact same cover art and each unique title is only looked up
once - unlike refresh_cover_art.py, which re-checks every single question
unconditionally.

Does its network lookups against an in-memory snapshot, then re-reads
questions.json fresh right before writing so it doesn't clobber a
concurrently-running scrape_reddit.py's newer data. Even so, run this while
the scraper is paused - the scraper holds its own in-memory copy of
questions.json for its whole run and will overwrite this script's changes
the next time it saves if both are active at once.
"""
import json
import os
import sys
import time
from collections import defaultdict

sys.path.insert(0, os.path.dirname(__file__))
from cover_art import find_cover_art  # noqa: E402

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
QUESTIONS_PATH = os.path.join(DATA_DIR, "questions.json")


def load_questions():
    with open(QUESTIONS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def main():
    data = load_questions()
    questions = data.get("questions", [])

    by_answer = defaultdict(list)
    for q in questions:
        by_answer[q["answer"]].append(q)

    # Reuse any URL already known for this answer instead of a fresh lookup -
    # covers the case where some instances resolved and others didn't.
    needs_lookup = []
    known = {}
    for answer, qs in by_answer.items():
        existing_url = next((q.get("cover_art_url") for q in qs if q.get("cover_art_url")), None)
        if existing_url:
            known[answer] = existing_url
        else:
            needs_lookup.append(answer)

    print(f"{len(by_answer)} unique answers, {len(known)} already have art, "
          f"{len(needs_lookup)} need a lookup", flush=True)

    found = 0
    for i, answer in enumerate(needs_lookup, 1):
        _, cover_art_url = find_cover_art(answer)
        if cover_art_url:
            known[answer] = cover_art_url
            found += 1
        print(f"[{i}/{len(needs_lookup)}] {answer!r}: {cover_art_url!r}", flush=True)
        time.sleep(0.5)

    print(f"Done looking up. Found art for {found}/{len(needs_lookup)} previously-missing answers.",
          flush=True)

    # Re-read fresh in case the scraper (or another process) touched the file
    # since we started, then only ever fill in blanks - never overwrite a
    # cover_art_url that's already set.
    data = load_questions()
    updated = 0
    for q in data.get("questions", []):
        if not q.get("cover_art_url") and q["answer"] in known:
            q["cover_art_url"] = known[q["answer"]]
            updated += 1

    with open(QUESTIONS_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"Updated cover_art_url on {updated} questions.", flush=True)


if __name__ == "__main__":
    main()
