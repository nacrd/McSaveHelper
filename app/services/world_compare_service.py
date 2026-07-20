"""存档对比服务。

对比两个世界的 level 元数据、玩家列表与区域文件签名，供 UI 展示差异。
"""
from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.omni.world_session import WorldSession
from core.scanner import scan_all_regions
from core.types import LogCallback


def _default_log(msg: str, lvl: str = "INFO") -> None:
    """No-op logger used when callers omit a log callback."""
    del msg, lvl


@dataclass
class CompareItem:
    """Single left/right comparison row."""

    name: str
    left: Any
    right: Any
    same: bool


@dataclass
class WorldCompareResult:
    """Full comparison payload for the compare view."""

    summary: Dict[str, int]
    world_info: List[CompareItem]
    players: List[CompareItem]
    regions: List[CompareItem]


class WorldCompareService:
    """对比两个 Java 版世界目录的元数据与区域签名。"""

    def __init__(self, log: Optional[LogCallback] = None) -> None:
        """初始化对比服务。

        Args:
            log: 可选日志回调。
        """
        self.log: LogCallback = log or _default_log

    def compare_worlds(
        self,
        left_path: Path,
        right_path: Path,
    ) -> WorldCompareResult:
        """对比两个存档路径。

        Args:
            left_path: 左侧世界路径。
            right_path: 右侧世界路径。

        Returns:
            WorldCompareResult: 世界信息、玩家与区域差异汇总。
        """
        left = WorldSession(left_path, log=self.log)
        right = WorldSession(right_path, log=self.log)

        world_info = self._compare_world_info(left, right)
        players = self._compare_players(left, right)
        regions = self._compare_regions(left_path, right_path)
        comparisons = world_info + players + regions
        changed = sum(1 for item in comparisons if not item.same)
        return WorldCompareResult(
            summary={
                "world_info": len(world_info),
                "players": len(players),
                "regions": len(regions),
                "changed": changed,
            },
            world_info=world_info,
            players=players,
            regions=regions,
        )

    def _compare_world_info(
        self,
        left: WorldSession,
        right: WorldSession,
    ) -> List[CompareItem]:
        """Compare level.dat-derived world info fields."""
        left_info = left.get_world_info()
        right_info = right.get_world_info()
        left_dict = asdict(left_info) if left_info else {}
        right_dict = asdict(right_info) if right_info else {}
        keys = sorted(set(left_dict) | set(right_dict))
        return [
            CompareItem(
                key,
                left_dict.get(key),
                right_dict.get(key),
                left_dict.get(key) == right_dict.get(key),
            )
            for key in keys
        ]

    def _compare_players(
        self,
        left: WorldSession,
        right: WorldSession,
    ) -> List[CompareItem]:
        """Compare player name/position/inventory summaries by UUID."""
        left_players = self._player_summary(left)
        right_players = self._player_summary(right)
        keys = sorted(set(left_players) | set(right_players))
        return [
            CompareItem(
                key,
                left_players.get(key),
                right_players.get(key),
                left_players.get(key) == right_players.get(key),
            )
            for key in keys
        ]

    def _compare_regions(
        self,
        left_path: Path,
        right_path: Path,
    ) -> List[CompareItem]:
        """Compare MCA files by relative path using size+sha256 signatures."""
        left_regions = {
            path.relative_to(left_path).as_posix(): self._file_signature(path)
            for path in scan_all_regions(left_path)
        }
        right_regions = {
            path.relative_to(right_path).as_posix(): self._file_signature(path)
            for path in scan_all_regions(right_path)
        }
        keys = sorted(set(left_regions) | set(right_regions))
        return [
            CompareItem(
                key,
                left_regions.get(key),
                right_regions.get(key),
                left_regions.get(key) == right_regions.get(key),
            )
            for key in keys
        ]

    def _player_summary(
        self,
        session: WorldSession,
    ) -> Dict[str, Dict[str, Any]]:
        """Build a compact per-player summary for comparison."""
        names = session.get_player_names()
        result: Dict[str, Dict[str, Any]] = {}
        for uuid, name in names.items():
            summary: Dict[str, Any] = {"name": name, "uuid": uuid}
            try:
                data = session.load_player_data(uuid)
                pos = data.get("Pos") if data is not None else None
                inventory = (
                    data.get("Inventory") if data is not None else None
                )
                summary["pos"] = [str(value) for value in pos] if pos else []
                summary["inventory_count"] = (
                    len(inventory) if inventory else 0
                )
            except (OSError, ValueError, TypeError, KeyError):
                summary["error"] = "读取失败"
            except Exception:
                # nbtlib / session load edge cases
                summary["error"] = "读取失败"
            result[uuid] = summary
        return result

    def _file_signature(self, path: Path) -> Dict[str, Any]:
        """Return size and sha256 for a region file.

        Args:
            path: MCA path.

        Returns:
            dict: ``{"size": int, "sha256": str}``; on I/O failure size/hash
            may be zero/empty with an ``error`` key.
        """
        try:
            stats = path.stat()
            digest = hashlib.sha256()
            with path.open("rb") as region_file:
                for chunk in iter(lambda: region_file.read(1024 * 1024), b""):
                    digest.update(chunk)
            return {"size": stats.st_size, "sha256": digest.hexdigest()}
        except OSError as exc:
            return {"size": 0, "sha256": "", "error": str(exc)}


def get_world_compare_service(
    log: Optional[LogCallback] = None,
) -> WorldCompareService:
    """返回绑定到调用方日志回调的对比服务实例。

    Args:
        log: 可选日志回调。

    Returns:
        WorldCompareService: 新服务实例。
    """
    return WorldCompareService(log=log)
