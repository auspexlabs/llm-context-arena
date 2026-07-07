"""Manifest scanning and delta detection for incremental reindex."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from .chunker import iter_source_files


@dataclass
class FileManifestEntry:
    path: str
    bytes: int
    mtime: float


@dataclass
class ManifestDelta:
    added: List[str] = field(default_factory=list)
    changed: List[str] = field(default_factory=list)
    removed: List[str] = field(default_factory=list)
    unchanged: List[str] = field(default_factory=list)

    @property
    def has_changes(self) -> bool:
        return bool(self.added or self.changed or self.removed)

    def to_dict(self) -> Dict[str, object]:
        return {
            "added": list(self.added),
            "changed": list(self.changed),
            "removed": list(self.removed),
            "unchanged_count": len(self.unchanged),
            "has_changes": self.has_changes,
        }


def scan_repo_files(root_dir: Path) -> Dict[str, FileManifestEntry]:
    """Build path → metadata map for all indexable source files under root."""
    entries: Dict[str, FileManifestEntry] = {}
    for src in iter_source_files(root_dir):
        try:
            stat = src.stat()
            rel = str(src.relative_to(root_dir)).replace("\\", "/")
            entries[rel] = FileManifestEntry(path=rel, bytes=stat.st_size, mtime=stat.st_mtime)
        except OSError:
            continue
    return entries


def files_meta_list(entries: Dict[str, FileManifestEntry]) -> List[dict]:
    """Serialize scan results for index_manifest.json."""
    return [
        {"path": e.path, "bytes": e.bytes, "mtime": e.mtime}
        for e in sorted(entries.values(), key=lambda x: x.path)
    ]


def scan_paths_metadata(root_dir: Path, relative_paths: List[str]) -> Dict[str, FileManifestEntry]:
    """Build metadata for explicit relative paths under root (git candidate scan)."""
    entries: Dict[str, FileManifestEntry] = {}
    for rel in relative_paths:
        rel_norm = rel.replace("\\", "/")
        src = root_dir / rel_norm
        if not src.is_file():
            continue
        try:
            stat = src.stat()
            entries[rel_norm] = FileManifestEntry(
                path=rel_norm, bytes=stat.st_size, mtime=stat.st_mtime
            )
        except OSError:
            continue
    return entries


def diff_manifest(
    indexed_files: Optional[List[dict]],
    current_files: Dict[str, FileManifestEntry],
) -> ManifestDelta:
    """Compare stored manifest file entries against a fresh repo scan."""
    indexed_map: Dict[str, dict] = {}
    if indexed_files:
        for item in indexed_files:
            path = item.get("path")
            if path:
                indexed_map[str(path)] = item

    delta = ManifestDelta()
    for path, entry in sorted(current_files.items()):
        prior = indexed_map.get(path)
        if prior is None:
            delta.added.append(path)
        elif prior.get("bytes") != entry.bytes or prior.get("mtime") != entry.mtime:
            delta.changed.append(path)
        else:
            delta.unchanged.append(path)

    for path in sorted(indexed_map.keys()):
        if path not in current_files:
            delta.removed.append(path)

    return delta