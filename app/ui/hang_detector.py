"""
独立的卡死检测和日志模块

提供独立的 UI 卡死和线程阻塞检测，输出到日志系统。
"""

import threading
import time
from typing import Optional, Dict, Any
from dataclasses import dataclass

try:
    import sys
    _FRAME_AVAILABLE = True
except ImportError:
    _FRAME_AVAILABLE = False


@dataclass
class HangReport:
    """卡死报告"""
    type: str  # "ui_hang" 或 "thread_block"
    duration: float  # 持续时间（秒）
    thread_name: Optional[str] = None
    stack_trace: Optional[str] = None
    timestamp: float = 0.0

    def __post_init__(self):
        if self.timestamp == 0.0:
            self.timestamp = time.time()


class HangDetector:
    """独立的卡死检测器

    专注于检测和记录卡死问题到日志系统。
    """

    def __init__(self):
        self._enabled = False
        self._running = False
        self._thread: Optional[threading.Thread] = None

        # UI 心跳
        self._last_ui_heartbeat: float = time.time()
        self._ui_hang_threshold: float = 15.0  # UI 卡死阈值（秒）
        self._ui_hang_alerted: bool = False

        # 线程监控
        self._thread_snapshots: Dict[int, Dict[str, Any]] = {}
        self._thread_block_threshold: float = 30.0  # 线程阻塞阈值（秒）
        self._blocked_threads: set = set()

        self._lock = threading.Lock()

    def enable(self) -> None:
        """启用卡死检测"""
        if self._enabled:
            return

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
        if self._thread:
            self._thread.join(timeout=2.0)
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

        while self._running:
            try:
                now = time.time()

                # 检测 UI 卡死
                self._check_ui_hang(now)

                # 检测线程阻塞
                self._check_thread_blocking(now)

            except Exception:
                pass

            time.sleep(check_interval)

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
        if not _FRAME_AVAILABLE:
            return

        try:
            frames = sys._current_frames()
            current_threads = set()

            for thread_id, frame in frames.items():
                current_threads.add(thread_id)

                # 获取线程名称
                thread_name = self._get_thread_name(thread_id)

                # 跳过守护线程和监控线程
                if "Daemon" in thread_name or "Monitor" in thread_name or "Detector" in thread_name:
                    continue

                # 提取位置指纹
                location = f"{
                    frame.f_code.co_filename}:{
                    frame.f_lineno}:{
                    frame.f_code.co_name}"

                # 检查是否为良性等待
                is_benign = self._is_benign_wait(frame)

                if thread_id not in self._thread_snapshots:
                    self._thread_snapshots[thread_id] = {
                        "location": location,
                        "timestamp": now,
                        "name": thread_name,
                        "alerted": False,
                    }
                else:
                    snapshot = self._thread_snapshots[thread_id]

                    if snapshot["location"] != location:
                        # 位置变化，线程活跃
                        snapshot["location"] = location
                        snapshot["timestamp"] = now
                        snapshot["alerted"] = False
                        self._blocked_threads.discard(thread_id)
                    else:
                        # 位置未变，检查超时
                        elapsed = now - snapshot["timestamp"]
                        threshold = self._thread_block_threshold * \
                            2 if is_benign else self._thread_block_threshold

                        if elapsed >= threshold and not snapshot["alerted"]:
                            # 提取堆栈
                            stack_lines = []
                            f = frame
                            depth = 0
                            while f is not None and depth < 3:
                                stack_lines.append(
                                    f"{f.f_code.co_filename}:{f.f_lineno} in {f.f_code.co_name}")
                                f = f.f_back
                                depth += 1

                            stack_trace = " -> ".join(stack_lines)

                            snapshot["alerted"] = True
                            self._blocked_threads.add(thread_id)

                            self._log_warning(
                                f"线程 [{thread_name}] 可能阻塞：{
                                    elapsed:.0f}s 无进展（阈值 {
                                    threshold:.0f}s）| 堆栈: {stack_trace}")

            # 清理已退出的线程
            dead_threads = set(self._thread_snapshots.keys()) - current_threads
            for thread_id in dead_threads:
                self._thread_snapshots.pop(thread_id, None)
                self._blocked_threads.discard(thread_id)

        except Exception:
            pass

    def _get_thread_name(self, thread_id: int) -> str:
        """获取线程名称"""
        try:
            for thread in threading.enumerate():
                if thread.ident == thread_id:
                    return thread.name
        except Exception:
            pass
        return f"Thread-{thread_id}"

    def _is_benign_wait(self, frame) -> bool:
        """判断是否为良性等待"""
        try:
            f = frame
            depth = 0
            while f is not None and depth < 10:
                func_name = f.f_code.co_name
                file_name = f.f_code.co_filename

                if func_name in (
                    'sleep',
                    'wait',
                    'join',
                    'select',
                    'poll',
                    'recv',
                        'accept'):
                    return True

                if 'threading.py' in file_name and func_name in (
                        'wait', '_wait'):
                    return True

                if 'queue.py' in file_name and func_name in ('get', 'put'):
                    return True

                f = f.f_back
                depth += 1
        except Exception:
            pass

        return False

    def _log_warning(self, message: str) -> None:
        """记录警告到日志系统"""
        try:
            from core.logger import logger
            logger.warning(f"{message}", module="HangDetector")
        except Exception:
            # 如果日志系统不可用，静默失败
            pass


# 全局单例
_hang_detector: Optional[HangDetector] = None


def get_hang_detector() -> HangDetector:
    """获取全局卡死检测器单例"""
    global _hang_detector
    if _hang_detector is None:
        _hang_detector = HangDetector()
    return _hang_detector
