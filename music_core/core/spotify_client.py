import re
import spotipy
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Any, Iterable, Optional, Set
from loguru import logger
from spotipy.oauth2 import SpotifyClientCredentials, SpotifyOAuth

from ..config import settings
from .api_calls import call_with_retry, make_session
from .cache_store import slim_track
from .merge_tree import normalize_playlist_id
from .preview_resolver import AudioPreviewResolver
from .tracks import extract_track

SAVED_BATCH_SIZE = 40
FULL_SAVED_READ_THRESHOLD = 3000

class SpotifyClient:
    """
    Unified, resilient Spotify client supporting both server/public credentials
    and user OAuth credentials, with automatic 429 rate-limit retries and workarounds
    for Spotify's API breaking changes (bulk 403 bypass, missing previews).
    """

    def __init__(
        self,
        auth_mode: str = "public",
        scope: Optional[str] = None,
        requests_timeout: int = 15
    ):
        """
        :param auth_mode: 'public' (SpotifyClientCredentials, no login) or 'user' (SpotifyOAuth)
        """
        self.auth_mode = auth_mode
        self.requests_timeout = requests_timeout
        self.session = make_session()
        self._artist_cache: Dict[str, Dict[str, Any]] = {}

        client_id = settings.spotipy_client_id
        client_secret = settings.spotipy_client_secret

        if not client_id or not client_secret:
            missing = settings.missing_spotify_credentials()
            raise EnvironmentError(
                f"Missing Spotify credentials: {', '.join(missing)}. "
                "Please configure them in .env"
            )

        # Public client (available in both modes for unauthenticated queries)
        self.sp_public = spotipy.Spotify(
            auth_manager=SpotifyClientCredentials(
                client_id=client_id,
                client_secret=client_secret
            ),
            requests_session=self.session,
            requests_timeout=self.requests_timeout
        )

        if auth_mode == "user":
            if scope is None:
                scope = (
                    "user-library-read,"
                    "user-follow-read,"
                    "playlist-read-private,"
                    "playlist-read-collaborative,"
                    "playlist-modify-public,"
                    "playlist-modify-private,"
                    "user-library-modify"
                )
            self.sp = spotipy.Spotify(
                auth_manager=SpotifyOAuth(
                    client_id=client_id,
                    client_secret=client_secret,
                    redirect_uri=settings.spotipy_redirect_uri,
                    scope=scope,
                    open_browser=True,
                    show_dialog=False,
                    cache_path=settings.cache_path
                ),
                requests_session=self.session,
                requests_timeout=self.requests_timeout
            )
            logger.info("SpotifyClient initialized in USER OAuth mode")
        else:
            self.sp = self.sp_public
            logger.info("SpotifyClient initialized in PUBLIC ClientCredentials mode")

    # =========================================================================
    # ARTIST CATALOG & COLLABORATION METHODS (WITH 403 BULK BYPASS)
    # =========================================================================

    def normalize_artist_id(self, artist_url_or_id: str) -> str:
        """Extracts standard 22-char Spotify artist ID from URLs or returns ID as is."""
        clean = artist_url_or_id.strip()
        if "spotify.com" in clean:
            match = re.search(r'artist/([a-zA-Z0-9]+)', clean)
            if match:
                return match.group(1)
        return clean

    def search_artists(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Search for artists by name with resilient retry."""
        try:
            results = call_with_retry(
                self.sp.search,
                q=query,
                limit=limit,
                type="artist"
            )
            items = results.get("artists", {}).get("items", [])
            output = []
            for item in items:
                output.append({
                    "id": item["id"],
                    "name": item["name"],
                    "url": item["external_urls"].get("spotify", f"https://open.spotify.com/artist/{item['id']}"),
                    "image": item["images"][0]["url"] if item.get("images") else None,
                    "genres": item.get("genres", [])
                })
            return output
        except Exception as e:
            logger.error(f"Error searching artists for '{query}': {e}")
            return []

    def scrape_web_artist(self, aid: str) -> Optional[Dict[str, Any]]:
        """
        Fallback parser that extracts artist profile and avatar directly from
        the public Spotify Web page without using API quota (immune to 429).
        """
        import base64
        import json
        import re
        import urllib.request
        url = f"https://open.spotify.com/artist/{aid}"
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                content = resp.read().decode("utf-8")
            match = re.search(r'<script id="initialState" type="text/plain">(.*?)</script>', content)
            if match:
                raw = base64.b64decode(match.group(1)).decode("utf-8")
                data = json.loads(raw)
                items = data.get("entities", {}).get("items", {})
                key = f"spotify:artist:{aid}"
                if key in items:
                    art = items[key]
                    name = art.get("profile", {}).get("name")
                    visuals = art.get("visuals") or {}
                    avatar = visuals.get("avatarImage") or {}
                    sources = avatar.get("sources", [])
                    img = sources[0].get("url") if sources else None
                    if name:
                        return {
                            "id": aid,
                            "name": name,
                            "url": img,
                            "external_url": f"https://open.spotify.com/artist/{aid}",
                            "genres": []
                        }
        except Exception as e:
            logger.debug(f"Web scraping fallback failed for artist {aid}: {e}")
        return None

    def get_artist(self, artist_id: str) -> Dict[str, Any]:
        """Fetch details of a single artist with in-memory caching and resilient web fallback."""
        aid = self.normalize_artist_id(artist_id)
        if aid in self._artist_cache:
            return self._artist_cache[aid]

        try:
            data = call_with_retry(self.sp.artist, aid)
            artist_obj = {
                "id": data.get("id", aid),
                "name": data.get("name", f"Artist {aid[:6]}"),
                "url": data.get("images", [{}])[0].get("url") if data.get("images") else None,
                "external_url": data.get("external_urls", {}).get("spotify", ""),
                "genres": data.get("genres", [])
            }
        except Exception as e:
            logger.warning(f"Spotify API failed for artist {aid} ({e}), trying public web fallback...")
            web_obj = self.scrape_web_artist(aid)
            if web_obj:
                artist_obj = web_obj
            else:
                artist_obj = {
                    "id": aid,
                    "name": f"Unknown ({aid[:6]})",
                    "url": None,
                    "external_url": f"https://open.spotify.com/artist/{aid}",
                    "genres": []
                }

        self._artist_cache[aid] = artist_obj
        return artist_obj

    def get_artists(self, artist_ids: List[str], max_workers: int = 5) -> List[Dict[str, Any]]:
        """
        Bypasses Spotify's 403 Forbidden on GET /v1/artists?ids=... by fetching
        single artists concurrently using a worker pool, caching, and web fallback.
        """
        unique_ids = list(dict.fromkeys(self.normalize_artist_id(aid) for aid in artist_ids if aid))
        results: Dict[str, Dict[str, Any]] = {}
        missing_ids = []

        for aid in unique_ids:
            if aid in self._artist_cache:
                results[aid] = self._artist_cache[aid]
            else:
                missing_ids.append(aid)

        if missing_ids:
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_to_id = {executor.submit(self.get_artist, aid): aid for aid in missing_ids}
                for future in as_completed(future_to_id):
                    aid = future_to_id[future]
                    try:
                        res = future.result()
                        results[aid] = res
                    except Exception as e:
                        logger.warning(f"Could not fetch artist {aid}: {e}")
                        # Final fallback
                        web_obj = self.scrape_web_artist(aid)
                        results[aid] = web_obj or {
                            "id": aid,
                            "name": f"Unknown ({aid[:6]})",
                            "url": None,
                            "external_url": f"https://open.spotify.com/artist/{aid}",
                            "genres": []
                        }

        return [results[aid] for aid in unique_ids if aid in results]

    def get_artist_albums(
        self,
        artist_id: str,
        limit: int = 10,
        country: str = "ES",
        album_type: str = "album,single,appears_on"
    ) -> List[Dict[str, Any]]:
        """
        Paginates through artist albums by querying each requested group separately.
        This prevents appears_on (which Spotify places at the very end) from being
        starved out by extensive album/single discographies.
        """
        aid = self.normalize_artist_id(artist_id)
        groups = [g.strip() for g in album_type.split(",") if g.strip()]
        all_albums = []
        seen_album_ids = set()

        for group in groups:
            offset = 0
            # For appears_on we scan up to 50 items (5 pages of 10)
            # For album and single we scan up to 30 items each
            max_group_items = 60 if group == "appears_on" else 30
            while True:
                response = call_with_retry(
                    self.sp.artist_albums,
                    aid,
                    limit=10,
                    offset=offset,
                    country=country,
                    album_type=group
                )
                items = response.get("items", [])
                if not items:
                    break
                for it in items:
                    if it["id"] not in seen_album_ids:
                        seen_album_ids.add(it["id"])
                        all_albums.append(it)
                offset += 10
                if offset >= response.get("total", 0) or offset >= max_group_items:
                    break

        return all_albums

    def get_album_tracks(self, album_uri_or_id: str) -> List[Dict[str, Any]]:
        """Fetch all tracks for a given album."""
        response = call_with_retry(self.sp.album_tracks, album_uri_or_id)
        return response.get("items", [])

    def resolve_track_preview(self, artist_name: str, track_name: str, spotify_preview: Optional[str] = None) -> Optional[str]:
        """Returns spotify_preview if available; otherwise falls back to AudioPreviewResolver (Deezer)."""
        if spotify_preview:
            return spotify_preview
        return AudioPreviewResolver.resolve_preview(artist_name, track_name)

    # =========================================================================
    # PLAYLIST & LIBRARY METHODS (FROM MUSIC_MANAGER)
    # =========================================================================

    def get_playlist_id(self, playlist_url_or_id: str) -> str:
        return normalize_playlist_id(playlist_url_or_id)

    def get_playlist_info(self, playlist_id: str) -> Dict[str, Any]:
        playlist_id = self.get_playlist_id(playlist_id)
        return call_with_retry(self.sp.playlist, playlist_id, fields="name,images,external_urls")

    def get_playlist_tracks(self, playlist_id: str, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        playlist_id = self.get_playlist_id(playlist_id)
        results = []
        offset = 0
        fetch_limit = 100

        while True:
            if limit and len(results) >= limit:
                break
            current_fetch = fetch_limit
            if limit:
                current_fetch = min(fetch_limit, limit - len(results))
                if current_fetch <= 0:
                    break

            response = call_with_retry(
                self.sp.playlist_items,
                playlist_id,
                offset=offset,
                limit=current_fetch,
                additional_types=['track']
            )

            if not response['items']:
                break

            results.extend(response['items'])
            offset += current_fetch

            if len(results) >= response['total']:
                break

        return results

    def get_saved_tracks(self) -> List[Dict[str, Any]]:
        results = []
        offset = 0
        limit = 50

        while True:
            response = call_with_retry(self.sp.current_user_saved_tracks, limit=limit, offset=offset)
            if not response['items']:
                break
            results.extend(response['items'])
            offset += limit
            if len(results) >= response['total']:
                break

        return results

    def get_saved_total(self) -> int:
        return call_with_retry(self.sp.current_user_saved_tracks, limit=1)['total']

    def filter_unsaved(self, track_uris: Iterable[str], saved_uris: Optional[Set[str]] = None) -> List[str]:
        uris = [u for u in dict.fromkeys(track_uris) if u.startswith("spotify:track:")]
        if saved_uris is None and len(uris) > FULL_SAVED_READ_THRESHOLD:
            saved_uris = {t['uri'] for t in (extract_track(i) for i in self.get_saved_tracks()) if t and t.get('uri')}
        if saved_uris is not None:
            return [u for u in uris if u not in saved_uris]

        unsaved = []
        for i in range(0, len(uris), SAVED_BATCH_SIZE):
            batch = uris[i:i + SAVED_BATCH_SIZE]
            flags = call_with_retry(self.sp.current_user_saved_tracks_contains, batch)
            unsaved.extend(uri for uri, saved in zip(batch, flags) if not saved)
        return unsaved

    def save_tracks(self, track_uris: List[str]):
        for i in range(0, len(track_uris), SAVED_BATCH_SIZE):
            call_with_retry(self.sp.current_user_saved_tracks_add, track_uris[i:i + SAVED_BATCH_SIZE])

    def sync_to_saved(self, track_uris: Iterable[str], saved_uris: Optional[Set[str]] = None) -> int:
        missing = self.filter_unsaved(track_uris, saved_uris)
        if missing:
            self.save_tracks(missing)
        return len(missing)

    def get_user_playlists(self) -> List[Dict[str, Any]]:
        results = []
        offset = 0
        limit = 50

        while True:
            response = call_with_retry(self.sp.current_user_playlists, limit=limit, offset=offset)
            if not response['items']:
                break
            results.extend(response['items'])
            offset += limit
            if len(results) >= response['total']:
                break

        return results

    def create_playlist(self, name: str, public: bool = False, description: str = "") -> str:
        playlist = call_with_retry(
            self.sp.current_user_playlist_create,
            name=name,
            public=public,
            description=description
        )
        return playlist['id']

    def add_tracks_to_playlist(self, playlist_id: str, track_uris: List[str]):
        playlist_id = self.get_playlist_id(playlist_id)
        for i in range(0, len(track_uris), 100):
            batch = track_uris[i:i + 100]
            call_with_retry(self.sp.playlist_add_items, playlist_id, batch)

    def insert_track(self, playlist_id: str, track_uri: str, position: int):
        playlist_id = self.get_playlist_id(playlist_id)
        call_with_retry(self.sp.playlist_add_items, playlist_id, [track_uri], position=position)

    def remove_track_from_playlist(self, playlist_id: str, track_uris: List[str]):
        playlist_id = self.get_playlist_id(playlist_id)
        for i in range(0, len(track_uris), 100):
            batch = track_uris[i:i + 100]
            call_with_retry(self.sp.playlist_remove_all_occurrences_of_items, playlist_id, batch)

    def get_followed_artists(self) -> List[Dict[str, Any]]:
        results = []
        after = None
        while True:
            response = self.sp.current_user_followed_artists(limit=50, after=after)
            artists = response['artists']['items']
            results.extend(artists)
            after = response['artists']['cursors'].get('after')
            if not after:
                break
        return results

    def plan_merge(
        self,
        target_playlist_id: str,
        source_playlist_ids: List[str],
        track_cache: Optional[Dict[str, List[Dict[str, Any]]]] = None
    ) -> List[Dict[str, Any]]:
        cache = track_cache if track_cache is not None else {}

        def tracks_of(playlist_id: str) -> List[Dict[str, Any]]:
            if playlist_id not in cache:
                tracks = (extract_track(t) for t in self.get_playlist_tracks(playlist_id))
                cache[playlist_id] = [slim_track(t) for t in tracks if t and t.get('uri')]
            return cache[playlist_id]

        target_id = self.get_playlist_id(target_playlist_id)
        known = {t['uri'] for t in tracks_of(target_id)}
        new_tracks = []
        for ref in source_playlist_ids:
            source_id = self.get_playlist_id(ref)
            for track in tracks_of(source_id):
                if track['uri'] not in known:
                    known.add(track['uri'])
                    new_tracks.append({**track, "from": source_id})
        return new_tracks

    def merge_playlists(
        self,
        target_playlist_id: str,
        source_playlist_ids: List[str],
        track_cache: Optional[Dict[str, List[Dict[str, Any]]]] = None
    ) -> int:
        cache = track_cache if track_cache is not None else {}
        new_tracks = self.plan_merge(target_playlist_id, source_playlist_ids, cache)
        addable = [t for t in new_tracks if not t['uri'].startswith("spotify:local:")]
        target_id = self.get_playlist_id(target_playlist_id)
        if addable:
            self.add_tracks_to_playlist(target_id, [t['uri'] for t in addable])
            cache[target_id] = cache[target_id] + [{k: v for k, v in t.items() if k != "from"} for t in addable]
        return len(addable)
