"""
WorldScanner - 存档文件扫描器
负责扫描存档目录结构，收集文件路径和元数据
支持 Minecraft 26.1 新版路径格式（向后兼容旧版）
"""
import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Set, Callable
from ..scanner import scan_all_regions
from ..utils import find_player_data_dirs, find_data_dirs


class WorldScanner:
    """存档文件扫描器"""

    def __init__(self, world_path: Path, log_callback: Optional[Callable] = None):
        self.world_path = world_path
        self._log = log_callback or (lambda msg, lvl="INFO": None)

    def scan_all(self) -> Dict[str, any]:
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

    def scan_dimensions(self, region_files: Dict[Tuple[int, int], Path]) -> List[Dict[str, str]]:
        """扫描存档中所有可用的维度目录（兼容 Minecraft 26.1 新旧路径）

        Args:
            region_files: 区域文件映射（来自 _scan_regions）

        Returns:
            维度信息列表，每项包含 id, name, region_dir
        """
        dimensions: List[Dict[str, str]] = []
        seen: set = set()

        # 构建已有 region 文件的父目录集合
        region_parent_dirs: set = {p.parent for p in region_files.values()}

        def _has_regions(region_dir: Path) -> bool:
            return region_dir in region_parent_dirs

        # 新版 (26.1) 维度路径映射：命名空间维度名 -> (显示名)
        new_dim_display = {
            "the_nether": "🔥 下界",
            "the_end": "🌌 末地",
            "overworld": "🌍 主世界",
        }

        # 扫描新版维度路径 dimensions/minecraft/<dim>/region
        mc_dims_base = self.world_path / "dimensions" / "minecraft"
        if mc_dims_base.is_dir():
            try:
                for dim_dir in mc_dims_base.iterdir():
                    if not dim_dir.is_dir():
                        continue
                    region_dir = dim_dir / "region"
                    if not _has_regions(region_dir):
                        continue
                    dim_name_str = dim_dir.name
                    dim_id = f"minecraft:{dim_name_str}"
                    if dim_id in seen:
                        continue
                    display_name = new_dim_display.get(dim_name_str, f"📦 minecraft:{dim_name_str}")
                    dimensions.append({"id": dim_id, "name": display_name, "region_dir": str(region_dir)})
                    seen.add(dim_id)
            except OSError:
                pass

        # 扫描主世界 region（始终为 overworld）
        overworld_region = self.world_path / "region"
        if "overworld" not in seen and _has_regions(overworld_region):
            dimensions.append({"id": "overworld", "name": "🌍 主世界", "region_dir": str(overworld_region)})
            seen.add("overworld")

        # 旧版 DIM* 格式（DIM-1、DIM1 及模组维度），仅在新版路径未覆盖时添加
        old_to_new = {"DIM-1": "minecraft:the_nether", "DIM1": "minecraft:the_end"}
        try:
            for dim_dir in self.world_path.iterdir():
                if not dim_dir.is_dir() or not dim_dir.name.startswith("DIM"):
                    continue
                new_dim_id = old_to_new.get(dim_dir.name)
                if new_dim_id and new_dim_id in seen:
                    continue  # 新版路径已存在，跳过

                region_dir = dim_dir / "region"
                dim_id = new_dim_id or dim_dir.name.lower()

                if dim_id not in seen and _has_regions(region_dir):
                    display_name = new_dim_display.get(
                        dim_dir.name, f"📦 {dim_dir.name}"
                    )
                    # 对 DIM-1 和 DIM1 使用对应显示名
                    if dim_dir.name == "DIM-1":
                        display_name = "🔥 下界"
                    elif dim_dir.name == "DIM1":
                        display_name = "🌌 末地"
                    dimensions.append({"id": dim_id, "name": display_name, "region_dir": str(region_dir)})
                    seen.add(dim_id)
        except OSError:
            pass

        # dimensions/{namespace}/{name} 格式（非 minecraft 命名空间的模组维度）
        dimensions_base = self.world_path / "dimensions"
        if dimensions_base.is_dir():
            try:
                for namespace_dir in dimensions_base.iterdir():
                    if not namespace_dir.is_dir():
                        continue
                    # minecraft 命名空间已在上面处理过
                    if namespace_dir.name == "minecraft":
                        continue
                    try:
                        for dim_dir in namespace_dir.iterdir():
                            if not dim_dir.is_dir():
                                continue

                            region_dir = dim_dir / "region"
                            if not _has_regions(region_dir):
                                continue

                            namespace = namespace_dir.name
                            dim_name_str = dim_dir.name
                            dim_id = f"{namespace}:{dim_name_str}"

                            if dim_id in seen:
                                continue

                            display_name = f"📦 {namespace}:{dim_name_str}"

                            dimensions.append({
                                "id": dim_id,
                                "name": display_name,
                                "region_dir": str(region_dir),
                            })
                            seen.add(dim_id)
                    except OSError:
                        pass
            except OSError:
                pass

        self._log(f"发现 {len(dimensions)} 个维度", "SCAN")
        return dimensions

    @staticmethod
    def _normalize_uuid(uuid: str) -> str:
        """规范化 UUID：移除连字符并转为小写"""
        return uuid.replace("-", "").lower()
