# 日志记录接口 API

本文对应阶段 2。接口基于 Python 标准库 `logging`，同时保留 MCSaveHelper 现有
`core.logger` 门面，调用方不需要直接管理线程、文件句柄或轮转状态。

## 1. 初始化

组合根启动时调用一次：

```python
from core.logger import LogLevel, setup_default_logging

setup_default_logging(
    enable_console=True,
    enable_file=True,
    level=LogLevel.INFO,
    capture_stdlib=True,
)
```

缺省文件输出使用 `~/.mc_save_helper/logs/archive/app-YYYY-MM-DD.jsonl`，按天滚动并按大小分片。
传入 `file_path` 时保留旧的纯文本 `FileHandler` 语义，便于启动故障兼容和测试替身。

## 2. 统一门面

```python
from core.logger import logger

logger.debug("开始扫描", module="WorldIndex")
logger.info("备份完成", module="Backup", extra={"size_bytes": 134217728})
logger.warn("使用降级解析器", module="NBT")

try:
    load_world()
except OSError:
    logger.error("读取存档失败", module="WorldRepository", exc_info=True)

logger.fatal("无法继续启动", module="QtApp", exc_info=True)
```

### 2.1 方法签名

```python
logger.debug(
    message: str,
    module: str = "",
    extra: dict[str, object] | None = None,
    exc_info: bool | None = None,
) -> None
```

`info`、`warn`、`warning`、`error`、`fatal`、`critical`、`success` 和 `api` 使用相同参数。
`fatal` 是 `critical` 的兼容别名；`warn` 是 `warning` 的兼容别名。`logger.log` 接受
`LogLevel`，并额外支持 `stack_info=True`。

### 2.2 参数规则

- `message` 是主消息；参数化格式请优先使用标准库 logger 的 `%s` 参数化调用。
- `module` 是面向用户筛选的稳定领域名，不应填入动态路径或对象 repr。
- `extra` 必须是可 JSON 化的键值对象。不可序列化值会安全转换为字符串；敏感键
  `password`、`token`、`secret`、`authorization`、`cookie` 默认写成 `<redacted>`。
- `exc_info=True` 只应在 `except` 块内使用；记录会保存异常类型、消息和完整堆栈。
- 调用立即返回，实际 I/O 在后台 worker 中完成；不要依赖返回值判断是否已经落盘。

## 3. 标准库 logging 兼容

`setup_default_logging(capture_stdlib=True)` 会将 root logger 接入同一异步队列：

```python
import logging

module_logger = logging.getLogger(__name__)
module_logger.info("下载完成", extra={"request_id": "r-42"})
```

标准库记录保留 `logger_name`、进程/线程信息和参数化后的消息。已有模块可以逐步迁移，不需要
一次性替换为 `core.logger`。桥接 handler 不传播到 `mcsavehelper` 内部 logger，避免重复记录。

## 4. 处理器和生命周期

- `DailyJsonlHandler`：按天和大小轮转，失败时写 emergency 文件。
- `FileHandler`：兼容旧的单文件大小轮转，传入显式 `file_path` 时使用。
- `ConsoleHandler`：输出到原始标准流，ERROR/FATAL 使用 stderr。
- `UIHandler`：通过回调把记录投递到 Qt 层；回调必须自行使用 `run_on_ui`。

应用退出时调用：

```python
from core.logger import logger

logger.flush()    # 等待队列排空并刷新 handler
logger.shutdown() # 幂等关闭 worker、桥接和文件句柄
```

handler 失败不会抛回业务线程；严重存储故障会产生 emergency 文件并通过后续 UI 状态展示。

## 5. 结构化 JSONL 字段

JSONL 每行包含 `schema_version`、`timestamp`、`timestamp_utc_us`、`level`、`category`、`module`、
`logger_name`、`process_id`、`thread_id`、`thread_name`、`message`、异常三字段、`extra`、
`fingerprint` 和 `created_at_utc_us`。近期查询、统计、告警通过 `core.logging.storage.JsonlLogStore`
后台扫描；查询器返回 `StoredLog`、`LogPage`、`LogStatistics` 等不可变结果，不把 Qt 控件或文件
句柄暴露给调用方。

## 6. 线程安全约束

1. 不在日志 handler 中触发新的业务日志，避免递归。
2. 不从 worker 线程直接更新 Qt 控件；UI handler 只发出 queued callback。
3. 不跨线程复用打开的文件对象；`DailyJsonlHandler` 是唯一写者。
4. `shutdown()` 后的新日志会被安全丢弃，不重新启动已经关闭的 worker。
