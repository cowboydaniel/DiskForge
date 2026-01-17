"""
Shared filesystem scanning helpers for cleanup-style operations.
"""

from __future__ import annotations

import fnmatch
import hashlib
import os
import shutil
from pathlib import Path
from typing import Iterable, Iterator

from diskforge.core.models import (
    DuplicateFileGroup,
    DuplicateScanResult,
    FileSelectionEntry,
    FileRemovalResult,
    FreeSpaceReport,
    JunkCleanupResult,
    JunkFile,
    JunkScanResult,
    LargeFileEntry,
    LargeFileScanResult,
    MoveApplicationResult,
)


def normalize_roots(roots: Iterable[str], fallback: Iterable[Path]) -> list[Path]:
    resolved = [Path(root).expanduser() for root in roots if root]
    if resolved:
        return resolved
    return [path for path in fallback]


def _match_exclude(path: Path, exclude_patterns: Iterable[str]) -> bool:
    for pattern in exclude_patterns:
        if fnmatch.fnmatch(path.as_posix(), pattern) or fnmatch.fnmatch(path.name, pattern):
            return True
    return False


def iter_files(
    roots: Iterable[Path],
    exclude_patterns: Iterable[str],
    *,
    follow_symlinks: bool = False,
    max_depth: int | None = None,
    include_symlinks: bool = False,
) -> Iterator[Path]:
    for root in roots:
        if not root.exists():
            continue
        root = root.resolve()
        for dirpath, dirnames, filenames in os.walk(root, followlinks=follow_symlinks):
            current = Path(dirpath)
            if max_depth is not None:
                relative_parts = current.relative_to(root).parts
                if len(relative_parts) >= max_depth:
                    dirnames[:] = []
            dirnames[:] = [d for d in dirnames if not _match_exclude(current / d, exclude_patterns)]
            for filename in filenames:
                path = current / filename
                if (path.is_symlink() and not include_symlinks) or _match_exclude(
                    path,
                    exclude_patterns,
                ):
                    continue
                yield path


def _root_archive_prefix(root: Path) -> Path:
    if root.name:
        return Path(root.name)
    sanitized = root.as_posix().strip("/").replace("/", "_")
    return Path(sanitized or "root")


def collect_file_selection(
    roots: Iterable[Path],
    exclude_patterns: Iterable[str],
    *,
    follow_symlinks: bool = False,
    max_depth: int | None = None,
) -> tuple[list[FileSelectionEntry], list[str], int]:
    selections: list[FileSelectionEntry] = []
    skipped: list[str] = []
    total_bytes = 0

    for root in roots:
        if not root.exists():
            skipped.append(str(root))
            continue
        if root.is_symlink() and not follow_symlinks:
            skipped.append(str(root))
            continue
        root = root.resolve()
        prefix = _root_archive_prefix(root)

        if root.is_file():
            if _match_exclude(root, exclude_patterns):
                continue
            stat_info = root.stat()
            size = stat_info.st_size
            total_bytes += size
            selections.append(
                FileSelectionEntry(
                    original_path=str(root),
                    archive_path=str(prefix),
                    is_dir=False,
                    size_bytes=size,
                    mode=stat_info.st_mode,
                    permissions=oct(stat_info.st_mode & 0o777),
                    uid=getattr(stat_info, "st_uid", None),
                    gid=getattr(stat_info, "st_gid", None),
                )
            )
            continue

        root_stat = root.stat() if follow_symlinks else root.lstat()
        selections.append(
            FileSelectionEntry(
                original_path=str(root),
                archive_path=str(prefix),
                is_dir=True,
                size_bytes=None,
                mode=root_stat.st_mode,
                permissions=oct(root_stat.st_mode & 0o777),
                uid=getattr(root_stat, "st_uid", None),
                gid=getattr(root_stat, "st_gid", None),
            )
        )

        for dirpath, dirnames, filenames in os.walk(root, followlinks=follow_symlinks):
            current = Path(dirpath)
            if max_depth is not None:
                relative_parts = current.relative_to(root).parts
                if len(relative_parts) >= max_depth:
                    dirnames[:] = []
            dirnames[:] = [d for d in dirnames if not _match_exclude(current / d, exclude_patterns)]
            for dirname in dirnames:
                dir_path = current / dirname
                if dir_path.is_symlink() and not follow_symlinks:
                    continue
                archive_path = prefix / dir_path.relative_to(root)
                dir_stat = dir_path.stat() if follow_symlinks else dir_path.lstat()
                selections.append(
                    FileSelectionEntry(
                        original_path=str(dir_path),
                        archive_path=str(archive_path),
                        is_dir=True,
                        size_bytes=None,
                        mode=dir_stat.st_mode,
                        permissions=oct(dir_stat.st_mode & 0o777),
                        uid=getattr(dir_stat, "st_uid", None),
                        gid=getattr(dir_stat, "st_gid", None),
                    )
                )
            for filename in filenames:
                file_path = current / filename
                if (file_path.is_symlink() and not follow_symlinks) or _match_exclude(
                    file_path,
                    exclude_patterns,
                ):
                    continue
                stat_info = file_path.stat() if follow_symlinks else file_path.lstat()
                size = stat_info.st_size
                total_bytes += size
                archive_path = prefix / file_path.relative_to(root)
                selections.append(
                    FileSelectionEntry(
                        original_path=str(file_path),
                        archive_path=str(archive_path),
                        is_dir=False,
                        size_bytes=size,
                        mode=stat_info.st_mode,
                        permissions=oct(stat_info.st_mode & 0o777),
                        uid=getattr(stat_info, "st_uid", None),
                        gid=getattr(stat_info, "st_gid", None),
                    )
                )

    return selections, skipped, total_bytes


