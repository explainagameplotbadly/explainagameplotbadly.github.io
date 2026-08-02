"""
Cover art source: the lead/infobox image of the English Wikipedia article
for a game, found via the game's already-confirmed Wikidata item (so we
reuse wikidata_lookup's instance-of-Q7889 check instead of re-disambiguating
by title).

IMPORTANT LICENSING CAVEAT: box art on Wikipedia is almost always a
"non-free" fair-use file hosted locally under en.wikipedia.org (not on
Commons), which is *why* Wikidata's P18 and MediaWiki's own pageimages API
both come up empty for it - both deliberately exclude non-free content,
since Wikipedia's fair-use rationale for these images is scoped to that one
article and doesn't extend to reuse elsewhere. This module bypasses that by
reading the REST summary endpoint directly, which does surface non-free
images. Anything this returns should be flagged to a human as
possibly-non-free before it's reused in another product, same as the
Fandom fallback.
"""
import re
import urllib.parse
import urllib.request

import wikidata_lookup

REST_SUMMARY = "https://en.wikipedia.org/api/rest_v1/page/summary/"
USER_AGENT = wikidata_lookup.USER_AGENT

NON_COVER_ART_KEYWORDS_RE = wikidata_lookup.NON_COVER_ART_KEYWORDS_RE


def _enwiki_sitelink(qid):
    data = wikidata_lookup._get({
        "action": "wbgetentities",
        "ids": qid,
        "props": "sitelinks",
        "format": "json",
    })
    sitelinks = data["entities"][qid].get("sitelinks", {})
    enwiki = sitelinks.get("enwiki")
    return enwiki["title"] if enwiki else None


def _page_image(title):
    url = REST_SUMMARY + urllib.parse.quote(title.replace(" ", "_"), safe="")
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    import json
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.load(resp)
    for key in ("originalimage", "thumbnail"):
        image = data.get(key)
        if image and image.get("source"):
            return image["source"]
    return None


def find_cover_art(title):
    """Return (canonical_label, cover_image_url_or_None) for a game title.

    Only follows Wikidata items already confirmed instance-of "video game"
    (Q7889), same restriction as wikidata_lookup, to avoid grabbing an image
    for an unrelated same-named article.
    """
    try:
        candidates = wikidata_lookup.search_candidates(title)
    except Exception:
        return title, None

    for candidate in candidates:
        qid = candidate["id"]
        try:
            entity = wikidata_lookup.get_entity(qid)
        except Exception:
            continue

        claims = entity.get("claims", {})
        instance_of = [
            c["mainsnak"]["datavalue"]["value"]["id"]
            for c in claims.get("P31", [])
            if "datavalue" in c.get("mainsnak", {})
        ]
        if wikidata_lookup.VIDEO_GAME_QID not in instance_of:
            continue

        label = entity.get("labels", {}).get("en", {}).get("value", title)

        try:
            enwiki_title = _enwiki_sitelink(qid)
        except Exception:
            return label, None
        if not enwiki_title:
            return label, None

        try:
            image_url = _page_image(enwiki_title)
        except Exception:
            return label, None

        if image_url and wikidata_lookup._looks_like_non_cover_art(image_url):
            return label, None

        return label, image_url

    return title, None
