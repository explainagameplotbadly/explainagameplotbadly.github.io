"""
Runs the Wikipedia/Fandom fallback cover art lookup (see cover_art_fallback.py)
against a list of game titles that Wikidata/Steam already failed on (see
backfill_missing_cover_art.py + cover_art.py).

Does NOT write to questions.json - both fallback sources carry licensing
caveats (non-free Wikipedia fair-use images, unlicensed fan-uploaded Fandom
images; see cover_art_fallback.py's docstring), so results are written to a
review JSON file instead. Use apply_cover_art_results.py to import a
finished run's output into questions.json as cover_art_pending fields, then
review_pending_cover_art.py to approve or reject each one.
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))
from cover_art_fallback import find_fallback_cover_art  # noqa: E402


def run(titles, out_path):
    results = []
    found = 0
    for i, title in enumerate(titles, 1):
        source, url = find_fallback_cover_art(title)
        if url:
            found += 1
            results.append({"answer": title, "source": source, "cover_art_url": url})
        print(f"[{i}/{len(titles)}] {title!r}: {source} {url!r}", flush=True)
        time.sleep(0.5)

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"Done. Found art for {found}/{len(titles)} via fallback sources. "
          f"Written to {out_path} for review.", flush=True)


if __name__ == "__main__":
    in_path = sys.argv[1] if len(sys.argv) > 1 else "cover_art_batch_1.json"
    out_path = sys.argv[2] if len(sys.argv) > 2 else "cover_art_fallback_results.json"
    base = os.path.join(os.path.dirname(__file__), "..")
    with open(os.path.join(base, in_path), "r", encoding="utf-8") as f:
        titles = json.load(f)
    run(titles, os.path.join(base, out_path))
