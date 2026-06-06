"""
测试 core/utils.py 模块
"""
import tempfile
from pathlib import Path
from core.utils import update_server_properties


def test_update_server_properties():
    """测试 update_server_properties 函数"""
    # 创建临时目录
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        
        # 测试场景1: server.properties 存在且有 level-name
        props_content = """\
# Minecraft server properties
level-name=world_old
gamemode=survival
difficulty=easy
"""
        props_path = tmp_path / "server.properties"
        props_path.write_text(props_content, encoding="utf-8")
        
        # 创建日志回调
        log_messages = []
        def log_callback(msg: str, level: str):
            log_messages.append((msg, level))
        
        # 执行更新
        update_server_properties(tmp_path, "world_new", log_callback)
        
        # 验证结果
        new_content = props_path.read_text(encoding="utf-8")
        assert "level-name=world_new" in new_content
        assert "level-name=world_old" not in new_content
        assert "gamemode=survival" in new_content
        
        # 测试场景2: server.properties 不存在
        props_path.unlink()
        log_messages.clear()
        
        update_server_properties(tmp_path, "world_another", log_callback)
        
        # 验证文件没有被创建
        assert not props_path.exists()
