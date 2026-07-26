"""
Refreshes cover_art_url for every existing question by re-looking it up on
Wikidata from the already-resolved answer text - no Reddit calls at all.
Safe to run any time questions.json exists; only touches cover_art_url, never
the answer/prompt/hints. Useful for backfilling art after a lookup-logic
change (e.g. the non-cover-art image filter) without re-scraping Reddit.
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))
from wikidata_lookup import find_cover_art  # noqa: E402

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
QUESTIONS_PATH = os.path.join(DATA_DIR, "questions.json")


def main():
    with open(QUESTIONS_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    questions = data.get("questions", [])
    updated = 0
    for i, q in enumerate(questions, 1):
        _, cover_art_url = find_cover_art(q["answer"])
        before = q.get("cover_art_url")
        if cover_art_url != before:
            print(f"[{i}/{len(questions)}] {q['answer']!r}: {before!r} -> {cover_art_url!r}", flush=True)
            q["cover_art_url"] = cover_art_url
            updated += 1
        else:
            print(f"[{i}/{len(questions)}] {q['answer']!r}: unchanged ({cover_art_url!r})", flush=True)
        time.sleep(0.5)

    with open(QUESTIONS_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"Done. Updated cover art for {updated}/{len(questions)} questions.")


if __name__ == "__main__":
    main()
