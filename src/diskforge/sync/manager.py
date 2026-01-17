"""
DiskForge sync manager.

Implements one-way and two-way sync with conflict resolution and hooks.
"""

from __future__ import annotations

import fnmatch
import json
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable

from diskforge.core.config import SyncConfig


@dataclass(frozen=True)
class FileSnapshot:
    path: Path
    relative_path: str
    size: int
    mtime: float


@dataclass
class SyncConflict:
    relative_path: str
    reason: str
    resolution: str


@dataclass
class SyncSummary:
    copied: int = 0
    skipped: int = 0
    conflicts: int = 0
    errors: int = 0


@dataclass
class SyncStatus:
    source: str
    target: str
    direction: str
    conflict_policy: str
    started_at: datetime
    ended_at: datetime | None = None
    summary: SyncSummary = field(default_factory=SyncSummary)
    conflicts: list[SyncConflict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "source": self.source,
            "target": self.target,
            "direction": self.direction,
            "conflict_policy": self.conflict_policy,
            "started_at": self.started_at.isoformat(),
            "ended_at": self.ended_at.isoformat() if self.ended_at else None,
            "summary": {
                "copied": self.summary.copied,
                "skipped": self.summary.skipped,
                "conflicts": self.summary.conflicts,
                "errors": self.summary.errors,
            },
            "conflicts": [
                {
                    "relative_path": conflict.relative_path,
                    "reason": conflict.reason,
                    "resolution": conflict.resolution,
                }
                for conflict in self.conflicts
            ],
            "errors": self.errors,
        }


