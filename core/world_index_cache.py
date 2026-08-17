"""Lightweight filesystem guards for immutable world-index snapshots."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True, order=True)
class WorldPathState:
    """A cheap filesystem state used to validate a cached index."""

    relative_path: str
    exists: bool
    mode: int
    size: int
    modified_ns: int
    changed_ns: int


@dataclass(frozen=True)
class WorldIndexCacheGuard:
    """Directory membership and mutable metadata guarding one snapshot."""

    directories: tuple[WorldPathState, ...]
    mutable_files: tuple[WorldPathState, ...]


def build_world_index_cache_guard(
    world: Path,
    indexed_paths: Iterable[Path],
    dimension_region_dirs: Iterable[Path],
    mutable_files: Iterable[Path],
) -> WorldIndexCacheGuard:
    """Capture the small set of states needed for warm cache validation.

    Args:
        world: Normalized Minecraft world root.
        indexed_paths: Files represented by the complete index probe.
        dimension_region_dirs: Active dimension region directories.
        mutable_files: Files whose contents affect cached metadata.

    Returns:
        An immutable guard suitable for repeated cheap validation.
    """
    directories = _cache_watch_directories(
        world,
        indexed_paths,
        dimension_region_dirs,
    )
    return WorldIndexCacheGuard(
        directories=_path_states(world, directories),
        mutable_files=_path_states(world, mutable_files),
    )


def is_world_index_cache_guard_current(
    world: Path,
    guard: WorldIndexCacheGuard,
) -> bool:
    """Return whether a guard still describes current index membership.

    Args:
        world: Normalized Minecraft world root.
        guard: Guard captured with a completed index snapshot.

    Returns:
        True when no watched directory or mutable file state changed.
    """
    directory_paths = tuple(
        _path_from_state(world, state.relative_path)
        for state in guard.directories
    )
    mutable_paths = tuple(
        _path_from_state(world, state.relative_path)
        for state in guard.mutable_files
    )
    return guard == WorldIndexCacheGuard(
        directories=_path_states(world, directory_paths),
        mutable_files=_path_states(world, mutable_paths),
    )


def _cache_watch_directories(
    world: Path,
    indexed_paths: Iterable[Path],
    dimension_region_dirs: Iterable[Path],
) -> tuple[Path, ...]:
    """Collect existing and expected directories affecting membership."""
    directories = _fixed_watch_directories(world)
    indexed_parents = {path.parent for path in indexed_paths}
    for parent in indexed_parents:
        _add_world_ancestors(world, parent, directories)
    for region_dir in dimension_region_dirs:
        _add_world_ancestors(world, region_dir, directories)
    _add_dimension_topology(world, directories)
    return tuple(sorted(directories, key=str))


def _fixed_watch_directories(world: Path) -> set[Path]:
    """Return known legacy and 26.1 directory locations, including missing ones."""
    return {
        world,
        world / "region",
        world / "playerdata",
        world / "players",
        world / "players" / "data",
        world / "players" / "stats",
        world / "players" / "advancements",
        world / "data",
        world / "data" / "minecraft",
        world / "stats",
        world / "advancements",
        world / "DIM-1",
        world / "DIM-1" / "region",
        world / "DIM1",
        world / "DIM1" / "region",
        world / "dimensions",
    }


def _add_dimension_topology(
    world: Path,
    directories: set[Path],
) -> None:
    """Watch empty custom dimension folders that may gain region files."""
    for directory in _unlinked_child_directories(world):
        directories.add(directory)
        if directory.name.startswith("DIM"):
            directories.add(directory / "region")
    dimensions_root = world / "dimensions"
    for namespace in _unlinked_child_directories(dimensions_root):
        directories.add(namespace)
        for dimension in _unlinked_child_directories(namespace):
            directories.add(dimension)
            directories.add(dimension / "region")


def _add_world_ancestors(
    world: Path,
    path: Path,
    directories: set[Path],
) -> None:
    """Add a world-relative directory and its ancestors to a watch set."""
    try:
        path.relative_to(world)
    except ValueError:
        return
    current = path
    while True:
        directories.add(current)
        if current == world:
            return
        current = current.parent


def _unlinked_child_directories(parent: Path) -> tuple[Path, ...]:
    """Return direct regular child directories without following links."""
    try:
        children = []
        for path in parent.iterdir():
            is_junction = getattr(path, "is_junction", lambda: False)
            if path.is_symlink() or bool(is_junction()):
                continue
            if path.is_dir():
                children.append(path)
        return tuple(sorted(children, key=str))
    except OSError:
        return ()


def _path_states(
    world: Path,
    paths: Iterable[Path],
) -> tuple[WorldPathState, ...]:
    """Read deterministic metadata states, including missing paths."""
    states = []
    for path in dict.fromkeys(paths):
        display_path = _display_path(world, path)
        try:
            metadata = path.lstat()
        except OSError:
            states.append(WorldPathState(display_path, False, 0, 0, 0, 0))
            continue
        states.append(
            WorldPathState(
                display_path,
                True,
                metadata.st_mode,
                metadata.st_size,
                metadata.st_mtime_ns,
                metadata.st_ctime_ns,
            )
        )
    return tuple(sorted(states))


def _path_from_state(world: Path, value: str) -> Path:
    """Resolve one world-relative or external guard path without I/O."""
    path = Path(value)
    return path if path.is_absolute() else world / path


def _display_path(world: Path, path: Path) -> str:
    """Use world-relative paths internally and normalized absolute paths outside."""
    absolute = path.absolute()
    try:
        return absolute.relative_to(world).as_posix()
    except ValueError:
        return str(path.resolve())


__all__ = [
    "WorldIndexCacheGuard",
    "WorldPathState",
    "build_world_index_cache_guard",
    "is_world_index_cache_guard_current",
]
