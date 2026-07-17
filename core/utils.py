"""通用工具函数

提供项目中常用的工具函数，目前主要包含 server.properties 的更新功能
以及 Minecraft 26.1 存档路径兼容辅助函数。
"""

from pathlib import Path
import re
import shutil
from typing import List

from .types import LogCallback


_INVALID_WORLD_NAME_CHARS = re.compile(r"[\\/\r\n]")


# ══════════════════════════════════════════════════════════
#  Minecraft 26.1 存档路径兼容辅助函数
# ══════════════════════════════════════════════════════════

def find_player_data_dirs(world_path: Path) -> List[Path]:
    """返回所有可能的玩家数据目录（新版 26.1 优先，向后兼容旧版）

    新版路径: <world>/players/data/
    旧版路径: <world>/playerdata/

    Args:
        world_path: 世界存档根目录

    Returns:
        存在的玩家数据目录列表（新版在前）
    """
    dirs: List[Path] = []
    new_dir = world_path / "players" / "data"
    old_dir = world_path / "playerdata"
    if new_dir.is_dir():
        dirs.append(new_dir)
    if old_dir.is_dir():
        dirs.append(old_dir)
    # 如果都不存在，返回旧路径作为默认（兼容新存档首次写入场景）
    return dirs if dirs else [old_dir]


def find_stats_dirs(world_path: Path) -> List[Path]:
    """返回所有可能的统计数据目录（新版 26.1 优先，向后兼容旧版）

    新版路径: <world>/players/stats/
    旧版路径: <world>/stats/
    """
    dirs: List[Path] = []
    new_dir = world_path / "players" / "stats"
    old_dir = world_path / "stats"
    if new_dir.is_dir():
        dirs.append(new_dir)
    if old_dir.is_dir():
        dirs.append(old_dir)
    return dirs if dirs else [old_dir]


def find_advancements_dirs(world_path: Path) -> List[Path]:
    """返回所有可能的进度数据目录（新版 26.1 优先，向后兼容旧版）

    新版路径: <world>/players/advancements/
    旧版路径: <world>/advancements/
    """
    dirs: List[Path] = []
    new_dir = world_path / "players" / "advancements"
    old_dir = world_path / "advancements"
    if new_dir.is_dir():
        dirs.append(new_dir)
    if old_dir.is_dir():
        dirs.append(old_dir)
    return dirs if dirs else [old_dir]


def find_data_dirs(world_path: Path) -> List[Path]:
    """返回所有可能的世界数据目录（新版 26.1 优先，向后兼容旧版）

    新版路径: <world>/data/minecraft/（命名空间子目录）
    旧版路径: <world>/data/
    """
    dirs: List[Path] = []
    new_dir = world_path / "data" / "minecraft"
    old_dir = world_path / "data"
    if new_dir.is_dir():
        dirs.append(new_dir)
    if old_dir.is_dir():
        dirs.append(old_dir)
    return dirs if dirs else [old_dir]


def is_mc26_format(world_path: Path) -> bool:
    """判断存档是否为 Minecraft 26.1+ 新版格式

    通过检查 players/data 目录是否存在来判断。
    """
    return (world_path / "players" / "data").is_dir()


def get_write_player_data_dir(world_path: Path) -> Path:
    """获取写入玩家数据的目标目录

    如果存档是 26.1 格式，返回新路径；否则返回旧路径。
    """
    if is_mc26_format(world_path):
        return world_path / "players" / "data"
    return world_path / "playerdata"


def get_write_stats_dir(world_path: Path) -> Path:
    """获取写入统计数据的目标目录"""
    if is_mc26_format(world_path):
        return world_path / "players" / "stats"
    return world_path / "stats"


def get_write_advancements_dir(world_path: Path) -> Path:
    """获取写入进度数据的目标目录"""
    if is_mc26_format(world_path):
        return world_path / "players" / "advancements"
    return world_path / "advancements"


def validate_world_name(world_name: str) -> str:
    """Validate a world folder name before it is joined into a path."""
    name = world_name.strip()
    if not name:
        raise ValueError("世界名称不能为空")
    if name in {".", ".."} or _INVALID_WORLD_NAME_CHARS.search(name):
        raise ValueError(f"不安全的世界名称: {world_name!r}")
    if Path(name).is_absolute():
        raise ValueError(f"世界名称不能是绝对路径: {world_name!r}")
    return name


