# AGENTS.md

本文件适用于仓库根目录及其全部子目录，用于指导 Codex 在 MCSaveHelper 中进行开发。
仓库当前代码、测试和配置是事实来源；本文档描述边界和工作方式，不替代阅读相关实现。

## 开始工作前

- 先运行 `git status --short`。工作区可能包含用户尚未提交的修改，必须保留并在其基础上工作。
- 先阅读目标模块、相邻实现和对应测试，再决定改动位置。不要按文件名猜测架构。
- 新增和本次修改到的代码必须遵循本文“代码标准”；硬规则必须满足，评审阈值用于发现需要
  拆分或说明的复杂代码。
- 只修改任务需要的文件；不要顺手格式化、重命名或重构无关代码。
- 除非用户明确要求，不要暂存、提交、推送、创建分支或修改发布状态。
- 不提交 `build/`、`dist/`、日志、缓存、崩溃报告或真实 Minecraft 存档。

## 项目概览

MCSaveHelper 是使用 Python 和 Flet 构建的 Minecraft Java 版存档管理工具，提供存档浏览、
备份恢复、迁移、修复、NBT 编辑、MCA 地图、搜索、对比和 UUID 处理能力。

依赖方向必须保持单向：

```text
main.py / app/application.py        组合根与应用协调
              |
              v
app/ui/ -> app/controllers/ -> app/services/ -> core/
   |                                  |
   +------------> app/adapters/ <-----+
```

- `app/ui/`：Flet 控件、视图、壳层和 UI 适配。
- `app/controllers/`：跨视图用例和状态协调；不得导入 `app.ui`。
- `app/services/`：业务流程、I/O 编排、回调和应用端口；避免依赖 Flet。
- `core/`：Minecraft 格式算法、NBT/MCA、UUID、日志和通用底层能力；不得依赖 `app`。
- `app/adapters/`：文件选择器等外部/平台适配器。
- `tests/`：与上述边界对应的 pytest 测试。

## 常用命令

安装并运行：

```bash
python -m pip install -r requirements.txt
python main.py
```

测试：

```bash
pytest -q
pytest -q tests/test_uuid_utils.py
pytest -q tests/test_uuid_utils.py::test_name
```

完整质量门禁：

```bash
flake8 app core tests build_nuitka.py main.py
mypy app core tests build_nuitka.py main.py
pyright
python -m compileall -q app core tests build_nuitka.py main.py
git diff --check
```

优先运行与改动直接相关的测试；共享服务、持久化、MCA/NBT 或跨模块契约发生变化时，交付前再
运行完整测试和全部质量门禁。不要用窄测试结果证明宽范围改动正确。

## 组合根与生命周期

- `app/application.py` 是应用组合根和协调器，不在其他模块复制全局应用状态。
- 应用级服务在 `app/bootstrap/services.py` 的 `AppServices`、`ServiceFactories` 和
  `create_app_services()` 中显式装配。
- 新应用级服务必须通过构造参数注入；不要新增模块级业务单例或隐藏缓存实例。
- 仅以下进程级基础设施可以有共享生命周期：主题代理/管理器、日志、翻译、性能追踪、MCA
  表面/瓦片缓存，以及可替换的快捷键、性能监控和反馈默认实例。
- 轻量操作服务应由应用持有或按需创建，并提供明确的 `dispose()`/`close()`（如果持有线程、
  计时器、文件、缓存回调或订阅）。

## 页面与 UI 集成

添加或调整顶层页面时同步检查以下位置：

1. `app/ui/application_shell.py::build_tab_definitions()`：侧边栏 id、翻译键和图标。
2. `app/ui/view_catalog.py::create_default_view_catalog()`：惰性视图工厂注册。
3. 页面类的 `get_top_actions()`：通过 `app/ui/view_actions.py::ViewAction` 暴露顶部命令。
4. 页面需要当前存档时实现 `on_save_selected(path: str)`。
5. 页面持有后台资源时实现幂等 `dispose()`，由 `ViewManager` 统一释放。

不要重新引入旧的 `Application._tab_defs`、`_create_view()` 或 `_get_top_actions()` 注册方式。
大型 Flet 控件树应提取到相邻的 `*_chrome.py` 或 builder 模块，并返回有类型的控件 bundle；
纯格式化、选择和报告逻辑应留在 UI 之外。

