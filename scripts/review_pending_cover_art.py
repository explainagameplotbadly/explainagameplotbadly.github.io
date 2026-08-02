"""
Review tool for cover_art_pending suggestions queued by scrape_reddit.py's
Wikipedia/Fandom fallback (see cover_art_fallback.py for why these need a
human check before going live: fair-use and fan-uploaded art, not the
freely-licensed Wikidata/Steam art cover_art_url normally holds).

Usage:
  review_pending_cover_art.py                  write an HTML gallery of every
                                                 pending answer for visual review
  review_pending_cover_art.py --html PATH       ...to a specific path instead
  review_pending_cover_art.py --approve A B     promote cover_art_pending ->
                                                 cover_art_url for these exact
                                                 answers (every question sharing
                                                 that answer)
  review_pending_cover_art.py --approve-all     promote every pending answer
  review_pending_cover_art.py --reject A B      discard the pending suggestion
                                                 for these answers (leaves no art,
                                                 so it can be re-suggested later)
"""
import argparse
import html
import json
import os

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
QUESTIONS_PATH = os.path.join(DATA_DIR, "questions.json")
DEFAULT_HTML_PATH = os.path.join(os.path.dirname(__file__), "..", "cover_art_pending_review.html")


def load_questions():
    with open(QUESTIONS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_questions(data):
    with open(QUESTIONS_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def pending_by_answer(questions):
    # One representative entry per unique answer - every question sharing an
    # answer was queued from the same lookup, so they're always identical.
    by_answer = {}
    for q in questions:
        pending = q.get("cover_art_pending")
        if pending:
            by_answer.setdefault(q["answer"], pending)
    return by_answer


def write_html(by_answer, out_path):
    cards = []
    for answer, pending in sorted(by_answer.items()):
        cards.append(f"""
        <figure>
          <img src="{html.escape(pending['cover_art_url'])}" loading="lazy" alt="{html.escape(answer)}">
          <figcaption>{html.escape(answer)}<br><small>{html.escape(pending['source'])}</small></figcaption>
        </figure>""")

    doc = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Pending cover art ({len(by_answer)})</title>
<style>
body {{ font-family: sans-serif; background: #111; color: #eee; margin: 2rem; }}
.grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: 1rem; }}
figure {{ margin: 0; background: #1c1c1c; padding: 0.5rem; border-radius: 6px; }}
img {{ width: 100%; height: 220px; object-fit: contain; background: #000; }}
figcaption {{ margin-top: 0.5rem; font-size: 0.85rem; }}
small {{ color: #999; }}
</style></head>
<body>
<h1>{len(by_answer)} pending cover art suggestions</h1>
<p>Approve with <code>review_pending_cover_art.py --approve "Exact Answer" ...</code>,
reject with <code>--reject</code>, or bulk-approve after spot-checking with
<code>--approve-all</code>.</p>
<div class="grid">{"".join(cards)}</div>
</body></html>"""

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(doc)
    print(f"Wrote {len(by_answer)} pending entries to {out_path}")


def approve(questions, answers):
    wanted = set(answers)
    count = 0
    for q in questions:
        if q["answer"] in wanted and q.get("cover_art_pending"):
            q["cover_art_url"] = q["cover_art_pending"]["cover_art_url"]
            del q["cover_art_pending"]
            count += 1
    return count


def approve_all(questions):
    count = 0
    for q in questions:
        if q.get("cover_art_pending"):
            q["cover_art_url"] = q["cover_art_pending"]["cover_art_url"]
            del q["cover_art_pending"]
            count += 1
    return count


def reject(questions, answers):
    wanted = set(answers)
    count = 0
    for q in questions:
        if q["answer"] in wanted and q.get("cover_art_pending"):
            del q["cover_art_pending"]
            count += 1
    return count


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--html", nargs="?", const=DEFAULT_HTML_PATH, metavar="PATH",
                         help="Write an HTML gallery of pending suggestions (default action)")
    parser.add_argument("--approve", nargs="+", metavar="ANSWER", help="Promote these answers' pending art to live")
    parser.add_argument("--approve-all", action="store_true", help="Promote every pending answer to live")
    parser.add_argument("--reject", nargs="+", metavar="ANSWER", help="Discard the pending suggestion for these answers")
    args = parser.parse_args()

    data = load_questions()
    questions = data.get("questions", [])
    did_something = False

    if args.approve:
        n = approve(questions, args.approve)
        print(f"Approved {n} question(s) across {len(args.approve)} answer(s).")
        did_something = True

    if args.approve_all:
        n = approve_all(questions)
        print(f"Approved {n} question(s) (all pending).")
        did_something = True

    if args.reject:
        n = reject(questions, args.reject)
        print(f"Rejected {n} question(s) across {len(args.reject)} answer(s).")
        did_something = True

    if did_something:
        save_questions(data)

    if args.html or not did_something:
        write_html(pending_by_answer(questions), args.html or DEFAULT_HTML_PATH)


if __name__ == "__main__":
    main()
