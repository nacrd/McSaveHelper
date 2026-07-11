# Native MCA 子系统开发文档

> 分支：`feat/native-mca`
> 目标：全项目弃用 anvil-parser2，自研只读/可写 MCA 层，并优先打通俯视图性能。

## 文档索引

| 文件 | 内容 |
|------|------|
| [PLAN.md](./PLAN.md) | 总体方案、阶段划分、API、风险 |
| [DEVLOG.md](./DEVLOG.md) | 开发日志（按时间追加） |
| [PHASE0_1_CHECKLIST.md](./PHASE0_1_CHECKLIST.md) | Phase 0/1 任务清单 |
| [PHASE2_CHECKLIST.md](./PHASE2_CHECKLIST.md) | Phase 2 任务清单 |

## 代码位置

```
core/mca/            # 自研 MCA 库
tests/test_mca_*.py  # 单元测试
scripts/bench_mca.py # 性能对照（vs anvil）
tests/fixtures/mca/  # 可选真实 .mca 样本
```

## 快速命令

```bash
pytest tests/test_mca_*.py -v
python scripts/bench_mca.py
python scripts/bench_mca.py --region path/to/r.0.0.mca
```
