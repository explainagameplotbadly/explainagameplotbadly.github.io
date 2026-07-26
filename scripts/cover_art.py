"""
Combines cover art sources: Wikidata first (broadest game coverage, though
sparse for images specifically), falling back to Steam's public store/CDN
(no key needed, official first-party art, but only for games sold on Steam)
when Wikidata has no image. The canonical display name always comes from
Wikidata (or the original title if no Wikidata match at all) - Steam is only
ever used for the image itself.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))
import wikidata_lookup  # noqa: E402
import steam_lookup  # noqa: E402


def find_cover_art(title):
    """Return (canonical_label, cover_image_url_or_None) for a game title."""
    label, cover_url = wikidata_lookup.find_cover_art(title)
    if cover_url:
        return label, cover_url

    steam_url = steam_lookup.find_cover_art(label)
    if steam_url:
        return label, steam_url

    return label, None
