# Phase 2 检查清单

## Heightmap + block 取样

- [x] compact heightmap unpack (9-bit, non-spanning)
- [x] surface_y_from_heightmap
- [x] block_id_at (1.16+ block_states + single-palette)
- [x] section scan fallback
- [x] unit tests

## Topview 切换

- [x] surface.py sampling API
- [x] topview_renderer uses core.mca
- [x] no runtime import anvil
- [ ] real-world visual check
- [ ] perf notes for tile_size 32/64/128

## Done when

```
pytest tests/test_mca_*.py -v
# explorer map topview tiles load progressively
```
