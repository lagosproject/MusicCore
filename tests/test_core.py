import pytest
from music_core import SpotifyClient, AudioPreviewResolver
from music_core.core.api_calls import humanize_seconds

def test_humanize_seconds():
    assert humanize_seconds(30) == "30 s"
    assert humanize_seconds(180) == "3 min"
    assert "horas" in humanize_seconds(7200)

def test_preview_resolver():
    preview = AudioPreviewResolver.resolve_preview("Daft Punk", "Get Lucky")
    assert preview is not None
    assert preview.startswith("http")
    assert ".mp3" in preview

def test_spotify_client_initialization():
    client = SpotifyClient(auth_mode="public")
    assert client.sp is not None
    assert client.auth_mode == "public"

def test_normalize_artist_id():
    client = SpotifyClient(auth_mode="public")
    aid = client.normalize_artist_id("https://open.spotify.com/artist/4tZwfgrHOc3mvqYlEYSvVi?si=123")
    assert aid == "4tZwfgrHOc3mvqYlEYSvVi"

def test_get_artists_bulk_bypass():
    client = SpotifyClient(auth_mode="public")
    artists = client.get_artists(["4tZwfgrHOc3mvqYlEYSvVi", "1rAv1GhTQ2rmG94p9lU3rB"])
    assert len(artists) == 2
    names = [a["name"] for a in artists]
    assert "Daft Punk" in names
    assert "Julian Casablancas" in names
