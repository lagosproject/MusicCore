import re
from typing import Callable, Dict, List, Set, Tuple
from .models import MergeJob

_PLAYLIST_REF = re.compile(r"playlist[/:]([A-Za-z0-9]{22})")
_BARE_ID = re.compile(r"^[A-Za-z0-9]{22}$")

def normalize_playlist_id(ref: str) -> str:
    """Bare playlist ID from a URL, a spotify: URI or an ID (returned stripped if unrecognised)."""
    ref = (ref or "").strip()
    match = _PLAYLIST_REF.search(ref)
    return match.group(1) if match else ref

def is_valid_playlist_id(ref: str) -> bool:
    return bool(_BARE_ID.match(normalize_playlist_id(ref)))

def _target(job: MergeJob) -> str:
    return normalize_playlist_id(job.target_id)

def _sources(job: MergeJob) -> List[str]:
    return [normalize_playlist_id(s) for s in job.source_ids]

def execution_order(jobs: List[MergeJob]) -> Tuple[List[MergeJob], List[MergeJob]]:
    """
    Orders jobs so every job runs after the jobs that fill its source playlists.
    Returns (ordered, cyclic); cyclic jobs depend on each other and cannot be ordered.
    """
    targets = {_target(j): j for j in jobs}
    pending = list(jobs)
    ordered: List[MergeJob] = []
    done: Set[str] = set()

    while pending:
        ready = None
        for job in pending:
            blockers = {
                targets[s].name for s in _sources(job)
                if s in targets and targets[s].name != job.name and targets[s].name not in done
            }
            if not blockers:
                ready = job
                break
        if ready is None:
            return ordered, pending
        pending.remove(ready)
        ordered.append(ready)
        done.add(ready.name)

    return ordered, []

def consumers(job: MergeJob, jobs: List[MergeJob]) -> List[MergeJob]:
    """Jobs that use this job's target playlist as one of their sources (its direct parents)."""
    target = _target(job)
    return [j for j in jobs if j.name != job.name and target in _sources(j)]

def propagation_plan(jobs: List[MergeJob], name: str) -> List[MergeJob]:
    """The job plus every job above it in the tree, in the order they must run."""
    start = next((j for j in jobs if j.name == name), None)
    if start is None:
        return []

    wanted = {start.name}
    frontier = [start]
    while frontier:
        for parent in consumers(frontier.pop(), jobs):
            if parent.name not in wanted:
                wanted.add(parent.name)
                frontier.append(parent)

    ordered, _ = execution_order(jobs)
    return [j for j in ordered if j.name in wanted]

def _walk_sources(job: MergeJob, jobs: List[MergeJob]) -> Tuple[List[str], List[str]]:
    """(every playlist below the job, in discovery order; the ones that are leaves)."""
    by_target = {_target(j): j for j in jobs}
    below: List[str] = []
    leaves: List[str] = []
    seen_jobs: Set[str] = {job.name}
    queue = list(_sources(job))
    while queue:
        playlist = queue.pop(0)
        if playlist in below or playlist == _target(job):
            continue
        below.append(playlist)
        child = by_target.get(playlist)
        if child is None:
            leaves.append(playlist)
        elif child.name not in seen_jobs:
            seen_jobs.add(child.name)
            queue = _sources(child) + queue
    return below, leaves

def subtree_playlists(job: MergeJob, jobs: List[MergeJob]) -> List[str]:
    """IDs of every playlist that feeds the job, directly or through other merges."""
    return _walk_sources(job, jobs)[0]

def leaf_playlists(job: MergeJob, jobs: List[MergeJob]) -> List[str]:
    """IDs of the playlists below the job that no merge fills: where songs are really placed."""
    return _walk_sources(job, jobs)[1]

def tree_playlist_ids(jobs: List[MergeJob]) -> List[str]:
    """Every playlist that takes part in any merge, as target or as source (no repeats)."""
    ids: List[str] = []
    for job in jobs:
        for playlist in [_target(job)] + _sources(job):
            if playlist and playlist not in ids:
                ids.append(playlist)
    return ids

def all_leaf_playlists(jobs: List[MergeJob]) -> List[str]:
    """Playlists used as a source that no merge fills: where songs are really placed."""
    targets = {_target(job) for job in jobs}
    leaves: List[str] = []
    for job in jobs:
        for playlist in _sources(job):
            if playlist and playlist not in targets and playlist not in leaves:
                leaves.append(playlist)
    return leaves

def creates_cycle(jobs: List[MergeJob], new_job: MergeJob) -> bool:
    """True if saving new_job (replacing any job with the same name) makes the tree circular."""
    candidate = [j for j in jobs if j.name != new_job.name] + [new_job]
    _, cyclic = execution_order(candidate)
    return bool(cyclic)

def shared_targets(jobs: List[MergeJob]) -> List[str]:
    """Playlist IDs that are the target of more than one job."""
    seen: Dict[str, int] = {}
    for job in jobs:
        seen[_target(job)] = seen.get(_target(job), 0) + 1
    return [pid for pid, count in seen.items() if count > 1]

def tree_lines(jobs: List[MergeJob], name_of: Callable[[str], str]) -> List[str]:
    """Markdown bullet list of the merge tree, roots first (a job nobody else consumes)."""
    by_target: Dict[str, List[MergeJob]] = {}
    for job in jobs:
        by_target.setdefault(_target(job), []).append(job)
    consumed = {s for job in jobs for s in _sources(job)}

    lines: List[str] = []
    shown: Set[str] = set()

    def render(job: MergeJob, depth: int) -> None:
        pad = "  " * depth
        if job.name in shown:
            lines.append(f"{pad}- ↻ {job.name} (ya mostrado o en ciclo)")
            return
        shown.add(job.name)
        lines.append(f"{pad}- **{job.name}** → {name_of(job.target_id)}")
        for src in job.source_ids:
            children = by_target.get(normalize_playlist_id(src), [])
            if children:
                for child in children:
                    render(child, depth + 1)
            else:
                lines.append(f"{pad}  - {name_of(src)}")

    for job in jobs:
        if _target(job) not in consumed:
            render(job, 0)
    for job in jobs:  # jobs only reachable through a cycle
        if job.name not in shown:
            render(job, 0)
    return lines
