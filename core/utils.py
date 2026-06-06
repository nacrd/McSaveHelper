"""通用工具函数

提供项目中常用的工具函数，目前主要包含 server.properties 的更新功能。
"""

from pathlib import Path

from .types import LogCallback


def update_server_properties(dest_dir: Path, world_name: str, log: LogCallback) -> None:
    """修改 server.properties 文件中的 level-name 设置

    查找并更新服务端根目录下的 server.properties 文件，
    将 level-name 属性设置为指定的世界文件夹名称。
    如果文件不存在则跳过更新。

    Args:
        dest_dir: 服务端根目录（包含 server.properties 文件）
        world_name: 新的世界文件夹名称
        log: 日志回调函数，接受 (消息, 级别) 两个参数
    """
    props_file: Path = dest_dir / "server.properties"

    if not props_file.exists():
        log("未找到 server.properties，跳过更新", "INFO")
        return

    try:
        lines: list[str] = props_file.read_text(encoding='utf-8').splitlines()
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

        props_file.write_text("\n".join(new_lines), encoding='utf-8')
        log(f"已更新 server.properties: level-name={world_name}", "CONFIG")

    except Exception as e:
        log(f"更新 server.properties 失败: {e}", "ERROR")
