# 🎵 MusicCore

A resilient, decoupled Python client and toolkit for Spotify Web API integration, playlist management, and audio previews.

## ✨ Features

* **Resilient Spotify Client (`SpotifyClient`)**:
  * **Dual Authentication**: Public `ClientCredentials` (for background catalog workers and APIs) and User `OAuth` (for library and playlist management).
  * **Rate Limit Handling**: Built-in `call_with_retry` inspecting HTTP `Retry-After` headers and avoiding infinite connection freezes.
  * **Spotify 2024/2025 Bulk 403 Bypass**: Transparent concurrent worker pool (`ThreadPoolExecutor`) over individual artist endpoints, bypassing Spotify's restriction on `GET /v1/artists?ids=...`.
  * **Artist Album Pagination**: Automatic handling of Spotify's updated limit constraints.
* **Audio Preview Fallback (`AudioPreviewResolver`)**:
  * Restores 30-second audio previews (which Spotify deprecated/nulled in late 2024) using Deezer public search API with disk caching.
* **Playlist Engine**:
  * Merge tree algorithms, propagation planning, and duplicate detection.

## 🚀 Installation

```bash
pip install -e .
```

## ⚙️ Configuration

Create a `.env` file or export environment variables:

```ini
SPOTIPY_CLIENT_ID=your_spotify_client_id
SPOTIPY_CLIENT_SECRET=your_spotify_client_secret
SPOTIPY_REDIRECT_URI=http://127.0.0.1:8978/callback
SPOTIFY_COUNTRY=ES
```

*(Also supports `clientID` and `clientSecret`).*

## 📖 Quick Usage

### Public Client & Artist Lookup

```python
from music_core import SpotifyClient

client = SpotifyClient(auth_mode="public")

# Search
results = client.search_artists("Daft Punk", limit=5)

# Bulk artist details (with 403 bypass)
artists = client.get_artists(["4tZwfgrHOc3mvqYlEYSvVi", "1rAv1GhTQ2rmG94p9lU3rB"])
```

### Audio Preview Resolver

```python
from music_core import AudioPreviewResolver

preview_url = AudioPreviewResolver.resolve_preview("Daft Punk", "Get Lucky")
# Returns direct MP3 stream URL (30s)
```

## 🧪 Tests

```bash
pytest
```

## 📄 License

MIT
