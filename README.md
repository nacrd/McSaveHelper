# MCSaveHelper

MCSaveHelper 是一个使用 Python 和 Flet 构建的 Minecraft 世界存档管理工具，面向
Java 版存档的检查、备份、迁移、编辑和分析工作流。

## 主要功能

- 存档浏览器：查看世界信息、玩家状态、物品栏、区域地图、统计信息和 NBT 树。
- 备份与恢复：创建完整恢复点，查看大小与文件数，恢复或删除受管理备份。
- 存档迁移：复制世界、转换 UUID、清理缓存，并在临时世界中完成版本处理后发布。
- 存档修复：只读检测区块、玩家数据和 `level.dat`，可在安全备份后执行修复。
- 地图与搜索：导出世界俯视图，搜索实体、方块和容器内容。
- 存档对比：比较两份世界的基础数据、玩家文件和不同维度的区域文件。
- 管理工具：UUID 映射、服务器属性、主题、语言和运行日志。

## 数据安全

- 备份保存在世界同级的 `.mcsavehelper_backups/<世界名>/` 目录中。
- 备份和恢复拒绝符号链接、目录联接、越界路径和不完整快照。
- 新恢复点包含逐文件 SHA-256 清单；恢复前会校验缺失、篡改和清单外文件。
- 备份中心可以主动验证恢复点，并按“保留最新 N 个”清理旧备份。
- 恢复和迁移发布使用同文件系统目录交换；发布失败会恢复原目录。
- 修复操作的安全备份失败时，后续区块、玩家和 NBT 写入不会启动。
- 单存档迁移在临时目录完成，转换成功并验证 `level.dat` 后才替换最终目标。
- 批量迁移为每个世界独立执行相同事务，支持安全点取消和结构化任务结果。
- 备份、迁移、修复、NBT 提交和区域重置按规范化世界路径互斥写入。

不要在 Minecraft 客户端或服务端仍然打开世界时执行写操作。工具会检测复制期间的
文件变化并拒绝发布，但关闭世界仍是获得一致快照的可靠方式。

## 运行

需要 Python 3.10 或更高版本。

```bash
pip install -r requirements.txt
python main.py
```

## 开发检查

```bash
pytest -q
flake8 app core tests
mypy app core tests
pyright
```

构建单文件或便携版本：

```bash
python -m pip install nuitka ordered-set ziglang zstandard
python build_nuitka.py onefile
python build_nuitka.py portable
```

Nuitka 构建产物分别位于 `dist/MCSaveHelper.exe` 和 `dist/MCSaveHelper/`。

## 项目结构

- `app/ui/`：Flet 页面、组件和交互适配。
- `app/controllers/`：跨页面用例协调。
- `app/services/`：备份、迁移、修复、搜索和分析等业务服务。
- `core/`：NBT、MCA、UUID 和文件格式算法。
- `translations/`：简体中文和英文界面文案。
- `tests/`：服务、核心算法、控制器和组件测试。

## 注意事项

当前迁移流程仅支持 Java 版存档，并保持源存档版本；不支持的 Bedrock 转换和跨版本
降级请求会被明确拒绝。对重要世界执行操作前，仍应先在“备份与恢复”页面创建恢复点。

## 协议

本项目使用 GPL-3.0 协议，详见 [LICENSE](LICENSE)。
