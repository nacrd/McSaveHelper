"""轻量性能计时埋点（性能优化基线用）

默认关闭；设置环境变量 MCSH_PERF=1 启用。启用时：
- 启动阶段计时写入 startup_timing.log（启动早期 logger 尚未就绪，直接写文件）
- 运行时埋点（progress 频率、帧时间、commit/scan 耗时）追加到 perf_runtime.log

所有调用在关闭时几乎零开销（开头一个 bool 判断即返回）。
"""
import os
import sys
import time
from pathlib import Path
from threading import Lock
from types import TracebackType
from typing import List, Optional, Tuple

PERF_ENABLED: bool = os.environ.get("MCSH_PERF", "") == "1"

_startup_marks: List[Tuple[str, float]] = []
_runtime_lock = Lock()
_runtime_path: Optional[Path] = None


def _project_root() -> Path:
    """日志写入目录：打包版取 exe 同级，源码态取项目根。"""
    if hasattr(sys, "_MEIPASS"):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


def _runtime_log_path() -> Path:
    global _runtime_path
    if _runtime_path is None:
        _runtime_path = _project_root() / "perf_runtime.log"
    return _runtime_path


# ─── 启动阶段计时 ──────────────────────────────────────

def startup_mark(label: str) -> None:
    """记录启动阶段时间戳。"""
    if not PERF_ENABLED:
        return
    _startup_marks.append((label, time.perf_counter()))


def flush_startup() -> None:
    """把启动阶段计时写入 startup_timing.log。"""
    if not PERF_ENABLED or not _startup_marks:
        return
    try:
        path = _project_root() / "startup_timing.log"
        t0 = _startup_marks[0][1]
        prev = t0
        lines = ["MCSaveHelper 启动耗时埋点 (MCSH_PERF=1)\n", "-" * 56 + "\n"]
        for label, ts in _startup_marks:
            lines.append(
                f"  {label:<38s} 累计 {ts - t0:7.3f}s | 段 {ts - prev:7.3f}s\n")
            prev = ts
        with open(path, "w", encoding="utf-8") as f:
            f.writelines(lines)
    except Exception:
        pass


# ─── 运行时埋点 ─────────────────────────────────────────

def runtime_log(message: str) -> None:
    """追加一行到 perf_runtime.log（线程安全）。"""
    if not PERF_ENABLED:
        return
    try:
        with _runtime_lock:
            with open(_runtime_log_path(), "a", encoding="utf-8") as f:
                f.write(f"[{time.strftime('%H:%M:%S')}] {message}\n")
    except Exception:
        pass


class PerfTimer:
    """计时上下文管理器；关闭时 __enter__/__exit__ 直接返回，零开销。"""

    __slots__ = ("label", "_start")

    def __init__(self, label: str) -> None:
        self.label = label
        self._start = 0.0

    def __enter__(self) -> "PerfTimer":
        if PERF_ENABLED:
            self._start = time.perf_counter()
        return self

    def __exit__(
        self,
        exc_type: Optional[type[BaseException]],
        exc: Optional[BaseException],
        tb: Optional[TracebackType],
    ) -> None:
        if not PERF_ENABLED:
            return
        elapsed_ms = (time.perf_counter() - self._start) * 1000.0
        runtime_log(f"timer  {self.label}  {elapsed_ms:8.2f} ms")


class RateMeter:
    """调用频率计数器，每秒汇总写入 perf_runtime.log。"""

    __slots__ = ("label", "_count", "_window_start")

    def __init__(self, label: str) -> None:
        self.label = label
        self._count = 0
        self._window_start = 0.0

    def hit(self) -> None:
        if not PERF_ENABLED:
            return
        now = time.perf_counter()
        if self._window_start == 0.0:
            self._window_start = now
        self._count += 1
        if now - self._window_start >= 1.0:
            runtime_log(
                f"rate   {self.label}  {self._count} calls / "
                f"{now - self._window_start:.2f}s")
            self._count = 0
            self._window_start = now


class FrameTimer:
    """累积帧耗时与附加指标，每秒输出 p50/p95/max。"""

    __slots__ = ("label", "_times", "_metrics", "_window_start")

    def __init__(self, label: str) -> None:
        self.label = label
        self._times: List[float] = []
        self._metrics: List[float] = []
        self._window_start = 0.0

    def record(self, elapsed_ms: float, metric: Optional[float] = None) -> None:
        if not PERF_ENABLED:
            return
        now = time.perf_counter()
        if self._window_start == 0.0:
            self._window_start = now
        self._times.append(elapsed_ms)
        if metric is not None:
            self._metrics.append(metric)
        if now - self._window_start >= 1.0:
            if self._times:
                s = sorted(self._times)
                n = len(s)
                p50 = s[n // 2]
                p95 = s[int(n * 0.95)] if n > 1 else s[0]
                m = max(self._metrics) if self._metrics else None
                mstr = f" shapes_max={int(m)}" if m is not None else ""
                runtime_log(
                    f"frame  {self.label}  n={n} p50={p50:.1f}ms "
                    f"p95={p95:.1f}ms max={s[-1]:.1f}ms{mstr}")
            self._times.clear()
            self._metrics.clear()
            self._window_start = now
