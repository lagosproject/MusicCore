import os
import json
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Optional, Dict
from loguru import logger
from ..config import settings

class AudioPreviewResolver:
    """
    Resolves 30-second audio preview MP3 URLs when Spotify returns preview_url: None.
    Uses Deezer's public search API as a high-reliability, zero-auth fallback.
    Results are cached on disk and in memory.
    """
    _memory_cache: Dict[str, Optional[str]] = {}
    _cache_loaded: bool = False

    @classmethod
    def _ensure_cache_loaded(cls):
        if cls._cache_loaded:
            return
        cls._cache_loaded = True
        cache_file = Path(settings.previews_cache_path)
        if cache_file.exists():
            try:
                with open(cache_file, "r", encoding="utf-8") as f:
                    cls._memory_cache = json.load(f)
            except Exception as e:
                logger.warning(f"Could not load previews cache: {e}")
                cls._memory_cache = {}

    @classmethod
    def _save_cache(cls):
        try:
            cache_file = Path(settings.previews_cache_path)
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(cls._memory_cache, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"Could not save previews cache: {e}")

    @classmethod
    def resolve_preview(cls, artist_name: str, track_name: str) -> Optional[str]:
        """
        Looks up a 30s preview mp3 URL for a given artist and track name.
        Returns a direct audio stream URL or None.
        """
        if not track_name:
            return None

        cls._ensure_cache_loaded()
        cache_key = f"{artist_name.lower().strip()} - {track_name.lower().strip()}"
        if cache_key in cls._memory_cache:
            return cls._memory_cache[cache_key]

        # Clean track name (remove parentheses, feats, etc. for cleaner search)
        import re
        clean_track = re.sub(r'\(.*?\)', '', track_name).strip()
        clean_track = re.sub(r'\[.*?\]', '', clean_track).strip()
        query = f"{artist_name} {clean_track}".strip()

        preview_url = None
        try:
            encoded_query = urllib.parse.quote(query)
            api_url = f"https://api.deezer.com/search?q={encoded_query}&limit=1"
            req = urllib.request.Request(
                api_url,
                headers={"User-Agent": "MusicCore/0.1.0"}
            )
            with urllib.request.urlopen(req, timeout=4) as response:
                if response.status == 200:
                    payload = json.loads(response.read().decode("utf-8"))
                    items = payload.get("data", [])
                    if items and items[0].get("preview"):
                        preview_url = items[0]["preview"]
        except Exception as e:
            logger.debug(f"Failed to fetch Deezer preview for '{query}': {e}")

        # Store in cache (even if None to avoid repeated failed lookups)
        cls._memory_cache[cache_key] = preview_url
        cls._save_cache()
        return preview_url
