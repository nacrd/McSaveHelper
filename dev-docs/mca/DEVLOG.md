## 2026-07-11 (process chunk LRU for LOD upgrades)

### Changes
- Process-level LRU of decoded ChunkBlocks (path+mtime+cx+cz), max 2500
- Progressive 16->32->64->128 reuses already-decoded chunks
- Faster PNG putdata + compress_level=1

### Bench r.0.0.mca (no disk cache)
| tile | cold | after lower LOD |
|------|------|-----------------|
| 16 | ~93ms | ~79ms |
| 32 | ~374ms | ~308ms |
| 64 | ~824ms | ~663ms |
| 128 | ~1476ms | **~389ms** |

Disk cache still ~1ms when hit.

---

## 2026-07-11 (faster topview: subsample + parallel decode)

### Changes
- Overview tiles decode fewer unique chunks (8/16/24/32 edge) then NN-upscale
- Parallel zlib+NBT decode (up to 6 workers)
- Shorter heightmap confirm walk (12 -> 4)

### Bench r.0.0.mca cold no-cache (mean of 3)
| tile | before | after |
|------|--------|-------|
| 16 | ~390ms | **~99ms** (~4x) |
| 32 | ~1510ms | **~354ms** (~4.3x) |
| 64 | ~1568ms | **~871ms** (~1.8x) |
| 128 | ~1.5s | ~1.5s (full 1024 chunks) |
| disk warm | 1ms | 1ms |

---

## 2026-07-11 (Phase 4 write path)

### Added

- core/mca/writer.py: WritableRegion (load/mutate/delete/save atomic)
- delete_chunk_entries for header-only chunk resets
- tests/test_mca_writer.py

### Migrated

- worker / pure_cleaner / converter write-backs
- region_editor reads + delete_chunks
- save_repair detector/chunk_repairer -> NativeRegion

### Validation

- 21 mca unit tests passed
- example_saves r.0.0.mca: open 1024 chunks -> WritableRegion save 1024 + .bak

### Note

Production code has zero anvil imports. Optional anvil only in scripts/bench_mca.py for compare.

---

## 2026-07-11 (fix pan: translate shapes, no rebuild)

Pan with only ~4 cells still lagged because each pan_update rebuilt the whole
canvas (even solid rects) via a heavy path.

Now pan_update only translates existing canvas shapes + hit bounds in place
and calls canvas.update(). Full rebuild + tile work runs on pan_end.

---

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

