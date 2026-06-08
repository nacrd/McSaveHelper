"""
测试 core/cleaner.py 模块
"""
import tempfile
from pathlib import Path
from core.cleaner import should_clean, clean_world
from core.constants import MinecraftConstants


def test_should_clean():
    """测试 should_clean 函数"""
    # 测试应该被清理的文件/目录
    assert should_clean(Path("logs")) is True
    assert should_clean(Path("crash-reports")) is True
    assert should_clean(Path("session.lock")) is True

    # 测试带扩展名的文件
    assert should_clean(Path("test.clientcache")) is True
    assert should_clean(Path("test.log")) is True

    # 测试不应该被清理的文件
    assert should_clean(Path("level.dat")) is False
    assert should_clean(Path("region")) is False
    assert should_clean(Path("playerdata")) is False


def test_clean_world():
    """测试 clean_world 函数"""
    # 创建一个临时目录作为测试世界
    with tempfile.TemporaryDirectory() as tmpdir:
        world_path = Path(tmpdir)

        # 创建一些应该被清理的文件和目录
        (world_path / "logs").mkdir()
        (world_path / "crash-reports").mkdir()
        (world_path / "session.lock").touch()
        (world_path / "test.clientcache").touch()
        (world_path / "test.log").touch()

        # 创建一些不应该被清理的文件
        (world_path / "level.dat").touch()
        (world_path / "region").mkdir()

        # 创建一个简单的日志回调函数
        log_messages = []

        def log_callback(msg: str, level: str):
            log_messages.append((msg, level))

        # 运行清理
        clean_world(world_path, log_callback)

        # 验证结果
        assert not (world_path / "logs").exists()
        assert not (world_path / "crash-reports").exists()
        assert not (world_path / "session.lock").exists()
        assert not (world_path / "test.clientcache").exists()
        assert not (world_path / "test.log").exists()

        # 验证重要文件还在
        assert (world_path / "level.dat").exists()
        assert (world_path / "region").exists()
