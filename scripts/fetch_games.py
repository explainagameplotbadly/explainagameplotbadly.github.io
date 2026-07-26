"""
Fetches a broad list of video game titles from Wikidata for the search-bar
autocomplete. No API key required. Run manually or via the weekly GitHub Action.

Source: Wikidata SPARQL endpoint, items that are instance-of "video game" (Q7889)
with at least 2 sitelinks (a low notability bar that filters out stubs/test items).

NOTE: deliberately no ORDER BY / LIMIT. Wikidata's query service doesn't reliably
compute a true top-N sort over a virtual/computed property like wikibase:sitelinks
across tens of thousands of rows - in testing, an `ORDER BY DESC(?sitelinks) LIMIT
15000` query silently produced an incomplete, near-arbitrarily-truncated result set
(missing well-known games like "Halo Infinite" despite it easily qualifying), rather
than erroring. Since the un-truncated result set at this notability bar is a
manageable ~28k rows, it's simpler and more correct to just fetch all of it.

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

QUERY = """
SELECT ?itemLabel WHERE {
  ?item wdt:P31 wd:Q7889 .
  ?item wikibase:sitelinks ?sitelinks .
  ?item rdfs:label ?itemLabel .
  FILTER(?sitelinks >= 2)
  FILTER(lang(?itemLabel) = "en" || lang(?itemLabel) = "mul")
}
"""


def fetch(retries=3):
    params = urllib.parse.urlencode({"query": QUERY, "format": "json"})
    req = urllib.request.Request(
        f"{WIKIDATA_SPARQL}?{params}",
        headers={"Accept": "application/sparql-results+json", "User-Agent": USER_AGENT},
    )
    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=150) as resp:
                return json.load(resp)
        except (urllib.error.URLError, TimeoutError) as exc:
            if attempt == retries:
                raise
            wait = 5 * attempt
            print(f"Wikidata request failed ({exc}), retrying in {wait}s...")
            time.sleep(wait)


def main():
    data = fetch()
    titles = set()
    for row in data["results"]["bindings"]:
        label = row["itemLabel"]["value"].strip()
        if not label:
            continue
        # Rows with no English label fall back to the raw QID (e.g. "Q12345") - skip those.
        if label.startswith("Q") and label[1:].isdigit():
            continue
        titles.add(label)

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
