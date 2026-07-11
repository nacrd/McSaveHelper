# 自研 MCA 读写与性能优化方案

## 1. 背景

当前热路径（俯视图、扫描、搜索、导出、修复）依赖 `anvil-parser2`。
anvil 的 `get_chunk` / `get_block` 面向完整 Chunk 对象模型，俯视采样却只需要：

1. 定位 chunk
2. 解压 NBT
3. Heightmap 取地表 Y
4. 一次 palette 取块

这导致 topview 单 region 可达秒级，并与扫描抢 CPU。

## 2. 目标

- 仓库内 **零 `import anvil`**
- NBT 统一 **nbtlib**
- topview 现代存档：32px p95 < 200ms / region；64px p95 < 500ms（SSD 基准）
- 写回安全：默认 backup + round-trip 校验

## 3. 非目标（本阶段）

- 不实现完整方块状态机
- 不一次替换所有写路径（写在 Phase 4）
- 不在 Phase 1 支持 LZ4 chunk 压缩

## 4. 包结构

```
core/mca/
  __init__.py       公共导出
  format.py         常量
  errors.py         异常
  chunk_codec.py    zlib/gzip
  region_file.py    Region 只读
  versions.py       DataVersion 分支
  heightmaps.py     Phase 2
  block_palette.py  Phase 2
  surface.py        Phase 2 俯视采样
  writer.py         Phase 4 写回
```

## 5. 阶段

| Phase | 内容 | 完成标准 |
|-------|------|----------|
| **0** | 文档、基准脚本、fixture 约定 | 文档 + bench 可运行 |
| **1** | Region 只读 + chunk NBT | 单测绿；可读真实 mca |
| **2** | Heightmap + block_id + topview 换引擎 | 基准达标；topview 无 anvil |
| **3** | 只读替换 search/export/stats/loader | 无读路径 anvil |
| **4** | 写回 editor/repair/cleaner | round-trip + backup |
| **5** | 移除 anvil 依赖 | requirements 清理 + CI grep |

## 6. Phase 1 API

```python
from core.mca import RegionFile, ChunkMissing

with RegionFile.open("r.0.0.mca") as rf:
    assert rf.has_chunk(0, 0)
    nbt = rf.read_chunk(0, 0)          # nbtlib compound
    for cx, cz in rf.iter_present_chunks():
        ...
```

## 7. 性能策略（摘要）

1. Heightmap 地表（最大杠杆）
2. tile LOD 32 默认 / 可视区请求
3. section 索引缓存 + 字符串 block id
4. 有界 worker + tile ready 合并刷新
5. 可选磁盘 tile 缓存 `(path,mtime,tile,algo_ver)`

## 8. 风险

| 风险 | 缓解 |
|------|------|
| 写坏档 | Phase 4 默认 backup；feature flag |
| 版本漏支持 | UnsupportedVersion 日志；占位色 |
| 性能不达 | 基准门槛不达标不切 export |

## 9. 参考

- Minecraft Wiki: Region file format / Chunk format
- 本地 anvil：`.venv/Lib/site-packages/anvil/region.py`（仅对照）
- 项目 nbt 栈：`nbtlib` + `core/nbt_utils.py`
