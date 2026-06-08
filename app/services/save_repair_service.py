"""Save Repair Service - 存档修复服务

修复损坏的区块、玩家数据、level.dat 错误。
支持并发处理、主动修复、取消操作、存档检测。
"""
import shutil
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import List, Dict, Any, Optional, Callable, Tuple, Set

import nbtlib
from nbtlib import Compound, String, Float, Int, List as NbtList, Double
from anvil import Region

from core.logger import logger
from core.scanner import scan_all_regions
from core.constants import MinecraftConstants


class IssueLevel(Enum):
    """问题严重程度"""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    FIXED = "fixed"


@dataclass
class RepairIssue:
    """单条修复问题记录"""
    level: IssueLevel
    category: str
    message: str
    file_path: str = ""


@dataclass
class RepairReport:
    """修复报告"""
    chunks_checked: int = 0
    chunks_damaged: int = 0
    chunks_quarantined_regions: int = 0
    players_checked: int = 0
    players_fixed: int = 0
    players_quarantined: int = 0
    level_dat_fixed: bool = False
    level_dat_repaired_fields: List[str] = field(default_factory=list)
    backup_path: str = ""
    elapsed_seconds: float = 0.0
    cancelled: bool = False
    issues: List[RepairIssue] = field(default_factory=list)

    @property
    def total_fixes(self) -> int:
        return (
            self.chunks_damaged
            + self.chunks_quarantined_regions * 1024
            + self.players_fixed
            + self.players_quarantined
            + (1 if self.level_dat_fixed else 0)
        )

    def summary_text(self) -> str:
        lines = [
            f"区块检查: {self.chunks_checked}",
            f"区块损坏: {self.chunks_damaged}",
            f"区域文件隔离: {self.chunks_quarantined_regions}",
            f"玩家检查: {self.players_checked}",
            f"玩家修复: {self.players_fixed}",
            f"玩家隔离: {self.players_quarantined}",
            f"level.dat: {'已修复' if self.level_dat_fixed else '正常'}",
        ]
        if self.level_dat_repaired_fields:
            lines.append(
                f"  修复字段: {
                    ', '.join(
                        self.level_dat_repaired_fields)}")
        if self.backup_path:
            lines.append(f"备份位置: {self.backup_path}")
        lines.append(f"耗时: {self.elapsed_seconds:.1f}s")
        if self.cancelled:
            lines.append("(操作已取消)")
        return "\n".join(lines)


@dataclass
class WorldInfo:
    """世界基本信息"""
    world_name: str = ""
    data_version: int = 0
    version_name: str = ""
    game_type: int = 0
    game_type_name: str = ""
    difficulty: int = 2
    difficulty_name: str = ""
    seed: int = 0
    spawn_pos: Tuple[int, int, int] = (0, 64, 0)
    world_size_mb: float = 0.0
    total_files: int = 0
    dimensions: List[str] = field(default_factory=list)
    region_count: int = 0
    total_chunks: int = 0
    player_count: int = 0
    has_level_dat: bool = False
    has_level_dat_old: bool = False
    play_time_ticks: int = 0


