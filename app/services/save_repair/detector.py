"""World Detector - 只读检测服务

检测存档状态，不修改任何文件。
"""
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable, Optional, List, Tuple, Set, Any

import nbtlib
from core.mca import NativeRegion as Region

from core.logger import logger
from core.scanner import scan_all_regions
from core.constants import MinecraftConstants
from core.utils import find_player_data_dirs

from .models import DetectReport, WorldInfo, IssueLevel, RepairIssue
from .validation_utils import (
    validate_chunk,
    validate_player_data,
    validate_level_dat_data,
)


# 游戏模式和难度名称映射
_GAME_TYPE_NAMES = {0: "生存", 1: "创造", 2: "冒险", 3: "旁观"}
_DIFFICULTY_NAMES = {0: "和平", 1: "简单", 2: "普通", 3: "困难"}


class WorldDetector:
    """存档检测器（只读）"""

    CHUNKS_PER_REGION = 1024

    def __init__(self, cancel_event: threading.Event) -> None:
        self._cancel_event = cancel_event

    @property
    def is_cancelled(self) -> bool:
        return self._cancel_event.is_set()

    def detect_world(
        self,
        world_path: Path,
        report: DetectReport,
        log: Callable[[str, str], None],
        progress: Callable[[float, str], None],
    ) -> None:
        """检测存档状态（只读，不修改任何文件）"""
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

    def _detect_world_info(
        self,
        world_path: Path,
        report: DetectReport,
        log: Callable[[str, str], None],
    ) -> None:
        """读取世界基本信息"""
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
            self._read_level_dat_info(world_path, info, log)

        # 维度和区域文件
        self._detect_dimensions(world_path, info)

        # 玩家数量（兼容 26.1 新旧路径）
        info.player_count = 0
        for playerdata_dir in find_player_data_dirs(world_path):
            if playerdata_dir.exists():
                info.player_count += len(list(playerdata_dir.glob("*.dat")))

        log(
            f"世界: {info.world_name}, 版本: {info.version_name}, "
            f"大小: {info.world_size_mb:.1f}MB, 区域: {info.region_count}, 玩家: {info.player_count}",
            "INFO",
        )

    def _read_level_dat_info(
        self,
        world_path: Path,
        info: WorldInfo,
        log: Callable[[str, str], None],
    ) -> None:
        """从 level.dat 读取世界信息"""
        try:
            nbt_data = nbtlib.load(str(world_path / "level.dat"))
            data = nbt_data.get("Data", {})
            if isinstance(data, nbtlib.tag.Compound):
                info.data_version = int(data.get("DataVersion", 0))
                info.version_name = MinecraftConstants.VERSION_MAP.get(
                    info.data_version, f"未知({info.data_version})"
                )
                info.game_type = int(data.get("GameType", 0))
                info.game_type_name = _GAME_TYPE_NAMES.get(info.game_type, "未知")
                info.difficulty = int(data.get("Difficulty", 2))
                info.difficulty_name = _DIFFICULTY_NAMES.get(info.difficulty, "未知")
                info.seed = int(data.get("RandomSeed", 0))
                info.spawn_pos = (
                    int(data.get("SpawnX", 0)),
                    int(data.get("SpawnY", 64)),
                    int(data.get("SpawnZ", 0)),
                )
                info.play_time_ticks = int(data.get("Time", 0))
        except Exception as e:
            log(f"无法读取 level.dat 基本信息: {e}", "WARNING")

    def _detect_dimensions(self, world_path: Path, info: WorldInfo) -> None:
        """检测维度和区域文件（兼容 Minecraft 26.1 新旧路径）"""
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
            elif len(parts) >= 5 and parts[0] == "dimensions" and parts[1] == "minecraft":
                # 26.1 新版路径: dimensions/minecraft/<dim>/region/...
                dimensions.add(f"minecraft:{parts[2]}")
            elif "dimensions" in parts:
                idx = parts.index("dimensions")
                if idx + 2 < len(parts):
                    dimensions.add(f"{parts[idx + 1]}:{parts[idx + 2]}")

        info.dimensions = sorted(dimensions)

        # 估算总区块数
        info.total_chunks = 0
        for rf in region_files:
            try:
                size = rf.stat().st_size
                info.total_chunks += min(1024, max(0, size // 4096))
            except OSError:
                pass

    def _detect_chunks(
        self,
        world_path: Path,
        report: DetectReport,
        log: Callable[[str, str], None],
        progress: Callable[[float, str], None],
    ) -> None:
        """检测区块文件"""
        region_files = scan_all_regions(world_path)
        total = len(region_files)

        if total == 0:
            log("未找到区块文件", "WARNING")
            return

        log(f"找到 {total} 个区域文件，开始逐块检测...", "INFO")
        report.chunks_checked = total * self.CHUNKS_PER_REGION

        completed = 0
        lock = threading.Lock()

        def detect_region(idx: int, region_file: Path) -> Tuple[int, List[str]]:
            """检测单个区域文件"""
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
                                if not validate_chunk(chunk):
                                    damaged += 1
                                    problems.append(f"区块({chunk_x},{chunk_z})数据无效")
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
        """检测玩家数据（兼容 Minecraft 26.1 新旧路径）"""
        player_files: List[Path] = []
        for playerdata_dir in find_player_data_dirs(world_path):
            if playerdata_dir.exists():
                player_files.extend(list(playerdata_dir.glob("*.dat")))

        if not player_files:
            log("玩家数据目录不存在", "INFO")
            return

        report.players_checked = len(player_files)
        log(f"找到 {len(player_files)} 个玩家数据文件", "INFO")

        for player_file in player_files:
            if self.is_cancelled:
                break

            issues: List[str] = []
            try:
                nbt_data = nbtlib.load(str(player_file))
                from .player_repairer import PLAYER_REQUIRED_FIELDS
                issues = validate_player_data(nbt_data, PLAYER_REQUIRED_FIELDS)
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
        """检测 level.dat"""
        from .level_repairer import LEVEL_DAT_REQUIRED_FIELDS

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

        # 检查必需字段和范围
        from .level_repairer import LEVEL_DAT_REQUIRED_FIELDS
        issues = validate_level_dat_data(data, LEVEL_DAT_REQUIRED_FIELDS)
        report.level_dat_issues = issues
        report.level_dat_ok = len(issues) == 0

        if report.level_dat_ok:
            log("level.dat 验证通过", "INFO")
        else:
            for issue in report.level_dat_issues:
                log(f"level.dat: {issue}", "WARNING")
