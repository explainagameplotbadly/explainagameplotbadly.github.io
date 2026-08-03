"""
Fetches a broad list of video game titles from Wikidata for the search-bar
autocomplete. No API key required. Run manually or via the weekly GitHub Action.

Source: Wikidata SPARQL endpoint, items that are instance-of "video game" (Q7889)
with at least 2 sitelinks (a low notability bar that filters out stubs/test items).

NOTE: paginated with OFFSET/LIMIT, sorted by ?item (the entity URI) rather than
fetched as one unbounded request. Confirmed by testing that a single request for
the full ~28k-row result set is unreliable - even with no ORDER BY at all, it
silently returned an incomplete result missing real, well-linked games (e.g.
"Deracine", an 11-sitelink FromSoftware title that satisfies every filter clause
when checked directly), almost certainly because evaluating the sitelinks/label
filters over the full candidate space hits an internal query timeout before
finishing, and WDQS returns whatever was materialized so far rather than an
error. Ordering by the entity URI itself (cheap, effectively index-backed,
unlike sorting by a computed property like sitelinks) keeps each page fast
enough to complete reliably; paging until an empty page is returned covers the
full ~28k rows in about 6 requests instead of one unreliable one.

Also checks the "mul" (multilingual) label language tag, not just "en". Wikidata
has been migrating labels that are identical across languages (common for modern
game titles, which are often just the English name everywhere) onto a single "mul"
tag instead of duplicating it per-language - filtering only "en" silently drops
any title that's been migrated this way.
"""
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

WIKIDATA_SPARQL = "https://query.wikidata.org/sparql"
OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "games.json")
USER_AGENT = "EAGPB-game/1.0 (https://github.com/jakeevancohen-max/Explain-a-Game-Plot-Poorly)"
PAGE_SIZE = 5000

QUERY_TEMPLATE = """
SELECT ?itemLabel WHERE {{
  ?item wdt:P31 wd:Q7889 .
  ?item wikibase:sitelinks ?sitelinks .
  ?item rdfs:label ?itemLabel .
  FILTER(?sitelinks >= 2)
  FILTER(lang(?itemLabel) = "en" || lang(?itemLabel) = "mul")
}}
ORDER BY ?item
LIMIT {limit}
OFFSET {offset}
"""


def fetch_page(offset, retries=6):
    query = QUERY_TEMPLATE.format(limit=PAGE_SIZE, offset=offset)
    params = urllib.parse.urlencode({"query": query, "format": "json"})
    req = urllib.request.Request(
        f"{WIKIDATA_SPARQL}?{params}",
        headers={"Accept": "application/sparql-results+json", "User-Agent": USER_AGENT},
    )
    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=90) as resp:
                return json.load(resp)
        except (urllib.error.URLError, TimeoutError) as exc:
            if attempt == retries:
                raise
            # A real weekly run hit a sustained stretch of 502/504/429s that
            # outlasted the previous 4-try/max-15s budget (confirmed via the
            # GitHub Actions run's own failure log) - longer backoff gives a
            # transient bad patch more room to pass before giving up. Even at
            # 6 tries this can still fail outright; the weekly workflow treats
            # that as non-fatal (continue-on-error) rather than blocking the
            # actually-important Reddit scrape on Wikidata's mood that day.
            wait = 10 * attempt
            print(f"Wikidata request failed ({exc}), retrying in {wait}s...")
            time.sleep(wait)


def fetch_all():
    titles = set()
    offset = 0
    page = 1
    while True:
        data = fetch_page(offset)
        rows = data["results"]["bindings"]
        print(f"  Page {page} (offset {offset}): {len(rows)} rows")
        if not rows:
            break
        for row in rows:
            label = row["itemLabel"]["value"].strip()
            if not label:
                continue
            # Rows with no matching-language label fall back to the raw QID
            # (e.g. "Q12345") - skip those.
            if label.startswith("Q") and label[1:].isdigit():
                continue
            titles.add(label)
        if len(rows) < PAGE_SIZE:
            break  # short page = last page
        offset += PAGE_SIZE
        page += 1
        time.sleep(1)
    return titles


def main():
    titles = fetch_all()
    games = sorted(titles, key=str.casefold)

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(
            {"source": "wikidata", "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "count": len(games), "games": games},
            f,
            ensure_ascii=False,
            indent=2,
        )

    print(f"Wrote {len(games)} game titles to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
