"""迁移服务 —— 封装快速/完整模式和批量处理逻辑"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from app.services.backup_service import BackupService
from app.services.config_service import ConfigService
from app.services.world_transaction import WorldTransactionService
from core.batch_processor import (
    BatchCancelledError,
    BatchProcessor,
    scan_worlds_directory,
)
from core.i18n import t
from core.types import LogCallback, ProgressCallback


@dataclass(frozen=True)
class MigrationOptions:
    """单次迁移任务的不可变选项快照。

    将模式开关、目标平台/版本与手动玩家名从冗长位置参数中抽离，
    便于单存档与批量路径共享同一组选项。

    Attributes:
        mode: 迁移模式，``fast`` 或 ``full``。
        offline: 是否离线 UUID 解析。
        clean: 是否清理无用文件。
        pure_clean: 是否纯清理模式。
        target_platform: 目标平台标识（当前仅支持 ``java``）。
        target_version: 目标版本标识；非空表示跨版本（当前会拒绝）。
        manual_names: 手动指定的玩家名称列表。
    """

    mode: str
    offline: bool = False
    clean: bool = False
    pure_clean: bool = False
    target_platform: str = "java"
    target_version: str = ""
    manual_names: tuple[str, ...] = ()

    @classmethod
    def from_manual_names_str(
        cls,
        *,
        mode: str,
        offline: bool,
        clean: bool,
        pure_clean: bool,
        target_platform: str,
        target_version: str,
        manual_names_str: str,
    ) -> "MigrationOptions":
        """从逗号分隔玩家名字符串构造选项。

        Args:
            mode: 迁移模式。
            offline: 离线模式开关。
            clean: 清理模式开关。
            pure_clean: 纯清理模式开关。
            target_platform: 目标平台。
            target_version: 目标版本。
            manual_names_str: 逗号分隔的玩家名。

        Returns:
            MigrationOptions: 规范化后的选项快照。
        """
        names = tuple(
            name.strip()
            for name in manual_names_str.split(",")
            if name.strip()
        )
        return cls(
            mode=mode,
            offline=offline,
            clean=clean,
            pure_clean=pure_clean,
            target_platform=target_platform,
            target_version=target_version,
            manual_names=names,
        )


# run_fast / run_full 延迟导入：它们经 core.full_mode 顶层导入 NBT 实现，
# 启动期不需要。在实际调用 migrate 时才导入。


class MigrationService:
    """存档迁移服务

    职责：
      - 执行单存档迁移（快速/完整模式）
      - 执行批量迁移
      - 扫描批量目录
      - 管理进度回调
    """

    def __init__(
        self,
        config: ConfigService,
        backup_service: BackupService,
        world_transactions: WorldTransactionService,
    ) -> None:
        """注入配置与备份能力；批量处理器按需创建。

        Args:
            config: 应用配置（目标版本、清理策略等）。
            backup_service: 应用共享备份服务。
            world_transactions: 应用共享世界发布事务。
        """
        self._config: ConfigService = config
        self._backup_service = backup_service
        self._world_transactions = world_transactions
        self._batch_processor: Optional[BatchProcessor] = None
        self._batch_worlds: List[Path] = []
        self._scan_result: str = ""

    @property
    def batch_worlds(self) -> List[Path]:
        """批量处理的世界存档列表

        Returns:
            List[Path]: 世界存档路径列表
        """
        return self._batch_worlds

    @property
    def scan_result(self) -> str:
        """扫描结果信息

        Returns:
            str: 扫描结果描述
        """
        return self._scan_result

    def scan_batch_dir(self, directory: str) -> List[Path]:
        """扫描批量目录，返回世界存档列表

        Args:
            directory: 要扫描的目录路径

        Returns:
            List[Path]: 找到的世界存档路径列表
        """
        bp = Path(directory)
        if not bp.exists():
            return []
        worlds = scan_worlds_directory(bp)
        self._batch_worlds = worlds
        if worlds:
            names = ", ".join([w.name for w in worlds[:3]])
            if len(worlds) > 3:
                names += "..."
            self._scan_result = t(
                "messages.scanned_worlds",
                "扫描到 {count} 个世界存档: {names}",
                count=len(worlds), names=names,
            )
        else:
            self._scan_result = t(
                "messages.no_valid_worlds",
                "未找到有效的世界存档（需要包含level.dat）",
            )
        return worlds

    def run_single(
        self,
        src: str,
        dest: str,
        world_name: str,
        mode: str,
        offline: bool,
        clean: bool,
        pure_clean: bool,
        target_platform: str,
        target_version: str,
        manual_names_str: str,
        log_cb: LogCallback,
        progress_cb: ProgressCallback,
    ) -> str:
        """执行单存档迁移。

        See class docs and :class:`MigrationOptions` for parameter meaning.
        """
        options = MigrationOptions.from_manual_names_str(
            mode=mode,
            offline=offline,
            clean=clean,
            pure_clean=pure_clean,
            target_platform=target_platform,
            target_version=target_version,
            manual_names_str=manual_names_str,
        )
        src_path, dest_path, output_path = self._validate_single_inputs(
            src,
            dest,
            world_name,
            options.mode,
        )

        from core.performance import get_tracker
        tracker = get_tracker()
        with tracker.track(
            "存档迁移",
            {"name": world_name, "mode": options.mode},
        ):
            published = self._execute_single_transaction(
                src_path=src_path,
                dest_path=dest_path,
                output_path=output_path,
                world_name=world_name,
                options=options,
                log_cb=log_cb,
                progress_cb=progress_cb,
            )
        return str(published)

    def run_batch(
        self,
        dest_dir: str,
        mode: str,
        offline: bool,
        clean: bool,
        pure_clean: bool,
        target_platform: str,
        target_version: str,
        manual_names_str: str,
        max_concurrent: int,
        log_cb: LogCallback,
        progress_cb: ProgressCallback,
    ) -> Dict[str, Any]:
        """执行批量迁移。

        内部将公共选项收束为 :class:`MigrationOptions`，再交给
        :class:`BatchProcessor`。
        """
        if not dest_dir.strip():
            raise ValueError("批量目标输出目录不能为空")
        options = MigrationOptions.from_manual_names_str(
            mode=mode,
            offline=offline,
            clean=clean,
            pure_clean=pure_clean,
            target_platform=target_platform,
            target_version=target_version,
            manual_names_str=manual_names_str,
        )
        dest_path = Path(dest_dir).expanduser().resolve()
        dest_path.mkdir(parents=True, exist_ok=True)
        world_names = [
            f"world_{i + 1}" for i in range(len(self._batch_worlds))
        ]
        self._batch_processor = self._create_batch_processor(
            max_concurrent=max_concurrent,
            options=options,
        )
        return self._batch_processor.process_batch(
            self._batch_worlds,
            dest_path,
            world_names,
            options.mode,
            options.offline,
            options.clean,
            options.pure_clean,
            list(options.manual_names),
            log_cb,
            progress_cb,
        )

    def _create_batch_processor(
        self,
        *,
        max_concurrent: int,
        options: MigrationOptions,
    ) -> BatchProcessor:
        return BatchProcessor(
            max_concurrent,
            version_detector=self._config.detect_minecraft_version,
            custom_mappings=(
                self._config.custom_uuid_mappings
                if self._config.use_custom_mapping
                else None
            ),
            task_handler=self._make_batch_task_handler(options),
        )

    def _make_batch_task_handler(
        self,
        options: MigrationOptions,
    ) -> Callable[
        [Path, Path, str, LogCallback, threading.Event],
        Dict[str, Any],
    ]:
        """Build the per-world task callback used by :class:`BatchProcessor`."""

        def migrate_task(
            source: Path,
            destination: Path,
            world_name: str,
            local_log: LogCallback,
            cancel_event: threading.Event,
        ) -> Dict[str, Any]:
            src_path, task_dest, output_path = self._validate_single_inputs(
                str(source),
                str(destination),
                world_name,
                options.mode,
            )
            published = self._execute_single_transaction(
                src_path=src_path,
                dest_path=task_dest,
                output_path=output_path,
                world_name=world_name,
                options=options,
                log_cb=local_log,
                progress_cb=lambda value: None,
                cancel_event=cancel_event,
                region_workers=1,
            )
            return {"success": True, "output_path": str(published)}

        return migrate_task

    def cancel_batch(self) -> bool:
        """请求取消进行中的批量迁移。

        Returns:
            bool: 若存在运行中的批量任务并已发出取消请求则为 True。
        """
        processor = self._batch_processor
        if processor is None or not processor.is_running:
            return False
        processor.stop()
        return True

    def _validate_single_inputs(
        self,
        src: str,
        dest: str,
        world_name: str,
        mode: str,
    ) -> tuple[Path, Path, Path]:
        if not dest.strip():
            raise ValueError("目标输出目录不能为空")
        if mode not in {"fast", "full"}:
            raise ValueError(f"不支持的迁移模式: {mode}")
        src_path = Path(src).expanduser().resolve()
        dest_path = Path(dest).expanduser().resolve()
        if not src_path.is_dir() or not (src_path / "level.dat").is_file():
            raise ValueError("源目录不是有效 Minecraft 存档")
        from core.utils import safe_destination_world

        output_path = safe_destination_world(src_path, dest_path, world_name)
        if output_path.exists() and (
            not output_path.is_dir()
            or (any(output_path.iterdir()) and not (output_path / "level.dat").is_file())
        ):
            raise ValueError(f"目标目录不是 Minecraft 存档，拒绝覆盖: {output_path}")
        dest_path.mkdir(parents=True, exist_ok=True)
        return src_path, dest_path, output_path

    def _execute_single_transaction(
        self,
        *,
        src_path: Path,
        dest_path: Path,
        output_path: Path,
        world_name: str,
        options: MigrationOptions,
        log_cb: LogCallback,
        progress_cb: ProgressCallback,
        cancel_event: Optional[threading.Event] = None,
        region_workers: Optional[int] = None,
    ) -> Path:
        """在暂存目录完成迁移并原子发布到目标世界。"""
        manual = list(options.manual_names)
        with self._backup_service.exclusive_operation(output_path):
            self._raise_if_batch_cancelled(cancel_event)
            staging_root = Path(tempfile.mkdtemp(
                prefix=f".mcsavehelper_migrate_{world_name}_",
                dir=dest_path,
            ))
            try:
                return self._migrate_in_staging(
                    src_path=src_path,
                    dest_path=dest_path,
                    output_path=output_path,
                    world_name=world_name,
                    options=options,
                    manual=manual,
                    staging_root=staging_root,
                    log_cb=log_cb,
                    progress_cb=progress_cb,
                    cancel_event=cancel_event,
                    region_workers=region_workers,
                )
            finally:
                shutil.rmtree(staging_root, ignore_errors=True)

    def _migrate_in_staging(
        self,
        *,
        src_path: Path,
        dest_path: Path,
        output_path: Path,
        world_name: str,
        options: MigrationOptions,
        manual: List[str],
        staging_root: Path,
        log_cb: LogCallback,
        progress_cb: ProgressCallback,
        cancel_event: Optional[threading.Event],
        region_workers: Optional[int],
    ) -> Path:
        self._raise_if_batch_cancelled(cancel_event)
        self._run_migration_modes(
            src_path=src_path,
            staging_root=staging_root,
            world_name=world_name,
            options=options,
            manual=manual,
            log_cb=log_cb,
            progress_cb=progress_cb,
            region_workers=region_workers,
        )
        prepared_world = staging_root / world_name
        self._publish_prepared_world(
            prepared_world=prepared_world,
            dest_path=dest_path,
            output_path=output_path,
            world_name=world_name,
            options=options,
            log_cb=log_cb,
            cancel_event=cancel_event,
        )
        return output_path

    def _publish_prepared_world(
        self,
        *,
        prepared_world: Path,
        dest_path: Path,
        output_path: Path,
        world_name: str,
        options: MigrationOptions,
        log_cb: LogCallback,
        cancel_event: Optional[threading.Event],
    ) -> None:
        from core.utils import update_server_properties

        if not (prepared_world / "level.dat").is_file():
            raise RuntimeError("迁移产物无效：缺少 level.dat")
        if not self._apply_version_conversion(
            prepared_world,
            options.target_platform,
            options.target_version,
            log_cb,
        ):
            raise RuntimeError(
                "版本/平台转换失败，请查看日志获取详细信息"
            )
        self._raise_if_batch_cancelled(cancel_event)
        backup_record = self._world_transactions.publish_prepared(
            prepared_world,
            output_path,
            backup_label="迁移覆盖前自动备份",
            cancel_check=(
                cancel_event.is_set if cancel_event is not None else None
            ),
        )
        if backup_record is not None:
            log_cb(
                f"已备份现有目标: {backup_record.backup_path}",
                "BACKUP",
            )
        update_server_properties(dest_path, world_name, log_cb)

    def _run_migration_modes(
        self,
        *,
        src_path: Path,
        staging_root: Path,
        world_name: str,
        options: MigrationOptions,
        manual: List[str],
        log_cb: LogCallback,
        progress_cb: ProgressCallback,
        region_workers: Optional[int],
    ) -> None:
        from core.fast_mode import run_fast
        from core.full_mode import run_full

        if options.mode == "fast":
            run_fast(
                src_path,
                staging_root,
                world_name,
                options.offline,
                options.clean,
                options.pure_clean,
                manual,
                log_cb,
                region_workers,
            )
            return
        custom_mappings = (
            self._config.custom_uuid_mappings
            if self._config.use_custom_mapping
            else None
        )
        run_full(
            src_path,
            staging_root,
            world_name,
            options.offline,
            options.clean,
            options.pure_clean,
            manual,
            log_cb,
            progress_cb,
            custom_mappings,
            region_workers,
        )

    @staticmethod
    def _raise_if_batch_cancelled(
        cancel_event: Optional[threading.Event],
    ) -> None:
        if cancel_event is not None and cancel_event.is_set():
            raise BatchCancelledError("批量迁移已取消，产物未发布")

    def _apply_version_conversion(
        self,
        world_path: Path,
        target_platform: str,
        target_version: str,
        log_cb: LogCallback,
    ) -> bool:
        del world_path
        rejection_reason = self._conversion_rejection_reason(
            target_platform,
            target_version,
        )
        if rejection_reason is not None:
            log_cb(rejection_reason, "ERROR")
            return False
        return True

    @staticmethod
    def _conversion_rejection_reason(
        target_platform: str,
        target_version: str,
    ) -> Optional[str]:
        if target_platform != "java":
            return "尚未接入可靠的基岩版转换引擎，已拒绝迁移"
        if target_version.strip():
            return "尚未实现可靠的跨版本数据迁移，已拒绝版本降级"
        return None

    @staticmethod
    def open_folder(path: str) -> None:
        """在系统文件管理器中打开目录。

        Args:
            path: 要打开的目录路径。
        """
        try:
            system = platform.system()
            if system == "Windows":
                # os.startfile is Windows-only; getattr keeps cross-platform mypy clean.
                startfile = getattr(os, "startfile", None)
                if startfile is not None:
                    startfile(path)
            elif system == "Darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except (OSError, ValueError, subprocess.SubprocessError):
            # best-effort: open explorer failure must not affect migration.
            pass
