# MCA 自研开发日志

格式：`## YYYY-MM-DD` 条目，最新在上。

---

## 2026-07-11 (Phase 2)

### 完成

- core/mca/nbt_access.py: nbtlib tree helpers
- core/mca/heightmaps.py: 9-bit heightmap unpack + surface_y_from_heightmap
- core/mca/block_palette.py: block_id_at / surface_block_id / section scan fallback
- core/mca/surface.py: sample_region_surface_ids/colors
- topview_renderer.py switched to core.mca (no runtime import anvil)

### 测试

```
pytest tests/test_mca_*.py -v
# 14 passed
```

### 行为说明

1. Surface prefers WORLD_SURFACE / MOTION_BLOCKING heightmap
2. If heightmap missing or air, walk down up to 8 blocks / section scan
3. PNG optimize=False for faster progressive tiles
4. search/export/stats/repair still use anvil (Phase 3/4)

### 下一步

- [ ] Real world bench + topview timings
- [ ] anvil vs native block id comparison tests
- [ ] Phase 3: replace read-only call sites

---

## 2026-07-11 (Phase 0/1)

### 分支

- 从 feat/map-display 拉出 feat/native-mca
- 保留既有 topview 调度修复

### Phase 0/1

- dev-docs/mca 方案与清单
- core.mca RegionFile 只读 + 合成单测
- scripts/bench_mca.py

### 决策

1. Phase 1 整文件读入内存
2. NBT 只走 nbtlib
3. topview 在 Phase 2 切换（已完成）

