"""
Cover art fallback source: guesses a game's Fandom wiki subdomain from its
title (e.g. "Golden Axe" -> goldenaxe.fandom.com) and reads that wiki's own
MediaWiki API for a page image. www.fandom.com's own cross-wiki search API
sits behind a Cloudflare bot challenge and can't be queried directly, but
individual wiki subdomains expose the same plain MediaWiki API Wikipedia
uses, unprotected.

Purely best-effort: the slug guess often doesn't exist (DNS/HTTP failure,
just skip) or resolves to the wrong wiki entirely. Every hit here is meant
for human review, not automatic use - Fandom-hosted box art is fan-uploaded,
usually without any license info attached, so provenance and reuse rights
are unknown per-image rather than governed by one blanket rule.
"""
import json
import re
import urllib.error
import urllib.parse
import urllib.request

USER_AGENT = "EAGPB-game/1.0 (https://github.com/jakeevancohen-max/Explain-a-Game-Plot-Poorly)"

NON_COVER_ART_KEYWORDS_RE = re.compile(
    r"\b(e3|pax|gdc|gamescom|comic.?con|expo|convention|conference|press|"
    r"screenshot|gameplay|trailer|logo|wordmark|developer|interview|panel|booth|"
    r"wiki.?wordmark|site.?logo|favicon|concept.?art|fan.?art|story.?mode|"
    r"character|portrait)\b",
    re.IGNORECASE,
)


def _looks_like_non_cover_art(filename):
    # See wikidata_lookup._looks_like_non_cover_art - underscore-joined wiki
    # filenames need normalizing before \b keyword matching works.
    return bool(NON_COVER_ART_KEYWORDS_RE.search(filename.replace("_", " ")))


def _slugify(title):
    return re.sub(r"[^a-z0-9]", "", title.lower())


def _get(wiki_slug, params, timeout=15):
    url = f"https://{wiki_slug}.fandom.com/api.php?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp)


def find_cover_art(title):
    """Return (wiki_slug, page_title, image_url) or None.

    image_url may be non-None with no license information at all - treat
    every result as a candidate for manual review, not a ready-to-use asset.
    """
    slug = _slugify(title)
    if not slug:
        return None

    try:
        search_data = _get(slug, {
            "action": "query",
            "list": "search",
            "srsearch": title,
            "srlimit": 3,
            "format": "json",
        })
    except (urllib.error.URLError, TimeoutError, OSError):
        return None
    except Exception:
        return None

    results = search_data.get("query", {}).get("search", [])
    if not results:
        return None

    # Only accept a result whose title is the query (optionally with a
    # trailing qualifier like "(NES)" or "(video game)") - not merely
    # overlapping. Rejects near-miss pages like "Skullgirl" (a character)
    # turning up for a "Skullgirls" search.
    target = _slugify(title)
    page_title = None
    for result in results:
        candidate_slug = _slugify(result["title"])
        # Exclude the wiki's own "<Title> Wiki" landing page - its page
        # image is usually a wordmark or a random featured-content image,
        # not the game's cover art.
        if candidate_slug.endswith("wiki") and not target.endswith("wiki"):
            continue
        if candidate_slug == target or candidate_slug.startswith(target):
            page_title = result["title"]
            break
    if page_title is None:
        return None

    try:
        image_data = _get(slug, {
            "action": "query",
            "titles": page_title,
            "prop": "pageimages",
            "piprop": "original",
            "format": "json",
        })
    except Exception:
        return None

    pages = image_data.get("query", {}).get("pages", {})
    for page in pages.values():
        original = page.get("original")
        if original and original.get("source"):
            image_url = original["source"]
            if _looks_like_non_cover_art(image_url):
                return None
            return slug, page_title, image_url

    return None
