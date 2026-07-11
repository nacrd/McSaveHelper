# Phase 0 / 1 检查清单

## Phase 0 — 脚手架与文档

- [x] 分支 `feat/native-mca`
- [x] `dev-docs/mca/PLAN.md`
- [x] `dev-docs/mca/DEVLOG.md`
- [x] `dev-docs/mca/README.md`
- [x] `scripts/bench_mca.py`
- [x] gitignore 允许跟踪 `dev-docs/mca/**`
- [ ] 在真实大存档上跑一遍 bench 并粘贴结果到 DEVLOG

## Phase 1 — 只读 Region + Chunk NBT

- [x] `RegionFile.open` / `from_bytes`
- [x] `chunk_location` / `has_chunk` / `iter_present_chunks`
- [x] `read_chunk_raw` / `read_chunk` (nbtlib)
- [x] 合成 region 单元测试
- [x] 错误类型：ChunkMissing / CorruptChunk / UnsupportedCompression
- [ ] 可选：从用户存档拷贝 1 个小 mca 到 `tests/fixtures/mca/`（若 < 1MB）
- [ ] 可选冒烟：生产路径暂不切换 anvil

## 完成定义（Phase 1）

```text
pytest tests/test_mca_region_file.py -v   # 全绿
python scripts/bench_mca.py               # 合成数据无异常
```

生产代码在 Phase 1 **允许仍使用 anvil**；切换从 Phase 2 topview 开始。
