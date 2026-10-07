from typing import Any, Dict, Optional

def extract_track(item: Any) -> Optional[Dict[str, Any]]:
    """
    Returns the track/episode dict from a playlist or saved-tracks item.
    Spotify items wrap the track under 'item' or 'track'. Bare dict accepted too.
    """
    if not isinstance(item, dict):
        return None
    for key in ("track", "item"):
        wrapped = item.get(key)
        if isinstance(wrapped, dict):
            return wrapped
    if item.get("uri") or item.get("name"):
        return item
    return None
