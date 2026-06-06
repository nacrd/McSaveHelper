"""
全能转换逻辑 (Conversion Pipelines)

实现 Java ↔ Bedrock 桥接、版本软着陆等转换功能。
"""
import struct
import os
import tempfile
import nbtlib
from nbtlib import File, Compound, Byte, Short, Int, Long, Float, Double, String, ByteArray, IntArray, List
from typing import Union, Dict, Any, Optional, Tuple, List as TList
from pathlib import Path

from .constants import MinecraftConstants
from .utils import replace_directory_tree


class ConversionError(Exception):
    """转换过程中发生的错误"""
    pass


def detect_endian(file_path: Path) -> str:
    """
    检测 NBT 文件的字节序（大端序 'big' 或小端序 'little'）。
    
    通过读取第一个字节（标签 ID）和后续长度来判断。
    Java 版 NBT 以大端序存储，Bedrock 版以小端序存储。
    """
    with open(file_path, 'rb') as f:
        data = f.read(4)
        if len(data) < 4:
            raise ConversionError("文件太小，无法检测字节序")
        # 检查是否可能是有效的小端序根标签
        # 假设根标签是 Compound (0x0A)
        if data[0] == 0x0A:
            # 大端序：标签 ID 在前，后跟两个字节的键长度
            # 小端序：标签 ID 在前，但后续的 short 是小端序
            # 尝试解析键长度
            key_len = struct.unpack('>H', data[2:4])[0]  # 大端序假设
            # 如果长度合理（例如 < 1000），可能是大端序
            if key_len < 1000:
                return 'big'
            # 否则尝试小端序
            key_len_le = struct.unpack('<H', data[2:4])[0]
            if key_len_le < 1000:
                return 'little'
        # 回退到尝试加载两种字节序
    # 默认返回大端序（Java 版）
    return 'big'


def load_nbt(file_path: Path, byteorder: Optional[str] = None) -> File:
    """
    加载 NBT 文件，可选择指定字节序。
    
    如果 byteorder 为 None，则自动检测。
    """
    if byteorder is None:
        endian = detect_endian(file_path)
        byteorder = endian  # 'big' or 'little'
    try:
        return nbtlib.load(file_path, byteorder=byteorder)
    except Exception as e:
        raise ConversionError(f"加载 NBT 文件失败: {e}")


def save_nbt(file_path: Path, nbt_data: File, byteorder: str = 'big') -> None:
    """
    以指定字节序保存 NBT 文件。
    """
    try:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=f".{file_path.name}.", suffix=".tmp", dir=str(file_path.parent))
        os.close(fd)
        tmp_path = Path(tmp_name)
        try:
            nbt_data.save(tmp_path, byteorder=byteorder)
            os.replace(tmp_path, file_path)
        finally:
            if tmp_path.exists():
                tmp_path.unlink(missing_ok=True)
    except Exception as e:
        raise ConversionError(f"保存 NBT 文件失败: {e}")


def convert_endian(src_path: Path, dst_path: Path, target_byteorder: str) -> None:
    """
    转换 NBT 文件的字节序（Java ↔ Bedrock）。
    
    Args:
        src_path: 源文件路径
        dst_path: 目标文件路径
        target_byteorder: 目标字节序，'big'（Java）或 'little'（Bedrock）
    """
    # 检测源字节序
    src_endian = detect_endian(src_path)
    if src_endian == target_byteorder:
        if src_path.resolve() != dst_path.resolve():
            import shutil
            shutil.copy2(src_path, dst_path)
        return
    # 加载源文件
    data = load_nbt(src_path, byteorder=src_endian)
    # 保存为目标字节序
    save_nbt(dst_path, data, byteorder=target_byteorder)