def scan_junk_files(
    roots: Iterable[Path],
    exclude_patterns: Iterable[str],
    *,
    max_files: int | None = None,
) -> JunkScanResult:
    files: list[JunkFile] = []
    total_size = 0
    scanned = 0
    skipped: list[str] = []

    for root in roots:
        if not root.exists():
            skipped.append(str(root))
            continue
        category = root.name or str(root)
        for path in iter_files([root], exclude_patterns):
            try:
                size = path.stat().st_size
            except OSError:
                continue
            files.append(JunkFile(path=str(path), size_bytes=size, category=category))
            total_size += size
            scanned += 1
            if max_files is not None and scanned >= max_files:
                return JunkScanResult(
                    roots=[str(root) for root in roots],
                    total_size_bytes=total_size,
                    file_count=len(files),
                    files=files,
                    skipped_paths=skipped,
                )
    return JunkScanResult(
        roots=[str(root) for root in roots],
        total_size_bytes=total_size,
        file_count=len(files),
        files=files,
        skipped_paths=skipped,
    )


def cleanup_junk_files(
    roots: Iterable[Path],
    exclude_patterns: Iterable[str],
    *,
    max_files: int | None = None,
) -> JunkCleanupResult:
    scan = scan_junk_files(roots, exclude_patterns, max_files=max_files)
    removal = remove_paths([Path(item.path) for item in scan.files])
    return JunkCleanupResult(
        roots=scan.roots,
        removed_files=removal.removed,
        failed_files=removal.failed,
        freed_bytes=removal.freed_bytes,
        total_files_removed=len(removal.removed),
        total_files_failed=len(removal.failed),
    )


def scan_large_files(
    roots: Iterable[Path],
    exclude_patterns: Iterable[str],
    *,
    min_size_bytes: int,
    max_results: int | None = None,
) -> LargeFileScanResult:
    entries: list[LargeFileEntry] = []
    total_size = 0
    total_count = 0
    for path in iter_files(roots, exclude_patterns):
        try:
            size = path.stat().st_size
        except OSError:
            continue
        if size < min_size_bytes:
            continue
        total_count += 1
        total_size += size
        entries.append(LargeFileEntry(path=str(path), size_bytes=size))

    entries.sort(key=lambda entry: entry.size_bytes, reverse=True)
    if max_results is not None:
        entries = entries[:max_results]

    return LargeFileScanResult(
        roots=[str(root) for root in roots],
        min_size_bytes=min_size_bytes,
        total_size_bytes=total_size,
        file_count=total_count,
        files=entries,
    )


def _hash_file(path: Path, chunk_size: int = 1024 * 1024) -> str | None:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            while chunk := handle.read(chunk_size):
                digest.update(chunk)
    except OSError:
        return None
    return digest.hexdigest()


