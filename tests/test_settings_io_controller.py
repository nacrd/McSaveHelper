"""设置页后台 I/O、防抖与生命周期回归测试。"""
from __future__ import annotations

import threading

from app.controllers.settings_io_controller import (
    CacheClearOutcome,
    SettingsIOController,
    SettingsIOControllerDependencies,
)
from app.models.config import ApplicationSettings
from app.services.cache_registry import CacheRegistryStats
from app.services.execution_runtime import (
    CancellationToken,
    ExecutionRuntime,
    LaneLimits,
)


class _ControlledDebounce:
    """让两次防抖等待通过同步原语确定性推进。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._calls = 0
        self.first_started = threading.Event()
        self.second_started = threading.Event()
        self.release_second = threading.Event()

    def __call__(self, token: CancellationToken, delay: float) -> bool:
        del delay
        with self._lock:
            self._calls += 1
            call = self._calls
        if call == 1:
            self.first_started.set()
            return token.wait(2)
        self.second_started.set()
        if not self.release_second.wait(2):
            raise TimeoutError("第二次防抖保存未获准继续")
        return token.is_cancelled


def _runtime() -> ExecutionRuntime:
    limits = LaneLimits(max_workers=1, queue_capacity=4)
    return ExecutionRuntime(io_limits=limits, cpu_limits=limits)


def test_debounced_save_cancels_stale_snapshot_and_uses_io_lane() -> None:
    runtime = _runtime()
    debounce = _ControlledDebounce()
    saved: list[tuple[int, str]] = []
    completed = threading.Event()

    def save(settings: ApplicationSettings) -> None:
        saved.append((settings.api_timeout, threading.current_thread().name))

    controller = SettingsIOController(SettingsIOControllerDependencies(
        execution_runtime=runtime,
        save_settings=save,
        reset_settings=ApplicationSettings,
        cache_snapshot=lambda: CacheRegistryStats(1, 0, ()),
        clear_caches=lambda: {},
        cache_path=lambda: "",
        runtime_snapshot=runtime.snapshot,
        dispatch=lambda callback: callback(),
        save_debounce_seconds=60,
        debounce_wait=debounce,
    ))
    try:
        controller.schedule_save(
            ApplicationSettings(api_timeout=11),
            lambda: None,
            lambda error: None,
        )
        assert debounce.first_started.wait(2)

        controller.schedule_save(
            ApplicationSettings(api_timeout=22),
            completed.set,
            lambda error: None,
        )
        assert debounce.second_started.wait(2)
        debounce.release_second.set()

        assert completed.wait(2)
        assert saved == [(22, "mcsavehelper-io-1")]
    finally:
        controller.close()
        runtime.shutdown(wait=True)


def test_cache_clear_runs_in_io_lane_and_close_suppresses_late_reset() -> None:
    runtime = _runtime()
    clear_threads: list[str] = []
    clear_results: list[CacheClearOutcome] = []
    clear_completed = threading.Event()
    reset_started = threading.Event()
    reset_release = threading.Event()
    reset_threads: list[str] = []
    reset_results: list[ApplicationSettings] = []

    def clear_caches() -> dict[str, int]:
        clear_threads.append(threading.current_thread().name)
        return {
            "deleted_files": 3,
            "freed_bytes": 1024,
            "memory_chunks_cleared": 4,
        }

    def reset_settings() -> ApplicationSettings:
        reset_threads.append(threading.current_thread().name)
        reset_started.set()
        if not reset_release.wait(2):
            raise TimeoutError("重置测试未获准继续")
        return ApplicationSettings(theme="light")

    def record_clear(outcome: CacheClearOutcome) -> None:
        clear_results.append(outcome)
        clear_completed.set()

    controller = SettingsIOController(SettingsIOControllerDependencies(
        execution_runtime=runtime,
        save_settings=lambda settings: None,
        reset_settings=reset_settings,
        cache_snapshot=lambda: CacheRegistryStats(2048, 0, ()),
        clear_caches=clear_caches,
        cache_path=lambda: "cache",
        runtime_snapshot=runtime.snapshot,
        dispatch=lambda callback: callback(),
    ))
    try:
        controller.clear_cache(
            record_clear,
            lambda error: None,
        )
        assert clear_completed.wait(2)
        assert clear_threads == ["mcsavehelper-io-1"]
        assert clear_results[0].metrics.deleted_files == 3
        assert clear_results[0].snapshot.cache_path == "cache"

        controller.reset(reset_results.append, lambda error: None)
        assert reset_started.wait(2)
        controller.close()
        controller.close()
        reset_release.set()
        runtime.shutdown(wait=True)

        assert controller.is_closed
        assert reset_threads == ["mcsavehelper-io-1"]
        assert reset_results == []
    finally:
        reset_release.set()
        controller.close()
        runtime.shutdown(wait=True)


def test_close_flushes_latest_snapshot_still_inside_debounce_window() -> None:
    runtime = _runtime()
    debounce_started = threading.Event()
    saved: list[tuple[ApplicationSettings, str]] = []

    def wait_for_close(token: CancellationToken, delay: float) -> bool:
        del delay
        debounce_started.set()
        return token.wait(2)

    controller = SettingsIOController(SettingsIOControllerDependencies(
        execution_runtime=runtime,
        save_settings=lambda settings: saved.append((
            settings,
            threading.current_thread().name,
        )),
        reset_settings=ApplicationSettings,
        cache_snapshot=lambda: CacheRegistryStats(0, 0, ()),
        clear_caches=lambda: {},
        cache_path=lambda: "",
        runtime_snapshot=runtime.snapshot,
        dispatch=lambda callback: callback(),
        debounce_wait=wait_for_close,
    ))
    settings = ApplicationSettings(api_timeout=31)
    try:
        controller.schedule_save(settings, lambda: None, lambda error: None)
        assert debounce_started.wait(2)

        controller.close()
        runtime.shutdown(wait=True)

        assert saved == [(settings, threading.current_thread().name)]
    finally:
        controller.close()
        runtime.shutdown(wait=True)
