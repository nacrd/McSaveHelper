# MCSaveHelper Qt 迁移计划

本文档描述将界面层从 Flet 迁移到 PySide6 (Qt for Python) 的架构、阶段与约定。
迁移采用**绞杀者模式（strangler）**：新建独立的 Qt 界面树，逐步迁移视图，
迁移期间 Flet 界面保持可用，最终删除 Flet 树。

## 当前进度

- 阶段 0 基础层已完成，`python main.py` 默认启动 Qt 应用。
- 阶段 1 简单视图已完成：`save_repair`、`backup_center`、`compare`、
  `mappings`、`settings`、`server_properties` 已在 Qt 侧边栏开放。
- 阶段 2 已完成 `migrator`，继续复用框架中立的 `MigrationController`；
  `explorer` 已完成 Qt 壳层、“存档信息”、玩家列表/详情编辑（HUD、分段表单、
  容器只读列表、暂存到共享 NBT 区、死亡点传送、摘要导出）、区域活动热力地图
  （维度切换、扫描、搜索、选择、标记增删、区块 NBT 打开、区域删除事务、
  地图 PNG 导出）、世界统计与实体/方块/容器搜索，以及 NBT/JSON 文件树、
  暂存审阅与安全提交；玩家物品格子（主背包/末影箱/装备/潜影盒预览与
  异步贴图）已完成；玩家头像、usercache 导入与在线名称查询已完成。
- 阶段 3 地图已经做好：俯视地图迁移完成（区域热力 + 俯视瓦片）。当前
  Explorer 开放「地图」tab（区域热力：维度切换、扫描、搜索、选择、标记增删、
  区块 NBT、区域删除事务、地图 PNG 导出）；俯视瓦片渲染的核心迁移与配色等
  纯逻辑模块就绪，待作为独立「俯视地图」tab 接入。
- Qt 已是唯一后端；Qt 树和组合根不得导入 `app.ui` 或 `flet`。

## 现状评估

| 层 | 行数 | 是否耦合 Flet | 迁移方式 |
|---|---:|---|---|
| `core/`（MCA/NBT/UUID/格式算法） | ~22700 | 否 | 原样复用 |
| `app/services/` `app/controllers/` `app/presenters/` `app/models/` `app/adapters/` `app/bootstrap/` | ~27100 | 否 | 原样复用 |
| `app/ui/`（视图、组件、壳层、侧边栏、主题） | ~33300 | 是 | 逐个迁移到 `app/qtui/` 后删除 |
| `app/core/`（window/view/dialog/progress/gui_optimizer 管理器） | ~2900 | 是 | 由 `app/qtui/` 对应模块替代 |
| `app/application*.py` 组合根与混合类、`main.py` | ~1100 | 是 | 重写组合根 |

关键事实：**业务层与核心层完全不含 Flet**。`FeatureContext` 风格的端口协议（翻译、
对话框、文件选择、进度、执行运行时、服务注入）已经是框架中立设计，Qt 版本只需
提供同一组端口的新实现。

## 目标架构

```text
main.py -> app/qtui/application.py (Qt 组合根, QMainWindow)
                        |
                        v
app/qtui/ (shell/sidebar/theme/dialogs/progress/view_manager)
        |                 |
        +--> app/qtui/views/* (QWidget 页面)
        +--> app/services, app/controllers, app/presenters, core（复用，不动）
```

- Qt 视图只依赖 `app/qtui/` 与业务层，绝不导入 `app/ui`（Flet 树）或 flet。
- 服务、控制器、presenter、core 的代码**一行不改**。
- 视图持有后台资源时实现幂等 `dispose()`；由 Qt 视图管理器统一释放。
- 后台回调可能晚于页面切换：沿用 generation / 取消标记 / 身份检查丢弃过期结果。

## 后端选择

`main.py` 直接启动 Qt 后端，不再保留旧的后端开关。`--console` 行为不变。

```bash
python main.py          # Qt 后端（默认）
```

## Flet → Qt 映射表

| Flet | Qt (PySide6) |
|---|---|
| `ft.Page` / `ft.app` | `QApplication` / `QMainWindow` |
| `ft.Column` / `ft.Row` | `QVBoxLayout` / `QHBoxLayout` |
| `ft.Container` | `QFrame`（QSS 边框/背景） |
| `ft.Text` | `QLabel` |
| `ft.TextField` | `QLineEdit` / `QPlainTextEdit` |
| `ft.Dropdown` | `QComboBox` |
| `ft.Checkbox` | `QCheckBox` |
| `ft.Button` 系列 | `QPushButton`（objectName 区分 primary/ghost/success/danger） |
| `ft.Icon` / `ft.Icons` | Unicode 字形或 `QStyle` 标准图标 |
| `ft.AlertDialog` / `ft.SnackBar` | `QMessageBox` / 状态栏提示 |
| `ft.ProgressBar` | `QProgressBar`（状态栏） |
| `ft.Stack` + `ft.GestureDetector` | `QGraphicsView` 或自定义 `paintEvent`（地图） |
| `ft.DataTable` | `QTableWidget` / `QTableView` |
| `ft.ListView` | `QScrollArea` + `QVBoxLayout` 或 `QListWidget` |
| `ft.ScrollMode.AUTO` | `QScrollArea`（widgetResizable） |
| `page.run_task` | `execution_runtime` + `run_on_ui` 投递回 UI 线程 |
| `run_on_ui(page, cb)` | `app/qtui/utils.py::run_on_ui(cb, *args)`（QueuedConnection） |
| `page.clipboard.set` | `QApplication.clipboard().setText` |
| `page.show_dialog` | `QMessageBox` / `QDialog` |
| `ft.Border` / `ft.BoxShadow` | QSS（`border: ...; box-shadow` 不支持时用边框色模拟） |
| `ThemeManager` / `THEME` | `app/qtui/theme.py`（同一套色板 + QSS） |

