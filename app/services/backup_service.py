"""Transactional world backup and restore operations."""
from __future__ import annotations

import json
import hashlib
import os
import re
import secrets
import shutil
import tempfile
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Callable, Iterator, Optional

from core.logger import logger
from app.services.world_write_coordinator import (
    WorldWriteCoordinator,
    WorldWriteLease,
)


ProgressCallback = Callable[[float, str], None]
_BACKUP_ID_RE = re.compile(r"^\d{8}T\d{6}Z-[0-9a-f]{8}$")
_METADATA_FILE = "backup.json"
_MANIFEST_FILE = "manifest.json"
_SNAPSHOT_DIR = "world"
_REPOSITORY_DIR = ".mcsavehelper_backups"


class BackupError(RuntimeError):
    """Raised when a backup operation cannot be completed safely."""


class BackupCancelledError(BackupError):
    """Raised when the user cancels a backup operation."""


@dataclass(frozen=True)
class BackupRecord:
    """Metadata for one managed world snapshot."""

    backup_id: str
    label: str
    world_name: str
    source_path: str
    created_at: datetime
    size_bytes: int
    file_count: int
    backup_path: Path
    valid: bool = True
    validation_error: str = ""
    manifest_sha256: str = ""

    @property
    def integrity_available(self) -> bool:
        return bool(self.manifest_sha256)


@dataclass(frozen=True)
class BackupVerification:
    """Result of checking a snapshot against its immutable manifest."""

    valid: bool
    complete: bool
    checked_files: int
    checked_bytes: int
    issues: tuple[str, ...] = ()


@dataclass
class _ManifestVerification:
    expected_paths: set[str]
    checked_files: int
    checked_bytes: int
    issues: list[str]