### Flet 0.85+ 约束

- 直接使用原生 API：`ft.Alignment`、`ft.BoxFit`、`ft.Border.all`、
  `ft.Container(expand=True)`；不要在 `main.py` 添加全局 monkey patch。
- Dropdown 变化绑定 `on_select`；对话框和 snack bar 使用 `page.show_dialog()`。
- `page.run_task()` 只接收 async callable。后台线程触发同步 UI 回调时使用
  `app.ui.utils.run_on_ui()`。
- 剪贴板调用通过 async callable 执行 `page.clipboard.set()`。
- 后台回调可能晚于页面/存档切换；使用 generation、取消标记或身份检查丢弃过期结果。
- UI 不得在工作线程直接更新，服务和 core 不得持有 Flet 控件。

## 当前存档上下文

- 当前存档由 `CurrentSaveStore` 和 `SaveContextManager` 管理，不在页面创建第二份全局状态。
- `app/models/save_context.py::CurrentSaveContext.from_path()` 以 `level.dat` 判断有效世界。
- 页面通过 `on_save_selected()` 接收上下文；服务方法仍应自行验证路径和必要文件，不能只信 UI。

## 存档写入与事务安全

任何会写入、替换或删除世界内容的功能都必须满足：

- 对规范化世界路径获取应用共享的写入租约。优先复用
  `BackupService.exclusive_operation()` 或 `app.services.world_writes.reserve()`。
- 同一世界的写操作互斥；不同世界可以并发。不要在业务模块创建独立 coordinator 绕过共享锁。
- 先在暂存目录完成全部修改和验证，再原子发布；失败或取消时保持原世界可用并清理暂存内容。
- 覆盖已有目标前创建可验证备份；备份失败必须阻止后续写入。
- 解析并约束所有外部路径，拒绝越界、符号链接、junction 和跨世界 region 路径。
- 取消仅发生在安全检查点，并返回结构化的取消/部分结果；不要把取消伪装成成功。
- 不允许在 Minecraft 客户端或服务端仍打开世界时执行写入。

参考实现：

- `app/services/backup_service.py`
- `app/services/migration_service.py`
- `app/services/save_repair_service.py`
- `core/omni/action_executor.py`
- `app/services/world_write_coordinator.py`

## MCA、MCC 与地图边界

- 区域读取由项目自有 `core/mca/` 实现。禁止添加、恢复或导入 `anvil-parser`、
  `anvil-parser2` 或 `anvil`。
- `RegionFile.open()` 使用只读 memory map，并支持外置超大区块流 `c.<x>.<z>.mcc`。
- 解压和大小上限必须作用在单个区块压缩流边界，不能以整个 MCA 文件大小代替。
- Minecraft 格式、坐标、视口、瓦片和渲染算法放在 `core/mca/`；地图会话协调放在
  `app/controllers/`；标记持久化和导出编排放在 `app/services/`；Flet 交互留在视图。
- MCA writer 修改后至少运行 region、codec、writer 和相关地图/修复测试，避免只验证读取路径。

## NBT 规则

- 使用项目自有 `core/nbt`（以及 `core/nbt_utils.py`/`core/omni/`），不要用 JSON 值替换 NBT tag 类型。
- 禁止添加、恢复或导入 `nbtlib` 作为运行时依赖；序列化/标签树以 `core.nbt` 为准。
- 修改前识别 Java 版本差异、根节点形状和大小写兼容字段；未知结构应保守跳过并记录。
- 所有文件句柄、memory map 和临时文件必须在异常路径释放。
- 多文件 NBT 操作沿用暂存世界事务，不允许一半文件已提交、一半失败。

## 国际化、日志与错误

- 用户可见文本必须在 `translations/zh_CN.json` 和 `translations/en_US.json` 同时添加键；
  两种语言的格式化占位符必须一致。它们是当前权威 UI 词典。
- 不要向旧的 `translations/Language.ZH_CN.json` 增加新 UI 键。
- 使用 `core/logger.py` 的统一 logger，并提供有意义的 `module`：

```python
from core.logger import logger

logger.info("操作成功", module="Migration")
logger.error("操作失败", module="Migration")
```

- 不要静默吞掉业务异常。只有清理、日志、UI 刷新等 best-effort 边界可以捕获宽泛异常，且不能
  改变主要操作的成功/失败语义。
