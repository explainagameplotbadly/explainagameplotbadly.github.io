"""
Shared helper: given a game title, try to find its Wikidata item and cover art.
No API key required (Wikidata's action API is open/anonymous).
"""
import json
import re
import urllib.parse
import urllib.request

API = "https://www.wikidata.org/w/api.php"
USER_AGENT = "EAGPB-game/1.0 (https://github.com/jakeevancohen-max/Explain-a-Game-Plot-Poorly)"
VIDEO_GAME_QID = "Q7889"

# Keywords that show up in Commons filenames for convention photos, screenshots,
# and other non-cover-art images used as a game's generic P18 "image" - not an
# exhaustive list, just the patterns seen often enough to be worth filtering.
NON_COVER_ART_KEYWORDS_RE = re.compile(
    r"\b(e3|pax|gdc|gamescom|comic.?con|expo|convention|conference|press|"
    r"screenshot|gameplay|trailer|logo|wordmark|developer|interview|panel|booth|"
    r"launch\s?party|preview\s?event)\b",
    re.IGNORECASE,
)


def _looks_like_non_cover_art(filename):
    return bool(NON_COVER_ART_KEYWORDS_RE.search(filename))


def _get(params):
    url = f"{API}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def search_candidates(title, limit=5):
    data = _get({
        "action": "wbsearchentities",
        "search": title,
        "language": "en",
        "type": "item",
        "limit": str(limit),
        "format": "json",
    })
    return data.get("search", [])


def get_entity(qid):
    data = _get({
        "action": "wbgetentities",
        "ids": qid,
        "props": "claims|labels",
        "languages": "en",
        "format": "json",
    })
    return data["entities"][qid]


def find_cover_art(title):
    """Return (canonical_label, cover_image_url_or_None) for a game title.

    Only accepts Wikidata items directly tagged instance-of "video game" (Q7889),
    to avoid attaching the wrong cover art to an unrelated same-named item.
    """
    try:
        candidates = search_candidates(title)
    except Exception:
        return title, None

    for candidate in candidates:
        qid = candidate["id"]
        try:
            entity = get_entity(qid)
        except Exception:
            continue

        claims = entity.get("claims", {})
        instance_of = [
            c["mainsnak"]["datavalue"]["value"]["id"]
            for c in claims.get("P31", [])
            if "datavalue" in c.get("mainsnak", {})
        ]
        if VIDEO_GAME_QID not in instance_of:
            continue

        label = entity.get("labels", {}).get("en", {}).get("value", title)

        # P2716 is the dedicated "box art image" property, but it's essentially
        # unused for video games on Wikidata (confirmed empty for common titles
        # incl. Portal 2, Celeste, Halo Infinite) - relying on it alone would
        # disable cover art almost entirely. So P18 (generic "image") is still
        # used as a fallback, but Wikipedia editors often set that to whatever
        # representative photo they had (a convention booth shot, a screenshot,
        # a press photo...) rather than actual cover art - confirmed in testing,
        # e.g. an "E3 2011" press photo got shown as Saints Row: The Third's
        # "cover art". Filenames for those non-cover-art photos reliably contain
        # a recognizable keyword (the event name, "screenshot", etc.), so those
        # are filtered out - imperfect, but better than showing a wrong image.
        image_claims = claims.get("P2716") or claims.get("P18")
        if not image_claims:
            return label, None

        try:
            filename = image_claims[0]["mainsnak"]["datavalue"]["value"]
        except (KeyError, IndexError):
            return label, None

        if _looks_like_non_cover_art(filename):
            return label, None

        cover_url = "https://commons.wikimedia.org/wiki/Special:FilePath/" + urllib.parse.quote(filename)
        return label, cover_url

    return title, None
