"""
Supplements the Wikidata game list (data/games.json) with SteamSpy's tracked-
games catalog - free, keyless, no signup. Run after fetch_games.py; merges into
whatever's already in games.json rather than overwriting it.

Covers PC/indie titles that may have no Wikidata entry at all, which matters
since games.json is used for both autocomplete AND answer-matching in
scrape_reddit.py - a title missing from it can never be resolved as an answer,
regardless of how clearly a Reddit thread confirms it.

This is unrelated to scripts/steam_lookup.py, which queries Steam's own store
search per-answer for cover art - this script instead bulk-fetches SteamSpy's
tracked-game list once, to widen the base title pool itself.
"""
import json
import os
import re
import time
import urllib.error
import urllib.request

STEAMSPY_API = "https://steamspy.com/api.php"
USER_AGENT = "EAGPB-game/1.0 (https://github.com/jakeevancohen-max/Explain-a-Game-Plot-Poorly)"
DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
GAMES_PATH = os.path.join(DATA_DIR, "games.json")
MAX_PAGES = 100  # safety cap - SteamSpy's page list stops well before this

# Matches up to 2 filler words followed by a word ending in a possessive
# apostrophe (e.g. "Marvel's ", "Sid Meier's ", "Tom Clancy's ").
POSSESSIVE_PREFIX_RE = re.compile(r"^(?:\S+\s+){0,2}\S*'s\s+")


def _dedup_key(title):
    return POSSESSIVE_PREFIX_RE.sub("", title.strip().replace("’", "'"), count=1).lower()


def _prefer(a, b):
    """Pick which of two near-duplicate titles to keep as canonical: the
    shorter one, or - since _dedup_key() lowercases and so also collapses
    pure-casing duplicates like Wikidata's "Final Fantasy" vs SteamSpy's
    stylized "FINAL FANTASY" - on a length tie, whichever isn't ALL CAPS.
    Without this tie-break the winner is arbitrary (Python set iteration
    order), so a previously-normal-cased answer could silently start
    displaying in all caps after a re-scrape."""
    if len(a) != len(b):
        return a if len(a) < len(b) else b
    if a.isupper() and not b.isupper():
        return b
    if b.isupper() and not a.isupper():
        return a
    return a


def dedup_near_duplicates(games):
    """Collapse possessive-brand-prefix variants of the same game (e.g.
    "Marvel's Spider-Man: Miles Morales" from SteamSpy's Steam-store naming
    vs Wikidata's "Spider-Man: Miles Morales") into one canonical entry.

    Keeping both strings for the same real game breaks subtitle-based answer
    matching in scrape_reddit.py's build_unique_subtitle_index() - a subtitle
    shared by two titles gets treated as a genuine ambiguous collision (like
    "New Horizons" belonging to two unrelated franchises) and excluded, even
    though here it's the same game under two spellings. It also clutters
    autocomplete with near-identical entries. The shorter, unprefixed form is
    kept since real conversation overwhelmingly drops the brand prefix.
    """
    by_key = {}
    for title in games:
        key = _dedup_key(title)
        current = by_key.get(key)
        by_key[key] = title if current is None else _prefer(current, title)
    return set(by_key.values())


def fetch_page(page, retries=4):
    url = f"{STEAMSPY_API}?request=all&page={page}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.load(resp)
        except Exception as exc:
            if attempt == retries:
                print(f"  SteamSpy page {page} failed after {retries} attempts: {exc}")
                return {}
            time.sleep(5 * attempt)


def fetch_all_names():
    names = set()
    for page in range(MAX_PAGES):
        data = fetch_page(page)
        if not data:
            break
        for entry in data.values():
            name = (entry.get("name") or "").strip()
            if name:
                names.add(name)
        print(f"  SteamSpy page {page}: {len(data)} entries (running total {len(names)})", flush=True)
        if len(data) < 1000:
            break  # short page = last page
        time.sleep(1)
    return names


def main():
    if os.path.exists(GAMES_PATH):
        with open(GAMES_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    else:
        data = {}
    existing = set(data.get("games", []))

    steamspy_names = fetch_all_names()
    new_names = steamspy_names - existing
    merged = existing | steamspy_names
    deduped = dedup_near_duplicates(merged)
    removed = len(merged) - len(deduped)

    data["games"] = sorted(deduped, key=str.casefold)
    data["count"] = len(data["games"])
    data["source"] = "wikidata+steamspy"
    data["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    os.makedirs(DATA_DIR, exist_ok=True)
    with open(GAMES_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(
        f"SteamSpy contributed {len(steamspy_names)} names, {len(new_names)} new. "
        f"Deduped {removed} possessive-prefix variants. Total games list: {len(deduped)}"
    )


if __name__ == "__main__":
    main()
