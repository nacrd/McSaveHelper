"""纯净扫描模块

移除存档中所有模组相关的方块和实体，让模组存档能够“无损”降级回原版服务端运行。
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional, Tuple

import nbtlib
import anvil

from .scanner import scan_all_regions
from .types import LogCallback


def is_vanilla_id(identifier: str) -> bool:
    """判断是否为原版ID（以 minecraft: 开头）"""
    return identifier.startswith("minecraft:")


def _process_one_region(
    region_file: Path,
) -> Tuple[str, int, int, int, Optional[str]]:
    """处理单个区域文件（线程池 worker）。

    Returns:
        (文件名, 扫描区块数, 替换方块数, 移除实体数, 错误信息|None)
    """
    try:
        region = anvil.Region.from_file(str(region_file))
        region_changes = 0
        chunks = 0
        blocks_replaced = 0
        entities_removed = 0
        for x in range(32):
            for z in range(32):
                chunk = region.get_chunk(x, z)
                if chunk is None:
                    continue
                chunks += 1
                br, er = _purge_mod_data_in_chunk(chunk)
                blocks_replaced += br
                entities_removed += er
                if br > 0 or er > 0:
                    region_changes += 1
        if region_changes > 0:
            region.save(str(region_file))  # type: ignore[attr-defined]
        return region_file.name, chunks, blocks_replaced, entities_removed, None
    except Exception as e:
        return region_file.name, 0, 0, 0, str(e)


def purge_mod_blocks_and_entities(world_path: Path, log: LogCallback) -> None:
    """从世界存档中移除所有模组相关的方块和实体

    Args:
        world_path: 世界存档路径
        log: 日志回调函数
    """
    log("开始纯净扫描：移除模组方块和实体", "PURE")
    region_files = scan_all_regions(world_path)
    total_regions = len(region_files)
    if total_regions == 0:
        log("未找到任何区域文件，跳过纯净扫描", "INFO")
        return

    total_chunks = 0
    total_blocks_replaced = 0
    total_entities_removed = 0

    # region 级并发（各处理独立文件，写回安全）
    # 参照 core/worker.py process_regions_parallel 的 ThreadPoolExecutor 模式
    workers = min(8, total_regions)
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
                log(f"处理区域文件失败 {name}: {err}", "ERROR")
            else:
                log(f"处理区域文件 ({done}/{total_regions}): {name}", "INFO")
                if br > 0 or er > 0:
                    log(f"  修改: 方块 {br}, 实体 {er}", "INFO")

    log("纯净扫描完成", "PURE")
    log(f"总计扫描 {total_chunks} 个区块", "INFO")
    log(f"替换了 {total_blocks_replaced} 个模组方块", "INFO")
    log(f"移除了 {total_entities_removed} 个模组实体", "INFO")


def _purge_mod_data_in_chunk(chunk) -> Tuple[int, int]:
    """单次遍历移除模组方块、实体和方块实体，返回 (替换方块数, 移除实体数)"""
    data = chunk.data if hasattr(chunk, 'data') else chunk
    if not isinstance(data, nbtlib.tag.Compound):
        return 0, 0

    blocks_replaced = 0
    entities_removed = 0

    # 1. 处理方块 palette
    sections = data.get('sections')
    if sections:
        for section in sections:
            palette = section.get('palette')
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
                    blocks_replaced += 1

    # 2. 处理实体
    entities_key = 'Entities' if 'Entities' in data else 'entities'
    entities = data.get(entities_key)
    if entities:
        vanilla_entities = []
        for entity in entities:
            entity_id = entity.get('id')
            if not isinstance(entity_id, nbtlib.tag.String):
                vanilla_entities.append(entity)
                continue
            if is_vanilla_id(str(entity_id)):
                vanilla_entities.append(entity)
            else:
                entities_removed += 1
        if entities_removed > 0:
            data[entities_key] = nbtlib.tag.List(vanilla_entities)

    # 3. 处理方块实体
    for key in ('block_entities', 'BlockEntities', 'TileEntities'):
        block_entities = data.get(key)
        if not block_entities:
            continue
        key_removed = 0
        vanilla_block_entities = []
        for block_entity in block_entities:
            block_entity_id = block_entity.get('id')
            if not isinstance(block_entity_id, nbtlib.tag.String):
                vanilla_block_entities.append(block_entity)
                continue
            if is_vanilla_id(str(block_entity_id)):
                vanilla_block_entities.append(block_entity)
            else:
                key_removed += 1
        if key_removed > 0:
            data[key] = nbtlib.tag.List(vanilla_block_entities)
            entities_removed += key_removed

    return blocks_replaced, entities_removed
