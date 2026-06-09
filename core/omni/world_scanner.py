"""
WorldScanner - 存档文件扫描器
负责扫描存档目录结构，收集文件路径和元数据
"""
import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Set, Callable
from ..scanner import scan_all_regions


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
        """扫描玩家数据文件

        Returns:
            UUID -> 文件路径的映射（UUID 已规范化为无连字符小写）
        """
        player_files = {}
        playerdata_dir = self.world_path / "playerdata"

        if playerdata_dir.is_dir():
            try:
                for f in playerdata_dir.iterdir():
                    if f.is_file() and f.suffix == ".dat":
                        uuid = self._normalize_uuid(f.stem)
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
        """扫描 data 目录

        Returns:
            数据文件路径列表
        """
        data_files = []
        data_dir = self.world_path / "data"

        if data_dir.is_dir():
            try:
                data_files = list(data_dir.glob("*.dat"))
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
        """扫描存档中所有可用的维度目录

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

        # 扫描原版维度
        vanilla_dims = [
            ("overworld", "🌍 主世界", self.world_path / "region"),
            ("nether", "🔥 下界", self.world_path / "DIM-1" / "region"),
            ("end", "🌌 末地", self.world_path / "DIM1" / "region"),
        ]

        for dim_id, dim_name, region_dir in vanilla_dims:
            if _has_regions(region_dir):
                dimensions.append({"id": dim_id, "name": dim_name, "region_dir": str(region_dir)})
                seen.add(dim_id)

        # DIM* 格式（旧版模组维度）
        try:
            for dim_dir in self.world_path.iterdir():
                if not dim_dir.is_dir() or not dim_dir.name.startswith("DIM"):
                    continue
                if dim_dir.name in ("DIM-1", "DIM1"):
                    continue

                region_dir = dim_dir / "region"
                dim_id = dim_dir.name.lower()

                if dim_id not in seen and _has_regions(region_dir):
                    dimensions.append({
                        "id": dim_id,
                        "name": f"📦 {dim_dir.name}",
                        "region_dir": str(region_dir),
                    })
                    seen.add(dim_id)
        except OSError:
            pass

        # dimensions/{namespace}/{name} 格式（1.16+ 模组维度）
        dimensions_base = self.world_path / "dimensions"
        if dimensions_base.is_dir():
            try:
                for namespace_dir in dimensions_base.iterdir():
                    if not namespace_dir.is_dir():
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
                            if namespace == "minecraft":
                                vanilla_map = {
                                    "overworld": "🌍 主世界",
                                    "the_nether": "🔥 下界",
                                    "the_end": "🌌 末地",
                                }
                                display_name = vanilla_map.get(dim_name_str, display_name)

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
