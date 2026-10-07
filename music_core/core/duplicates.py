import re
import time
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple
from loguru import logger
from .tracks import extract_track

MODE_SAME_TRACK = "uri"    # the very same Spotify track repeated
MODE_SAME_TITLE = "title"  # same artist and title, possibly different releases

# Words that mark an alternative release of the same song: "(Remastered 2011)", "- Radio Edit"...
# Remix, live, acoustic, instrumental... are NOT here: they are different versions.
_VERSION_WORDS = re.compile(
    r"remaster|version|versi[oó]n|edit\b|radio|mono|stereo|deluxe|bonus|explicit|clean|single|"
    r"album|original|feat|ft\.|with |con ",
    re.IGNORECASE,
)
_BRACKETS = re.compile(r"\(([^)]*)\)|\[([^\]]*)\]")
_DASH_SUFFIX = re.compile(r"\s-\s(.*)$")

@dataclass
class DuplicateGroup:
    key: str
    name: str
    artist: str
    positions: List[int] = field(default_factory=list)  # in the list given
    uris: List[str] = field(default_factory=list)
    tracks: List[Dict[str, Any]] = field(default_factory=list)  # slim track of each copy
    added: List[str] = field(default_factory=list)  # when each copy was added to the playlist

    @property
    def extras(self) -> int:
        return len(self.positions) - 1

    @property
    def distinct_uris(self) -> List[str]:
        """The different releases in the group, in the order they appear."""
        return list(dict.fromkeys(self.uris))

@dataclass
class DedupeResult:
    removed: int = 0
    restored: int = 0
    error: Optional[str] = None
    lost: List[str] = field(default_factory=list)  # URIs that were removed and could not be put back

@dataclass
class DedupeOps:
    """What has to be done on the playlist. Spotify only removes a track by URI (every copy)."""
    remove_entirely: List[str] = field(default_factory=list)  # versions that go away completely
    collapse: List[str] = field(default_factory=list)         # tracks kept once: remove every copy, put one back

def _ascii_lower(text: str) -> str:
    return unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower()

def title_key(track: Dict[str, Any]) -> str:
    """artist|title with accents, case, punctuation and version tags ignored. Empty if not enough data."""
    title = track.get("name") or ""

    def drop_version_tags(match):
        inner = match.group(1) or match.group(2) or ""
        return " " if _VERSION_WORDS.search(inner) else match.group(0)

    title = _BRACKETS.sub(drop_version_tags, title)
    suffix = _DASH_SUFFIX.search(title)
    if suffix and _VERSION_WORDS.search(suffix.group(1)):
        title = title[:suffix.start()]
    title = re.sub(r"[^a-z0-9]+", " ", _ascii_lower(title)).strip()

    artists = track.get("artists") or []
    first = artists[0].get("name") if artists and isinstance(artists[0], dict) else ""
    artist = re.sub(r"[^a-z0-9]+", " ", _ascii_lower(first or "")).strip()
    return f"{artist}|{title}" if title and artist else ""

def find_duplicate_groups(items: Sequence[Any], mode: str = MODE_SAME_TRACK) -> List[DuplicateGroup]:
    """Groups of tracks that appear more than once. Positions are indexes into `items`."""
    groups: Dict[str, DuplicateGroup] = {}
    for position, item in enumerate(items):
        track = extract_track(item)
        uri = (track or {}).get("uri")
        if not uri or uri.startswith("spotify:local:"):
            continue  # local files cannot be reliably removed by position
        key = uri if mode == MODE_SAME_TRACK else title_key(track)
        if not key:
            continue
        artists = track.get("artists") or []
        artist = ", ".join(a.get("name") or "" for a in artists if isinstance(a, dict))
        group = groups.setdefault(key, DuplicateGroup(key, track.get("name") or uri, artist))
        group.positions.append(position)
        group.uris.append(uri)
        group.tracks.append(track)
        group.added.append((item.get("added_at") or "") if isinstance(item, dict) else "")
    return [g for g in groups.values() if len(g.positions) > 1]

def plan_operations(groups: Sequence[DuplicateGroup], keep: Dict[str, str]) -> DedupeOps:
    """
    What to do for the groups the user decided on. `keep` maps a group key to the URI to keep.
    Every other version is removed entirely; the kept one is only touched if it appears more than once.
    """
    ops = DedupeOps()
    for group in groups:
        kept_uri = keep.get(group.key)
        if kept_uri is None or kept_uri not in group.uris:
            continue
        for uri in group.distinct_uris:
            if uri != kept_uri and uri not in ops.remove_entirely:
                ops.remove_entirely.append(uri)
        if group.uris.count(kept_uri) > 1 and kept_uri not in ops.collapse:
            ops.collapse.append(kept_uri)
    return ops

def format_duration(duration_ms: Optional[int]) -> str:
    if not duration_ms:
        return ""
    minutes, seconds = divmod(round(duration_ms / 1000), 60)
    return f"{minutes}:{seconds:02d}"

def _year(track: Dict[str, Any]) -> str:
    return ((track.get("album") or {}).get("release_date") or "")[:4]

