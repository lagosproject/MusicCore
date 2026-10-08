"""
music_core: Core utilities, resilient Spotify client, and audio preview services.
"""

from .config import settings
from .core.spotify_client import SpotifyClient
from .core.preview_resolver import AudioPreviewResolver
from .core.deduplication import clean_track_title, get_track_fingerprint, choose_best_track_version
from .core.youtube_resolver import YouTubeTrackResolver
from .core.playlist_transfer import PlaylistTransfer

__all__ = [
    "settings",
    "SpotifyClient",
    "AudioPreviewResolver",
    "clean_track_title",
    "get_track_fingerprint",
    "choose_best_track_version",
    "YouTubeTrackResolver",
    "PlaylistTransfer"
]
