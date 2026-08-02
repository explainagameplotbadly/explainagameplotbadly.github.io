"""
Cover art source: Metacritic's schema.org/VideoGame structured data
(JSON-LD embedded in every game page), read via a guessed URL slug -
Metacritic has no public search API, so this constructs
metacritic.com/game/<slug>/ directly from the title and treats a 404 as
"no match" rather than searching, the same approach fandom_lookup.py uses
for wiki subdomains. Verified with a plain unauthenticated request: despite
Cloudflare's challenge script being present in the page, a bare GET gets
the real rendered page, not a bot challenge.

Used as a third source alongside Wikidata/Steam (cover_art.py) rather than
a review-queued fallback like Wikipedia/Fandom - Metacritic aggregates
official publisher-submitted artwork, not fan uploads.

CAVEAT: the "image" field is a 16:9 promotional crop, not the portrait box
art Wikidata/Steam/Wikipedia usually provide (the site's cover art element
has no fixed aspect ratio, so this will render shorter/wider than other
sources). Metacritic's image CDN rejects any crop size other than the one
already encoded in the URL - swapping the height/width query params 403s -
so there's no way to request a portrait crop of the same asset.
"""
import json
import re
import urllib.error
import urllib.request

USER_AGENT = "EAGPB-game/1.0 (https://github.com/jakeevancohen-max/Explain-a-Game-Plot-Poorly)"
LD_JSON_RE = re.compile(r'<script type="application/ld\+json"[^>]*>(.*?)</script>', re.DOTALL)


def _slugify(title):
    slug = title.lower()
    slug = re.sub(r"['’:]", "", slug)
    slug = re.sub(r"[^a-z0-9]+", "-", slug).strip("-")
    return slug


def find_cover_art(title):
    """Return a Metacritic cover image URL for `title`, or None."""
    slug = _slugify(title)
    if not slug:
        return None

    req = urllib.request.Request(
        f"https://www.metacritic.com/game/{slug}/", headers={"User-Agent": USER_AGENT}
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, TimeoutError, OSError):
        return None

    match = LD_JSON_RE.search(body)
    if not match:
        return None
    try:
        data = json.loads(match.group(1))
    except json.JSONDecodeError:
        return None

    if data.get("@type") != "VideoGame":
        return None
    # Guard against a near-miss slug landing on an unrelated page (e.g. a
    # fuzzy redirect) instead of a hard 404.
    if _slugify(data.get("name", "")) != slug:
        return None

    return data.get("image") or None
