import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional
from .tracks import extract_track

def slim_track(track: Dict[str, Any]) -> Dict[str, Any]:
    """Keeps only the track fields the app uses."""
    slim: Dict[str, Any] = {
        "id": track.get("id"),
        "uri": track.get("uri"),
        "name": track.get("name"),
        "duration_ms": track.get("duration_ms"),
        "artists": [
            {"id": a.get("id"), "name": a.get("name")}
            for a in track.get("artists") or []
            if isinstance(a, dict)
        ],
    }
    if track.get("explicit") is not None:
        slim["explicit"] = bool(track["explicit"])
    album = track.get("album") or {}
    images = album.get("images") or []
    slim_album: Dict[str, Any] = {}
    if album.get("name"):
        slim_album["name"] = album["name"]
    if album.get("release_date"):
        slim_album["release_date"] = album["release_date"]
    if images and isinstance(images[0], dict):
        slim_album["images"] = [{"url": images[0].get("url")}]
    if slim_album:
        slim["album"] = slim_album
    return slim

def slim_item(item: Any) -> Optional[Dict[str, Any]]:
    """Slim version of a playlist/saved item."""
    track = extract_track(item)
    if not track:
        return None
    slim: Dict[str, Any] = {"item": slim_track(track)}
    if isinstance(item, dict) and item.get("added_at"):
        slim["added_at"] = item["added_at"]
    return slim

def slim_items(items: List[Any]) -> List[Dict[str, Any]]:
    slimmed = (slim_item(i) for i in items)
    return [s for s in slimmed if s is not None]

def slim_cache(cache: Dict[str, List[Any]]) -> Dict[str, List[Dict[str, Any]]]:
    return {key: slim_items(items) for key, items in cache.items()}

def atomic_write_json(path: Path, data: Any, compact: bool = False) -> None:
    """Writes JSON through a temporary file, so a crash never leaves a half-written file."""
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    kwargs: Dict[str, Any] = {"ensure_ascii": False}
    if compact:
        kwargs["separators"] = (",", ":")
    else:
        kwargs["indent"] = 4
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, **kwargs)
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()
