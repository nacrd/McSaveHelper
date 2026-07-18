"""Tests for migrator pure option helpers."""
from app.ui.views.migrator_options import (
    PLATFORM_OPTIONS,
    VERSION_OPTIONS,
    format_uuid_query_result,
    format_version_label,
    mode_description,
    version_downgrade_warning,
)


def test_format_version_label_with_and_without_note() -> None:
    assert format_version_label("1.21.4", 3953, "最新正式版").endswith("最新正式版")
    assert "ID: 3952" in format_version_label("1.21.0", 3952)


def test_mode_description_for_fast_and_full() -> None:
    assert "快速模式" in mode_description("fast")
    assert "完整模式" in mode_description("full")


def test_version_downgrade_warning_threshold() -> None:
    assert version_downgrade_warning(2586) is None
    warning = version_downgrade_warning(1343)
    assert warning is not None
    assert "1343" in warning


def test_format_uuid_query_result_online_and_offline() -> None:
    offline_only = format_uuid_query_result("Steve", "offline-1")
    assert "离线 UUID: offline-1" in offline_only
    assert "未获取到" in offline_only

    online = format_uuid_query_result(
        "Steve",
        "offline-1",
        online_uuid="online-1",
        official_name="Notch",
    )
    assert "正版 UUID: online-1" in online
    assert "官方名称: Notch" in online


def test_unsupported_conversion_options_are_not_exposed() -> None:
    assert VERSION_OPTIONS == []
    assert PLATFORM_OPTIONS == [("java", "Java 版")]
