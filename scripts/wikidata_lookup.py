"""
Shared helper: given a game title, try to find its Wikidata item and cover art.
No API key required (Wikidata's action API is open/anonymous).
"""
import json
import urllib.parse
import urllib.request

API = "https://www.wikidata.org/w/api.php"
USER_AGENT = "EAGPB-game/1.0 (https://github.com/jakeevancohen-max/Explain-a-Game-Plot-Poorly)"
VIDEO_GAME_QID = "Q7889"


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

        # Prefer P2716 (dedicated "box art image" property) over the generic P18 (image).
        image_claims = claims.get("P2716") or claims.get("P18")
        if not image_claims:
            return label, None

        try:
            filename = image_claims[0]["mainsnak"]["datavalue"]["value"]
        except (KeyError, IndexError):
            return label, None

        cover_url = "https://commons.wikimedia.org/wiki/Special:FilePath/" + urllib.parse.quote(filename)
        return label, cover_url

    return title, None