## 阶段划分

1. **阶段 0 —— 基础层（已完成）**
   - `app/qtui/`：theme（QSS）、icons、utils（`run_on_ui`）、view_actions、
     components（buttons/cards/fields/layout）、dialogs、progress、context、
     registry、sidebar、view_manager、shell、application（Qt 组合根）。
   - `main.py --qt` 后端开关；`requirements.txt` 增加 `PySide6`。
   - 首批视图：`server_properties`（表单类，逻辑已与框架解耦）。
   - 测试：`tests/test_qtui_*.py` 覆盖 theme/registry/view_manager/视图逻辑。

2. **阶段 1 —— 简单视图（已完成）**
   `save_repair`、`backup_center`、`compare`、`mappings`、`settings`、
   `server_properties` 全部迁完。每迁完一个即从 Qt 侧边栏开放对应标签。

3. **阶段 2 —— 复杂视图（已完成）**
   `migrator` 已完成（复用 `app/controllers/migration_controller.py`）；
   `explorer` 壳层、存档信息、玩家详情编辑、区域活动热力地图（含标记、
   区块 NBT、区域删除事务、地图导出）、stats_tab、搜索、NBT/JSON 文件树
   与事务提交、玩家物品格子（含装备与潜影盒预览）已完成；
   头像/usercache 已完成。

4. **阶段 3 —— 地图画布（已完成）**
   地图已经做好：区域活动热力地图（现有「地图」tab）与俯视地图均已迁移，
   完整支持 activity/topview/biome/structure 显示模式、世界/区域/区块/区块内
   细节层级、平移/滚轮缩放/双击放大/右键层级回退、标记命中与边缘钳位、
   俯视瓦片渐进渲染与地图 PNG 导出。

5. **阶段 4 —— 收尾（已完成）**
   - Qt 已成为唯一后端，`main.py` 只保留 `--console` 调试参数。
   - 删除 `app/ui/`、Flet 管理器、旧组合根与 `flet`/`flet-desktop` 依赖。
   - 自动语言导入、性能监控、侧边栏模式和日志面板已接入 Qt 生命周期。
   - 更新 Nuitka 构建与文档。

## 移植清单（Flet 树 -> Qt 树）

| Flet 文件 | Qt 文件 |
|---|---|
| `app/ui/theme.py` | `app/qtui/theme.py`（色板复制，QSS 生成） |
| `app/ui/icons.py` | `app/qtui/icons.py`（字形表） |
| `app/ui/utils.py`（run_on_ui/safe_update） | `app/qtui/utils.py` |
| `app/ui/view_actions.py` | `app/qtui/view_actions.py`（handler 无事件参数） |
| `app/ui/components/*` | `app/qtui/components/*` |
| `app/ui/sidebar*.py` | `app/qtui/sidebar.py` |
| `app/ui/application_shell.py` | `app/qtui/shell.py` |
| `app/core/dialog_manager.py` | `app/qtui/dialogs.py` |
| `app/core/progress_manager.py` | `app/qtui/progress.py` |
| `app/core/view_manager.py` | `app/qtui/view_manager.py` |
| `app/core/window_manager.py` | `app/qtui/application.py`（窗口生命周期并入组合根） |
| `app/ui/view_catalog.py`/`feature_registry.py` | `app/qtui/registry.py` |
| `app/ui/feature_context.py` | `app/qtui/context.py` |
| `app/application*.py` | `app/qtui/application.py` |
| `app/ui/views/*` | `app/qtui/views/*` |
| `app/ui/notifications.py`/`feedback.py` | `app/qtui/shell.py`（状态栏/消息框） |

## 线程与生命周期约定

- Qt 控件只能在主线程操作。工作线程完成回调一律经
  `app/qtui/utils.py::run_on_ui` 投递（内部使用带 `QueuedConnection` 的信号）。
- `execution_runtime` 的 `OperationScope.submit` + `add_done_callback` 保持原样
  使用；视图在 `dispose()` 中 `scope.close()` 并递增 generation。
- 对话框与文件选择器若被工作线程调用，先投递回主线程再弹出。
- 关闭窗口时：取消视图任务 -> 关闭 execution_runtime -> 关闭服务
  （`world_indexes.close`、`cache_registry.close`、纹理服务等）。

## 测试策略

- 业务层测试全部保留，零改动。
- 新增 `tests/test_qtui_*.py`：主题 QSS 生成、registry 目录、view manager 生命周期、
  视图纯逻辑（复用 presenters/service 的最小数据）。
- 不构造真实存档、不依赖网络；文件操作使用 `tmp_path`。
- 每个迁移视图至少有一个"纯逻辑"测试（如属性读写、busy 状态、generation 丢弃）。
- 架构门禁：Qt 树不得导入 `app.ui` / `flet`（用测试断言防止回退）。

## 风险与注意

- `server_properties` 等视图硬编码中文字符串，未走翻译键：迁移时保持行为一致，
  翻译键化作为单独清理项，避免扩大本任务范围。
- `settings`（1047 行）与 `explorer`（8000+ 行）是大头，按阶段拆分，
  不在一次改动中同时迁移。
- 地图画布的渲染热路径保持纯函数（`core/mca/`），Qt 只负责最终绘制。
- 复制到 `app/qtui/theme.py` 的色板是过渡期数据源；Flet 树删除时以 Qt 版为唯一权威。