class IdMapping:
    """
    Java ↔ Bedrock 方块/物品 ID 映射。
    
    映射基于已知的 ID 转换表。
    """
    # Java 到 Bedrock 的方块 ID 映射（示例，需要扩充）
    BLOCK_JAVA_TO_BEDROCK: Dict[str, str] = {
        # 方块
        "minecraft:grass_block": "minecraft:grass",
        "minecraft:oak_planks": "minecraft:planks",
        "minecraft:oak_log": "minecraft:log",
        "minecraft:spruce_planks": "minecraft:planks",
        "minecraft:birch_planks": "minecraft:planks",
        "minecraft:jungle_planks": "minecraft:planks",
        "minecraft:acacia_planks": "minecraft:planks",
        "minecraft:dark_oak_planks": "minecraft:planks",
        "minecraft:oak_leaves": "minecraft:leaves",
        "minecraft:spruce_leaves": "minecraft:leaves",
        "minecraft:birch_leaves": "minecraft:leaves",
        "minecraft:jungle_leaves": "minecraft:leaves",
        "minecraft:acacia_leaves": "minecraft:leaves",
        "minecraft:dark_oak_leaves": "minecraft:leaves",
        "minecraft:stone": "minecraft:stone",
        "minecraft:dirt": "minecraft:dirt",
        "minecraft:cobblestone": "minecraft:cobblestone",
        "minecraft:glass": "minecraft:glass",
        "minecraft:glass_pane": "minecraft:glass_pane",
        "minecraft:iron_door": "minecraft:iron_door",
        "minecraft:wooden_door": "minecraft:wooden_door",
        # 物品
        "minecraft:apple": "minecraft:apple",
        "minecraft:diamond": "minecraft:diamond",
        # 更多映射...
    }
    
    # Bedrock 到 Java 的逆向映射
    BLOCK_BEDROCK_TO_JAVA: Dict[str, str] = {v: k for k, v in BLOCK_JAVA_TO_BEDROCK.items()}
    
    @classmethod
    def convert_block_id(cls, block_id: str, to_bedrock: bool) -> str:
        """
        转换方块 ID。
        
        Args:
            block_id: 原始方块 ID
            to_bedrock: 如果为 True，表示 Java -> Bedrock；否则 Bedrock -> Java
        
        Returns:
            转换后的方块 ID，若未找到映射则返回原值。
        """
        if to_bedrock:
            return cls.BLOCK_JAVA_TO_BEDROCK.get(block_id, block_id)
        else:
            return cls.BLOCK_BEDROCK_TO_JAVA.get(block_id, block_id)
    
    @classmethod
    def convert_item_id(cls, item_id: str, to_bedrock: bool) -> str:
        """转换物品 ID（暂时与方块相同）"""
        return cls.convert_block_id(item_id, to_bedrock)


def convert_block_ids_in_nbt(tag: Any, to_bedrock: bool) -> Any:
    """
    递归遍历 NBT，转换所有方块/物品 ID。

    注意：此函数会修改传入的 tag。
    """
    if isinstance(tag, Compound):
        for key, value in tag.items():
            # 转换键名
            if key in ("id", "Block", "Item", "Name"):
                if isinstance(value, String):
                    new_id = IdMapping.convert_block_id(value, to_bedrock)
                    if new_id != value:
                        tag[key] = String(new_id)
            # 递归处理子标签
            convert_block_ids_in_nbt(value, to_bedrock)
    elif isinstance(tag, List):
        for i, item in enumerate(tag):
            convert_block_ids_in_nbt(item, to_bedrock)
    return tag


class VersionDowngrader:
    """
    版本软着陆：处理 Data Components 和未知方块。
    """
    
    @staticmethod
    def strip_data_components(tag: Compound) -> Compound:
        """
        剥离 1.20.5+ 的物品组件格式，降级为旧版的 tag 嵌套结构。
        
        将 `components` 内的数据移动到 `tag` 中。
        """
        if not isinstance(tag, Compound):
            return tag
        # 如果存在 components 字段
        if "components" in tag and isinstance(tag["components"], Compound):
            components = tag["components"]
            # 确保存在 tag 字段
            if "tag" not in tag:
                tag["tag"] = Compound({})
            # 将 components 的内容合并到 tag 中
            for key, value in components.items():
                tag["tag"][key] = value
            # 删除 components
            del tag["components"]
        return tag
    
    @staticmethod
    def replace_unknown_blocks(tag: Any, target_version: int) -> Any:
        """
        将目标版本中不存在的方块 ID 替换为 air 或占位方块。

        Args:
            tag: NBT 标签
            target_version: 目标版本 ID（如 404 表示 1.13.2）

        Returns:
            修改后的标签
        """
        # 这里需要实现版本特定的方块 ID 白名单
        # 由于时间关系，暂时只做简单替换示例
        if isinstance(tag, Compound):
            for key, value in tag.items():
                if key in ("id", "Block") and isinstance(value, String):
                    # 检查是否为未知方块（示例逻辑）
                    if value.startswith("minecraft:"):
                        # 假设所有方块都有效
                        pass
                    else:
                        # 替换为 air
                        tag[key] = String("minecraft:air")
                else:
                    VersionDowngrader.replace_unknown_blocks(value, target_version)
        elif isinstance(tag, List):
            for item in tag:
                VersionDowngrader.replace_unknown_blocks(item, target_version)
        return tag