def scan_duplicate_files(
    roots: Iterable[Path],
    exclude_patterns: Iterable[str],
    *,
    min_size_bytes: int,
) -> DuplicateScanResult:
    by_size: dict[int, list[Path]] = {}
    skipped: list[str] = []
    for path in iter_files(roots, exclude_patterns):
        try:
            size = path.stat().st_size
        except OSError:
            continue
        if size < min_size_bytes:
            continue
        by_size.setdefault(size, []).append(path)

    groups: list[DuplicateFileGroup] = []
    wasted_bytes = 0
    for size, candidates in by_size.items():
        if len(candidates) < 2:
            continue
        by_hash: dict[str, list[Path]] = {}
        for path in candidates:
            file_hash = _hash_file(path)
            if not file_hash:
                skipped.append(str(path))
                continue
            by_hash.setdefault(file_hash, []).append(path)
        for file_hash, matches in by_hash.items():
            if len(matches) < 2:
                continue
            sorted_paths = sorted(str(path) for path in matches)
            groups.append(DuplicateFileGroup(size_bytes=size, file_hash=file_hash, paths=sorted_paths))
            wasted_bytes += size * (len(sorted_paths) - 1)

    return DuplicateScanResult(
        roots=[str(root) for root in roots],
        min_size_bytes=min_size_bytes,
        total_wasted_bytes=wasted_bytes,
        duplicate_groups=groups,
        skipped_paths=skipped,
    )


def remove_paths(paths: Iterable[Path]) -> FileRemovalResult:
    removed: list[str] = []
    failed: list[str] = []
    freed_bytes = 0

    for path in paths:
        if not path.exists():
            failed.append(str(path))
            continue
        try:
            if path.is_dir():
                freed_bytes += _dir_size(path)
                shutil.rmtree(path)
            else:
                freed_bytes += path.stat().st_size
                path.unlink()
            removed.append(str(path))
        except OSError:
            failed.append(str(path))

    return FileRemovalResult(
        removed=removed,
        failed=failed,
        freed_bytes=freed_bytes,
        message=_format_removal_message(removed, failed, freed_bytes),
    )


def _dir_size(path: Path) -> int:
    total = 0
    for root, _, files in os.walk(path):
        for filename in files:
            try:
                total += (Path(root) / filename).stat().st_size
            except OSError:
                continue
    return total


def _format_removal_message(removed: list[str], failed: list[str], freed_bytes: int) -> str:
    return (
        f"Removed {len(removed)} items, "
        f"failed to remove {len(failed)} items, "
        f"freed {freed_bytes} bytes."
    )


def build_free_space_report(
    roots: Iterable[Path],
    exclude_patterns: Iterable[str],
    *,
    junk_max_files: int | None,
    large_min_size_bytes: int,
    large_max_results: int | None,
    duplicate_min_size_bytes: int,
) -> FreeSpaceReport:
    junk_scan = scan_junk_files(roots, exclude_patterns, max_files=junk_max_files)
    large_scan = scan_large_files(
        roots,
        exclude_patterns,
        min_size_bytes=large_min_size_bytes,
        max_results=large_max_results,
    )
    duplicate_scan = scan_duplicate_files(roots, exclude_patterns, min_size_bytes=duplicate_min_size_bytes)

    total_reclaimable = (
        junk_scan.total_size_bytes
        + large_scan.total_size_bytes
        + duplicate_scan.total_wasted_bytes
    )
    return FreeSpaceReport(
        roots=junk_scan.roots,
        total_reclaimable_bytes=total_reclaimable,
        junk_bytes=junk_scan.total_size_bytes,
        large_files_bytes=large_scan.total_size_bytes,
        duplicate_bytes=duplicate_scan.total_wasted_bytes,
        junk_files=junk_scan.files,
        large_files=large_scan.files,
        duplicate_groups=duplicate_scan.duplicate_groups,
    )


def move_application(source: Path, destination_root: Path) -> MoveApplicationResult:
    source = source.expanduser()
    destination_root = destination_root.expanduser()
    if not source.exists():
        return MoveApplicationResult(
            success=False,
            message="Source path does not exist.",
            source_path=str(source),
            destination_path="",
            bytes_moved=0,
        )
    destination_root.mkdir(parents=True, exist_ok=True)
    destination = destination_root / source.name
    if destination.exists():
        return MoveApplicationResult(
            success=False,
            message="Destination path already exists.",
            source_path=str(source),
            destination_path=str(destination),
            bytes_moved=0,
        )
    bytes_moved = _dir_size(source) if source.is_dir() else source.stat().st_size
    try:
        shutil.move(str(source), str(destination))
    except OSError as exc:
        return MoveApplicationResult(
            success=False,
            message=str(exc),
            source_path=str(source),
            destination_path=str(destination),
            bytes_moved=0,
        )
    return MoveApplicationResult(
        success=True,
        message="Application moved successfully.",
        source_path=str(source),
        destination_path=str(destination),
        bytes_moved=bytes_moved,
    )
