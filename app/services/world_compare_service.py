"""存档对比服务"""
import threading
from pathlib import Path
import hashlib
from typing import Any, Dict, List, Optional
from dataclasses import asdict, dataclass

from core.omni.world_session import WorldSession
from core.scanner import scan_all_regions
from core.types import LogCallback


def _default_log(msg: str, lvl: str = "INFO") -> None:
    pass


@dataclass
class CompareItem:
    name: str
    left: Any
    right: Any
    same: bool


@dataclass
class WorldCompareResult:
    summary: Dict[str, int]
    world_info: List[CompareItem]
    players: List[CompareItem]
    regions: List[CompareItem]


class WorldCompareService:
    def __init__(self, log: Optional[LogCallback] = None) -> None:
        self.log: LogCallback = log or _default_log

    def compare_worlds(
            self,
            left_path: Path,
            right_path: Path) -> WorldCompareResult:
        left = WorldSession(left_path, log=self.log)
        right = WorldSession(right_path, log=self.log)

        world_info = self._compare_world_info(left, right)
        players = self._compare_players(left, right)
        regions = self._compare_regions(left_path, right_path)
        changed = sum(
            1 for item in world_info +
            players +
            regions if not item.same)
        return WorldCompareResult(
            summary={
                "world_info": len(world_info),
                "players": len(players),
                "regions": len(regions),
                "changed": changed},
            world_info=world_info,
            players=players,
            regions=regions,
        )

    def _compare_world_info(
            self,
            left: WorldSession,
            right: WorldSession) -> List[CompareItem]:
        li = left.get_world_info()
        ri = right.get_world_info()
        ldict = asdict(li) if li else {}
        rdict = asdict(ri) if ri else {}
        keys = sorted(set(ldict) | set(rdict))
        return [
            CompareItem(
                key,
                ldict.get(key),
                rdict.get(key),
                ldict.get(key) == rdict.get(key)) for key in keys]

    def _compare_players(
            self,
            left: WorldSession,
            right: WorldSession) -> List[CompareItem]:
        lplayers = self._player_summary(left)
        rplayers = self._player_summary(right)
        keys = sorted(set(lplayers) | set(rplayers))
        return [
            CompareItem(
                key,
                lplayers.get(key),
                rplayers.get(key),
                lplayers.get(key) == rplayers.get(key)) for key in keys]

    def _compare_regions(
            self,
            left_path: Path,
            right_path: Path) -> List[CompareItem]:
        left_regions = {p.name: self._file_signature(
            p) for p in scan_all_regions(left_path)}
        right_regions = {p.name: self._file_signature(
            p) for p in scan_all_regions(right_path)}
        keys = sorted(set(left_regions) | set(right_regions))
        return [
            CompareItem(
                key,
                left_regions.get(key),
                right_regions.get(key),
                left_regions.get(key) == right_regions.get(key)) for key in keys]

    def _player_summary(
            self, session: WorldSession) -> Dict[str, Dict[str, Any]]:
        names = session.get_player_names()
        result: Dict[str, Dict[str, Any]] = {}
        for uuid, name in names.items():
            summary: Dict[str, Any] = {"name": name, "uuid": uuid}
            try:
                data = session.load_player_data(uuid)
                pos = data.get("Pos") if data is not None else None
                inventory = data.get("Inventory") if data is not None else None
                summary["pos"] = [str(v) for v in pos] if pos else []
                summary["inventory_count"] = len(inventory) if inventory else 0
            except Exception:
                summary["error"] = "读取失败"
            result[uuid] = summary
        return result

    def _file_signature(self, path: Path) -> Dict[str, Any]:
        st = path.stat()
        return {"size": st.st_size, "mtime": int(st.st_mtime)}


_compare_service: Optional[WorldCompareService] = None
_compare_service_lock = threading.Lock()


def get_world_compare_service(
        log: Optional[LogCallback] = None) -> WorldCompareService:
    """获取世界比较服务单例（线程安全）"""
    global _compare_service
    with _compare_service_lock:
        if _compare_service is None:
            _compare_service = WorldCompareService(log=log)
        elif log is not None:
            _compare_service.log = log
    return _compare_service