def safe_destination_world(
        src_world: Path,
        dest_dir: Path,
        world_name: str) -> Path:
    """Return a validated destination world path under dest_dir."""
    safe_name = validate_world_name(world_name)
    base = dest_dir.resolve()
    dest_world = (base / safe_name).resolve()
    try:
        dest_world.relative_to(base)
    except ValueError as exc:
        raise ValueError(f"目标路径越界: {dest_world}") from exc
    _ensure_distinct_tree(src_world.resolve(), dest_world)
    return dest_world


def _ensure_distinct_tree(src_path: Path, dst_path: Path) -> None:
    if src_path == dst_path:
        raise ValueError("源路径和目标路径不能相同")
    if _is_relative_to(dst_path, src_path):
        raise ValueError("目标路径不能位于源路径内部")
    if _is_relative_to(src_path, dst_path):
        raise ValueError("目标路径不能是源路径的父目录")


def _is_relative_to(path: Path, base: Path) -> bool:
    try:
        path.relative_to(base)
        return True
    except ValueError:
        return False


def replace_directory_tree(
        src_path: Path,
        dst_path: Path,
        *,
        ignore=None) -> None:
    """Safely replace dst_path with a copy of src_path using atomic operations.

    使用原子操作确保数据完整性：先复制到临时目录，成功后再替换目标目录。
    如果复制过程中发生错误，原目标目录会被保留。
    """
    import tempfile
    import os

    src_resolved = src_path.resolve()
    dst_resolved = dst_path.resolve()
    _ensure_distinct_tree(src_resolved, dst_resolved)

    if dst_resolved.exists():
        if not dst_resolved.is_dir():
            raise ValueError(f"目标路径不是目录: {dst_resolved}")
        if (
            any(dst_resolved.iterdir())
            and not (dst_resolved / "level.dat").exists()
        ):
            raise ValueError(f"目标目录不是 Minecraft 存档目录，拒绝删除: {dst_resolved}")

    dst_resolved.parent.mkdir(parents=True, exist_ok=True)

    # 使用原子操作：先复制到临时目录，再替换
    temp_dir = None
    try:
        # 创建临时目录（在目标目录的父目录下）
        temp_dir = tempfile.mkdtemp(
            prefix=f".tmp_{dst_resolved.name}_",
            dir=str(dst_resolved.parent)
        )
        temp_path = Path(temp_dir)

        # 复制源目录到临时目录
        shutil.copytree(
            src_resolved,
            temp_path / dst_resolved.name,
            ignore=ignore)

        # 原子替换：先删除旧目录（如果存在），再移动临时目录
        final_temp_path = temp_path / dst_resolved.name
        if dst_resolved.exists():
            shutil.rmtree(dst_resolved)

        # 使用 os.replace 进行原子移动
        os.replace(str(final_temp_path), str(dst_resolved))
        temp_dir = None  # 标记为已成功处理

    finally:
        # 清理临时目录（如果还有）
        if temp_dir and Path(temp_dir).exists():
            shutil.rmtree(temp_dir, ignore_errors=True)


def update_server_properties(
        dest_dir: Path,
        world_name: str,
        log: LogCallback) -> None:
    """修改 server.properties 文件中的 level-name 设置

    查找并更新服务端根目录下的 server.properties 文件，
    将 level-name 属性设置为指定的世界文件夹名称。
    如果文件不存在则跳过更新。

    Args:
        dest_dir: 服务端根目录（包含 server.properties 文件）
        world_name: 新的世界文件夹名称
        log: 日志回调函数，接受 (消息, 级别) 两个参数
    """
    world_name = validate_world_name(world_name)
    props_file: Path = dest_dir / "server.properties"

    if not props_file.exists():
        log("未找到 server.properties，跳过更新", "INFO")
        return

    try:
        original = props_file.read_text(encoding='utf-8')
        newline = "\r\n" if "\r\n" in original else "\n"
        had_trailing_newline = original.endswith(("\n", "\r"))
        lines: list[str] = original.splitlines()
        new_lines: list[str] = []
        found: bool = False

        for line in lines:
            if line.startswith("level-name="):
                new_lines.append(f"level-name={world_name}")
                found = True
            else:
                new_lines.append(line)

        if not found:
            new_lines.append(f"level-name={world_name}")

        content = newline.join(new_lines)
        if had_trailing_newline:
            content += newline
        props_file.write_text(content, encoding='utf-8')
        log(f"已更新 server.properties: level-name={world_name}", "CONFIG")

    except Exception as e:
        log(f"更新 server.properties 失败: {e}", "ERROR")
