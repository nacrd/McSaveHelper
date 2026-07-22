"""纯净扫描模块

移除存档中所有模组相关的方块和实体，让模组存档能够“无损”降级回原版服务端运行。
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional, Tuple

import core.nbt as nbtlib
from .parallel import clamp_workers
from .scanner import scan_all_entity_regions, scan_all_regions
from .types import LogCallback


def is_vanilla_id(identifier: str) -> bool:
    """判断是否为原版ID（以 minecraft: 开头）"""
    return identifier.startswith("minecraft:")


def _process_one_region(
    region_file: Path,
) -> Tuple[str, int, int, int, Optional[str]]:
    """处理单个区域文件（线程池 worker）。

    Returns:
        tuple: ``(文件名, 扫描区块数, 替换方块数, 移除实体数, 错误|None)``。
    """
    try:
        from core.mca import WritableRegion

        region = WritableRegion.open(region_file)
        region_changes = 0
        chunks = 0
        blocks_replaced = 0
        entities_removed = 0
        for _x, _z, data in region.iter_chunks():
            chunks += 1
            block_count, entity_count = _purge_mod_data_in_chunk(data)
            blocks_replaced += block_count
            entities_removed += entity_count
            if block_count > 0 or entity_count > 0:
                region_changes += 1
        if region_changes > 0:
            region.save(region_file, backup=True)
        return (
            region_file.name,
            chunks,
            blocks_replaced,
            entities_removed,
            None,
        )
    except (OSError, ValueError, TypeError, RuntimeError, KeyError) as exc:
        return region_file.name, 0, 0, 0, str(exc)
    except Exception as exc:
        # Worker boundary: keep purging other regions.
        return region_file.name, 0, 0, 0, str(exc)


def purge_mod_blocks_and_entities(
    world_path: Path,
    log: LogCallback,
    max_workers: Optional[int] = None,
) -> bool:
    """从世界存档中移除所有模组相关的方块和实体

    Args:
        world_path: 世界存档路径
        log: 日志回调函数
        max_workers: 可选区域级并发上限；批量世界任务应传 1。
    """
    log("开始纯净扫描：移除模组方块和实体", "PURE")
    region_files = scan_all_regions(world_path) + scan_all_entity_regions(world_path)
    total_regions = len(region_files)
    if total_regions == 0:
        log("未找到任何区域文件，跳过纯净扫描", "INFO")
        return True

    total_chunks = 0
    total_blocks_replaced = 0
    total_entities_removed = 0
    errors = 0

    # region 级并发（各处理独立文件，写回安全）；上限由 core.parallel 统一钳制。
    workers = clamp_workers(max_workers, item_count=total_regions)
    done = 0
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [
            executor.submit(_process_one_region, rf) for rf in region_files
        ]
        for future in as_completed(futures):
            done += 1
            name, chunks, br, er, err = future.result()
            total_chunks += chunks
            total_blocks_replaced += br
            total_entities_removed += er
            if err:
                errors += 1
                log(f"处理区域文件失败 {name}: {err}", "ERROR")
            else:
                log(f"处理区域文件 ({done}/{total_regions}): {name}", "INFO")
                if br > 0 or er > 0:
                    log(f"  修改: 方块 {br}, 实体 {er}", "INFO")

    if errors:
        log(f"纯净扫描未完整完成: {errors} 个区域文件失败", "ERROR")
    else:
        log("纯净扫描完成", "PURE")
    log(f"总计扫描 {total_chunks} 个区块", "INFO")
    log(f"替换了 {total_blocks_replaced} 个模组方块", "INFO")
    log(f"移除了 {total_entities_removed} 个模组实体", "INFO")
    return errors == 0


def _get_chunk_root(data: nbtlib.tag.Compound) -> nbtlib.tag.Compound:
    level = data.get("Level")
    return level if isinstance(level, nbtlib.tag.Compound) else data


def _replace_modded_palette_entries(data: nbtlib.tag.Compound) -> int:
    replaced = 0
    root = _get_chunk_root(data)
    sections = root.get('sections') or root.get('Sections')
    if sections:
        for section in sections:
            block_states = section.get("block_states") or section.get("BlockStates")
            palette = None
            if isinstance(block_states, nbtlib.Compound):
                palette = block_states.get("palette") or block_states.get("Palette")
            palette = palette or section.get('Palette') or section.get('palette')
            if not palette:
                continue
            for block_state in palette:
                block_id = block_state.get('Name')
                if not isinstance(block_id, nbtlib.tag.String):
                    continue
                if not is_vanilla_id(str(block_id)):
                    block_state['Name'] = nbtlib.tag.String('minecraft:air')
                    if 'Properties' in block_state:
                        del block_state['Properties']
                    replaced += 1
    return replaced


def _filter_modded_entities(data: nbtlib.tag.Compound, key: str) -> int:
    entries = data.get(key)
    if not entries:
        return 0
    vanilla_entries = []
    removed = 0
    for entry in entries:
        entry_id = entry.get('id')
        if not isinstance(entry_id, nbtlib.tag.String) or is_vanilla_id(
                str(entry_id)):
            vanilla_entries.append(entry)
        else:
            removed += 1
    if removed:
        data[key] = nbtlib.tag.List(vanilla_entries)
    return removed


def _purge_mod_data_in_chunk(chunk) -> Tuple[int, int]:
    """移除模组方块、实体和方块实体，返回 (替换方块数, 移除实体数)。"""
    data = chunk.data if hasattr(chunk, 'data') else chunk
    if not isinstance(data, nbtlib.tag.Compound):
        return 0, 0

    root = _get_chunk_root(data)
    entities_removed = 0
    for entities_key in ('entities', 'Entities'):
        entities_removed += _filter_modded_entities(root, entities_key)
    for key in ('block_entities', 'BlockEntities', 'TileEntities'):
        entities_removed += _filter_modded_entities(root, key)
    return _replace_modded_palette_entries(data), entities_removed