- 服务优先返回有类型的 dataclass 结果或抛出领域异常；UI 负责把结果翻译成提示。

## 实现与测试约定

- 遵循相邻模块现有结构，不强制每个改动机械创建 view/service/controller 三件套。
- 新业务功能通常需要 service + UI/controller（如适用）+ pytest；Minecraft 格式算法应先在
  core 中实现并用纯测试覆盖。
- 使用 `tmp_path`、构造的最小 NBT/MCA 数据和 fixtures；测试不得修改真实存档、用户配置或
  仓库内示例世界。
- 涉及线程时测试取消、过期回调、同世界冲突和不同世界并发；不得依赖固定长时间 sleep。
- 涉及持久化时测试损坏文件、路径逃逸、原子替换失败和重启后读取。
- 涉及 UI 时优先测试纯 builder、controller、presenter 和服务契约；仅在行为必须时构造 Flet
  控件。
- 架构或生命周期变化时运行 `tests/test_architecture.py`、`tests/test_service_lifetimes.py` 和
  `tests/test_infra_instances.py`。
- Nuitka 配置变化时运行 `tests/test_build_nuitka.py`，并在条件允许时实际构建和启动产物。

## Nuitka 构建

Windows 发布构建使用 Nuitka + Zig：

```bash
python -m pip install nuitka ordered-set ziglang zstandard
python build_nuitka.py onefile
python build_nuitka.py portable
```

产物：

- `dist/MCSaveHelper.exe`
- `dist/MCSaveHelper/MCSaveHelper.exe`

构建耗时较长，只在打包逻辑、资源收集、入口兼容或用户明确要求时执行。CI 构建 Python 版本以
`.github/workflows/build.yml` 为准。打包态错误日志应写到可执行文件同目录的
`startup_error.log`；调试可执行文件使用 `--console`。

## 代码标准

本节适用于所有新增代码和本次任务实际修改到的代码。目标是让代码容易理解、验证、修改和删除，
而不是单纯满足格式工具。下列条款是项目内统一基线，与 PEP 8、类型检查和质量门禁一致；与
仓库已有约定冲突时，以相邻模块的既有风格和本文硬规则为准。

### 硬规则

- 遵循 PEP 8：4 空格缩进、合理空行、`snake_case` / `PascalCase` / `UPPER_SNAKE_CASE`、
  导入顺序为标准库 → 第三方 → 本项目（组内字母序，组间空一行）。
- Flake8、Mypy、Pyright 和相关测试必须通过。
- 单行不超过 100 字符，圈复杂度不得超过 Flake8 配置的 15。
- 不得破坏 `UI -> controllers -> services -> core` 的依赖方向；核心逻辑与界面分离。
- 不得用无理由的 `Any`、`# type: ignore`、`# noqa` 或宽泛异常捕获掩盖问题。
- 禁止裸 `except:`；捕获具体异常，错误信息写清操作、目标与原因。
- 禁止可变默认参数（如 `def f(items=[])`）；使用 `None` 并在函数内创建新容器。
- 判断「未提供」用 `is None` / `is not None`；判断「空容器」用真值或 `len`，二者语义不同，
  不得混用。
- 文件、memory map、线程、计时器、订阅和临时目录在成功、失败与取消路径都必须释放。
- 不得通过提高全局阈值、关闭检查或添加笼统豁免解决局部质量问题。

### 复杂度与长度阈值

以下是新代码的设计目标和重构触发点，不是机械切割代码的理由：

| 项目 | 目标 | 触发评审或拆分 |
|---|---:|---:|
| 函数可执行逻辑 | 不超过 30 行 | 超过 50 行 |
| 圈复杂度 | 不超过 10 | 超过 12；硬上限 15 |
| 控制流嵌套 | 不超过 3 层 | 超过 4 层 |
| 普通函数参数 | 不超过 5 个 | 超过 7 个 |
| 类的实现规模 | 不超过 250 行 | 超过 350 行 |
| 模块规模 | 不超过 500 行 | 超过 700 行 |

行数不包含空行、纯注释和只含声明的数据表。Flet 声明树、格式表、协议适配器等确实需要保持
局部完整性的代码可以超过阈值，但必须职责单一、分段清晰且有针对性测试。

