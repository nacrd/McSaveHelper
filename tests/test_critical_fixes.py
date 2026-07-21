"""
测试关键修复的场景覆盖
"""
import tempfile
import threading
from pathlib import Path

import pytest


class TestConfigServiceConcurrency:
    """测试 ConfigService 的并发安全性"""

    def test_concurrent_config_updates(self):
        """测试多线程同时更新配置时的线程安全"""
        from app.services.config_service import ConfigService

        # 使用临时目录避免影响真实配置
        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)

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

    def test_config_copy_not_reference(self):
        """测试 get_config_dict 返回副本而非引用"""
        from app.services.config_service import ConfigService

        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)
            config = ConfigService(config_dir)

            # 获取配置副本
            config_copy = config.get_config_dict()

            # 修改副本
            config_copy["test_key"] = "test_value"

            # 验证原配置未被修改
            original_config = config.get_config_dict()
            assert "test_key" not in original_config, "配置副本不是独立副本"

    def test_invalid_config_is_backed_up(self):
        """测试损坏配置会备份并回退默认值"""
        from app.services.config_service import ConfigService

        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)
            (config_dir / "config.json").write_text(
                "{invalid json", encoding="utf-8"
            )
            config = ConfigService(config_dir)

            assert config.version_detection is True
            assert (config_dir / "config.json.bak").exists()


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
        from typing import Any, cast

        from core.converter import save_nbt

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            test_file = tmp_path / "test.dat"

            # 创建一个无效的 NBT 数据来触发保存失败
            invalid_data = "not a valid nbt"

            with pytest.raises(Exception):
                save_nbt(test_file, cast(Any, invalid_data))

            # 检查是否有遗留的临时文件
            temp_files = list(tmp_path.glob(".*.tmp"))
            assert len(temp_files) == 0, f"残留临时文件: {temp_files}"

    def test_convert_world_rejects_unimplemented_downgrade(self):
        """测试世界转换拒绝未实现的跨版本降级"""
        from core.converter import ConversionError, convert_world

        with tempfile.TemporaryDirectory() as tmpdir:
            world_path = Path(tmpdir)
            (world_path / "level.dat").write_bytes(b"bad")

            with pytest.raises(ConversionError, match="尚未实现"):
                convert_world(
                    world_path,
                    world_path,
                    target_platform="java",
                    target_version=1)

    def test_migration_rejects_unimplemented_conversion(self):
        """测试迁移服务会暴露未实现的版本转换"""
        from app.services.config_service import ConfigService
        from app.services.migration_service import MigrationService

        with tempfile.TemporaryDirectory() as tmpdir:
            from app.services.backup_service import BackupService
            from app.services.world_transaction import WorldTransactionService
            from app.services.world_write_coordinator import WorldWriteCoordinator

            coordinator = WorldWriteCoordinator()
            backup = BackupService(coordinator)
            service = MigrationService(
                ConfigService(Path(tmpdir) / "config"),
                backup,
                WorldTransactionService(coordinator, backup),
            )
            logs = []

            ok = service._apply_version_conversion(
                Path(tmpdir), "java", "1", lambda msg, level: logs.append(
                    (msg, level)))

            assert ok is False
            assert any(
                level == "ERROR" and "尚未实现" in msg for msg,
                level in logs)


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
            assert (
                dst_dir / "level.dat").read_text(encoding="utf-8") == "source content", "内容未被替换"
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
            assert (
                dst_dir / "level.dat").read_text(encoding="utf-8") == "existing content", "原内容被修改"

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

        controller_path = Path(__file__).parent.parent / \
            "app" / "controllers" / "migration_controller.py"
        content = controller_path.read_text(encoding="utf-8")

        # 解析 AST
        tree = ast.parse(content)

        # 查找所有属性访问
        private_attr_accesses = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                if isinstance(node.value, ast.Name) and node.value.id == 'app':
                    if isinstance(
                            node.attr,
                            str) and node.attr.startswith('_'):
                        # 排除 _t 方法（这是翻译方法）
                        if node.attr != '_t':
                            private_attr_accesses.append(f"app.{node.attr}")

        # 应该没有直接访问私有属性
        assert len(private_attr_accesses) == 0, \
            f"检测到直接访问私有属性: {private_attr_accesses}"


