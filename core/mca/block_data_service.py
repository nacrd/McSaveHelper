from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class BlockStateInfo:
    x: int
    y: int
    z: int
    section_y: int
    local_x: int
    local_y: int
    local_z: int
    palette_index: int
    name: str
    properties: Dict[str, str]


@dataclass
class SetBlockResult:
    success: bool
    old_name: str
    new_name: str
    palette_index: int
    repacked: bool
    message: str


class BlockDataService:
    """方块读写服务。

    性能：对同一 section 的 block_states 缓存 decoded indices，
    set_block_at 批量编辑时避免每次 O(4096) decode/encode。
    section 对象被替换或 repack 时自动失效。
    """

    def __init__(self) -> None:
        # key: id(block_states) → (indices, palette_size, dirty)
        self._indices_cache: Dict[int, Tuple[List[int], int, bool]] = {}

    def clear_cache(self) -> None:
        """清空索引缓存（chunk 替换/重载时调用）。"""
        self._indices_cache.clear()

    def _get_cached_indices(
            self, data: Any, palette_size: int, block_states: Any) -> List[int]:
        """取/建 decoded indices 缓存。"""
        cache_key = id(block_states) if block_states is not None else id(data)
        cached = self._indices_cache.get(cache_key)
        if cached is not None:
            indices, cached_size, _dirty = cached
            if cached_size == palette_size:
                return indices
        if data is None or palette_size <= 1:
            indices = [0] * 4096
        else:
            indices = self._decode_all_indices(data, palette_size)
        self._indices_cache[cache_key] = (indices, palette_size, False)
        return indices

    def _invalidate_cache(self, block_states: Any) -> None:
        if block_states is not None:
            self._indices_cache.pop(id(block_states), None)

    def get_block_at(
            self,
            chunk_data: Any,
            world_x: int,
            world_y: int,
            world_z: int) -> Optional[BlockStateInfo]:
        local_x = world_x & 15
        local_y = world_y & 15
        local_z = world_z & 15
        section_y = world_y // 16
        sections = self._get(chunk_data, "sections")
        if sections is None:
            return None
        section = self._find_section(sections, section_y)
        if section is None:
            return BlockStateInfo(
                world_x,
                world_y,
                world_z,
                section_y,
                local_x,
                local_y,
                local_z,
                0,
                "minecraft:air",
                {})
        block_states = self._get(section, "block_states")
        if block_states is None:
            palette = self._get(
                section,
                "Palette") or self._get(
                section,
                "palette")
            data = self._get(section, "BlockStates")
        else:
            palette = self._get(block_states, "palette")
            data = self._get(block_states, "data")
        if palette is None or len(palette) == 0:
            return None
        palette_index = self._decode_palette_index(
            data, len(palette), local_x, local_y, local_z)
        if palette_index < 0 or palette_index >= len(palette):
            return None
        state = palette[palette_index]
        return BlockStateInfo(
            x=world_x,
            y=world_y,
            z=world_z,
            section_y=section_y,
            local_x=local_x,
            local_y=local_y,
            local_z=local_z,
            palette_index=palette_index,
            name=self._value(self._get(state, "Name", "unknown")),
            properties=self._properties(self._get(state, "Properties")),
        )

    def set_block_at(
        self,
        chunk_data: Any,
        world_x: int,
        world_y: int,
        world_z: int,
        block_name: str,
        properties: Optional[Dict[str, str]] = None,
    ) -> SetBlockResult:
        local_x = world_x & 15
        local_y = world_y & 15
        local_z = world_z & 15
        section_y = world_y // 16
        sections = self._get(chunk_data, "sections")
        if sections is None:
            return SetBlockResult(
                False, "", block_name, -1, False, "区块无 sections 数据")
        section = self._find_section(sections, section_y)
        if section is None:
            return SetBlockResult(
                False, "", block_name, -1, False, f"未找到 section Y={section_y}")
        block_states = self._get(section, "block_states")
        if block_states is None:
            return SetBlockResult(
                False,
                "",
                block_name,
                -1,
                False,
                "section 无 block_states（旧版格式暂不支持写入）",
            )
        palette = self._get(block_states, "palette")
        data = self._get(block_states, "data")
        if palette is None or len(palette) == 0:
            return SetBlockResult(
                False, "", block_name, -1, False, "palette 为空")
        old_palette_size = len(palette)
        old_index = self._decode_palette_index(
            data, old_palette_size, local_x, local_y, local_z)
        if old_index < 0 or old_index >= old_palette_size:
            return SetBlockResult(
                False,
                "",
                block_name,
                -1,
                False,
                f"当前 palette_index={old_index} 越界",
            )
        old_state = palette[old_index]
        old_name = self._value(self._get(old_state, "Name", "unknown"))
        new_palette_index = self._find_or_add_palette_entry(
            palette, block_name, properties or {})
        if new_palette_index == old_index:
            return SetBlockResult(
                True,
                old_name,
                block_name,
                new_palette_index,
                False,
                "目标方块与当前方块相同，无需修改")
        new_palette_size = len(palette)
        old_bits = max(4, (old_palette_size - 1).bit_length()
                       ) if old_palette_size > 1 else 4
        new_bits = max(4, (new_palette_size - 1).bit_length()
                       ) if new_palette_size > 1 else 4
        repacked = new_bits != old_bits
        # 用缓存的 decoded indices，批量编辑同一 section 时避免重复 O(4096) 解码
        all_indices = self._get_cached_indices(data, old_palette_size, block_states)
        target_flat = (local_y * 16 + local_z) * 16 + local_x
        all_indices[target_flat] = new_palette_index
        new_data = self._encode_all_indices(all_indices, new_palette_size)
        self._set_block_states_data(block_states, new_data)
        # 写回后更新缓存（palette_size 可能变化；repack 时 bits 变了但 indices 仍有效）
        self._indices_cache[id(block_states)] = (
            all_indices, new_palette_size, False)
        return SetBlockResult(
            success=True,
            old_name=old_name,
            new_name=block_name,
            palette_index=new_palette_index,
            repacked=repacked,
            message=f"已将 {old_name} 替换为 {block_name}（palette #{new_palette_index}）" + (
                "，数据已重打包" if repacked else ""),
        )

    def _find_or_add_palette_entry(
            self, palette: Any, block_name: str, properties: Dict[str, str]) -> int:
        for i, entry in enumerate(palette):
            name = self._value(self._get(entry, "Name", ""))
            if name != block_name:
                continue
            entry_props = self._properties(self._get(entry, "Properties"))
            if entry_props == properties:
                return i
        new_entry = self._create_palette_entry(block_name, properties)
        if isinstance(palette, list):
            palette.append(new_entry)
        elif hasattr(palette, "append"):
            palette.append(new_entry)
        else:
            try:
                converted = list(palette)
                converted.append(new_entry)
                return len(converted) - 1
            except Exception:
                return -1
        return len(palette) - 1

    def _create_palette_entry(self, block_name: str,
                              properties: Dict[str, str]) -> Any:
        try:
            from nbtlib import Compound, String
            entry = Compound({"Name": String(block_name)})
            if properties:
                props = Compound({k: String(v) for k, v in properties.items()})
                entry["Properties"] = props
            return entry
        except ImportError:
            fallback_entry: Dict[str, Any] = {"Name": block_name}
            if properties:
                fallback_entry["Properties"] = properties
            return fallback_entry

    def _decode_all_indices(self, data: Any, palette_size: int) -> List[int]:
        if data is None or palette_size <= 1:
            return [0] * 4096
        bits = max(4, (palette_size - 1).bit_length())
        values = [int(item) & ((1 << 64) - 1) for item in list(data)]
        values_per_long = max(1, 64 // bits)
        padded_expected = (4096 + values_per_long - 1) // values_per_long
        mask = (1 << bits) - 1
        indices = []
        if len(values) == padded_expected:
            for i in range(4096):
                long_index = i // values_per_long
                bit_offset = (i % values_per_long) * bits
                if long_index < len(values):
                    indices.append((values[long_index] >> bit_offset) & mask)
                else:
                    indices.append(0)
        else:
            for i in range(4096):
                bit_index = i * bits
                long_index = bit_index // 64
                bit_offset = bit_index % 64
                if long_index >= len(values):
                    indices.append(0)
                    continue
                value = values[long_index] >> bit_offset
                end_offset = bit_offset + bits
                if end_offset > 64 and long_index + 1 < len(values):
                    value |= values[long_index + 1] << (64 - bit_offset)
                indices.append(value & mask)
        return indices

    def _encode_all_indices(
            self,
            indices: List[int],
            palette_size: int) -> List[int]:
        bits = (
            max(4, (palette_size - 1).bit_length())
            if palette_size > 1 else 4
        )
        values_per_long = 64 // bits
        num_longs = (4096 + values_per_long - 1) // values_per_long
        longs = [0] * num_longs
        for i, palette_index in enumerate(indices):
            long_index = i // values_per_long
            bit_offset = (i % values_per_long) * bits
            longs[long_index] |= (
                palette_index & ((1 << bits) - 1)
            ) << bit_offset
        for j in range(num_longs):
            if longs[j] >= (1 << 63):
                longs[j] -= (1 << 64)
        return longs

    def _set_block_states_data(
            self,
            block_states: Any,
            longs: List[int]) -> None:
        current_data = self._get(block_states, "data")
        if current_data is not None and self._update_existing_data(
                current_data, longs):
            return
        if self._set_nbtlib_long_array(block_states, longs):
            return
        if self._set_legacy_long_array(block_states, longs):
            return
        self._set_plain_long_array(block_states, longs)

    @staticmethod
    def _update_existing_data(current_data: Any, longs: List[int]) -> bool:
        if not hasattr(current_data, "__len__") or not hasattr(
                current_data, "__setitem__"):
            return False
        try:
            if len(current_data) == len(longs):
                for index, value in enumerate(longs):
                    current_data[index] = value
                return True
            clear = getattr(current_data, "clear", None)
            extend = getattr(current_data, "extend", None)
            if callable(clear) and callable(extend):
                clear()
                extend(longs)
                return True
        except Exception:
            return False
        return False

    @staticmethod
    def _set_nbtlib_long_array(block_states: Any, longs: List[int]) -> bool:
        try:
            from nbtlib.tag import LongArray

            block_states["data"] = LongArray(longs)
            return True
        except Exception:
            return False

    @staticmethod
    def _set_legacy_long_array(block_states: Any, longs: List[int]) -> bool:
        try:
            from nbt.nbt import TAG_Long_Array  # type: ignore[import-untyped]

            block_states["data"] = TAG_Long_Array(longs)
            return True
        except Exception:
            return False

    @staticmethod
    def _set_plain_long_array(block_states: Any, longs: List[int]) -> None:
        try:
            block_states["data"] = longs
        except Exception:
            pass

    def _find_section(self, sections: Any, section_y: int) -> Any:
        for section in sections:
            y_tag = self._get(section, "Y")
            if y_tag is not None and int(self._value(y_tag)) == section_y:
                return section
        return None

    def _decode_palette_index(
            self,
            data: Any,
            palette_size: int,
            local_x: int,
            local_y: int,
            local_z: int) -> int:
        if data is None or palette_size <= 1:
            return 0
        bits = max(4, (palette_size - 1).bit_length())
        index = (local_y * 16 + local_z) * 16 + local_x
        values = [int(item) & ((1 << 64) - 1) for item in list(data)]
        values_per_long = max(1, 64 // bits)
        padded_expected = (4096 + values_per_long - 1) // values_per_long
        mask = (1 << bits) - 1
        if len(values) == padded_expected:
            long_index = index // values_per_long
            bit_offset = (index % values_per_long) * bits
            return (values[long_index] >> bit_offset) & mask
        bit_index = index * bits
        long_index = bit_index // 64
        bit_offset = bit_index % 64
        value = values[long_index] >> bit_offset
        end_offset = bit_offset + bits
        if end_offset > 64 and long_index + 1 < len(values):
            value |= values[long_index + 1] << (64 - bit_offset)
        return value & mask

    def _properties(self, properties: Any) -> Dict[str, str]:
        if properties is None:
            return {}
        result: Dict[str, str] = {}
        for key in self._keys(properties):
            result[str(key)] = self._value(self._get(properties, key))
        return result

    def _get(self, node: Any, key: str, default: Any = None) -> Any:
        if isinstance(node, dict):
            return node.get(key, default)
        if hasattr(node, "keys") and hasattr(node, "__getitem__"):
            try:
                return node[key] if key in node.keys() else default
            except Exception:
                return default
        return default

    def _keys(self, node: Any) -> list:
        if isinstance(node, dict):
            return list(node.keys())
        if hasattr(node, "keys"):
            return list(node.keys())
        return []

    def _value(self, value: Any) -> str:
        return str(getattr(value, "value", value))
