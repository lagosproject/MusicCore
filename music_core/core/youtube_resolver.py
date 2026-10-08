import os
import re
import json
import unicodedata
from pathlib import Path
from typing import Optional, Dict, Any, List
from loguru import logger
from ..config import settings

def normalize_text(text: str) -> str:
    """Lowercases, removes accents and symbols for robust string comparison."""
    if not text:
        return ""
    text = unicodedata.normalize('NFKD', str(text))
    text = "".join([c for c in text if not unicodedata.combining(c)])
    return re.sub(r'[^a-zA-Z0-9]', '', text.lower())

def clean_track_query(track_name: str) -> str:
    """Removes extra noise from track title like (Remastered...), [Official Video], etc."""
    if not track_name:
        return ""
    cleaned = re.sub(r'\(.*?(?:remaster|deluxe|version|audio|feat|ft\.).*?\)', '', track_name, flags=re.IGNORECASE)
    cleaned = re.sub(r'\[.*?(?:remaster|deluxe|version|audio|feat|ft\.).*?\]', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    return cleaned or track_name

class YouTubeTrackResolver:
    """
    Intelligent YouTube audio and video resolver with 3-tier cascaded search:
    1. Prioritizes official record label '- Topic' channels (YouTube Music catalog).
    2. Searches for 'official audio' / studio audio.
    3. Filters out interviews, TV broadcasts, live chatter, and react videos.
    4. Analyzes playback heatmaps to extract high-retention chorus/hook timestamps.
    5. Caches matches persistently on disk.
    """
    _memory_cache: Dict[str, Optional[Dict[str, Any]]] = {}
    _cache_loaded: bool = False

    @classmethod
    def _ensure_cache_loaded(cls):
        if cls._cache_loaded:
            return
        cls._cache_loaded = True
        cache_file = Path(settings.youtube_cache_path)
        if cache_file.exists():
            try:
                with open(cache_file, "r", encoding="utf-8") as f:
                    cls._memory_cache = json.load(f)
            except Exception as e:
                logger.warning(f"Could not load YouTube cache: {e}")
                cls._memory_cache = {}

    @classmethod
    def _save_cache(cls):
        try:
            cache_file = Path(settings.youtube_cache_path)
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(cls._memory_cache, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"Could not save YouTube cache: {e}")

    @classmethod
    def _get_ydl_opts(cls, cookies_file: Optional[str] = None) -> dict:
        opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
            'skip_download': True,
            'socket_timeout': 15,
            'nocheckcertificate': True,
            'format': 'bestaudio/best',
            'extractor_args': {
                'youtube': {
                    'player_client': ['web', 'mweb', 'tv'],
                }
            },
        }
        if cookies_file and os.path.exists(cookies_file):
            opts['cookiefile'] = cookies_file
        return opts

    @classmethod
    def select_fragment_times(
        cls,
        heatmap: Optional[List[Dict[str, Any]]],
        total_duration: float,
        n_fragments: int = 3,
        fragment_duration: float = 30.0,
        min_distance: float = 45.0,
    ) -> List[float]:
        """
        Chooses start times for audio segments using heatmap replay data
        or fallback uniform spacing (10% to 80%).
        """
        max_start = max(0.0, total_duration - fragment_duration)
        if max_start <= 0:
            return [0.0]

        if heatmap:
            candidates = sorted(heatmap, key=lambda x: x.get('value', 0), reverse=True)
            selected: List[float] = []
            for segment in candidates:
                t = float(segment.get('start_time', 0))
                t = max(0.0, min(t, max_start))
                if not any(abs(t - prev) < min_distance for prev in selected):
                    selected.append(t)
                if len(selected) == n_fragments:
                    break
            if selected:
                return sorted(selected)

        # Fallback: uniform spacing
        zone_start = total_duration * 0.10
        zone_end = max(total_duration * 0.80, zone_start)
        if n_fragments == 1:
            return [zone_start + (zone_end - zone_start) / 2]

        step = (zone_end - zone_start) / (n_fragments - 1) if n_fragments > 1 else 0
        times = [zone_start + i * step for i in range(n_fragments)]
        return [round(t, 2) for t in times]

    @classmethod
    def resolve_track(
        cls,
        track_name: str,
        artist_name: Optional[str] = None,
        cookies_file: Optional[str] = None,
        force_refresh: bool = False
    ) -> Optional[Dict[str, Any]]:
        """
        Finds the official YouTube track using multi-strategy search.
        Returns a dictionary with video metadata or None.
        """
        if not track_name:
            return None

        cls._ensure_cache_loaded()
        cache_key = f"{artist_name.lower().strip() if artist_name else ''} - {track_name.lower().strip()}"
        if cache_key in cls._memory_cache and not force_refresh:
            return cls._memory_cache[cache_key]

        try:
            import yt_dlp
        except ImportError:
            logger.warning("yt-dlp is not installed. YouTube track resolution is unavailable.")
            return None

        query = clean_track_query(track_name)
        strategies = [
            (f'ytsearch5:{query} - Topic', 'Topic channel'),
            (f'ytsearch5:{query} official audio', 'Official audio'),
            (f'ytsearch5:{query}', 'Plain search'),
        ]

        if artist_name:
            strategies.extend([
                (f'ytsearch5:{query} {artist_name} - Topic', 'Topic channel (with artist)'),
                (f'ytsearch5:{query} {artist_name} official audio', 'Official audio (with artist)'),
                (f'ytsearch5:{query} {artist_name}', 'Plain search (with artist)'),
            ])

        blacklist = [' tv', 'news', 'interview', 'entrevista', 'show', 'trailer', 'reaction', 'react']
        artist_norm = normalize_text(artist_name) if artist_name else ""
        track_norm = normalize_text(track_name)

        ydl_opts = cls._get_ydl_opts(cookies_file)

        matched_entry: Optional[Dict[str, Any]] = None

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                for search_query, strategy_name in strategies:
                    try:
                        info = ydl.extract_info(search_query, download=False)
                        entries = info.get('entries', []) if info else []
                        if not entries:
                            continue

                        for entry in entries:
                            if not entry:
                                continue
                            uploader = (entry.get('uploader') or "").lower()
                            channel = (entry.get('channel') or "").lower()
                            title = (entry.get('title') or "").lower()

                            uploader_norm = normalize_text(uploader)
                            channel_norm = normalize_text(channel)
                            title_norm = normalize_text(title)

                            is_topic = channel.strip().endswith('- topic') or uploader.strip().endswith('- topic')

                            # 1. Topic channel match
                            if is_topic and (not artist_name or artist_name.lower() in channel or artist_norm in channel_norm):
                                matched_entry = entry
                                break

                            # 2. Blacklist check
                            if any(word in uploader for word in blacklist):
                                if artist_name and artist_name.lower() not in uploader and artist_norm not in uploader_norm:
                                    continue

                            # 3. Text match
                            if not artist_name or (
                                artist_name.lower() in uploader or
                                artist_name.lower() in title or
                                artist_norm in uploader_norm or
                                artist_norm in title_norm
                            ):
                                matched_entry = entry
                                break

                        if matched_entry:
                            break

                    except Exception as e:
                        logger.debug(f"Search strategy '{strategy_name}' failed: {e}")
                        continue

        except Exception as e:
            logger.warning(f"Error resolving YouTube track for '{artist_name} - {track_name}': {e}")
            matched_entry = None

        if matched_entry:
            video_id = matched_entry.get('id')
            url = matched_entry.get('webpage_url') or f"https://www.youtube.com/watch?v={video_id}"
            channel_name = matched_entry.get('channel') or matched_entry.get('uploader') or ""
            is_topic = channel_name.strip().lower().endswith('- topic')
            duration = float(matched_entry.get('duration') or 0.0)
            heatmap = matched_entry.get('heatmap') or []

            result = {
                'id': video_id,
                'url': url,
                'title': matched_entry.get('title'),
                'channel': channel_name,
                'uploader': matched_entry.get('uploader'),
                'duration': duration,
                'is_topic': is_topic,
                'thumbnails': [t.get('url') for t in matched_entry.get('thumbnails', []) if t.get('url')][:3],
                'highlights': cls.select_fragment_times(heatmap, duration) if duration > 0 else [0.0]
            }
            cls._memory_cache[cache_key] = result
            cls._save_cache()
            return result

        cls._memory_cache[cache_key] = None
        cls._save_cache()
        return None
