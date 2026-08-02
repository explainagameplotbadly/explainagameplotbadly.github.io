"""
Imports a fallback-source lookup results file (produced by
backfill_fallback_cover_art.py: a list of {answer, source, cover_art_url})
into questions.json as cover_art_pending fields, ready for
review_pending_cover_art.py. Never sets cover_art_url directly - see
cover_art_fallback.py for why these sources need a human check first.

Skips any question that already has cover_art_url or cover_art_pending set,
so re-running with an overlapping results file is always safe.
"""
import json
import os
import sys

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
QUESTIONS_PATH = os.path.join(DATA_DIR, "questions.json")


def main():
    if len(sys.argv) < 2:
        print("Usage: apply_cover_art_results.py <results.json>", file=sys.stderr)
        sys.exit(1)

    with open(sys.argv[1], "r", encoding="utf-8") as f:
        results = json.load(f)
    by_answer = {r["answer"]: {"source": r["source"], "cover_art_url": r["cover_art_url"]} for r in results}

    with open(QUESTIONS_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    updated = 0
    for q in data.get("questions", []):
        if q.get("cover_art_url") or q.get("cover_art_pending"):
            continue
        pending = by_answer.get(q["answer"])
        if pending:
            q["cover_art_pending"] = pending
            updated += 1

    with open(QUESTIONS_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"Queued {updated} questions with a pending cover art suggestion "
          f"from {len(results)} results in {sys.argv[1]}.")


if __name__ == "__main__":
    main()
