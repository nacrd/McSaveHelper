"""线程监控辅助模块

提供线程阻塞检测相关的辅助函数和逻辑。
"""
import threading
from typing import Dict, Any


class ThreadMonitoringMixin:
    """线程监控混入类，提供线程阻塞检测功能"""

    _thread_snapshots: Dict[int, Dict[str, Any]]
    _blocked_threads: set[int]
    thread_block_timeout: float

    def _should_alert(self, key: str) -> bool:
        raise NotImplementedError

    def _fire_alert(self, alert: Any) -> None:
        raise NotImplementedError

    def _process_thread(self, thread_id: int, frame, now: float) -> None:
        """处理单个线程的检查"""
        thread_name = self._get_thread_name(thread_id)
        if (
            thread_id == threading.get_ident()
            or self._is_exempt_thread(thread_name)
        ):
            self._thread_snapshots.pop(thread_id, None)
            self._blocked_threads.discard(thread_id)
            return

        location = (
            f"{frame.f_code.co_filename}:"
            f"{frame.f_lineno}:{frame.f_code.co_name}"
        )

        is_benign_wait = self._is_benign_wait(frame)
        if is_benign_wait:
            self._update_benign_thread(thread_id, location, thread_name, now)
            return

        if thread_id not in self._thread_snapshots:
            self._create_thread_snapshot(
                thread_id, location, thread_name, is_benign_wait, now
            )
        else:
            self._check_thread_progress(
                thread_id, location, is_benign_wait, frame, now
            )

    def _update_benign_thread(
        self, thread_id: int, location: str, thread_name: str, now: float
    ) -> None:
        """更新良性等待线程"""
        self._thread_snapshots[thread_id] = {
            "location": location,
            "timestamp": now,
            "alerted": False,
            "name": thread_name,
            "benign": True,
        }
        self._blocked_threads.discard(thread_id)

    def _create_thread_snapshot(
        self, thread_id: int, location: str, thread_name: str,
        is_benign_wait: bool, now: float
    ) -> None:
        """创建新线程快照"""
        self._thread_snapshots[thread_id] = {
            "location": location,
            "timestamp": now,
            "alerted": False,
            "name": thread_name,
            "benign": is_benign_wait,
        }

    def _check_thread_progress(
        self, thread_id: int, location: str, is_benign_wait: bool,
        frame, now: float
    ) -> None:
        """检查线程进度"""
        snapshot = self._thread_snapshots[thread_id]

        if snapshot["location"] != location:
            self._update_thread_location(
                snapshot, location, is_benign_wait, thread_id, now
            )
        else:
            self._check_thread_timeout(
                snapshot, thread_id, is_benign_wait, frame, now
            )

    def _update_thread_location(
        self, snapshot: Dict, location: str, is_benign_wait: bool,
        thread_id: int, now: float
    ) -> None:
        """更新线程位置"""
        snapshot["location"] = location
        snapshot["timestamp"] = now
        snapshot["alerted"] = False
        snapshot["benign"] = is_benign_wait
        self._blocked_threads.discard(thread_id)

    def _check_thread_timeout(
        self, snapshot: Dict, thread_id: int, is_benign_wait: bool,
        frame, now: float
    ) -> None:
        """检查线程超时"""
        elapsed = now - snapshot["timestamp"]
        threshold = (
            self.thread_block_timeout * 2
            if is_benign_wait
            else self.thread_block_timeout
        )

        if elapsed >= threshold:
            if (
                not snapshot["alerted"]
                and self._should_alert(f"thread_block_{thread_id}")
            ):
                self._alert_blocked_thread(
                    snapshot, thread_id, is_benign_wait,
                    elapsed, threshold, frame
                )

    def _alert_blocked_thread(
        self, snapshot: Dict, thread_id: int, is_benign_wait: bool,
        elapsed: float, threshold: float, frame
    ) -> None:
        """发出线程阻塞告警"""
        from app.ui.performance.health import AlertLevel, HealthAlert

        stack_info = self._extract_stack(frame)
        thread_name = snapshot.get("name", f"Thread-{thread_id}")
        level = AlertLevel.WARNING if is_benign_wait else AlertLevel.CRITICAL

        self._fire_alert(HealthAlert(
            level=level,
            category="thread_block",
            message=(
                f"线程 {thread_name} 可能阻塞："
                f"{elapsed:.0f}s 无进展（阈值 "
                f"{threshold:.0f}s）\n堆栈:\n{stack_info}"
            ),
            value=elapsed,
            threshold=threshold,
        ))

        snapshot["alerted"] = True
        self._blocked_threads.add(thread_id)

    def _cleanup_dead_threads(self, current_threads: set) -> None:
        """清理已退出的线程"""
        dead_threads = set(self._thread_snapshots.keys()) - current_threads
        for thread_id in dead_threads:
            self._thread_snapshots.pop(thread_id, None)
            self._blocked_threads.discard(thread_id)

    def _extract_stack(self, frame, max_depth: int = 5) -> str:
        """提取堆栈信息"""
        stack_lines = []
        f = frame
        depth = 0
        while f is not None and depth < max_depth:
            stack_lines.append(
                f"  {f.f_code.co_filename}:{f.f_lineno} "
                f"in {f.f_code.co_name}"
            )
            f = f.f_back
            depth += 1
        return "\n".join(stack_lines) if stack_lines else "N/A"

    def _is_exempt_thread(self, thread_name: str) -> bool:
        """判断线程是否为常驻/框架线程，不参与阻塞告警。"""
        if not thread_name:
            return False
        exempt_exact = {
            "ResourceMonitor",
            "LogManager-Worker",
        }
        if thread_name in exempt_exact:
            return True
        exempt_prefixes = (
            "asyncio_",
            "ThreadPoolExecutor-",
        )
        return thread_name.startswith(exempt_prefixes)

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
        """判断是否为良性等待（time.sleep, Event.wait 等）"""
        try:
            f = frame
            depth = 0
            while f is not None and depth < 10:
                func_name = f.f_code.co_name
                file_name = f.f_code.co_filename

                # 常见的良性等待模式
                if func_name in (
                    'sleep', 'wait', 'join', 'select',
                    'poll', 'recv', 'accept',
                ):
                    return True

                # threading 模块的等待
                if 'threading.py' in file_name and func_name in ('wait', '_wait'):
                    return True

                # queue 模块的阻塞获取
                if 'queue.py' in file_name and func_name in ('get', 'put'):
                    return True

                f = f.f_back
                depth += 1
        except Exception:
            pass

        return False
