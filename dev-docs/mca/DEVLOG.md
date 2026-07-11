## 2026-07-11 (fix pan lag + flicker)

### Cause
- Pan handlers already on UI thread but redraw went through run_on_ui (async queue) -> lag
- Every pan frame rebuilt many cv.Image(base64) shapes -> flicker and jank

### Fix
- Pan: direct _schedule_interactive_redraw() (~15fps), no run_on_ui
- While camera_busy: draw solid color rects only (no Images/labels/chunk grid)
- On idle: full redraw + progressive tiles
- Zoom anim still uses run_on_ui (timer thread) but no Images mid-anim

---

## 2026-07-11 (fix interaction freeze)

### Cause

Pan/zoom triggered full canvas rebuild + progressive tile upgrades every frame
(60fps anim + 32x32 chunk mesh), starving UI thread (could not move/select/close).

### Fix

- Rebuild cap ~20fps during interaction
- camera_busy: while panning/zooming skip tile fetch, skip chunk mesh
- After idle ~180ms, one rebuild that requests tiles
- Zoom anim ticks 50ms, tile upgrades only on settle
- Cap visible tile requests to 80

---

## 2026-07-11 (progressive LOD 16/32/64/128)

### Behavior

- Visible tiles first request PREVIEW 16px (~0.6s cold)
- Then step up: 16->32->64->128 based on zoom/view level
- Selected region + neighbors prioritized
- Disk cache still used per size; warm hits ~1ms
- base64 canvas cache invalidates on size upgrade

### Zoom mapping

- overview: target 32 (via 16 first)
- region focus (scale>=2.2): target 64
- chunk view (scale>=5.5): target 128

---

## 2026-07-11 (topview cache + LOD)

### Changes

- core/mca/tile_cache.py: disk PNG cache keyed by path+mtime+size+tile+algo
- DEFAULT_TILE_SIZE 128 -> 32 (overview), DETAIL_TILE_SIZE 128 -> 64
- region_map workers max 2-4; default tile size 32
- render_region_topview(use_disk_cache=True)

### example_saves/新的世界 r.-2.0.mca

- cold tile32/64: ~1.56s
- warm disk cache: ~1ms
- second app open for same regions should feel instant for cached tiles

---

## 2026-07-11 (example_saves validation)

World: example_saves/新的世界

### Correctness (r.-2.0.mca, 8.6MB, 1024 chunks)

- surface samples: grass_block / oak_leaves / water look correct
- grid32 top: grass 606, water 184, oak_leaves 143

### Performance

RegionFile open ~80-95ms
64-chunk native read batch ~58ms vs anvil ~113ms (~2x faster)

Topview (lazy sections):
- tile 32/64/128: ~1.6-1.7s per full region (1024 chunks present)
- bottleneck: zlib+nbtlib full chunk parse for nearly every chunk at overview sampling

### Notes

- Lazy section decode improved ~2.3s -> ~1.6s
- Further gains: disk tile cache, progressive low-res first, or lighter NBT subset parser

---

## 2026-07-11 (fix)

### Heightmap Y + performance

User confirmed topview colors and speed OK after:

- 1.18+ heightmap: block_y = value + min_y - 1 (min_y=-64)
- Prefer MOTION_BLOCKING for map coloring
- ChunkBlocks cache (heightmap + section palettes once per chunk)

Commit: 8265164

---

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

