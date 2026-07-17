"""
WorldScanner - 存档文件扫描器
负责扫描存档目录结构，收集文件路径和元数据
支持 Minecraft 26.1 新版路径格式（向后兼容旧版）
"""
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Set, Callable
from ..region_utils import scan_region_dir
from ..scanner import scan_all_regions
from ..utils import find_player_data_dirs, find_data_dirs


class WorldScanner:
    """存档文件扫描器"""

    _VANILLA_DIMENSION_NAMES = {
        "overworld": "🌍 主世界",
        "the_nether": "🔥 下界",
        "the_end": "🌌 末地",
    }
    _LEGACY_DIMENSION_IDS = {
        "DIM-1": "minecraft:the_nether",
        "DIM1": "minecraft:the_end",
    }

    def __init__(self, world_path: Path, log_callback: Optional[Callable] = None):
        self.world_path = world_path
        self._log = log_callback or (lambda msg, lvl="INFO": None)

    def scan_all(self) -> Dict[str, Any]:
        """扫描所有文件并返回扫描结果

        Returns:
            包含 player_files, region_files, data_files, usercache 的字典
        """
        player_files = self._scan_players()
        region_files = self._scan_regions()
        data_files = self._scan_data()
        usercache = self._scan_usercache(set(player_files.keys()))

        return {
            'player_files': player_files,
            'region_files': region_files,
            'data_files': data_files,
            'usercache': usercache,
        }

    def _scan_players(self) -> Dict[str, Path]:
        """扫描玩家数据文件（兼容 Minecraft 26.1 新旧路径）

        新版路径: players/data/*.dat
        旧版路径: playerdata/*.dat

        Returns:
            UUID -> 文件路径的映射（UUID 已规范化为无连字符小写）
        """
        player_files = {}

        for playerdata_dir in find_player_data_dirs(self.world_path):
            try:
                for f in playerdata_dir.iterdir():
                    if f.is_file() and f.suffix == ".dat":
                        uuid = self._normalize_uuid(f.stem)
                        # 新版路径优先，不覆盖已有的
                        if uuid not in player_files:
                            player_files[uuid] = f
            except OSError:
                pass

        self._log(f"发现 {len(player_files)} 个玩家数据文件", "SCAN")
        return player_files

    def _scan_regions(self) -> Dict[Tuple[int, int], Path]:
        """扫描区域文件

        Returns:
            (x, z) -> 文件路径的映射
        """
        region_files = {}
        all_regions = scan_all_regions(self.world_path)

        for f in all_regions:
            # 解析文件名 r.x.z.mca
            if f.stem.startswith("r."):
                parts = f.stem.split(".")
                if len(parts) == 3:
                    try:
                        x, z = int(parts[1]), int(parts[2])
                        region_files[(x, z)] = f
                    except ValueError:
                        pass

        self._log(f"发现 {len(region_files)} 个区域文件", "SCAN")
        return region_files

    def _scan_data(self) -> List[Path]:
        """扫描 data 目录（兼容 Minecraft 26.1 新旧路径）

        新版路径: data/minecraft/*.dat
        旧版路径: data/*.dat

        Returns:
            数据文件路径列表
        """
        data_files = []
        seen_names: Set[str] = set()

        for data_dir in find_data_dirs(self.world_path):
            try:
                for f in data_dir.glob("*.dat"):
                    if f.name not in seen_names:
                        data_files.append(f)
                        seen_names.add(f.name)
            except OSError:
                pass

        self._log(f"发现 {len(data_files)} 个数据文件", "SCAN")
        return data_files

    def _scan_usercache(self, player_set: Set[str]) -> Dict[str, str]:
        """扫描 usercache.json 文件

        Args:
            player_set: 已发现的玩家 UUID 集合

        Returns:
            UUID -> 玩家名称的映射
        """
        best_cache: Dict[str, str] = {}
        best_match = -1

        # 仅检查有限的候选路径，不遍历 versions/ 子目录
        candidate_paths = self._get_usercache_candidates()

        for path in candidate_paths:
            if not path.is_file():
                continue

            try:
                with open(path, "r", encoding="utf-8") as f:
                    entries = json.load(f)

                cache_map: Dict[str, str] = {}
                match_count = 0

                for entry in entries:
                    uuid = entry.get("uuid", "").replace("-", "")
                    name = entry.get("name", "")
                    if uuid and name:
                        cache_map[uuid] = name
                        if uuid in player_set:
                            match_count += 1

                self._log(f"候选 usercache: {path}, 匹配 {match_count}/{len(player_set)}", "IMPORT")

                if match_count > best_match:
                    best_match = match_count
                    best_cache = cache_map

                if match_count == len(player_set):
                    break  # 完美匹配，提前退出

            except Exception as e:
                self._log(f"解析 usercache {path} 失败: {e}", "WARNING")

        if best_cache:
            self._log(f"已从 usercache 更新 {best_match} 个玩家名称", "SCAN")

        return best_cache

    def _get_usercache_candidates(self) -> List[Path]:
        """获取 usercache.json 的候选路径列表"""
        candidate_paths: List[Path] = []

        # 同级目录
        candidate_paths.append(self.world_path / "usercache.json")

        # 父目录
        candidate_paths.append(self.world_path.parent / "usercache.json")

        # 向上查找 .minecraft（最多 5 层）
        current = self.world_path
        for _ in range(5):
            parent = current.parent
            if parent == current:
                break
            if parent.name == ".minecraft":
                candidate_paths.append(parent / "usercache.json")
                break
            current = parent

        return candidate_paths

    def scan_dimensions(
        self,
        region_files: Dict[Tuple[int, int], Path],
    ) -> List[Dict[str, str]]:
        """扫描存档中所有可用的维度目录（兼容 Minecraft 26.1 新旧路径）

        Args:
            region_files: 区域文件映射（来自 _scan_regions）

        Returns:
            维度信息列表，每项包含 id, name, region_dir
        """
        dimensions: List[Dict[str, str]] = []
        seen: Set[str] = set()
        known_region_dirs = {path.parent for path in region_files.values()}

        self._scan_modern_minecraft_dimensions(
            dimensions,
            seen,
            known_region_dirs,
        )
        self._add_dimension(
            dimensions,
            seen,
            known_region_dirs,
            dim_id="overworld",
            display_name=self._VANILLA_DIMENSION_NAMES["overworld"],
            region_dir=self.world_path / "region",
        )
        self._scan_legacy_dimensions(dimensions, seen, known_region_dirs)
        self._scan_custom_dimensions(dimensions, seen, known_region_dirs)

        self._log(f"发现 {len(dimensions)} 个维度", "SCAN")
        return dimensions

    def _scan_modern_minecraft_dimensions(
        self,
        dimensions: List[Dict[str, str]],
        seen: Set[str],
        known_region_dirs: Set[Path],
    ) -> None:
        dimensions_root = self.world_path / "dimensions" / "minecraft"
        for dimension_dir in self._iter_directories(dimensions_root):
            dimension_name = dimension_dir.name
            dim_id = (
                "overworld"
                if dimension_name == "overworld"
                else f"minecraft:{dimension_name}"
            )
            self._add_dimension(
                dimensions,
                seen,
                known_region_dirs,
                dim_id=dim_id,
                display_name=self._VANILLA_DIMENSION_NAMES.get(
                    dimension_name,
                    f"📦 minecraft:{dimension_name}",
                ),
                region_dir=dimension_dir / "region",
            )

    def _scan_legacy_dimensions(
        self,
        dimensions: List[Dict[str, str]],
        seen: Set[str],
        known_region_dirs: Set[Path],
    ) -> None:
        for dimension_dir in self._iter_directories(self.world_path):
            if not dimension_dir.name.startswith("DIM"):
                continue
            dim_id = self._LEGACY_DIMENSION_IDS.get(
                dimension_dir.name,
                dimension_dir.name.lower(),
            )
            display_name = {
                "DIM-1": self._VANILLA_DIMENSION_NAMES["the_nether"],
                "DIM1": self._VANILLA_DIMENSION_NAMES["the_end"],
            }.get(dimension_dir.name, f"📦 {dimension_dir.name}")
            self._add_dimension(
                dimensions,
                seen,
                known_region_dirs,
                dim_id=dim_id,
                display_name=display_name,
                region_dir=dimension_dir / "region",
            )

    def _scan_custom_dimensions(
        self,
        dimensions: List[Dict[str, str]],
        seen: Set[str],
        known_region_dirs: Set[Path],
    ) -> None:
        dimensions_root = self.world_path / "dimensions"
        for namespace_dir in self._iter_directories(dimensions_root):
            if namespace_dir.name == "minecraft":
                continue
            for dimension_dir in self._iter_directories(namespace_dir):
                dim_id = f"{namespace_dir.name}:{dimension_dir.name}"
                self._add_dimension(
                    dimensions,
                    seen,
                    known_region_dirs,
                    dim_id=dim_id,
                    display_name=f"📦 {dim_id}",
                    region_dir=dimension_dir / "region",
                )

    def _add_dimension(
        self,
        dimensions: List[Dict[str, str]],
        seen: Set[str],
        known_region_dirs: Set[Path],
        *,
        dim_id: str,
        display_name: str,
        region_dir: Path,
    ) -> None:
        if dim_id in seen or not self._has_regions(
            region_dir,
            known_region_dirs,
        ):
            return
        dimensions.append({
            "id": dim_id,
            "name": display_name,
            "region_dir": str(region_dir),
        })
        seen.add(dim_id)

    @staticmethod
    def _has_regions(region_dir: Path, known_region_dirs: Set[Path]) -> bool:
        return region_dir in known_region_dirs or bool(scan_region_dir(region_dir))

    @staticmethod
    def _iter_directories(parent: Path) -> List[Path]:
        if not parent.is_dir():
            return []
        try:
            return sorted(
                (path for path in parent.iterdir() if path.is_dir()),
                key=lambda path: path.name,
            )
        except OSError:
            return []

    @staticmethod
    def _normalize_uuid(uuid: str) -> str:
        """规范化 UUID：移除连字符并转为小写"""
        return uuid.replace("-", "").lower()