@dataclass
class DetectReport:
    """存档检测报告（只读，不修改任何文件）"""
    world_info: WorldInfo = field(default_factory=WorldInfo)
    chunks_checked: int = 0
    chunks_damaged: int = 0
    unreadable_regions: List[str] = field(default_factory=list)
    players_checked: int = 0
    players_with_issues: int = 0
    player_issues: Dict[str, List[str]] = field(default_factory=dict)
    level_dat_ok: bool = False
    level_dat_issues: List[str] = field(default_factory=list)
    elapsed_seconds: float = 0.0
    cancelled: bool = False
    issues: List[RepairIssue] = field(default_factory=list)

    @property
    def has_problems(self) -> bool:
        return (
            self.chunks_damaged > 0
            or len(self.unreadable_regions) > 0
            or self.players_with_issues > 0
            or not self.level_dat_ok
        )

    def summary_text(self) -> str:
        lines: List[str] = []
        info = self.world_info

        lines.append("── 世界信息 ──")
        if info.world_name:
            lines.append(f"名称: {info.world_name}")
        if info.version_name:
            lines.append(
                f"版本: {
                    info.version_name} (DataVersion {
                    info.data_version})")
        if info.game_type_name:
            lines.append(f"模式: {info.game_type_name}")
        lines.append(f"难度: {info.difficulty_name}")
        lines.append(f"种子: {info.seed}")
        lines.append(f"出生点: {info.spawn_pos}")
        if info.play_time_ticks > 0:
            hours = info.play_time_ticks / 72000
            lines.append(f"游戏时间: {hours:.1f} 小时")
        lines.append(f"存档大小: {info.world_size_mb:.1f} MB")
        lines.append(
            f"维度: {
                ', '.join(
                    info.dimensions) if info.dimensions else '无'}")
        lines.append(f"区域文件: {info.region_count}, 区块: {info.total_chunks}")
        lines.append(f"玩家: {info.player_count}")

        lines.append("")
        lines.append("── 检测结果 ──")
        lines.append(f"区块检查: {self.chunks_checked}, 损坏: {self.chunks_damaged}")
        if self.unreadable_regions:
            lines.append(f"无法读取的区域文件: {len(self.unreadable_regions)}")
            for name in self.unreadable_regions[:10]:
                lines.append(f"  - {name}")
            if len(self.unreadable_regions) > 10:
                lines.append(f"  ... 共 {len(self.unreadable_regions)} 个")
        lines.append(
            f"玩家检查: {
                self.players_checked}, 有问题: {
                self.players_with_issues}")
        if self.player_issues:
            for pname, pissues in list(self.player_issues.items())[:5]:
                lines.append(f"  {pname}: {', '.join(pissues)}")
        lines.append(f"level.dat: {'正常' if self.level_dat_ok else '异常'}")
        if self.level_dat_issues:
            for issue in self.level_dat_issues:
                lines.append(f"  - {issue}")

        lines.append(f"\n耗时: {self.elapsed_seconds:.1f}s")
        if self.cancelled:
            lines.append("(操作已取消)")

        if not self.has_problems:
            lines.append("\n存档状态良好，未发现问题。")
        else:
            lines.append(f"\n发现 {len(self.issues)} 个问题，建议执行修复。")

        return "\n".join(lines)


_GAME_TYPE_NAMES = {0: "生存", 1: "创造", 2: "冒险", 3: "旁观"}
_DIFFICULTY_NAMES = {0: "和平", 1: "简单", 2: "普通", 3: "困难"}


# level.dat 中 Data 下的必需字段及其默认值
_LEVEL_DAT_REQUIRED_FIELDS: Dict[str, Any] = {
    "DataVersion": 0,
    "version": None,
    "LevelName": "World",
    "generatorName": "default",
    "SpawnX": 0,
    "SpawnY": 64,
    "SpawnZ": 0,
    "RandomSeed": 0,
    "Time": 0,
    "DayTime": 0,
    "GameType": 0,
    "Difficulty": 2,
    "DifficultyLocked": 0,
    "allowCommands": 1,
    "initialized": 1,
    "WorldGenSettings": None,
}

# 玩家数据必需字段及默认值工厂函数（避免跨文件共享可变对象）


def _player_defaults() -> Dict[str, Any]:
    return {
        "Pos": NbtList[NbtList[Double]]([
            NbtList[Double]([0.0, 64.0, 0.0])
        ]),
        "Rotation": NbtList[NbtList[Float]]([
            NbtList[Float]([0.0, 0.0])
        ]),
        "Health": Float(20.0),
        "foodLevel": Int(20),
        "foodSaturationLevel": Float(5.0),
        "XpLevel": Int(0),
        "XpP": Float(0.0),
        "Inventory": NbtList[Compound]([]),
        "Dimension": String("minecraft:overworld"),
        "playerGameType": Int(0),
    }


