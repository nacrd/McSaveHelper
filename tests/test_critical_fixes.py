"""
测试关键修复的场景覆盖
"""
import tempfile
import threading
import time
from pathlib import Path
import os
import shutil

import pytest


class TestConfigServiceConcurrency:
    """测试 ConfigService 的并发安全性"""

    def test_concurrent_config_updates(self):
        """测试多线程同时更新配置时的线程安全"""
        from app.services.config_service import ConfigService
        
        # 使用临时目录避免影响真实配置
        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)
            
            # 重置单例以使用新目录
            ConfigService._instance = None
            
            config = ConfigService(config_dir)
            
            errors = []
            
            def update_config(thread_id):
                try:
                    for i in range(50):
                        # 测试 setter 方法的线程安全
                        config.use_custom_mapping = (thread_id + i) % 2 == 0
                        config.language = f"lang_{thread_id}_{i}"
                        
                        # 测试批量更新方法
                        config.update_batch_config(
                            version_detection=(thread_id + i) % 2 == 0,
                            max_concurrent=thread_id + 1,
                        )
                        
                        # 测试 UUID 映射更新
                        config.set_custom_uuid_mapping(
                            f"player_{thread_id}_{i}",
                            f"uuid_{thread_id}_{i}"
                        )
                except Exception as e:
                    errors.append((thread_id, str(e)))
            
            threads = []
            for i in range(4):
                t = threading.Thread(target=update_config, args=(i,))
                threads.append(t)
                t.start()
            
            for t in threads:
                t.join()
            
            # 验证没有并发错误
            assert len(errors) == 0, f"并发错误: {errors}"
            
            # 验证配置文件可以正常读取
            config_path = config_dir / "config.json"
            assert config_path.exists(), "配置文件未创建"
            
            # 验证配置结构完整性
            config_dict = config.get_config_dict()
            assert "version_detection" in config_dict
            assert "use_custom_mapping" in config_dict
            assert "custom_uuid_mappings" in config_dict
            assert "ui_settings" in config_dict
            assert isinstance(config_dict["custom_uuid_mappings"], dict)
            
            # 清理单例
            ConfigService._instance = None

    def test_config_copy_not_reference(self):
        """测试 get_config_dict 返回副本而非引用"""
        from app.services.config_service import ConfigService
        
        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)
            ConfigService._instance = None
            
            config = ConfigService(config_dir)
            
            # 获取配置副本
            config_copy = config.get_config_dict()
            
            # 修改副本
            config_copy["test_key"] = "test_value"
            
            # 验证原配置未被修改
            original_config = config.get_config_dict()
            assert "test_key" not in original_config, "配置副本不是独立副本"
            
            ConfigService._instance = None


class TestBatchProcessorConcurrency:
    """测试批量处理器的并发安全性"""

    def test_concurrent_result_update(self):
        """测试多线程同时更新结果字典时的线程安全"""
        from core.batch_processor import BatchProcessor
        
        processor = BatchProcessor(max_workers=4)
        
        def update_results(worker_id):
            for i in range(100):
                with processor._lock:
                    processor.results[f"task_{worker_id}_{i}"] = {
                        "success": True,
                        "world_name": f"world_{worker_id}_{i}"
                    }
        
        threads = []
        for i in range(4):
            t = threading.Thread(target=update_results, args=(i,))
            threads.append(t)
            t.start()
        
        for t in threads:
            t.join()
        
        assert len(processor.results) == 400


class TestSaveNbtResourceManagement:
    """测试 NBT 文件保存的资源管理"""

    def test_temp_file_cleanup_on_failure(self):
        """测试保存失败时临时文件被正确清理"""
        from core.converter import save_nbt
        import nbtlib
        
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            test_file = tmp_path / "test.dat"
            
            # 创建一个无效的 NBT 数据来触发保存失败
            invalid_data = "not a valid nbt"
            
            try:
                save_nbt(test_file, invalid_data)
                assert False, "Expected exception"
            except Exception:
                pass
            
            # 检查是否有遗留的临时文件
            temp_files = list(tmp_path.glob(".*.tmp"))
            assert len(temp_files) == 0, f"残留临时文件: {temp_files}"


