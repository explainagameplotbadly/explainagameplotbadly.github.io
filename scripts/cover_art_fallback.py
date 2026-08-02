"""
Fallback cover art lookup: tries Wikipedia, then Fandom, for a game that
cover_art.py (Wikidata/Steam) couldn't find official art for. Shared by
scrape_reddit.py (per new question, live) and backfill_fallback_cover_art.py
(batch, over a title list).

LICENSING: unlike cover_art.py's sources, both of these are reuse-risky -
wikipedia_lookup returns non-free fair-use images, fandom_lookup returns
fan-uploaded images with no license info at all (see each module's own
docstring). A hit here is only ever a *candidate* for human review, never
ready-to-publish art - callers must queue it (e.g. as cover_art_pending),
not store it as a live cover_art_url.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
import wikipedia_lookup  # noqa: E402
import fandom_lookup  # noqa: E402


def find_fallback_cover_art(title):
    """Return (source, cover_image_url) or (None, None). Review candidate
    only - see module docstring."""
    try:
        _, wiki_url = wikipedia_lookup.find_cover_art(title)
    except Exception:
        wiki_url = None
    if wiki_url:
        return "wikipedia", wiki_url

    try:
        fandom_result = fandom_lookup.find_cover_art(title)
    except Exception:
        fandom_result = None
    if fandom_result:
        return "fandom", fandom_result[2]

    return None, None
