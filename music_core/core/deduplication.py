import re
from typing import Dict, Any, Tuple, Optional

def clean_track_title(title: str) -> str:
    """
    Cleans track title to detect duplicates across album versions,
    remasters, radio edits, and live recordings.
    """
    if not title:
        return ""
    t = title.lower().strip()
    # Remove content inside brackets/parentheses for common version patterns
    t = re.sub(
        r'[\(\[](remastered?|live|deluxe|radio edit|mono|version|acoustic|instrumental|edit|original mix|extended mix|from [^\]\)]+).*?[\)\]]',
        '',
        t,
        flags=re.IGNORECASE
    )
    # Remove trailing hyphenated suffixes
    suffixes = [
        '- remastered', '- remaster', '- live', '- radio edit',
        '- deluxe', '- mono', '- version', '- edit'
    ]
    for s in suffixes:
        if s in t:
            t = t.split(s)[0]
    # Clean whitespace and trailing punctuation
    t = re.sub(r'\s+', ' ', t).strip(' -_')
    return t or title.lower().strip()

def get_track_fingerprint(track: Dict[str, Any]) -> Tuple[str, tuple]:
    """
    Returns a fingerprint (cleaned_title, sorted_artist_ids) for track deduplication.
    """
    cleaned_name = clean_track_title(track.get("name", ""))
    artists = tuple(sorted(track.get("artists", [])))
    return (cleaned_name, artists)

def choose_best_track_version(track_a: Dict[str, Any], track_b: Dict[str, Any]) -> Dict[str, Any]:
    """
    Given two duplicate tracks, selects the best version
    (prioritizes having an audio preview and a high-res thumbnail).
    """
    # 1. Preview availability
    if track_a.get("preview") and not track_b.get("preview"):
        return track_a
    if track_b.get("preview") and not track_a.get("preview"):
        return track_b
    # 2. Thumbnail availability
    if track_a.get("thumbnail") and not track_b.get("thumbnail"):
        return track_a
    if track_b.get("thumbnail") and not track_a.get("thumbnail"):
        return track_b
    # 3. Prefer cleaner/shorter title (standard edition vs long bonus track title)
    if len(track_a.get("name", "")) <= len(track_b.get("name", "")):
        return track_a
    return track_b
