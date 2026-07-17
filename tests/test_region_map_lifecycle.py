import asyncio

import pytest

from app.services.region_map_service import RegionMapService


def test_region_map_services_do_not_share_mutable_state() -> None:
    first = RegionMapService()
    second = RegionMapService()
    first._mca_data[(1, 2)] = 123

    assert first is not second
    assert first.get_all_data() == {(1, 2): 123}
    assert second.get_all_data() == {}

    first.close()
    second.close()


def test_region_map_service_instances_are_fresh() -> None:
    first = RegionMapService()
    second = RegionMapService()

    assert first is not second

    first.close()
    second.close()


def test_close_releases_executor_and_rejects_new_scan(tmp_path) -> None:
    service = RegionMapService()
    executor = service._ensure_topview_executor()

    service.close()
    service.close()

    assert service._closed is True
    assert service._topview_executor is None
    assert executor._shutdown is True
    with pytest.raises(RuntimeError, match="已关闭"):
        asyncio.run(service.start_silent_scan(str(tmp_path)))