class SaveRepairService:
    """存档修复服务"""

    CHUNKS_PER_REGION = 1024

    def __init__(self) -> None:
        self._cancel_event = threading.Event()

    def cancel(self) -> None:
        """请求取消正在进行的修复操作"""
        self._cancel_event.set()

    @property
    def is_cancelled(self) -> bool:
        return self._cancel_event.is_set()

    # ── 存档检测（只读）────────────────────────────────────

    def detect_world(
        self,
        world_path: Path,
        progress_callback: Optional[Callable[[float, str], None]] = None,
        log_callback: Optional[Callable[[str, str], None]] = None,
    ) -> DetectReport:
        """检测存档状态（只读，不修改任何文件）

        Args:
            world_path: 存档路径
            progress_callback: 进度回调
            log_callback: 日志回调

        Returns:
            DetectReport 检测报告
        """
        self._cancel_event.clear()
        report = DetectReport()
        start_time = time.monotonic()

        def log(msg: str, level: str = "INFO") -> None:
            getattr(
                logger,
                level.lower(),
                logger.info)(
                msg,
                module="SaveDetect")
            if log_callback:
                log_callback(msg, level)
            issue_level = {
                "INFO": IssueLevel.INFO,
                "WARNING": IssueLevel.WARNING,
                "ERROR": IssueLevel.ERROR,
                "SUCCESS": IssueLevel.FIXED,
            }.get(level.upper(), IssueLevel.INFO)
            report.issues.append(RepairIssue(
                level=issue_level,
                category="detect",
                message=msg,
            ))

        def progress(value: float, msg: str) -> None:
            if progress_callback:
                progress_callback(min(value, 1.0), msg)

        try:
            if not world_path.exists():
                raise FileNotFoundError(f"存档路径不存在: {world_path}")

            log(f"开始检测存档: {world_path}")

            # 1. 基本信息
            progress(0.05, "读取世界信息...")
            self._detect_world_info(world_path, report, log)

            # 2. 区块检测
            progress(0.15, "扫描区块文件...")
            self._detect_chunks(world_path, report, log, progress)

            # 3. 玩家检测
            progress(0.80, "检测玩家数据...")
            self._detect_players(world_path, report, log)

            # 4. level.dat 检测
            progress(0.92, "检测 level.dat...")
            self._detect_level_dat(world_path, report, log)

            if self.is_cancelled:
                report.cancelled = True
                log("检测操作已取消", "WARNING")

            progress(1.0, "检测完成")
            if report.has_problems:
                log(f"检测完成，发现 {len(report.issues)} 个问题", "WARNING")
            else:
                log("检测完成，存档状态良好", "SUCCESS")

        except Exception as e:
            log(f"检测失败: {e}", "ERROR")
            logger.error(str(e), module="SaveDetect")

        report.elapsed_seconds = time.monotonic() - start_time
        return report

    def _detect_world_info(
        self,
        world_path: Path,
        report: DetectReport,
        log: Callable[[str, str], None],
    ) -> None:
        info = report.world_info
        info.world_name = world_path.name

        # 存档大小和文件数（单次 stat 调用，避免双重 stat）
        total_size = 0
        file_count = 0
        for entry in world_path.rglob("*"):
            try:
                st = entry.stat()
                if st.st_mode & 0o170000 == 0o100000:
                    total_size += st.st_size
                    file_count += 1
            except OSError:
                pass
        info.world_size_mb = total_size / (1024 * 1024)
        info.total_files = file_count

        # level.dat 存在性
        info.has_level_dat = (world_path / "level.dat").exists()
        info.has_level_dat_old = (world_path / "level.dat_old").exists()

        # 从 level.dat 读取世界信息
        if info.has_level_dat:
            try:
                nbt_data = nbtlib.load(str(world_path / "level.dat"))
                data = nbt_data.get("Data", {})
                if isinstance(data, nbtlib.tag.Compound):
                    info.data_version = int(data.get("DataVersion", 0))
                    info.version_name = MinecraftConstants.VERSION_MAP.get(
                        info.data_version, f"未知({info.data_version})"
                    )
                    info.game_type = int(data.get("GameType", 0))
                    info.game_type_name = _GAME_TYPE_NAMES.get(
                        info.game_type, "未知")
                    info.difficulty = int(data.get("Difficulty", 2))
                    info.difficulty_name = _DIFFICULTY_NAMES.get(
                        info.difficulty, "未知")
                    info.seed = int(data.get("RandomSeed", 0))
                    info.spawn_pos = (
                        int(data.get("SpawnX", 0)),
                        int(data.get("SpawnY", 64)),
                        int(data.get("SpawnZ", 0)),
                    )
                    info.play_time_ticks = int(data.get("Time", 0))
            except Exception as e:
                log(f"无法读取 level.dat 基本信息: {e}", "WARNING")

        # 维度和区域文件
        region_files = scan_all_regions(world_path)
        info.region_count = len(region_files)
        dimensions: Set[str] = set()
        for rf in region_files:
            rel = rf.relative_to(world_path)
            parts = rel.parts
            if len(parts) >= 3 and parts[0] == "region":
                dimensions.add("minecraft:overworld")
            elif len(parts) >= 3 and parts[0] == "DIM-1":
                dimensions.add("minecraft:the_nether")
            elif len(parts) >= 3 and parts[0] == "DIM1":
                dimensions.add("minecraft:the_end")
            elif "dimensions" in parts:
                idx = parts.index("dimensions")
                if idx + 2 < len(parts):
                    dimensions.add(f"{parts[idx]}:{parts[idx + 1]}")
        info.dimensions = sorted(dimensions)

        # 估算总区块数（只统计可读文件大小，不打开）
        info.total_chunks = 0
        for rf in region_files:
            try:
                size = rf.stat().st_size
                # 每个区域文件最多 1024 个区块
                # 简单按大小估算有数据的区块
                info.total_chunks += min(1024, max(0, size // 4096))
            except OSError:
                pass

        # 玩家数量
        playerdata_dir = world_path / "playerdata"
        if playerdata_dir.exists():
            info.player_count = len(list(playerdata_dir.glob("*.dat")))

        log(
            f"世界: {
                info.world_name}, 版本: {
                info.version_name}, " f"大小: {
                info.world_size_mb:.1f}MB, 区域: {
                    info.region_count}, 玩家: {
                        info.player_count}",
            "INFO",
        )

    def _detect_chunks(
        self,
        world_path: Path,
        report: DetectReport,
        log: Callable[[str, str], None],
        progress: Callable[[float, str], None],
    ) -> None:
        region_files = scan_all_regions(world_path)
        total = len(region_files)

        if total == 0:
            log("未找到区块文件", "WARNING")
            return

        log(f"找到 {total} 个区域文件，开始逐块检测...", "INFO")
        report.chunks_checked = total * self.CHUNKS_PER_REGION

        completed = 0
        lock = threading.Lock()

        def detect_region(
                idx: int, region_file: Path) -> Tuple[int, List[str]]:
            """检测单个区域文件，返回 (损坏区块数, 问题列表)"""
            if self.is_cancelled:
                return 0, []

            damaged = 0
            problems: List[str] = []

            try:
                region = Region.from_file(str(region_file))

                for chunk_x in range(32):
                    for chunk_z in range(32):
                        if self.is_cancelled:
                            return damaged, problems
                        try:
                            chunk = region.get_chunk(chunk_x, chunk_z)
                            if chunk is not None:
                                if not self._validate_chunk(chunk):
                                    damaged += 1
                                    problems.append(
                                        f"区块({chunk_x},{chunk_z})数据无效")
                        except Exception:
                            damaged += 1

                if damaged > 0:
                    log(f"{region_file.name}: {damaged} 个损坏区块", "WARNING")

            except Exception as e:
                problems.append(f"无法读取: {e}")
                log(f"无法读取区域文件 {region_file.name}: {e}", "ERROR")
                with lock:
                    report.unreadable_regions.append(region_file.name)

            with lock:
                nonlocal completed
                completed += 1
                progress(
                    0.15 + (completed / total) * 0.65,
                    f"检测区块文件 {completed}/{total}",
                )

            return damaged, problems

        max_workers = min(max(1, (total + 3) // 4), 8)

        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {
                pool.submit(detect_region, idx, rf): rf
                for idx, rf in enumerate(region_files)
            }
            for future in as_completed(futures):
                if self.is_cancelled:
                    pool.shutdown(wait=False, cancel_futures=True)
                    break
                try:
                    d, _ = future.result(timeout=120)
                    report.chunks_damaged += d
                except Exception as e:
                    rf = futures[future]
                    log(f"检测 {rf.name} 异常: {e}", "ERROR")

    def _detect_players(
        self,
        world_path: Path,
        report: DetectReport,
        log: Callable[[str, str], None],
    ) -> None:
        playerdata_dir = world_path / "playerdata"
        if not playerdata_dir.exists():
            log("playerdata 目录不存在", "INFO")
            return

        player_files = list(playerdata_dir.glob("*.dat"))
        report.players_checked = len(player_files)
        log(f"找到 {len(player_files)} 个玩家数据文件", "INFO")

        for player_file in player_files:
            if self.is_cancelled:
                break

            issues: List[str] = []
            try:
                nbt_data = nbtlib.load(str(player_file))

                missing = self._find_missing_player_fields(nbt_data)
                if missing:
                    issues.append(f"缺失字段: {', '.join(missing)}")

                # 检查 Health 值范围
                if "Health" in nbt_data:
                    try:
                        health = float(nbt_data["Health"])
                        if health < 0 or health > 20:
                            issues.append(f"Health 值异常: {health}")
                    except (ValueError, TypeError):
                        issues.append("Health 值类型错误")

            except Exception as e:
                issues.append(f"无法读取: {e}")

            if issues:
                report.players_with_issues += 1
                report.player_issues[player_file.name] = issues
                log(f"玩家 {player_file.name}: {'; '.join(issues)}", "WARNING")

    def _detect_level_dat(
        self,
        world_path: Path,
        report: DetectReport,
        log: Callable[[str, str], None],
    ) -> None:
        level_dat = world_path / "level.dat"
        level_dat_old = world_path / "level.dat_old"

        if not level_dat.exists():
            report.level_dat_ok = False
            report.level_dat_issues.append("level.dat 不存在")
            if level_dat_old.exists():
                report.level_dat_issues.append("可用 level.dat_old 恢复")
                log("level.dat 不存在，但 level.dat_old 可用", "WARNING")
            else:
                report.level_dat_issues.append("level.dat_old 也不存在，无法恢复")
                log("level.dat 和 level.dat_old 都不存在", "ERROR")
            return

        try:
            nbt_data = nbtlib.load(str(level_dat))
        except Exception as e:
            report.level_dat_ok = False
            report.level_dat_issues.append(f"NBT 解析失败: {e}")
            log(f"level.dat 无法解析: {e}", "ERROR")
            return

        if "Data" not in nbt_data:
            report.level_dat_ok = False
            report.level_dat_issues.append("缺少 Data 字段")
            log("level.dat 缺少 Data 字段", "ERROR")
            return

        data = nbt_data["Data"]
        if not isinstance(data, nbtlib.tag.Compound):
            report.level_dat_ok = False
            report.level_dat_issues.append("Data 字段类型错误")
            log("level.dat 的 Data 字段类型错误", "ERROR")
            return

        # 检查必需字段
        missing_fields: List[str] = []
        for field_name, default_value in _LEVEL_DAT_REQUIRED_FIELDS.items():
            if field_name not in data and default_value is not None:
                missing_fields.append(field_name)

        # 检查范围异常
        range_issues: List[str] = []
        for spawn_field in ("SpawnX", "SpawnY", "SpawnZ"):
            if spawn_field in data:
                try:
                    val = int(data[spawn_field])
                    if spawn_field == "SpawnY" and (val < -64 or val > 320):
                        range_issues.append(f"{spawn_field} 超出范围: {val}")
                except (ValueError, TypeError):
                    range_issues.append(f"{spawn_field} 值类型错误")

        if "Difficulty" in data:
            try:
                val = int(data["Difficulty"])
                if val < 0 or val > 3:
                    range_issues.append(f"Difficulty 超出范围: {val}")
            except (ValueError, TypeError):
                range_issues.append("Difficulty 值类型错误")

        report.level_dat_issues = [
            *(f"缺失字段: {f}" for f in missing_fields),
            *range_issues,
        ]
        report.level_dat_ok = len(report.level_dat_issues) == 0

        if report.level_dat_ok:
            log("level.dat 验证通过", "INFO")
        else:
            for issue in report.level_dat_issues:
                log(f"level.dat: {issue}", "WARNING")

    # ── 修复接口 ──────────────────────────────────────────

    def repair_world(
        self,
        world_path: Path,
        fix_chunks: bool = True,
        fix_players: bool = True,
        fix_level_dat: bool = True,
        backup: bool = True,
        max_workers: int = 4,
        progress_callback: Optional[Callable[[float, str], None]] = None,
        log_callback: Optional[Callable[[str, str], None]] = None,
    ) -> RepairReport:
        """修复世界存档

        Args:
            world_path: 存档路径
            fix_chunks: 是否修复区块
            fix_players: 是否修复玩家数据
            fix_level_dat: 是否修复 level.dat
            backup: 是否备份
            max_workers: 并发处理区域文件的最大线程数
            progress_callback: 进度回调 (0.0~1.0, 描述)
            log_callback: 日志回调 (消息, 级别)

        Returns:
            RepairReport 修复报告
        """
        self._cancel_event.clear()
        report = RepairReport()
        start_time = time.monotonic()

        def log(msg: str, level: str = "INFO") -> None:
            getattr(
                logger,
                level.lower(),
                logger.info)(
                msg,
                module="SaveRepair")
            if log_callback:
                log_callback(msg, level)
            issue_level = {
                "INFO": IssueLevel.INFO,
                "WARNING": IssueLevel.WARNING,
                "ERROR": IssueLevel.ERROR,
                "SUCCESS": IssueLevel.FIXED,
            }.get(level.upper(), IssueLevel.INFO)
            report.issues.append(RepairIssue(
                level=issue_level,
                category="general",
                message=msg,
            ))

        def progress(value: float, msg: str) -> None:
            if progress_callback:
                progress_callback(min(value, 1.0), msg)

        try:
            if not world_path.exists():
                raise FileNotFoundError(f"存档路径不存在: {world_path}")

            log(f"开始修复存档: {world_path}")

            # 备份
            if backup and not self.is_cancelled:
                progress(0.02, "创建备份...")
                try:
                    backup_path = self._create_backup(world_path, progress)
                    report.backup_path = str(backup_path)
                    log(f"已创建备份: {backup_path}", "SUCCESS")
                except Exception as e:
                    log(f"备份失败: {e}", "ERROR")
                    report.backup_path = ""

            # 修复区块
            if fix_chunks and not self.is_cancelled:
                progress(0.10, "扫描区块文件...")
                self._repair_chunks(world_path, report, log, progress)

            # 修复玩家数据
            if fix_players and not self.is_cancelled:
                progress(0.75, "修复玩家数据...")
                self._repair_players(world_path, report, log)

            # 修复 level.dat
            if fix_level_dat and not self.is_cancelled:
                progress(0.90, "修复 level.dat...")
                self._repair_level_dat(world_path, report, log)

            if self.is_cancelled:
                report.cancelled = True
                log("修复操作已取消", "WARNING")

            progress(1.0, "修复完成")
            log(
                f"修复完成 - 区块: {report.chunks_checked} 检查/{report.chunks_damaged} 损坏, "
                f"玩家: {report.players_checked} 检查/{report.players_fixed} 修复",
                "SUCCESS",
            )

        except Exception as e:
            log(f"修复失败: {e}", "ERROR")
            logger.error(str(e), module="SaveRepair")

        report.elapsed_seconds = time.monotonic() - start_time
        return report

    # ── 备份 ──────────────────────────────────────────────

    def _create_backup(
        self,
        world_path: Path,
        progress: Callable[[float, str], None],
    ) -> Path:
        import tempfile

        backup_name = f"{world_path.name}_backup"
        backup_path = world_path.parent / backup_name

        counter = 1
        while backup_path.exists():
            backup_path = world_path.parent / f"{backup_name}_{counter}"
            counter += 1

        temp_backup_dir: Optional[Path] = None
        try:
            temp_backup_dir = Path(
                tempfile.mkdtemp(
                    prefix="mcsavehelper_backup_"))
            dest = temp_backup_dir / world_path.name

            # 带进度的复制
            self._copytree_with_progress(world_path, dest, progress)

            shutil.move(str(dest), str(backup_path))
            return backup_path

        except Exception as e:
            if temp_backup_dir and temp_backup_dir.exists():
                shutil.rmtree(temp_backup_dir, ignore_errors=True)
            raise RuntimeError(f"备份失败: {e}")

    def _copytree_with_progress(
        self,
        src: Path,
        dst: Path,
        progress: Callable[[float, str], None],
    ) -> None:
        """带进度回调的目录复制"""
        # 先统计总文件数（缓存文件大小，避免三次 stat 调用）
        file_sizes: List[tuple] = []
        for f in src.rglob("*"):
            try:
                st = f.stat()
                if st.st_mode & 0o170000 == 0o100000:
                    file_sizes.append((f, st.st_size))
            except OSError:
                pass
        total_size = sum(s for _, s in file_sizes)
        file_count = len(file_sizes)

        dst.mkdir(parents=True, exist_ok=True)
        copied_size = 0

        for idx, (src_file, file_size) in enumerate(file_sizes):
            if self.is_cancelled:
                raise RuntimeError("备份已取消")

            rel = src_file.relative_to(src)
            dst_file = dst / rel
            dst_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_file, dst_file)

            copied_size += file_size
            if total_size > 0:
                pct = copied_size / total_size
                progress(0.02 + pct * 0.08, f"备份中... {idx + 1}/{file_count}")

    # ── 区块修复 ──────────────────────────────────────────

    def _repair_chunks(
        self,
        world_path: Path,
        report: RepairReport,
        log: Callable[[str, str], None],
        progress: Callable[[float, str], None],
    ) -> None:
        region_files = scan_all_regions(world_path)
        total = len(region_files)

        if total == 0:
            log("未找到区块文件", "WARNING")
            return

        log(f"找到 {total} 个区块文件", "INFO")

        completed = 0
        lock = threading.Lock()

        def process_region(
                idx: int, region_file: Path) -> Tuple[int, int, int]:
            """处理单个区域文件，返回 (checked, damaged, quarantined_flag)"""
            if self.is_cancelled:
                return 0, 0, 0

            checked = 0
            damaged = 0
            quarantined = 0

            try:
                region = Region.from_file(str(region_file))
                region_damaged = 0

                for chunk_x in range(32):
                    for chunk_z in range(32):
                        if self.is_cancelled:
                            return checked, damaged, quarantined
                        try:
                            chunk = region.get_chunk(chunk_x, chunk_z)
                            if chunk is not None:
                                ok = self._validate_chunk(chunk)
                                if not ok:
                                    region_damaged += 1
                                    damaged += 1
                        except Exception:
                            region_damaged += 1
                            damaged += 1

                checked = 1

                if region_damaged > 0:
                    log(
                        f"区块文件 {region_file.name} 包含 {region_damaged} 个损坏区块",
                        "WARNING",
                    )

            except Exception as e:
                log(f"无法读取区块文件 {region_file.name}: {e}", "ERROR")
                self._quarantine_file(region_file, log)
                quarantined = 1

            with lock:
                nonlocal completed
                completed += 1
                progress(
                    0.10 + (completed / total) * 0.65,
                    f"检查区块文件 {completed}/{total}",
                )

            return checked, damaged, quarantined

        max_workers = min(max(1, (len(region_files) + 3) // 4), 8)

        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {
                pool.submit(process_region, idx, rf): rf
                for idx, rf in enumerate(region_files)
            }
            for future in as_completed(futures):
                if self.is_cancelled:
                    pool.shutdown(wait=False, cancel_futures=True)
                    break
                try:
                    c, d, q = future.result(timeout=120)
                    report.chunks_checked += c
                    report.chunks_damaged += d
                    report.chunks_quarantined_regions += q
                except Exception as e:
                    rf = futures[future]
                    log(f"处理 {rf.name} 异常: {e}", "ERROR")

    def _validate_chunk(self, chunk: Any) -> bool:
        """验证区块数据完整性

        检查:
        1. chunk.data 存在且为 Compound
        2. Level 字段存在
        3. Sections 列表存在且非空
        4. DataVersion 存在
        """
        try:
            data = getattr(chunk, "data", None)
            if data is None:
                return False
            if not isinstance(data, nbtlib.tag.Compound):
                return False

            # 检查 Level 或直接子字段 (1.18+ 扁平化)
            has_level = "Level" in data
            has_sections = "sections" in data or "Sections" in data
            has_data_version = "DataVersion" in data

            if not has_data_version and not has_level and not has_sections:
                return False

            # 如果有 Level 子结构，验证其完整性
            if has_level:
                level = data["Level"]
                if not isinstance(level, nbtlib.tag.Compound):
                    return False
                # Sections 应该存在
                sections = level.get("Sections") or level.get("sections")
                if sections is not None and len(sections) == 0:
                    return False

            return True
        except Exception:
            return False

    def _quarantine_file(self, file_path: Path,
                         log: Callable[[str, str], None]) -> None:
        try:
            new_path = file_path.with_suffix(file_path.suffix + ".corrupted")
            if new_path.exists():
                timestamp = time.strftime("%Y%m%d_%H%M%S")
                new_path = file_path.with_suffix(
                    f"{file_path.suffix}.corrupted_{timestamp}")
                log(f"已有隔离文件存在，使用新名称: {new_path.name}", "WARNING")

            file_path.rename(new_path)
            log(f"已隔离损坏文件: {file_path.name} -> {new_path.name}", "WARNING")
        except Exception as e:
            log(f"无法隔离文件 {file_path.name}: {e}", "ERROR")

    # ── 玩家数据修复 ──────────────────────────────────────

    def _repair_players(
        self,
        world_path: Path,
        report: RepairReport,
        log: Callable[[str, str], None],
    ) -> None:
        playerdata_dir = world_path / "playerdata"
        if not playerdata_dir.exists():
            log("playerdata 目录不存在", "WARNING")
            return

        player_files = list(playerdata_dir.glob("*.dat"))
        log(f"找到 {len(player_files)} 个玩家数据文件", "INFO")

        for player_file in player_files:
            if self.is_cancelled:
                break

            try:
                nbt_data = nbtlib.load(str(player_file))
                report.players_checked += 1

                missing = self._find_missing_player_fields(nbt_data)
                if missing:
                    repaired = self._repair_player_fields(nbt_data, missing)
                    if repaired:
                        # 保存修复后的数据
                        nbt_data.save(player_file)
                        report.players_fixed += 1
                        log(
                            f"玩家数据 {
                                player_file.name} 已修复缺失字段: {
                                ', '.join(repaired)}",
                            "SUCCESS",
                        )
                        report.issues.append(
                            RepairIssue(
                                level=IssueLevel.FIXED,
                                category="player",
                                message=f"{
                                    player_file.name}: 修复 {
                                    ', '.join(repaired)}",
                                file_path=str(player_file),
                            ))
                    else:
                        log(f"玩家数据 {player_file.name} 字段完整", "INFO")

            except Exception as e:
                log(f"无法读取玩家数据 {player_file.name}: {e}", "ERROR")
                self._quarantine_file(player_file, log)
                report.players_quarantined += 1
                report.issues.append(RepairIssue(
                    level=IssueLevel.ERROR,
                    category="player",
                    message=f"{player_file.name}: 已隔离 ({e})",
                    file_path=str(player_file),
                ))

    def _find_missing_player_fields(self, nbt_data: Any) -> List[str]:
        """查找玩家数据中缺失的必需字段"""
        missing: List[str] = []
        for field_name in _player_defaults():
            if field_name not in nbt_data:
                missing.append(field_name)
        return missing

    def _repair_player_fields(
        self,
        nbt_data: Any,
        missing: List[str],
    ) -> List[str]:
        """尝试用默认值填充缺失字段，返回实际修复的字段列表"""
        defaults = _player_defaults()
        repaired: List[str] = []
        for field_name in missing:
            default = defaults.get(field_name)
            if default is None:
                continue
            try:
                nbt_data[field_name] = default
                repaired.append(field_name)
            except Exception:
                pass
        return repaired

    # ── level.dat 修复 ────────────────────────────────────

    def _repair_level_dat(
        self,
        world_path: Path,
        report: RepairReport,
        log: Callable[[str, str], None],
    ) -> None:
        level_dat = world_path / "level.dat"
        level_dat_old = world_path / "level.dat_old"

        if not level_dat.exists():
            if level_dat_old.exists():
                log("level.dat 不存在，尝试从 level.dat_old 恢复", "WARNING")
                shutil.copy2(level_dat_old, level_dat)
                report.level_dat_fixed = True
                log("已从 level.dat_old 恢复", "SUCCESS")
            else:
                log("level.dat 和 level.dat_old 都不存在", "ERROR")
            return

        # 尝试加载并验证
        try:
            nbt_data = nbtlib.load(str(level_dat))
        except Exception as e:
            log(f"level.dat 无法解析: {e}", "ERROR")
            self._restore_level_dat_from_backup(
                level_dat, level_dat_old, report, log)
            return

        # 检查 Data 字段
        if "Data" not in nbt_data:
            log("level.dat 缺少 Data 字段", "ERROR")
            self._restore_level_dat_from_backup(
                level_dat, level_dat_old, report, log)
            return

        data = nbt_data["Data"]
        if not isinstance(data, nbtlib.tag.Compound):
            log("level.dat 的 Data 字段类型错误", "ERROR")
            self._restore_level_dat_from_backup(
                level_dat, level_dat_old, report, log)
            return

        # 字段级修复
        repaired_fields = self._repair_level_dat_fields(data, log)
        if repaired_fields:
            report.level_dat_fixed = True
            report.level_dat_repaired_fields = repaired_fields
            # 保存修复后的 level.dat
            try:
                nbt_data.save(level_dat)
                log(f"level.dat 已保存修复 ({', '.join(repaired_fields)})", "SUCCESS")
            except Exception as e:
                log(f"保存 level.dat 失败: {e}", "ERROR")
        else:
            log("level.dat 验证通过", "INFO")

    def _restore_level_dat_from_backup(
        self,
        level_dat: Path,
        level_dat_old: Path,
        report: RepairReport,
        log: Callable[[str, str], None],
    ) -> None:
        if not level_dat_old.exists():
            log("level.dat_old 不存在，无法恢复", "ERROR")
            return

        log("尝试从 level.dat_old 恢复", "WARNING")
        shutil.copy2(level_dat_old, level_dat)

        try:
            nbtlib.load(str(level_dat))
            report.level_dat_fixed = True
            log("已从 level.dat_old 恢复", "SUCCESS")
        except Exception:
            log("level.dat_old 也已损坏", "ERROR")

    def _repair_level_dat_fields(
        self,
        data: Any,
        log: Callable[[str, str], None],
    ) -> List[str]:
        """验证并修复 level.dat Data 中的字段，返回修复的字段名列表"""
        repaired: List[str] = []

        for field_name, default_value in _LEVEL_DAT_REQUIRED_FIELDS.items():
            if field_name not in data:
                if default_value is None:
                    continue
                try:
                    data[field_name] = default_value
                    repaired.append(field_name)
                    log(f"level.dat 补充缺失字段: {field_name}", "WARNING")
                except Exception:
                    pass

        # 修复 SpawnX/Y/Z 为合理范围
        for spawn_field in ("SpawnX", "SpawnY", "SpawnZ"):
            if spawn_field in data:
                try:
                    val = int(data[spawn_field])
                    if spawn_field == "SpawnY" and (val < -64 or val > 320):
                        data[spawn_field] = 64
                        repaired.append(f"{spawn_field}(范围修正)")
                except (ValueError, TypeError):
                    pass

        # 修复 Health 在合理范围
        for health_field in ("Difficulty",):
            if health_field in data:
                try:
                    val = int(data[health_field])
                    if val < 0 or val > 3:
                        data[health_field] = 2
                        repaired.append(f"{health_field}(范围修正)")
                except (ValueError, TypeError):
                    pass

        return repaired