class SyncManager:
    """Handles file synchronization between two paths."""

    def __init__(self, config: SyncConfig) -> None:
        self.config = config

    def run(
        self,
        source: Path,
        target: Path,
        direction: str | None = None,
        conflict_policy: str | None = None,
        exclude_patterns: Iterable[str] | None = None,
    ) -> SyncStatus:
        direction = direction or self.config.direction
        conflict_policy = conflict_policy or self.config.conflict_policy
        patterns = list(exclude_patterns or self.config.exclude_patterns)

        status = SyncStatus(
            source=str(source),
            target=str(target),
            direction=direction,
            conflict_policy=conflict_policy,
            started_at=datetime.now(),
        )

        self._run_hooks(self.config.schedule.on_start_hooks, status)

        try:
            source_map = self._snapshot_tree(source, patterns)
            target_map = self._snapshot_tree(target, patterns)

            if direction == "one-way":
                self._sync_one_way(source, target, source_map, target_map, status)
            elif direction == "two-way":
                self._sync_two_way(
                    source,
                    target,
                    source_map,
                    target_map,
                    conflict_policy,
                    status,
                )
            else:
                raise ValueError(f"Unsupported sync direction: {direction}")
        except Exception as exc:
            status.errors.append(str(exc))
            status.summary.errors += 1
        finally:
            status.ended_at = datetime.now()
            self.save_status(status)
            self._run_hooks(self.config.schedule.on_complete_hooks, status)

        return status

    def save_status(self, status: SyncStatus) -> None:
        """Persist sync status to configured status file."""
        path = self.config.status_file
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as handle:
            json.dump(status.to_dict(), handle, indent=2)

    def load_status(self) -> dict[str, object] | None:
        """Load last sync status from file."""
        path = self.config.status_file
        if not path.exists():
            return None
        with open(path) as handle:
            return json.load(handle)

    def _snapshot_tree(self, root: Path, patterns: list[str]) -> dict[str, FileSnapshot]:
        snapshot: dict[str, FileSnapshot] = {}
        if not root.exists():
            return snapshot

        for path in root.rglob("*"):
            if not path.is_file():
                continue
            relative_path = path.relative_to(root).as_posix()
            if self._is_excluded(relative_path, patterns):
                continue
            stat = path.stat()
            snapshot[relative_path] = FileSnapshot(
                path=path,
                relative_path=relative_path,
                size=stat.st_size,
                mtime=stat.st_mtime,
            )
        return snapshot

    def _is_excluded(self, relative_path: str, patterns: list[str]) -> bool:
        return any(fnmatch.fnmatch(relative_path, pattern) for pattern in patterns)

    def _sync_one_way(
        self,
        source: Path,
        target: Path,
        source_map: dict[str, FileSnapshot],
        target_map: dict[str, FileSnapshot],
        status: SyncStatus,
    ) -> None:
        for rel_path, src_snapshot in source_map.items():
            tgt_snapshot = target_map.get(rel_path)
            if tgt_snapshot is None or self._is_newer(src_snapshot, tgt_snapshot):
                try:
                    self._copy_file(src_snapshot.path, target / rel_path)
                    status.summary.copied += 1
                except Exception as exc:
                    status.errors.append(f"{rel_path}: {exc}")
                    status.summary.errors += 1
            else:
                status.summary.skipped += 1

    def _sync_two_way(
        self,
        source: Path,
        target: Path,
        source_map: dict[str, FileSnapshot],
        target_map: dict[str, FileSnapshot],
        conflict_policy: str,
        status: SyncStatus,
    ) -> None:
        all_paths = sorted(set(source_map) | set(target_map))
        for rel_path in all_paths:
            src_snapshot = source_map.get(rel_path)
            tgt_snapshot = target_map.get(rel_path)

            if src_snapshot and not tgt_snapshot:
                self._copy_with_status(src_snapshot.path, target / rel_path, rel_path, status)
                continue
            if tgt_snapshot and not src_snapshot:
                self._copy_with_status(tgt_snapshot.path, source / rel_path, rel_path, status)
                continue
            if not src_snapshot or not tgt_snapshot:
                continue

            if self._equivalent(src_snapshot, tgt_snapshot):
                status.summary.skipped += 1
                continue

            resolution = self._resolve_conflict(
                conflict_policy,
                source,
                target,
                src_snapshot,
                tgt_snapshot,
                rel_path,
                status,
            )
            if resolution == "skipped":
                status.summary.skipped += 1

    def _resolve_conflict(
        self,
        conflict_policy: str,
        source: Path,
        target: Path,
        src_snapshot: FileSnapshot,
        tgt_snapshot: FileSnapshot,
        rel_path: str,
        status: SyncStatus,
    ) -> str:
        if conflict_policy == "source_wins":
            self._copy_with_status(src_snapshot.path, target / rel_path, rel_path, status)
            return "source_wins"
        if conflict_policy == "target_wins":
            self._copy_with_status(tgt_snapshot.path, source / rel_path, rel_path, status)
            return "target_wins"
        if conflict_policy == "newest_wins":
            if self._is_newer(src_snapshot, tgt_snapshot):
                self._copy_with_status(src_snapshot.path, target / rel_path, rel_path, status)
                return "source_wins"
            self._copy_with_status(tgt_snapshot.path, source / rel_path, rel_path, status)
            return "target_wins"

        conflict = SyncConflict(
            relative_path=rel_path,
            reason="content_mismatch",
            resolution="skipped",
        )
        status.conflicts.append(conflict)
        status.summary.conflicts += 1
        self._run_hooks(
            self.config.schedule.on_conflict_hooks,
            status,
            conflict_path=rel_path,
        )
        return "skipped"

    def _copy_with_status(
        self,
        source: Path,
        destination: Path,
        rel_path: str,
        status: SyncStatus,
    ) -> None:
        try:
            self._copy_file(source, destination)
            status.summary.copied += 1
        except Exception as exc:
            status.errors.append(f"{rel_path}: {exc}")
            status.summary.errors += 1

    def _copy_file(self, source: Path, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)

    def _is_newer(self, source: FileSnapshot, target: FileSnapshot) -> bool:
        if source.mtime != target.mtime:
            return source.mtime > target.mtime
        return source.size != target.size

    def _equivalent(self, source: FileSnapshot, target: FileSnapshot) -> bool:
        return source.size == target.size and int(source.mtime) == int(target.mtime)

    def _run_hooks(
        self,
        hooks: Iterable[str],
        status: SyncStatus,
        conflict_path: str | None = None,
    ) -> None:
        if not hooks:
            return
        env = os.environ.copy()
        env.update(
            {
                "SYNC_SOURCE": status.source,
                "SYNC_TARGET": status.target,
                "SYNC_DIRECTION": status.direction,
                "SYNC_CONFLICT_POLICY": status.conflict_policy,
            }
        )
        if conflict_path:
            env["SYNC_CONFLICT_PATH"] = conflict_path
        for hook in hooks:
            try:
                subprocess.run(hook, shell=True, check=False, env=env)
            except Exception as exc:
                status.errors.append(f"hook:{hook}:{exc}")
                status.summary.errors += 1
