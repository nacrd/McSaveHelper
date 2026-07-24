import pytest

from app.services.block_data_service import get_block_data_service
from app.services.config_service import ConfigService
from app.services.execution_runtime import (
    ExecutionRuntime,
    LaneLimits,
    RuntimeClosedError,
)
from app.services.parallel_runner import create_runtime_parallel_runner
from app.services.server_properties_service import get_server_properties_service
from app.services.world_compare_service import get_world_compare_service
from app.services.world_stats_service import get_world_stats_service


def test_lightweight_service_factories_return_isolated_instances() -> None:
    factories = (
        get_block_data_service,
        get_server_properties_service,
        get_world_compare_service,
        get_world_stats_service,
    )

    for factory in factories:
        assert factory() is not factory()


def test_log_callbacks_are_not_overwritten_by_another_caller() -> None:
    def first_log(message, level) -> None:
        del message, level

    def second_log(message, level) -> None:
        del message, level

    first = get_world_stats_service(first_log)
    second = get_world_stats_service(second_log)

    assert first.log is first_log
    assert second.log is second_log


def test_config_services_have_explicit_isolated_lifetimes(tmp_path) -> None:
    first = ConfigService(tmp_path / "first")
    second = ConfigService(tmp_path / "second")

    first.language = "en_US"

    assert first is not second
    assert first.language == "en_US"
    assert second.language == "zh_CN"


def test_parallel_runner_follows_shared_runtime_lifetime() -> None:
    runtime = ExecutionRuntime(
        io_limits=LaneLimits(1, 1),
        cpu_limits=LaneLimits(1, 1),
    )
    runner = create_runtime_parallel_runner(runtime)

    assert runner.map("lifetime", [1], lambda value: value + 1) == [2]
    assert runtime.shutdown(wait=True) is True

    with pytest.raises(RuntimeClosedError):
        runner.map("closed", [1], lambda value: value)
