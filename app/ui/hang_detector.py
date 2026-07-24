"""
独立的卡死检测和日志模块

提供独立的 UI 卡死和线程阻塞检测，输出到日志系统。
"""

import sys
import threading
import time
from typing import Optional, Dict, Any


_SKIPPED_THREAD_TOKENS = (
    "Daemon",
    "Monitor",
    "Detector",
    "topview",
    "HangDetector",
    "LogManager",
)
_GENERIC_WAIT_FUNCTIONS = frozenset(
    {
        "sleep",
        "wait",
        "_wait",
        "join",
        "select",
        "poll",
        "_poll",
        "recv",
        "accept",
        "get",
        "put",
        "_worker",
        "_run_once",
        "run_forever",
        "run_until_complete",
    }
)


class HangDetector:
    """独立的卡死检测器

    专注于检测和记录卡死问题到日志系统。
    """

    def __init__(self) -> None:
        """初始化 UI 挂起检测器。"""
        self._enabled = False
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        # UI 心跳
        self._last_ui_heartbeat: float = time.time()
        self._ui_hang_threshold: float = 15.0  # UI 卡死阈值（秒）
        self._ui_hang_alerted: bool = False

        # 线程监控
        self._thread_snapshots: Dict[int, Dict[str, Any]] = {}
        self._thread_block_threshold: float = 30.0  # 线程阻塞阈值（秒）

        self._lock = threading.Lock()

    def enable(self) -> None:
        """启用卡死检测"""
        thread = self._thread
        if self._enabled and thread is not None and thread.is_alive():
            return

        self._stop_event.clear()
        self._enabled = True
        self._running = True
        self._last_ui_heartbeat = time.time()
        self._thread = threading.Thread(
            target=self._detection_loop,
            daemon=True,
            name="HangDetector")
        self._thread.start()

    def disable(self) -> None:
        """禁用卡死检测"""
        self._enabled = False
        self._running = False
        self._stop_event.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2.0)
        if thread is None or not thread.is_alive():
            self._thread = None

    def ui_heartbeat(self) -> None:
        """UI 线程心跳，应由主循环定期调用"""
        with self._lock:
            self._last_ui_heartbeat = time.time()
            if self._ui_hang_alerted:
                self._ui_hang_alerted = False

    def _detection_loop(self) -> None:
        """检测循环"""
        check_interval = 3.0  # 每 3 秒检查一次

        while self._running and not self._stop_event.is_set():
            try:
                now = time.time()

                # 检测 UI 卡死
                self._check_ui_hang(now)

                # 检测线程阻塞
                self._check_thread_blocking(now)

            except Exception:
                # Detector must never crash the monitor thread.
                pass

            if self._stop_event.wait(check_interval):
                return

    def _check_ui_hang(self, now: float) -> None:
        """检测 UI 卡死"""
        with self._lock:
            elapsed = now - self._last_ui_heartbeat

        if elapsed >= self._ui_hang_threshold:
            if not self._ui_hang_alerted:
                self._ui_hang_alerted = True
                self._log_warning(
                    f"UI 可能已卡死：{
                        elapsed:.0f}s 无心跳响应（阈值 {
                        self._ui_hang_threshold:.0f}s）")

    def _check_thread_blocking(self, now: float) -> None:
        """检测线程阻塞"""
        try:
            frames = sys._current_frames()
            current_threads = set(frames)
            for thread_id, frame in frames.items():
                self._inspect_thread_frame(thread_id, frame, now)
            self._remove_dead_threads(current_threads)

        except Exception:
            # Frame introspection can fail under concurrent teardown.
            pass

    def _inspect_thread_frame(self, thread_id: int, frame: Any, now: float) -> None:
        """更新一个线程的快照，忽略明确的空闲等待。"""
        thread_name = self._get_thread_name(thread_id)
        if any(token in thread_name for token in _SKIPPED_THREAD_TOKENS):
            return
        if self._is_benign_wait(frame):
            self._clear_thread_snapshot(thread_id)
            return

        location = self._frame_location(frame)
        snapshot = self._thread_snapshots.get(thread_id)
        if snapshot is None:
            self._thread_snapshots[thread_id] = {
                "location": location,
                "timestamp": now,
                "name": thread_name,
                "alerted": False,
            }
            return
        if snapshot["location"] != location:
            self._reset_thread_snapshot(snapshot, location, now)
            return
        self._check_thread_timeout(thread_id, frame, snapshot, now)

    def _check_thread_timeout(
        self,
        thread_id: int,
        frame: Any,
        snapshot: Dict[str, Any],
        now: float,
    ) -> None:
        elapsed = now - snapshot["timestamp"]
        threshold = self._thread_block_threshold
        if elapsed < threshold or snapshot["alerted"]:
            return
        stack_trace = self._stack_trace(frame)
        snapshot["alerted"] = True
        self._log_warning(
            f"线程 [{snapshot['name']}] 可能阻塞：{elapsed:.0f}s 无进展"
            f"（阈值 {threshold:.0f}s）| 堆栈: {stack_trace}"
        )

    def _clear_thread_snapshot(self, thread_id: int) -> None:
        self._thread_snapshots.pop(thread_id, None)

    def _reset_thread_snapshot(
        self,
        snapshot: Dict[str, Any],
        location: str,
        now: float,
    ) -> None:
        snapshot["location"] = location
        snapshot["timestamp"] = now
        snapshot["alerted"] = False

    @staticmethod
    def _frame_location(frame: Any) -> str:
        return (
            f"{frame.f_code.co_filename}:"
            f"{frame.f_lineno}:{frame.f_code.co_name}"
        )

    @staticmethod
    def _stack_trace(frame: Any) -> str:
        stack_lines = []
        current = frame
        for _ in range(3):
            if current is None:
                break
            stack_lines.append(
                f"{current.f_code.co_filename}:{current.f_lineno} "
                f"in {current.f_code.co_name}"
            )
            current = current.f_back
        return " -> ".join(stack_lines)

    def _remove_dead_threads(self, current_threads: set[int]) -> None:
        """清理已退出的线程。"""
        dead_threads = set(self._thread_snapshots) - current_threads
        for thread_id in dead_threads:
            self._clear_thread_snapshot(thread_id)

    def _get_thread_name(self, thread_id: int) -> str:
        """获取线程名称"""
        try:
            for thread in threading.enumerate():
                if thread.ident == thread_id:
                    return thread.name
        except RuntimeError:
            # enumerate() can race while threads exit
            pass
        return f"Thread-{thread_id}"

    def _is_benign_wait(self, frame: Any) -> bool:
        """判断是否为良性等待（空闲阻塞，不是卡死）。"""
        try:
            current = frame
            for _ in range(12):
                if current is None:
                    break
                if self._is_benign_wait_frame(current):
                    return True
                current = current.f_back
        except (AttributeError, RuntimeError, TypeError):
            pass

        return False

    @staticmethod
    def _is_benign_wait_frame(frame: Any) -> bool:
        func_name = frame.f_code.co_name
        if func_name in _GENERIC_WAIT_FUNCTIONS:
            return True
        # Names too common to treat as generic parks — only trust them in
        # known idle-wait modules.
        lower = frame.f_code.co_filename.replace("\\", "/").lower()
        if func_name == "result" and "concurrent" in lower and "futures" in lower:
            return True
        return func_name == "_select" and "selectors.py" in lower

    def _log_warning(self, message: str) -> None:
        """记录警告到日志系统"""
        try:
            from core.logger import logger
            logger.warning(f"{message}", module="HangDetector")
        except Exception:
            # Logger may not be initialized during early startup/teardown.
            pass


# 全局单例
_hang_detector: Optional[HangDetector] = None


def get_hang_detector() -> HangDetector:
    """获取全局卡死检测器单例"""
    global _hang_detector
    if _hang_detector is None:
        _hang_detector = HangDetector()
    return _hang_detector
