"""通用工具函数"""
from pathlib import Path
from typing import Callable, Optional


def update_server_properties(dest_dir: Path, world_name: str, log: Callable[[str, str], None]) -> None:
    """
    修改 server.properties 文件中的 level-name 设置。
    
    Args:
        dest_dir: 服务端根目录（包含 server.properties）
        world_name: 新的世界文件夹名称
        log: 日志回调函数，接受 (消息, 级别) 参数
    """
    props = dest_dir / "server.properties"
    if props.exists():
        lines = props.read_text(encoding='utf-8').splitlines()
        new_lines = []
        found = False
        for line in lines:
            if line.startswith("level-name="):
                new_lines.append(f"level-name={world_name}")
                found = True
            else:
                new_lines.append(line)
        if not found:
            new_lines.append(f"level-name={world_name}")
        props.write_text("\n".join(new_lines), encoding='utf-8')
        log(f"已更新 server.properties: level-name={world_name}", "CONFIG")
    else:
        log("未找到 server.properties，跳过更新", "INFO")