def _added_date(added_at: str) -> str:
    """'2024-03-12T21:00:00Z' -> '12/03/2024'."""
    match = re.match(r"(\d{4})-(\d{2})-(\d{2})", added_at or "")
    return f"{match.group(3)}/{match.group(2)}/{match.group(1)}" if match else ""

def describe_copy(track: Dict[str, Any], added_at: str = "") -> str:
    """One line that tells two copies apart: album, year, length, explicit and when it was added."""
    album = (track.get("album") or {}).get("name") or "álbum desconocido"
    year = _year(track)
    parts = [f"{album} ({year})" if year else album, format_duration(track.get("duration_ms"))]
    if track.get("explicit"):
        parts.append("explícita")
    if _added_date(added_at):
        parts.append(f"añadida el {_added_date(added_at)}")
    return " · ".join(p for p in parts if p)

def track_url(track: Dict[str, Any]) -> str:
    track_id = track.get("id") or (track.get("uri") or "").split(":")[-1]
    return f"https://open.spotify.com/track/{track_id}" if track_id else ""

def copies_to_remove(group: DuplicateGroup, kept_uri: str) -> List[Tuple[Dict[str, Any], str]]:
    """(track, added_at) of the copies that go away for this group (the kept one stays once)."""
    if kept_uri not in group.uris:
        return []
    kept_index = group.uris.index(kept_uri)
    return [(t, a) for i, (t, a) in enumerate(zip(group.tracks, group.added)) if i != kept_index]

def _usable_uris(items: Sequence[Any]) -> List[str]:
    return [t["uri"] for t in (extract_track(i) for i in items) if t and t.get("uri")]

def _slot(item: Any) -> Optional[str]:
    """URI at one position of the playlist, or None for an unavailable entry (it still takes a position)."""
    track = extract_track(item)
    return track.get("uri") if track else None

def _settled_uris(client, playlist_id: str, expected: List[str], sleep: Callable[[float], None], tries: int = 6) -> List[str]:
    """Reads the playlist until it matches `expected`, giving Spotify a few seconds to reflect the changes."""
    uris = _usable_uris(client.get_playlist_tracks(playlist_id))
    for _ in range(tries):
        if uris == expected:
            break
        sleep(1.5)
        uris = _usable_uris(client.get_playlist_tracks(playlist_id))
    return uris

def remove_duplicates(
    client,
    playlist_id: str,
    mode: str,
    keep: Dict[str, str],
    on_progress: Optional[Callable[[int, int], None]] = None,
    sleep: Callable[[float], None] = time.sleep,
) -> DedupeResult:
    """
    Removes the duplicates the user decided on (`keep`: group key -> URI to keep).

    Spotify's API ignores positions when removing and removes every copy of a URI, so a track that
    is kept once is handled by removing all its copies and putting one back where the first was
    (its "added on" date becomes today). Versions that go away entirely are removed in one go.
    One track at a time, so a failure never leaves more than one track missing. At the end it re-reads
    the playlist and puts back any track that had to stay and is not there.
    """
    before_items = client.get_playlist_tracks(playlist_id)
    groups = find_duplicate_groups(before_items, mode)
    ops = plan_operations(groups, keep)
    if not ops.remove_entirely and not ops.collapse:
        return DedupeResult()

    slots: List[Optional[str]] = [_slot(item) for item in before_items]  # same positions as in Spotify
    total = len(ops.collapse) + (1 if ops.remove_entirely else 0)
    done = 0
    error = None
    lost: List[str] = []

    def advance():
        nonlocal done
        done += 1
        if on_progress:
            on_progress(done, total)

    try:
        if ops.remove_entirely:
            client.remove_track_from_playlist(playlist_id, ops.remove_entirely)
            gone = set(ops.remove_entirely)
            slots = [s for s in slots if s not in gone]
            advance()

        for uri in ops.collapse:
            position = slots.index(uri)  # where the first copy is now
            client.remove_track_from_playlist(playlist_id, [uri])
            slots = [s for s in slots if s != uri]
            try:
                client.insert_track(playlist_id, uri, position)
                slots.insert(position, uri)
            except Exception as insert_error:
                logger.error(f"Could not put {uri} back at {position}: {insert_error}")
                try:
                    client.add_tracks_to_playlist(playlist_id, [uri])  # at the end: better than losing it
                    slots.append(uri)
                except Exception:
                    lost.append(uri)
                raise
            advance()
    except Exception as e:
        logger.error(f"Removing duplicates failed: {type(e).__name__}: {e}")
        error = f"{type(e).__name__}: {e}"

    expected = [s for s in slots if s]
    after_uris = _settled_uris(client, playlist_id, expected, sleep)
    present = Counter(after_uris)
    restored = 0
    for group in groups:
        kept = keep.get(group.key)
        if kept in group.uris and present[kept] == 0 and kept not in lost:
            logger.warning(f"{kept} is missing after the cleanup; putting it back")
            client.add_tracks_to_playlist(playlist_id, [kept])
            present[kept] += 1
            restored += 1

    removed = len(_usable_uris(before_items)) - (len(after_uris) + restored)
    return DedupeResult(removed=max(removed, 0), restored=restored, error=error, lost=lost)