历史代码超限不代表每次任务都要顺带重构。仅当本次改动继续扩大超限职责、需要反复理解同一
复杂分支或无法可靠测试时，才在任务范围内拆分。不要为了凑行数制造一次性函数、无意义抽象
或过多跨文件跳转。

### 函数与控制流

- 一个函数完成一个可命名的动作；名称和返回值应概括其完整效果（单一职责）。
- 优先用 guard clause 和早返回处理错误、空值和不支持状态，减少主路径缩进与深层嵌套。
- 复杂条件提取为有意义的布尔变量或纯判断函数；禁止嵌套三元表达式。
- 同一函数不要同时承担解析、业务决策、磁盘写入和 UI 更新。
- 避免用布尔参数切换完全不同的流程；使用枚举、配置 dataclass 或明确的独立方法。
- 循环体超过约 20 行、含多层分支或多种副作用时，提取为可独立测试的操作。
- 多个回滚步骤或资源清理形成协议时，使用 context manager、`ExitStack` 或专用事务对象。
- 不要为了消除少量重复而牺牲局部可读性；抽象必须统一真实不变量或变化原因。

### 模块与类

- 模块围绕一个领域概念或适配边界组织，禁止 `utils2.py`、`helpers_new.py` 等模糊命名。
- 类只拥有一种变化原因；UI 控件树、业务状态、I/O 和线程生命周期不要塞进同一个类。
- 构造函数只建立有效对象，不执行长耗时扫描、网络请求或不可逆写入。
- 依赖通过构造函数显式注入。依赖过多时先拆职责，再考虑 frozen dependency dataclass。
- 持有后台资源或订阅的类必须提供幂等 `dispose()`/`close()` 并明确所有权。
- 只有在消除真实重复、统一重要不变量或形成可替换端口时才新增基类、协议或公共 helper。
- 修改超大模块时，新增职责优先提取；不要继续扩大已有“上帝类”。
- 可独立运行的脚本/入口模块提供 `main()`，并用 `if __name__ == "__main__":` 调用；
  应用本体入口保持 `main.py` / `app/application.py` 组合根，不在业务模块复制第二套启动流程。

### 命名与局部可读性

- 模块、函数和变量用 `snake_case`，类用 `PascalCase`，常量用 `UPPER_SNAKE_CASE`。
- 名称表达领域含义，避免无法限定职责的 `data`、`info`、`item`、`temp`、`manager`。
- 布尔值优先用 `is_`、`has_`、`can_`、`should_`；集合使用复数名。
- `on_*` 表示事件入口，`handle_*` 表示处理动作，`build_*` 表示纯构建，`create_*` 表示
  创建有身份或生命周期的对象。
- 单字母变量只用于非常局部且含义明显的坐标、索引或数学表达式。
- 先搜索仓库术语，不为同一概念引入第二套名称。
- 优先有意义的中间变量，避免重复属性链、魔法索引和密集的一行表达式。
- 主流程应能一次阅读理解；简单决定不应迫使读者在多个文件间反复跳转。
- 排序、扫描和输出顺序应确定，避免 UI 和测试因字典或线程完成顺序抖动。

### 类型、文档与数据模型

- 所有公共函数、方法、回调和 dataclass 字段必须有类型注解（参数与返回值）。
- 公共接口 docstring 使用简洁 Google 风格，至少说明用途，并在有参数/返回/异常时包含
  `Args` / `Returns` / `Raises`；私有辅助函数可写一行摘要，复杂协议仍应写清不变量。
- 已知结构不长期使用 `dict[str, Any]`；使用 dataclass、TypedDict、Enum 或领域值对象。
- 返回值只表达一种语义；不要让 `None` 同时表示未找到、取消、失败和尚未加载。
- 文件系统 API 使用 `pathlib.Path`，只在 UI 和序列化边界转换为字符串。
- 不可变依赖和结果优先使用 `@dataclass(frozen=True)`；可变状态必须有明确所有者。
- 多项结果使用有名称的 dataclass，不返回难以辨认的长 tuple。
- `cast()` 仅用于已验证但类型系统无法推断的边界；`Any` 仅限无类型第三方边界并尽快转换。

### 错误、日志与资源

- 在最接近原因的层抛出领域异常，在 controller/UI 边界转为用户提示。
- 捕获具体异常类型（如 `OSError`、`ValueError`、领域错误）；`except Exception` 仅用于
  进程/线程入口、事务回滚和 best-effort 清理，并必须保持失败语义。
