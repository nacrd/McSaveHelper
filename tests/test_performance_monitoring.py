"""框架中立性能监控服务测试。"""
from __future__ import annotations

from app.services.performance_monitoring import PerformanceMonitoringService


def test_resource_samples_are_bounded() -> None:
    service = PerformanceMonitoringService(max_samples=2)

    service._sample_once()
    service._sample_once()
    service._sample_once()

    memory = service.snapshot("memory_usage")
    cpu = service.snapshot("cpu_usage")
    assert len(memory) == 2
    assert len(cpu) == 2
    assert all(metric.unit == "MB" for metric in memory)
    assert all(metric.unit == "%" for metric in cpu)
    service.close()


def test_configure_starts_and_stops_idempotently() -> None:
    service = PerformanceMonitoringService()

    service.configure(True, 1.0)
    service.configure(True, 30.0)
    assert service.enabled is True
    assert service.print_interval == 30.0

    service.configure(False, 2.0)
    service.close()
    assert service.enabled is False
    assert service.print_interval == 5.0
