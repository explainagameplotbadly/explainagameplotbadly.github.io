"""
Cover art fallback source: Steam's public store search + CDN. No API key
required - store search and the CDN image URLs are both open/anonymous, and
these are the publisher/storefront's own official assets (legitimate for
reuse, unlike scraping arbitrary web images of unclear license).

Only covers games available on Steam (mostly PC/indie titles) - console
exclusives still have no source and correctly return None.
"""
import json
import re
import urllib.parse
import urllib.request

SEARCH_API = "https://store.steampowered.com/api/storesearch"
CDN_TEMPLATE = "https://cdn.akamai.steamstatic.com/steam/apps/{app_id}/library_600x900.jpg"
USER_AGENT = "EAGPB-game/1.0 (https://github.com/jakeevancohen-max/Explain-a-Game-Plot-Poorly)"

# Steam store search returns DLC, soundtracks, artbooks, demos etc. alongside
# the base game - these name patterns flag results to skip.
NON_BASE_GAME_RE = re.compile(
    r"\b(soundtrack|ost|artbook|art book|demo|dlc|expansion|season pass|"
    r"dedicated server|bonus content|digital deluxe|upgrade)\b",
    re.IGNORECASE,
)


def _normalize(title):
    return re.sub(r"[^a-z0-9]+", "", title.lower())


def find_cover_art(title):
    """Return a Steam library cover image URL for `title`, or None."""
    params = urllib.parse.urlencode({"term": title, "cc": "us", "l": "en"})
    req = urllib.request.Request(
        f"{SEARCH_API}?{params}", headers={"User-Agent": USER_AGENT}
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.load(resp)
    except Exception:
        return None

    target = _normalize(title)
    for item in data.get("items", []):
        if item.get("type") != "app":
            continue
        name = item.get("name", "")
        if NON_BASE_GAME_RE.search(name):
            continue
        if _normalize(name) != target:
            continue
        return CDN_TEMPLATE.format(app_id=item["id"])

    return None