- 禁止空 `except` 与裸 `except:`。允许忽略的清理错误需说明原因，且不得覆盖主异常。
- 错误消息包含操作、目标和原因，但不得记录密钥、隐私数据或超大 NBT 内容。
- 使用 `with`、`try/finally` 或 `ExitStack` 管理资源；回滚失败时保留原始和回滚异常。
- 服务优先返回有类型的 dataclass 结果或抛出领域异常，UI 负责提示和翻译。

### 性能

- 循环内不重复计算不变式：把常量查找、路径规范化、正则编译、配置读取提到循环外。
- 简单映射/过滤优先推导式；大数据集、可提前终止或只需遍历一次时优先生成器。
- 热路径避免无意义的中间 list/dict 拷贝；需要多次遍历时再物化。
- 不以微优化牺牲可读性；先保证正确与可测，再针对已证明的瓶颈优化。
- I/O 与解析结果在合理范围内缓存，但缓存必须有明确失效条件与所有权。

### 注释与文档

- 注释解释“为什么”和格式、线程、安全约束，不复述代码表面行为。
- 公共 API、复杂事务、格式算法和不直观的回调协议使用简洁 docstring（见上文
  Args/Returns/Raises 要求）。
- TODO 必须写明具体事项和触发条件；禁止 `TODO: fix later`。
- 修改行为时同步更新相关 docstring、README、翻译和构建说明。
- 删除失效注释和被注释掉的代码，历史由 Git 保存。

### 并发与 I/O

- 后台任务必须定义所有者、取消方式、完成通知和关闭行为。
- 不用固定 `sleep` 协调线程；使用 Event、Lock、Queue、Future 或明确的 join。
- 持锁范围只覆盖共享状态不变量，不在锁内执行 UI 回调、网络或长耗时磁盘操作。
- 回调默认可能重入、延迟或发生在释放后；调用前检查 generation、取消状态或身份。
- 进度值应单调且范围明确，高频循环需要节流。
- 单文件写入使用临时文件和原子替换；多文件世界修改使用事务暂存目录。

### 测试友好与测试代码质量

- 核心逻辑尽量纯函数或无隐藏副作用：输入经参数传入，输出经返回值给出；I/O、时间、随机
  和全局状态通过注入或显式端口隔离，便于单测。
- 避免把路径、版本号、超时、限额等写死在业务分支中；提取为常量、配置或参数。
- 测试名称描述条件和可观察结果，遵循 Arrange / Act / Assert。
- 单个测试只证明一个主要行为，优先验证公开行为和不变量，不绑定私有实现细节。
- 缺陷修复必须增加能在修复前失败的回归测试。
- 同一规则的输入矩阵用参数化，避免复制大段测试代码。
- 并发测试使用同步原语并检查线程异常；文件测试使用 `tmp_path`。
- Mock 只用于外部边界；核心格式、事务和路径安全使用真实的最小数据结构。
- 测试必须确定、隔离和可重复，不依赖顺序、网络、真实配置或真实世界存档。

### 标准例外

超过评审阈值时优先重构。若保持现状更清晰，变更说明必须解释为何拆分会破坏局部性、格式协议
或事务完整性，并指出覆盖复杂分支与失败路径的测试。`# noqa`、`# type: ignore` 和 lint 豁免
是最后手段，必须限定到具体行和规则，并说明第三方限制或无法表达的运行时不变量。

### 语言与提交

- Python 文件默认使用 ASCII；已有中文模块可继续使用 UTF-8。
- 用户界面和项目内注释以中文为主，标识符遵循现有英文命名。
- 提交信息使用 conventional commits，type 前缀保留英文，说明必须为中文，例如：
  `feat: 添加 UUID 映射工具`、`fix: 修复存档解析崩溃`。

## 完成标准

交付前确认：

- 行为满足请求，失败、取消、空数据和重入路径有明确结果。
- 没有越过层级边界、创建隐藏业务单例或绕过世界写入协调器。
- 新 UI 文本已双语同步，文档和构建资源清单按需更新。
- 相关测试通过；改动风险需要时完整门禁通过。
- `git diff --check` 通过，`git status --short` 中没有意外文件，用户原有改动未被覆盖。