class BackupService:
    """Create and publish backups without exposing arbitrary filesystem paths."""

    def __init__(
        self,
        coordinator: Optional[WorldWriteCoordinator] = None,
    ) -> None:
        self._cancel_event = threading.Event()
        self._coordinator = coordinator or WorldWriteCoordinator()

    def cancel(self) -> None:
        """Request cancellation at the next copy checkpoint."""
        self._cancel_event.set()

    def create_backup(
        self,
        world_path: Path | str,
        label: str = "",
        progress_callback: Optional[ProgressCallback] = None,
    ) -> BackupRecord:
        """Create a complete snapshot and publish it atomically."""
        world = self._validate_world(world_path)
        clean_label = self._validate_label(label)
        with self.exclusive_operation(world):
            self._cancel_event.clear()
            repository = self._ensure_repository(world)
            backup_id = self._new_backup_id(repository)
            final_dir = repository / backup_id
            temp_dir = Path(tempfile.mkdtemp(prefix=".creating-", dir=repository))
            try:
                files = list(self._iter_source_files(world))
                total_size = sum(size for _, _, size, _ in files)
                snapshot = temp_dir / _SNAPSHOT_DIR
                snapshot.mkdir()
                copied_size = self._copy_files(
                    files,
                    snapshot,
                    total_size,
                    progress_callback,
                    0.0,
                    0.92,
                )
                self._check_cancelled()
                manifest_sha256 = self._write_manifest(
                    temp_dir,
                    snapshot,
                    files,
                )
                record = BackupRecord(
                    backup_id=backup_id,
                    label=clean_label,
                    world_name=world.name,
                    source_path=str(world),
                    created_at=datetime.now(timezone.utc),
                    size_bytes=copied_size,
                    file_count=len(files),
                    backup_path=final_dir,
                    manifest_sha256=manifest_sha256,
                )
                self._write_metadata(temp_dir, record)
                self._progress(progress_callback, 0.96, "正在验证备份...")
                self._validate_snapshot(snapshot)
                os.replace(temp_dir, final_dir)
                self._progress(progress_callback, 1.0, "备份创建完成")
                logger.info(f"已创建存档备份: {final_dir}", module="Backup")
                return record
            except Exception:
                shutil.rmtree(temp_dir, ignore_errors=True)
                raise

    def list_backups(self, world_path: Path | str) -> list[BackupRecord]:
        """List managed backups, including damaged entries with an error state."""
        world = self._validate_world(world_path)
        repository = self._repository_path(world)
        if not repository.exists():
            return []
        self._assert_safe_directory(repository, world.parent)

        records: list[BackupRecord] = []
        for backup_dir in repository.iterdir():
            if not backup_dir.is_dir() or backup_dir.name.startswith("."):
                continue
            if not _BACKUP_ID_RE.fullmatch(backup_dir.name):
                continue
            try:
                record = self._read_record(world, backup_dir)
            except BackupError as exc:
                created_at = datetime.fromtimestamp(
                    backup_dir.stat().st_mtime,
                    tz=timezone.utc,
                )
                record = BackupRecord(
                    backup_id=backup_dir.name,
                    label="",
                    world_name=world.name,
                    source_path=str(world),
                    created_at=created_at,
                    size_bytes=0,
                    file_count=0,
                    backup_path=backup_dir,
                    valid=False,
                    validation_error=str(exc),
                )
            records.append(record)
        return sorted(records, key=lambda item: item.created_at, reverse=True)

    def restore_backup(
        self,
        world_path: Path | str,
        backup_id: str,
        progress_callback: Optional[ProgressCallback] = None,
    ) -> BackupRecord:
        """Restore a snapshot with a rollback directory exchange."""
        world = self._validate_world(world_path)
        with self.exclusive_operation(world):
            self._cancel_event.clear()
            record = self._get_record(world, backup_id)
            if not record.valid:
                raise BackupError(f"备份不可用: {record.validation_error}")

            verification = self._verify_record(
                record,
                lambda value, message: self._progress(
                    progress_callback,
                    value * 0.25,
                    message,
                ),
            )
            if verification.complete and not verification.valid:
                details = "; ".join(verification.issues[:3])
                raise BackupError(f"备份完整性校验失败: {details}")

            snapshot = record.backup_path / _SNAPSHOT_DIR
            files = list(self._iter_source_files(snapshot))
            total_size = sum(size for _, _, size, _ in files)
            staging_root = Path(tempfile.mkdtemp(
                prefix=f".{world.name}.restore-",
                dir=world.parent,
            ))
            prepared = staging_root / world.name
            prepared.mkdir()
            rollback = world.parent / f".{world.name}.rollback-{secrets.token_hex(4)}"
            published = False
            try:
                self._copy_files(
                    files,
                    prepared,
                    total_size,
                    progress_callback,
                    0.25,
                    0.63,
                )
                self._check_cancelled()
                self._progress(progress_callback, 0.92, "正在验证恢复数据...")
                self._validate_snapshot(prepared)

                os.replace(world, rollback)
                try:
                    os.replace(prepared, world)
                    published = True
                except Exception:
                    os.replace(rollback, world)
                    raise

                self._progress(progress_callback, 0.98, "正在清理旧数据...")
                try:
                    shutil.rmtree(rollback)
                except OSError as exc:
                    logger.warning(
                        f"备份恢复完成，但旧目录清理失败: {rollback}: {exc}",
                        module="Backup",
                    )
                self._progress(progress_callback, 1.0, "备份恢复完成")
                logger.info(
                    f"已恢复存档备份 {backup_id}: {world}",
                    module="Backup",
                )
                return record
            except Exception:
                if not published and rollback.exists() and not world.exists():
                    os.replace(rollback, world)
                raise
            finally:
                shutil.rmtree(staging_root, ignore_errors=True)

    def verify_backup(
        self,
        world_path: Path | str,
        backup_id: str,
        progress_callback: Optional[ProgressCallback] = None,
    ) -> BackupVerification:
        """Verify one managed snapshot without modifying world data."""
        world = self._validate_world(world_path)
        with self.exclusive_operation(world):
            record = self._get_record(world, backup_id)
            return self._verify_record(record, progress_callback)

    def prune_backups(
        self,
        world_path: Path | str,
        keep_latest: int,
    ) -> list[BackupRecord]:
        """Delete older managed snapshots while retaining the newest entries."""
        if keep_latest < 1:
            raise BackupError("至少需要保留 1 个恢复点")
        world = self._validate_world(world_path)
        with self.exclusive_operation(world):
            records = self.list_backups(world)
            removed: list[BackupRecord] = []
            repository = self._repository_path(world)
            for record in records[keep_latest:]:
                self._assert_safe_directory(record.backup_path, repository)
                shutil.rmtree(record.backup_path)
                removed.append(record)
            if removed:
                logger.info(
                    f"已清理 {len(removed)} 个旧恢复点: {world}",
                    module="Backup",
                )
            return removed

    def delete_backup(self, world_path: Path | str, backup_id: str) -> None:
        """Delete one managed backup selected by its generated identifier."""
        world = self._validate_world(world_path)
        with self.exclusive_operation(world):
            if not _BACKUP_ID_RE.fullmatch(backup_id):
                raise BackupError("无效的备份标识")
            repository = self._repository_path(world)
            self._assert_safe_directory(repository, world.parent)
            backup_path = repository / backup_id
            self._assert_safe_directory(backup_path, repository)
            shutil.rmtree(backup_path)
            logger.info(
                f"已删除存档备份 {backup_id}: {backup_path}",
                module="Backup",
            )

    def _get_record(
        self,
        world: Path,
        backup_id: str,
        validate_snapshot: bool = True,
    ) -> BackupRecord:
        if not _BACKUP_ID_RE.fullmatch(backup_id):
            raise BackupError("无效的备份标识")
        repository = self._repository_path(world)
        self._assert_safe_directory(repository, world.parent)
        backup_dir = repository / backup_id
        self._assert_safe_directory(backup_dir, repository)
        return self._read_record(world, backup_dir, validate_snapshot)

    def _read_record(
        self,
        world: Path,
        backup_dir: Path,
        validate_snapshot: bool = True,
    ) -> BackupRecord:
        self._assert_safe_directory(backup_dir, self._repository_path(world))
        metadata_path = backup_dir / _METADATA_FILE
        try:
            if metadata_path.stat().st_size > 64 * 1024:
                raise BackupError("备份元数据过大")
            data = json.loads(metadata_path.read_text(encoding="utf-8"))
            source_path = str(data["source_path"])
            if os.path.normcase(source_path) != os.path.normcase(str(world)):
                raise BackupError("备份不属于当前存档")
            created_at = datetime.fromisoformat(str(data["created_at"]))
            record = BackupRecord(
                backup_id=backup_dir.name,
                label=str(data.get("label", "")),
                world_name=str(data["world_name"]),
                source_path=source_path,
                created_at=created_at,
                size_bytes=int(data["size_bytes"]),
                file_count=int(data["file_count"]),
                backup_path=backup_dir,
                manifest_sha256=str(data.get("manifest_sha256", "")),
            )
        except BackupError:
            raise
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
            raise BackupError(f"无法读取备份元数据: {exc}") from exc
        if record.world_name != world.name:
            raise BackupError("备份世界名称不匹配")
        if record.size_bytes < 0 or record.file_count < 0:
            raise BackupError("备份元数据包含无效计数")
        if validate_snapshot:
            self._validate_snapshot(backup_dir / _SNAPSHOT_DIR)
        return record

    def _validate_world(self, world_path: Path | str) -> Path:
        if not str(world_path).strip():
            raise BackupError("存档路径不能为空")
        world = Path(world_path).expanduser().resolve()
        if not world.is_dir() or not (world / "level.dat").is_file():
            raise BackupError("请选择包含 level.dat 的有效存档目录")
        if self._is_link_or_reparse(world):
            raise BackupError("不支持通过符号链接或目录联接管理存档")
        return world

    @staticmethod
    def _validate_label(label: str) -> str:
        clean = label.strip()
        if len(clean) > 60:
            raise BackupError("备份备注不能超过 60 个字符")
        if any(ord(char) < 32 for char in clean):
            raise BackupError("备份备注不能包含控制字符")
        return clean

    def _ensure_repository(self, world: Path) -> Path:
        repository = self._repository_path(world)
        base = repository.parent
        base.mkdir(exist_ok=True)
        self._assert_safe_directory(base, world.parent)
        repository.mkdir(exist_ok=True)
        self._assert_safe_directory(repository, base)
        return repository

    @staticmethod
    def _repository_path(world: Path) -> Path:
        return world.parent / _REPOSITORY_DIR / world.name

    def _assert_safe_directory(self, path: Path, parent: Path) -> None:
        try:
            path.resolve().relative_to(parent.resolve())
        except (OSError, ValueError) as exc:
            raise BackupError(f"备份路径越过安全边界: {path}") from exc
        if not path.is_dir():
            raise BackupError(f"备份目录不存在: {path}")
        current = path
        while current != parent:
            if self._is_link_or_reparse(current):
                raise BackupError(f"备份路径包含符号链接或目录联接: {current}")
            current = current.parent

    @staticmethod
    def _is_link_or_reparse(path: Path) -> bool:
        if path.is_symlink():
            return True
        try:
            attributes = path.stat(follow_symlinks=False).st_file_attributes
        except (AttributeError, OSError):
            return False
        return bool(attributes & 0x400)

    def _iter_source_files(
        self,
        source: Path,
    ) -> Iterator[tuple[Path, Path, int, int]]:
        for root, directories, filenames in os.walk(source, followlinks=False):
            root_path = Path(root)
            for directory in directories:
                candidate = root_path / directory
                if self._is_link_or_reparse(candidate):
                    raise BackupError(f"存档中包含不支持的目录链接: {candidate}")
            for filename in filenames:
                candidate = root_path / filename
                if self._is_link_or_reparse(candidate):
                    raise BackupError(f"存档中包含不支持的文件链接: {candidate}")
                try:
                    stat = candidate.stat()
                except OSError as exc:
                    raise BackupError(f"无法读取存档文件: {candidate}") from exc
                yield (
                    candidate,
                    candidate.relative_to(source),
                    stat.st_size,
                    stat.st_mtime_ns,
                )

    def _copy_files(
        self,
        files: list[tuple[Path, Path, int, int]],
        destination: Path,
        total_size: int,
        progress_callback: Optional[ProgressCallback],
        progress_start: float,
        progress_span: float,
    ) -> int:
        copied_size = 0
        for index, source_file in enumerate(files, start=1):
            source, relative, expected_size, expected_mtime = source_file
            self._check_cancelled()
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            current_stat = source.stat()
            if (
                current_stat.st_size != expected_size
                or current_stat.st_mtime_ns != expected_mtime
            ):
                raise BackupError(f"复制期间源文件发生变化: {source}")
            copied_size += expected_size
            fraction = copied_size / total_size if total_size else index / max(len(files), 1)
            self._progress(
                progress_callback,
                progress_start + fraction * progress_span,
                f"正在复制文件 {index}/{len(files)}",
            )
        return copied_size

    def _check_cancelled(self) -> None:
        if self._cancel_event.is_set():
            raise BackupCancelledError("备份操作已取消")

    @staticmethod
    def _validate_snapshot(snapshot: Path) -> None:
        if not snapshot.is_dir() or not (snapshot / "level.dat").is_file():
            raise BackupError("备份快照不完整，缺少 level.dat")

    @staticmethod
    def _write_metadata(directory: Path, record: BackupRecord) -> None:
        data = {
            "schema_version": 1,
            "backup_id": record.backup_id,
            "label": record.label,
            "world_name": record.world_name,
            "source_path": record.source_path,
            "created_at": record.created_at.isoformat(),
            "size_bytes": record.size_bytes,
            "file_count": record.file_count,
            "manifest_sha256": record.manifest_sha256,
        }
        metadata = directory / _METADATA_FILE
        metadata.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _write_manifest(
        self,
        directory: Path,
        snapshot: Path,
        files: list[tuple[Path, Path, int, int]],
    ) -> str:
        entries = []
        for _, relative, expected_size, _ in files:
            target = snapshot / relative
            entries.append({
                "path": relative.as_posix(),
                "size": expected_size,
                "sha256": self._hash_file(target),
            })
        payload = json.dumps(
            {"schema_version": 1, "files": entries},
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        (directory / _MANIFEST_FILE).write_bytes(payload)
        return hashlib.sha256(payload).hexdigest()

    def _verify_record(
        self,
        record: BackupRecord,
        progress_callback: Optional[ProgressCallback],
    ) -> BackupVerification:
        if not record.integrity_available:
            return self._legacy_verification(progress_callback)
        try:
            entries = self._read_manifest(record)
        except BackupError as exc:
            return BackupVerification(
                valid=False,
                complete=True,
                checked_files=0,
                checked_bytes=0,
                issues=(str(exc),),
            )

        snapshot = record.backup_path / _SNAPSHOT_DIR
        manifest_result = self._verify_manifest_entries(
            entries,
            snapshot,
            progress_callback,
        )
        manifest_result.issues.extend(
            self._manifest_path_issues(snapshot, manifest_result.expected_paths)
        )
        self._progress(progress_callback, 1.0, "备份完整性校验完成")
        return BackupVerification(
            valid=not manifest_result.issues,
            complete=True,
            checked_files=manifest_result.checked_files,
            checked_bytes=manifest_result.checked_bytes,
            issues=tuple(manifest_result.issues),
        )

    def _verify_manifest_entries(
        self,
        entries: list[object],
        snapshot: Path,
        progress_callback: Optional[ProgressCallback],
    ) -> _ManifestVerification:
        expected_paths: set[str] = set()
        checked_files = 0
        checked_bytes = 0
        issues: list[str] = []
        for index, entry in enumerate(entries, start=1):
            try:
                checked_size = self._verify_manifest_entry(
                    entry,
                    snapshot,
                    expected_paths,
                )
                checked_files += 1
                checked_bytes += checked_size
            except (BackupError, OSError, ValueError) as exc:
                issues.append(str(exc))
            self._progress(
                progress_callback,
                index / max(len(entries), 1) * 0.9,
                f"正在校验文件 {index}/{len(entries)}",
            )
        return _ManifestVerification(
            expected_paths=expected_paths,
            checked_files=checked_files,
            checked_bytes=checked_bytes,
            issues=issues,
        )

    def _verify_manifest_entry(
        self,
        entry: object,
        snapshot: Path,
        expected_paths: set[str],
    ) -> int:
        relative, expected_size, expected_hash = self._manifest_entry(entry)
        path_key = relative.as_posix()
        if path_key in expected_paths:
            raise BackupError(f"清单包含重复路径: {path_key}")
        expected_paths.add(path_key)
        target = (snapshot / relative).resolve()
        target.relative_to(snapshot.resolve())
        if not target.is_file() or self._is_link_or_reparse(target):
            raise BackupError(f"备份文件缺失或类型无效: {path_key}")
        stat = target.stat()
        if stat.st_size != expected_size:
            raise BackupError(f"备份文件大小不匹配: {path_key}")
        if self._hash_file(target) != expected_hash:
            raise BackupError(f"备份文件摘要不匹配: {path_key}")
        return stat.st_size

    def _manifest_path_issues(
        self,
        snapshot: Path,
        expected_paths: set[str],
    ) -> list[str]:
        issues: list[str] = []
        try:
            actual_paths = {
                relative.as_posix()
                for _, relative, _, _ in self._iter_source_files(snapshot)
            }
            extras = actual_paths - expected_paths
            missing = expected_paths - actual_paths
            if extras:
                issues.append(f"备份包含清单外文件: {sorted(extras)[0]}")
            if missing:
                issues.append(f"备份缺少清单文件: {sorted(missing)[0]}")
        except BackupError as exc:
            issues.append(str(exc))
        return issues

    def _legacy_verification(
        self,
        progress_callback: Optional[ProgressCallback],
    ) -> BackupVerification:
        message = "旧版备份没有完整性清单"
        self._progress(progress_callback, 1.0, message)
        return BackupVerification(
            valid=True,
            complete=False,
            checked_files=0,
            checked_bytes=0,
            issues=(message,),
        )

    def _read_manifest(self, record: BackupRecord) -> list[object]:
        manifest_path = record.backup_path / _MANIFEST_FILE
        try:
            if manifest_path.stat().st_size > 64 * 1024 * 1024:
                raise BackupError("备份清单过大")
            payload = manifest_path.read_bytes()
            if hashlib.sha256(payload).hexdigest() != record.manifest_sha256:
                raise BackupError("备份清单摘要不匹配")
            data = json.loads(payload.decode("utf-8"))
            if data.get("schema_version") != 1:
                raise BackupError("不支持的备份清单版本")
            entries = data["files"]
            if not isinstance(entries, list):
                raise BackupError("备份清单文件列表无效")
            if len(entries) != record.file_count:
                raise BackupError("备份清单文件数量不匹配")
            return entries
        except BackupError:
            raise
        except (OSError, UnicodeError, ValueError, TypeError, KeyError) as exc:
            raise BackupError(f"无法读取备份清单: {exc}") from exc

    @staticmethod
    def _manifest_entry(entry: object) -> tuple[Path, int, str]:
        if not isinstance(entry, dict):
            raise BackupError("备份清单条目类型无效")
        raw_path = entry.get("path")
        size = entry.get("size")
        digest = entry.get("sha256")
        if not isinstance(raw_path, str) or not raw_path:
            raise BackupError("备份清单路径无效")
        pure_path = PurePosixPath(raw_path)
        if "\\" in raw_path or pure_path.is_absolute() or any(
            part in {"", ".", ".."} for part in pure_path.parts
        ) or any(":" in part for part in pure_path.parts):
            raise BackupError(f"备份清单路径越界: {raw_path}")
        if not isinstance(size, int) or size < 0:
            raise BackupError(f"备份清单大小无效: {raw_path}")
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise BackupError(f"备份清单摘要无效: {raw_path}")
        return Path(*pure_path.parts), size, digest

    @staticmethod
    def _hash_file(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _progress(
        callback: Optional[ProgressCallback],
        value: float,
        message: str,
    ) -> None:
        if callback:
            callback(min(max(value, 0.0), 1.0), message)

    @staticmethod
    def _new_backup_id(repository: Path) -> str:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        while True:
            backup_id = f"{timestamp}-{secrets.token_hex(4)}"
            if not (repository / backup_id).exists():
                return backup_id

    def exclusive_operation(self, world_path: Path | str) -> WorldWriteLease:
        """Reserve backup/restore publication for a larger write workflow."""
        return self._coordinator.reserve(world_path)
