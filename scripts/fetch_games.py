"""
Fetches a broad list of video game titles from Wikidata for the search-bar
autocomplete. No API key required. Run manually or via the weekly GitHub Action.

Source: Wikidata SPARQL endpoint, items that are instance-of "video game" (Q7889),
sorted by sitelink count (a rough notability signal) so obscure/duplicate/test
items don't dominate the list.
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
MAX_GAMES = 15000

QUERY = f"""
SELECT ?itemLabel ?sitelinks WHERE {{
  ?item wdt:P31 wd:Q7889 .
  ?item wikibase:sitelinks ?sitelinks .
  FILTER(?sitelinks > 0)
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
}}
ORDER BY DESC(?sitelinks)
LIMIT {MAX_GAMES}
"""


def fetch(retries=3):
    params = urllib.parse.urlencode({"query": QUERY, "format": "json"})
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