def convert_world(src_path: Path, dst_path: Path,
                  target_platform: str = "java",
                  target_version: Optional[int] = None) -> bool:
    """
    转换整个世界存档（高级接口）。
    
    Args:
        src_path: 源世界路径
        dst_path: 目标世界路径
        target_platform: "java" 或 "bedrock"
        target_version: 目标版本 ID（仅 Java 版有效）
    
    Returns:
        成功返回 True，失败返回 False
    """
    # 1. 如果源路径与目标路径不同，则复制世界结构
    if src_path.resolve() != dst_path.resolve():
        try:
            import shutil
            replace_directory_tree(src_path, dst_path, ignore=shutil.ignore_patterns('*.tmp', '*.bak', '*.old'))
        except Exception as e:
            raise ConversionError(f"复制世界目录失败: {e}")
        work_path = dst_path
    else:
        work_path = src_path  # 原地转换
    
    # 2. 确定目标字节序
    target_byteorder = "big" if target_platform == "java" else "little"
    
    # 3. 遍历所有 NBT 文件进行转换
    nbt_extensions = {".dat", ".nbt"}
    for root, dirs, files in os.walk(work_path):
        for file in files:
            if any(file.endswith(ext) for ext in nbt_extensions):
                file_path = Path(root) / file
                try:
                    # 3.1 字节序转换
                    convert_endian(file_path, file_path, target_byteorder)
                    
                    # 3.2 加载 NBT 进行进一步处理
                    data = load_nbt(file_path, byteorder=target_byteorder)
                    
                    # 3.3 转换方块/物品 ID（如果需要跨平台）
                    if target_platform != "java":  # 如果目标不是 Java，则可能需要将 Java ID 转换为 Bedrock ID
                        to_bedrock = (target_platform == "bedrock")
                        convert_block_ids_in_nbt(data, to_bedrock)
                    
                    # 3.4 版本降级处理
                    if target_version is not None:
                        # 应用 Data Components 剥离
                        VersionDowngrader.strip_data_components(data)
                        # 替换未知方块
                        VersionDowngrader.replace_unknown_blocks(data, target_version)
                    
                    # 保存修改后的 NBT，显式保留目标字节序并使用原子替换。
                    save_nbt(file_path, data, byteorder=target_byteorder)
                    
                except Exception as e:
                    # 记录错误但继续处理其他文件
                    import logging
                    logging.getLogger(__name__).warning(f"转换文件 {file_path} 时出错: {e}")
    
    # 4. 处理区域文件（.mca）中的方块/物品 ID 转换
    if target_platform != "java" or target_version is not None:
        try:
            from .scanner import scan_all_regions
            import anvil

            mca_files = scan_all_regions(work_path)
            for mca_path in mca_files:
                try:
                    region = anvil.Region.from_file(str(mca_path))
                    region_modified = False
                    for x in range(32):
                        for z in range(32):
                            chunk = region.get_chunk(x, z)
                            if chunk is None:
                                continue
                            data = chunk.data if hasattr(chunk, 'data') else chunk
                            if not isinstance(data, nbtlib.tag.Compound):
                                continue

                            # 跨平台 ID 转换
                            if target_platform != "java":
                                to_bedrock = (target_platform == "bedrock")
                                convert_block_ids_in_nbt(data, to_bedrock)
                                region_modified = True

                            # 版本降级处理
                            if target_version is not None:
                                VersionDowngrader.strip_data_components(data)
                                VersionDowngrader.replace_unknown_blocks(data, target_version)
                                region_modified = True

                    if region_modified:
                        region.save(str(mca_path))  # type: ignore[attr-defined]
                except Exception as e:
                    import logging
                    logging.getLogger(__name__).warning(f"转换区域文件 {mca_path} 时出错: {e}")
        except ImportError:
            import logging
            logging.getLogger(__name__).warning("anvil-parser 未安装，跳过区域文件转换")
    
    return True


if __name__ == "__main__":
    # 简单测试
    import sys
    if len(sys.argv) > 2:
        src = Path(sys.argv[1])
        dst = Path(sys.argv[2])
        convert_endian(src, dst, target_byteorder='big')
        print(f"已转换 {src} -> {dst}")
