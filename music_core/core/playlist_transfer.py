import csv
import json
from pathlib import Path
from typing import List, Dict, Any, Optional, Callable
from loguru import logger
from .youtube_resolver import YouTubeTrackResolver

class PlaylistTransfer:
    """
    Handles playlist transfer and exchange between Spotify and YouTube.
    Resolves each track to its verified YouTube link and exports playlists
    into multiple standard formats (M3U8, JSON, CSV).
    """

    @classmethod
    def resolve_tracks(
        cls,
        tracks: List[Dict[str, Any]],
        on_progress: Optional[Callable[[int, int, Dict[str, Any], Optional[Dict[str, Any]]], None]] = None,
        cookies_file: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Takes a list of track items (with 'name'/'title' and 'artist') and
        resolves each to its corresponding YouTube counterpart.
        """
        resolved: List[Dict[str, Any]] = []
        total = len(tracks)

        for idx, t in enumerate(tracks, start=1):
            title = t.get('name') or t.get('title') or ""
            artist = t.get('artist')
            if not artist and t.get('artists'):
                raw_artists = t.get('artists')
                if isinstance(raw_artists, list) and len(raw_artists) > 0:
                    first = raw_artists[0]
                    artist = first.get('name') if isinstance(first, dict) else str(first)

            yt_match = YouTubeTrackResolver.resolve_track(
                track_name=title,
                artist_name=artist,
                cookies_file=cookies_file
            )

            item = {
                'spotify_id': t.get('id'),
                'spotify_uri': t.get('uri'),
                'title': title,
                'artist': artist,
                'album': t.get('album', {}).get('name') if isinstance(t.get('album'), dict) else t.get('album'),
                'duration_ms': t.get('duration_ms'),
                'youtube': yt_match
            }
            resolved.append(item)

            if on_progress:
                try:
                    on_progress(idx, total, t, yt_match)
                except Exception as e:
                    logger.debug(f"Progress callback error: {e}")

        return resolved

    @classmethod
    def resolve_spotify_playlist(
        cls,
        spotify_client,
        playlist_id: str,
        limit: Optional[int] = None,
        on_progress: Optional[Callable[[int, int, Dict[str, Any], Optional[Dict[str, Any]]], None]] = None,
        cookies_file: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Fetches all tracks from a Spotify playlist using SpotifyClient, then
        resolves each to YouTube.
        """
        raw_items = spotify_client.get_playlist_tracks(playlist_id, limit=limit)
        tracks: List[Dict[str, Any]] = []

        for item in raw_items:
            t = item.get('track') or item
            if not t or not isinstance(t, dict):
                continue
            if t.get('type') == 'episode':
                continue
            tracks.append(t)

        logger.info(f"Resolving {len(tracks)} tracks from Spotify playlist to YouTube...")
        return cls.resolve_tracks(tracks, on_progress=on_progress, cookies_file=cookies_file)

    @classmethod
    def export_m3u(cls, resolved_tracks: List[Dict[str, Any]], output_path: str, playlist_name: str = "Transferred Playlist") -> str:
        """
        Exports resolved tracks into an M3U8 playlist with extended #EXTINF tags.
        Tracks without a valid YouTube match are skipped.
        """
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        lines = ["#EXTM3U", f"#PLAYLIST:{playlist_name}"]
        matched_count = 0

        for t in resolved_tracks:
            yt = t.get('youtube')
            if not yt or not yt.get('url'):
                continue
            duration_sec = int(yt.get('duration') or ((t.get('duration_ms') or 0) / 1000))
            title = t.get('title') or "Unknown Title"
            artist = t.get('artist') or "Unknown Artist"
            lines.append(f"#EXTINF:{duration_sec},{artist} - {title}")
            lines.append(yt['url'])
            matched_count += 1

        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")

        logger.info(f"Exported {matched_count}/{len(resolved_tracks)} tracks to M3U: {path}")
        return str(path)

    @classmethod
    def export_json(cls, resolved_tracks: List[Dict[str, Any]], output_path: str) -> str:
        """Exports resolved playlist data as formatted JSON."""
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(resolved_tracks, f, ensure_ascii=False, indent=2)
        logger.info(f"Exported {len(resolved_tracks)} tracks to JSON: {path}")
        return str(path)

    @classmethod
    def export_csv(cls, resolved_tracks: List[Dict[str, Any]], output_path: str) -> str:
        """Exports resolved tracks into a clean CSV spreadsheet."""
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        fieldnames = [
            'spotify_id', 'artist', 'title', 'album',
            'youtube_id', 'youtube_url', 'youtube_title',
            'youtube_channel', 'is_topic', 'duration_sec'
        ]

        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for t in resolved_tracks:
                yt = t.get('youtube') or {}
                writer.writerow({
                    'spotify_id': t.get('spotify_id', ''),
                    'artist': t.get('artist', ''),
                    'title': t.get('title', ''),
                    'album': t.get('album', ''),
                    'youtube_id': yt.get('id', ''),
                    'youtube_url': yt.get('url', ''),
                    'youtube_title': yt.get('title', ''),
                    'youtube_channel': yt.get('channel', ''),
                    'is_topic': yt.get('is_topic', False),
                    'duration_sec': yt.get('duration', 0)
                })

        logger.info(f"Exported {len(resolved_tracks)} tracks to CSV: {path}")
        return str(path)
