import os
import json
import csv
from unittest.mock import patch, MagicMock
import pytest
from music_core.core.youtube_resolver import (
    normalize_text,
    clean_track_query,
    YouTubeTrackResolver
)
from music_core.core.playlist_transfer import PlaylistTransfer

def test_normalize_text():
    assert normalize_text("Éxito Español 2026!") == "exitoespanol2026"
    assert normalize_text("Bad Bunny - Tití Me Preguntó") == "badbunnytitimepregunto"
    assert normalize_text("") == ""

def test_clean_track_query():
    assert clean_track_query("Song Title (Remastered 2020)") == "Song Title"
    assert clean_track_query("Another Song [Official Audio]") == "Another Song"
    assert clean_track_query("Simple Song") == "Simple Song"

def test_select_fragment_times_heatmap():
    heatmap = [
        {"start_time": 10.0, "value": 0.2},
        {"start_time": 60.0, "value": 0.95}, # Top peak
        {"start_time": 120.0, "value": 0.8}, # Second peak
        {"start_time": 70.0, "value": 0.9},  # Too close to 60 (< 45s min_dist)
    ]
    # Total 200s, ask for 2 fragments
    times = YouTubeTrackResolver.select_fragment_times(heatmap, 200.0, n_fragments=2, min_distance=45.0)
    assert len(times) == 2
    assert 60.0 in times
    assert 120.0 in times
    assert sorted(times) == times

def test_select_fragment_times_fallback():
    # Without heatmap, uniform spacing between 10% and 80% of 100s -> 10s, 45s, 80s
    times = YouTubeTrackResolver.select_fragment_times(None, 100.0, n_fragments=3)
    assert len(times) == 3
    assert times[0] == 10.0
    assert times[-1] == 80.0

@patch("yt_dlp.YoutubeDL")
def test_youtube_resolver_topic_channel(mock_ydl_cls, tmp_path):
    mock_ydl = MagicMock()
    mock_ydl_cls.return_value.__enter__.return_value = mock_ydl

    mock_entries = [
        {
            "id": "vid123",
            "title": "Obsesión",
            "channel": "Aventura - Topic",
            "uploader": "Aventura - Topic",
            "duration": 240,
            "webpage_url": "https://www.youtube.com/watch?v=vid123",
            "heatmap": []
        }
    ]
    mock_ydl.extract_info.return_value = {"entries": mock_entries}

    # Clear memory cache for this test
    YouTubeTrackResolver._memory_cache.clear()

    res = YouTubeTrackResolver.resolve_track("Obsesión", "Aventura", force_refresh=True)
    assert res is not None
    assert res["id"] == "vid123"
    assert res["is_topic"] is True
    assert res["channel"] == "Aventura - Topic"

def test_playlist_transfer_exporters(tmp_path):
    resolved_tracks = [
        {
            "spotify_id": "sp1",
            "title": "Bailando",
            "artist": "Enrique Iglesias",
            "album": "Sex and Love",
            "duration_ms": 240000,
            "youtube": {
                "id": "yt_bailando",
                "url": "https://www.youtube.com/watch?v=yt_bailando",
                "title": "Bailando",
                "channel": "Enrique Iglesias - Topic",
                "is_topic": True,
                "duration": 240
            }
        },
        {
            "spotify_id": "sp2",
            "title": "Despacito",
            "artist": "Luis Fonsi",
            "album": "Vida",
            "duration_ms": 230000,
            "youtube": None
        }
    ]

    # Test M3U export
    m3u_file = tmp_path / "playlist.m3u8"
    PlaylistTransfer.export_m3u(resolved_tracks, str(m3u_file), "Latino Hits")
    assert m3u_file.exists()
    content = m3u_file.read_text(encoding="utf-8")
    assert "#EXTM3U" in content
    assert "Enrique Iglesias - Bailando" in content
    assert "https://www.youtube.com/watch?v=yt_bailando" in content
    # sp2 has no youtube, shouldn't be in M3U
    assert "Despacito" not in content

    # Test JSON export
    json_file = tmp_path / "playlist.json"
    PlaylistTransfer.export_json(resolved_tracks, str(json_file))
    assert json_file.exists()
    with open(json_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert len(data) == 2
    assert data[0]["spotify_id"] == "sp1"

    # Test CSV export
    csv_file = tmp_path / "playlist.csv"
    PlaylistTransfer.export_csv(resolved_tracks, str(csv_file))
    assert csv_file.exists()
    with open(csv_file, "r", encoding="utf-8") as f:
        reader = list(csv.DictReader(f))
    assert len(reader) == 2
    assert reader[0]["artist"] == "Enrique Iglesias"
    assert reader[0]["youtube_id"] == "yt_bailando"
