# MCA 自研开发日志

格式：`## YYYY-MM-DD` 条目，最新在上。

---

## 2026-07-11

### 分支

- 从 `feat/map-display` 拉出 **`feat/native-mca`**
- 保留既有 topview 调度修复（有界队列、UI 线程 rebuild、HangDetector 良性等待）

### Phase 0 完成

- 建立 `dev-docs/mca/` 方案与清单文档
- `.gitignore` 调整：忽略 `dev-docs/*`，但 **跟踪** `dev-docs/mca/**`
- 增加 `scripts/bench_mca.py`（合成 region + 可选真实路径；可对照 anvil）

### Phase 1 起步（只读 Region）

落地代码：

| 模块 | 作用 |
|------|------|
| `core/mca/format.py` | sector/header/compression 常量 |
| `core/mca/errors.py` | McaError / ChunkMissing / CorruptChunk … |
| `core/mca/chunk_codec.py` | zlib/gzip 解压（及压缩 helper） |
| `core/mca/region_file.py` | `RegionFile.open` / `read_chunk` / `iter_present_chunks` |
| `core/mca/versions.py` | DataVersion 常量与 section 范围 |
| `heightmaps.py` / `block_palette.py` | Phase 2 占位 stub |

测试：

- `tests/test_mca_region_file.py`：用 zlib+nbtlib **合成最小 region**，验证 location、缺 chunk、read_chunk 字段

### 决策记录

1. Phase 1 **整文件读入内存**（实现简单）；大文件 mmap 留到有基准数据再做。
2. NBT 只走 **nbtlib**，不引入 anvil 自带的 `nbt` 包。
3. topview **暂不切换**；等 Phase 2 heightmap 完成再改 `topview_renderer.py`。
4. 合成 fixture 内嵌测试，避免仓库提交巨大 `.mca`。

### 下一步（Phase 1 收尾 → Phase 2）

- [ ] 用真实存档跑 `scripts/bench_mca.py --region ...` 记录基线
- [ ] 实现 `heightmaps.surface_y_from_heightmap`
- [ ] 实现 `block_palette.block_id_at`
- [ ] `surface.py` + 切换 `topview_renderer`
- [ ] anvil 对照测试：随机列 block id 一致

### 已知限制

- 不支持 compression=4 (LZ4)
- 不支持写回
- heightmap / block 取样仍为 stub