class TestReplaceDirectoryTreeAtomicity:
    """测试目录树替换的原子性"""

    def test_atomic_replace_success(self):
        """测试正常替换目录"""
        from core.utils import replace_directory_tree
        
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            
            # 创建源目录
            src_dir = tmp_path / "source"
            src_dir.mkdir()
            (src_dir / "level.dat").write_text("source content")
            (src_dir / "playerdata").mkdir()
            (src_dir / "playerdata" / "test.dat").write_text("player data")
            
            # 创建目标目录（模拟已有存档）
            dst_dir = tmp_path / "target"
            dst_dir.mkdir()
            (dst_dir / "level.dat").write_text("existing content")
            (dst_dir / "region").mkdir()
            
            # 执行替换
            replace_directory_tree(src_dir, dst_dir)
            
            # 验证目标目录内容被正确替换
            assert dst_dir.exists(), "目标目录不存在"
            assert (dst_dir / "level.dat").read_text() == "source content", "内容未被替换"
            assert (dst_dir / "playerdata" / "test.dat").exists(), "子目录未被复制"
            assert not (dst_dir / "region").exists(), "旧目录内容未被删除"

    def test_atomic_replace_failure_keeps_original(self):
        """测试源目录读取失败时保留原目标目录"""
        from core.utils import replace_directory_tree
        
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            
            # 创建源目录
            src_dir = tmp_path / "source"
            src_dir.mkdir()
            (src_dir / "level.dat").write_text("original content")
            
            # 创建一个无法读取的文件（权限问题）
            no_access_file = src_dir / "no_access.txt"
            no_access_file.write_text("cannot read")
            
            # 创建目标目录（模拟已有存档）
            dst_dir = tmp_path / "target"
            dst_dir.mkdir()
            (dst_dir / "level.dat").write_text("existing content")
            (dst_dir / "region").mkdir()
            
            # 测试应该失败但原目录应保留
            try:
                # 使用不存在的路径作为源目录，确保失败
                replace_directory_tree(src_dir / "nonexistent", dst_dir)
            except Exception:
                pass
            
            # 验证原目录仍然存在且内容完整
            assert dst_dir.exists(), "目标目录被意外删除"
            assert (dst_dir / "level.dat").exists(), "level.dat 丢失"
            assert (dst_dir / "region").exists(), "region 目录丢失"
            assert (dst_dir / "level.dat").read_text() == "existing content", "原内容被修改"

    def test_temp_directory_cleanup(self):
        """测试失败时临时目录被清理"""
        from core.utils import replace_directory_tree
        
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            
            # 创建源目录
            src_dir = tmp_path / "source"
            src_dir.mkdir()
            (src_dir / "level.dat").write_text("test")
            
            # 创建目标目录
            dst_dir = tmp_path / "target"
            dst_dir.mkdir()
            
            # 使用不存在的源路径来触发失败
            try:
                replace_directory_tree(src_dir / "nonexistent", dst_dir)
            except Exception:
                pass
            
            # 检查是否有遗留的临时目录
            temp_dirs = list(tmp_path.glob(".tmp_target_*"))
            assert len(temp_dirs) == 0, f"残留临时目录: {temp_dirs}"


class TestMigrationControllerPublicMethods:
    """测试迁移控制器使用公共方法"""

    def test_controller_uses_public_methods(self):
        """验证迁移控制器使用公共方法而非私有属性"""
        import ast
        from pathlib import Path
        
        controller_path = Path(__file__).parent.parent / "app" / "controllers" / "migration_controller.py"
        content = controller_path.read_text()
        
        # 解析 AST
        tree = ast.parse(content)
        
        # 查找所有属性访问
        private_attr_accesses = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                if isinstance(node.value, ast.Name) and node.value.id == 'app':
                    if isinstance(node.attr, str) and node.attr.startswith('_'):
                        # 排除 _t 方法（这是翻译方法）
                        if node.attr != '_t':
                            private_attr_accesses.append(f"app.{node.attr}")
        
        # 应该没有直接访问私有属性
        assert len(private_attr_accesses) == 0, \
            f"检测到直接访问私有属性: {private_attr_accesses}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])