class TestOmniNbtEditing:
    def test_nbt_tree_parses_paths_and_coerces_values(self):
        from app.ui.views.explorer.nbt_tree.parser import parse_path, coerce_value
        from core.nbt import Int, String
        from core.nbt.tag import IntArray

        assert parse_path("Inventory[0].Count") == [
            "Inventory", 0, "Count"]
        assert coerce_value("64", Int(1), "Int") == Int(64)
        assert coerce_value(
            "diamond", String("stone"), "String") == String("diamond")
        assert list(
            coerce_value(
                "[1, 2, 3]", IntArray(
                    [0]), "IntArray")) == [
                1, 2, 3]

    def test_world_session_commits_staged_player_nbt_list_path(
            self, tmp_path: Path):
        import core.nbt as nbtlib
        from core.nbt import Compound, File, Int, String
        from core.nbt.tag import List
        from core.omni.world_session import WorldSession

        world = tmp_path / "world"
        playerdata = world / "playerdata"
        playerdata.mkdir(parents=True)
        level = File(Compound({"Data": Compound(
            {"Version": Compound({"Id": Int(1), "Name": String("test")})})}))
        level.save(world / "level.dat")

        player_uuid = "11111111-1111-1111-1111-111111111111"
        player = File(Compound({"Inventory": List[Compound](
            [Compound({"Count": Int(1), "id": String("minecraft:stone")})]), }))
        player.save(playerdata / f"{player_uuid}.dat")

        session = WorldSession(world, log=lambda msg, level="INFO": None)
        session.queue_modify_nbt(
            player_uuid, [
                "Inventory", 0, "Count"], Int(64))

        assert session.get_queue_size() == 1
        assert session.commit(backup=True)
        assert session.get_queue_size() == 0
        assert (tmp_path / "world.backup").exists()

        updated = nbtlib.load(playerdata / f"{player_uuid}.dat")
        assert updated["Inventory"][0]["Count"] == Int(64)

    def test_world_session_commits_level_dat_relative_path(
            self, tmp_path: Path):
        import core.nbt as nbtlib
        from core.nbt import Compound, File, Int, String
        from core.omni.world_session import WorldSession

        world = tmp_path / "world"
        world.mkdir()
        level = File(Compound({"Data": Compound(
            {"LevelName": String("old"), "Version": Compound({"Id": Int(1)})})}))
        level.save(world / "level.dat")

        session = WorldSession(world, log=lambda msg, level="INFO": None)
        session.queue_modify_nbt(
            Path("level.dat"), [
                "Data", "LevelName"], String("new"))

        assert session.get_queue_size() == 1
        assert session.commit(backup=True)

        updated = nbtlib.load(world / "level.dat")
        assert updated["Data"]["LevelName"] == String("new")

    def test_world_session_commits_data_dat_string_path(self, tmp_path: Path):
        import core.nbt as nbtlib
        from core.nbt import Compound, File, Int, String
        from core.omni.world_session import WorldSession

        world = tmp_path / "world"
        data_dir = world / "data"
        data_dir.mkdir(parents=True)
        level = File(
            Compound({"Data": Compound({"Version": Compound({"Id": Int(1)})})}))
        level.save(world / "level.dat")
        raids = File(Compound({"Data": Compound({"Name": String("old")})}))
        raids.save(data_dir / "raids.dat")

        session = WorldSession(world, log=lambda msg, level="INFO": None)
        session.queue_modify_nbt(
            "data/raids.dat", ["Data", "Name"], String("new"))

        assert session.get_queue_size() == 1
        assert session.commit(backup=True)

        updated = nbtlib.load(data_dir / "raids.dat")
        assert updated["Data"]["Name"] == String("new")

    def test_world_session_rejects_nbt_target_outside_world(
            self, tmp_path: Path):
        from core.nbt import Compound, File, Int, String
        from core.omni.world_session import WorldSession

        world = tmp_path / "world"
        world.mkdir()
        level = File(
            Compound({"Data": Compound({"Version": Compound({"Id": Int(1)})})}))
        level.save(world / "level.dat")
        outside = tmp_path / "outside.dat"
        File(Compound({"Data": Compound({"Name": String("old")})})).save(
            outside)

        session = WorldSession(world, log=lambda msg, level="INFO": None)
        session.queue_modify_nbt(outside, ["Data", "Name"], String("new"))

        assert session.get_queue_size() == 1
        assert not session.commit(backup=False)

    def test_world_session_commits_json_relative_path(self, tmp_path: Path):
        import json
        from core.nbt import Compound, File, Int
        from core.omni.world_session import WorldSession

        world = tmp_path / "world"
        stats_dir = world / "stats"
        stats_dir.mkdir(parents=True)
        level = File(
            Compound({"Data": Compound({"Version": Compound({"Id": Int(1)})})}))
        level.save(world / "level.dat")
        stats_path = stats_dir / "player.json"
        stats_path.write_text(json.dumps(
            {"stats": {"minecraft:mined": {"minecraft:stone": 1}}}), encoding="utf-8")

        session = WorldSession(world, log=lambda msg, level="INFO": None)
        session.queue_modify_json(
            "stats/player.json", ["stats", "minecraft:mined", "minecraft:stone"], 8)

        assert session.get_queue_size() == 1
        assert session.commit(backup=True)

        updated = json.loads(stats_path.read_text(encoding="utf-8"))
        assert updated["stats"]["minecraft:mined"]["minecraft:stone"] == 8

    def test_world_session_commits_nbt_add_and_delete_operations(
            self, tmp_path: Path):
        import core.nbt as nbtlib
        from core.nbt import Compound, File, Int, String
        from core.nbt.tag import List
        from core.omni.world_session import WorldSession

        world = tmp_path / "world"
        world.mkdir()
        level = File(Compound({"Data": Compound({
            "Version": Compound({"Id": Int(1)}),
            "Rules": Compound({"Old": String("remove")}),
            "Items": List[Int]([Int(1)]),
        })}))
        level.save(world / "level.dat")

        session = WorldSession(world, log=lambda msg, level="INFO": None)
        session.queue_modify_nbt(
            Path("level.dat"), [
                "Data", "Rules", "Added"], String("ok"), operation="add")
        session.queue_modify_nbt(
            Path("level.dat"), [
                "Data", "Rules", "Old"], None, operation="delete")
        session.queue_modify_nbt(
            Path("level.dat"), [
                "Data", "Items", 1], Int(2), operation="add")

        assert session.commit(backup=False)
        updated = nbtlib.load(world / "level.dat")
        assert updated["Data"]["Rules"]["Added"] == String("ok")
        assert "Old" not in updated["Data"]["Rules"]
        assert list(updated["Data"]["Items"]) == [Int(1), Int(2)]

    def test_world_session_commits_json_add_and_delete_operations(
            self, tmp_path: Path):
        import json
        from core.nbt import Compound, File, Int
        from core.omni.world_session import WorldSession

        world = tmp_path / "world"
        stats_dir = world / "stats"
        stats_dir.mkdir(parents=True)
        File(Compound({"Data": Compound({"Version": Compound({"Id": Int(1)})})})).save(
            world / "level.dat")
        stats_path = stats_dir / "player.json"
        stats_path.write_text(json.dumps(
            {"stats": {"old": 1}, "items": ["a"]}), encoding="utf-8")

        session = WorldSession(world, log=lambda msg, level="INFO": None)
        session.queue_modify_json(
            "stats/player.json", ["stats", "new"], 2, operation="add")
        session.queue_modify_json(
            "stats/player.json", ["stats", "old"], None, operation="delete")
        session.queue_modify_json(
            "stats/player.json", ["items", 1], "b", operation="add")

        assert session.commit(backup=False)
        updated = json.loads(stats_path.read_text(encoding="utf-8"))
        assert updated["stats"] == {"new": 2}
        assert updated["items"] == ["a", "b"]

    def test_world_session_serializes_chunk_record_with_length_and_zlib_type(
            self, tmp_path: Path):
        import zlib
        from core.nbt import Compound, File, Int
        from core.omni.world_session import WorldSession

        world = tmp_path / "world"
        world.mkdir()
        region_path = world / "region" / "r.0.0.mca"
        region_path.parent.mkdir(parents=True)
        region_path.write_bytes(b"\x00" * 8192)

        level = File(
            Compound({"Data": Compound({"Version": Compound({"Id": Int(1)})})}))
        level.save(world / "level.dat")

        chunk = File({"DataVersion": Int(1)}, gzipped=False)

        session = WorldSession(world, log=lambda msg, level="INFO": None)
        session._executor._write_chunk(region_path, 0, 0, chunk)

        raw = region_path.read_bytes()
        loc = raw[:4]
        offset = int.from_bytes(loc[:3], "big") * 4096
        sectors = loc[3]
        assert offset >= 8192
        assert sectors >= 1
        length = int.from_bytes(raw[offset:offset + 4], "big")
        assert raw[offset + 4] == 2
        compressed = raw[offset + 5:offset + 4 + length]
        assert zlib.decompress(compressed)

    def test_block_data_service_reads_single_palette_block_without_data(self):
        from app.services.block_data_service import BlockDataService

        chunk = {
            "sections": [
                {
                    "Y": 4,
                    "block_states": {
                        "palette": [{"Name": "minecraft:stone"}],
                    },
                }
            ]
        }

        info = BlockDataService().get_block_at(chunk, 8, 64, 8)

        assert info is not None
        assert info.name == "minecraft:stone"
        assert info.section_y == 4
        assert info.palette_index == 0

    def test_block_data_service_decodes_compacted_palette_indices(self):
        from app.services.block_data_service import BlockDataService

        palette = [{"Name": "minecraft:air"}, {"Name": "minecraft:chest"}]
        data = [0] * 256
        index = (10 * 16 + 3) * 16 + 2
        bits = 4
        values_per_long = 64 // bits
        data[index // values_per_long] |= 1 << (
            (index % values_per_long) * bits
        )
        chunk = {"sections": [
            {"Y": 4, "block_states": {"palette": palette, "data": data}}]}

        info = BlockDataService().get_block_at(chunk, 2, 74, 3)

        assert info is not None
        assert info.name == "minecraft:chest"
        assert info.local_x == 2
        assert info.local_y == 10
        assert info.local_z == 3

    def test_nbt_tree_coerces_json_values(self):
        from app.ui.views.explorer.nbt_tree.parser import coerce_value

        assert coerce_value("42", 1, "int") == 42
        assert coerce_value("3.5", 1.0, "float") == 3.5
        assert coerce_value("false", True, "bool") is False
        assert coerce_value("null", None, "NoneType") is None

    def test_nbt_tree_can_load_readonly_data(self):
        from app.ui.views.explorer.nbt_tree import NBTTreeView

        tree = NBTTreeView()
        tree.load_nbt({"Entities": []}, editable=False)

        assert tree.get_modified_data() == {"Entities": []}
        assert tree._editable is False

    def test_nbt_tree_expand_all_enables_full_display(self):
        from app.ui.views.explorer.nbt_tree import NBTTreeView

        tree = NBTTreeView()
        tree.load_nbt({"Entities": [{"id": "minecraft:zombie"}]})
        tree.expand_all()

        assert tree._expand_all is True
        assert tree._show_all_children is True

        tree.collapse_all()

        assert tree._expand_all is False
        assert tree._collapse_all is True
        assert tree._show_all_children is False

    def test_nbt_tree_collects_overview_stats(self):
        from app.ui.views.explorer.nbt_tree import NBTTreeView

        stats = NBTTreeView()._collect_stats({
            "Level": {
                "DataVersion": 3953,
                "Entities": [{"id": "minecraft:pig"}],
            }
        })

        assert stats == {"fields": 5, "containers": 4, "values": 2}

    def test_explorer_extracts_chunk_entities_and_block_entities(self):
        from app.ui.views.explorer.explorer_helpers import extract_chunk_objects

        chunk_data = {
            "Entities": [
                {"id": "minecraft:zombie", "Pos": [1.0, 64.0, 2.0]},
            ],
            "block_entities": [
                {"id": "minecraft:chest", "x": 3, "y": 65, "z": 4},
            ],
        }

        objects = extract_chunk_objects(chunk_data)

        assert len(objects) == 2
        assert objects[0]["title"] == "实体 #1: minecraft:zombie"
        assert objects[0]["subtitle"] == "(1.0, 64.0, 2.0)"
        assert objects[1]["title"] == "方块实体 #1: minecraft:chest"
        assert objects[1]["subtitle"] == "(3, 65, 4)"

    def test_explorer_converts_world_coords_to_region_and_local_chunk(self):
        from app.ui.views.explorer.explorer_view import ExplorerView

        assert ExplorerView._world_coords_to_region_chunk(0, 0) == (0, 0, 0, 0)
        assert ExplorerView._world_coords_to_region_chunk(
            511, 511) == (
            0, 0, 31, 31)
        assert ExplorerView._world_coords_to_region_chunk(
            512, 512) == (
            1, 1, 0, 0)
        assert ExplorerView._world_coords_to_region_chunk(
            -1, -1) == (-1, -1, 31, 31)
        assert ExplorerView._world_coords_to_region_chunk(
            -512, -512) == (-1, -1, 0, 0)

    def test_explorer_formats_change_summary(self):
        from app.models.nbt_edit import NbtChange
        from app.ui.views.explorer.explorer_helpers import format_change_summary

        summary = format_change_summary(0, NbtChange(
            target="test",
            target_label="玩家 NBT: test",
            format="json",
            operation="set",
            path=("stats", "minecraft:mined", "minecraft:stone"),
            display_path="stats.minecraft:mined.minecraft:stone",
            old_value=1,
            new_value=8,
        ))

        assert "#1 [JSON] 玩家 NBT: test" in summary
        assert "stats.minecraft:mined.minecraft:stone" in summary
        assert "- 1" in summary
        assert "+ 8" in summary

    def test_explorer_coerces_player_edit_values_like_nbt_tags(self):
        from app.ui.views.explorer.explorer_view import ExplorerView
        from core.nbt import Float, Int

        assert ExplorerView._coerce_like_tag("20", Float(1.0)) == Float(20.0)
        assert ExplorerView._coerce_like_tag(
            "Float(60.0)", Float(1.0)) == Float(60.0)
        assert ExplorerView._coerce_like_tag("12.0", Int(1)) == Int(12)
        assert ExplorerView._tag_display_value(Float(60.0)) == "60.0"

    def test_block_data_service_set_block_replaces_in_palette(self):
        from app.services.block_data_service import BlockDataService

        palette = [
            {"Name": "minecraft:air"},
            {"Name": "minecraft:stone"},
            {"Name": "minecraft:chest"},
        ]
        bits = 4
        values_per_long = 64 // bits
        num_longs = (4096 + values_per_long - 1) // values_per_long
        data = [0] * num_longs
        target_flat = (10 * 16 + 3) * 16 + 2
        long_idx = target_flat // values_per_long
        bit_off = (target_flat % values_per_long) * bits
        data[long_idx] |= 2 << bit_off

        chunk = {"sections": [
            {"Y": 4, "block_states": {"palette": palette, "data": data}}]}

        svc = BlockDataService()
        info_before = svc.get_block_at(chunk, 2, 74, 3)
        assert info_before is not None
        assert info_before.name == "minecraft:chest"

        result = svc.set_block_at(chunk, 2, 74, 3, "minecraft:stone")
        assert result.success is True
        assert result.old_name == "minecraft:chest"
        assert result.new_name == "minecraft:stone"
        assert result.repacked is False

        info_after = svc.get_block_at(chunk, 2, 74, 3)
        assert info_after is not None
        assert info_after.name == "minecraft:stone"

    def test_block_data_service_set_block_adds_new_palette_entry(self):
        from app.services.block_data_service import BlockDataService

        palette = [
            {"Name": "minecraft:air"},
            {"Name": "minecraft:stone"},
        ]
        bits = 4
        values_per_long = 64 // bits
        num_longs = (4096 + values_per_long - 1) // values_per_long
        data = [0] * num_longs
        target_flat = (5 * 16 + 7) * 16 + 3
        long_idx = target_flat // values_per_long
        bit_off = (target_flat % values_per_long) * bits
        data[long_idx] |= 1 << bit_off

        chunk = {"sections": [
            {"Y": 4, "block_states": {"palette": palette, "data": data}}]}

        svc = BlockDataService()
        result = svc.set_block_at(chunk, 3, 69, 7, "minecraft:diamond_block")
        assert result.success is True
        assert result.old_name == "minecraft:stone"
        assert result.new_name == "minecraft:diamond_block"
        assert len(palette) == 3
        assert result.repacked is False

        info_after = svc.get_block_at(chunk, 3, 69, 7)
        assert info_after is not None
        assert info_after.name == "minecraft:diamond_block"

    def test_block_data_service_encode_decode_roundtrip(self):
        from app.services.block_data_service import BlockDataService

        svc = BlockDataService()
        for palette_size in [2, 16, 17, 256]:
            indices = list(range(palette_size)) * (4096 // palette_size)
            remainder = 4096 - len(indices)
            indices.extend([0] * remainder)
            encoded = svc._encode_all_indices(indices, palette_size)
            decoded = svc._decode_all_indices(encoded, palette_size)
            assert decoded == indices, f"Roundtrip failed for palette_size={palette_size}"

    def test_block_data_service_set_block_with_properties(self):
        from app.services.block_data_service import BlockDataService

        palette = [{"Name": "minecraft:air"},
                   {"Name": "minecraft:oak_stairs",
                    "Properties": {"facing": "north",
                                   "half": "bottom"}},
                   ]
        bits = 4
        values_per_long = 64 // bits
        num_longs = (4096 + values_per_long - 1) // values_per_long
        data = [0] * num_longs

        chunk = {"sections": [
            {"Y": 0, "block_states": {"palette": palette, "data": data}}]}

        svc = BlockDataService()
        result = svc.set_block_at(
            chunk, 0, 0, 0, "minecraft:oak_stairs", {
                "facing": "south", "half": "top"})
        assert result.success is True
        assert result.new_name == "minecraft:oak_stairs"
        assert len(palette) == 3

        info_after = svc.get_block_at(chunk, 0, 0, 0)
        assert info_after is not None
        assert info_after.name == "minecraft:oak_stairs"
        assert info_after.properties.get("facing") == "south"
        assert info_after.properties.get("half") == "top"

    def test_block_data_service_set_block_same_block_noop(self):
        from app.services.block_data_service import BlockDataService

        palette = [{"Name": "minecraft:air"}, {"Name": "minecraft:stone"}]
        bits = 4
        values_per_long = 64 // bits
        num_longs = (4096 + values_per_long - 1) // values_per_long
        data = [0] * num_longs

        chunk = {"sections": [
            {"Y": 0, "block_states": {"palette": palette, "data": data}}]}

        svc = BlockDataService()
        result = svc.set_block_at(chunk, 0, 0, 0, "minecraft:air")
        assert result.success is True
        assert "相同" in result.message
        assert len(palette) == 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
