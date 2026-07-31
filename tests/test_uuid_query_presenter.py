"""UUID 查询结果格式化与输入校验的纯函数测试。"""
from __future__ import annotations

from app.presenters.uuid_query_presenter import (
    format_name_history_query,
    normalize_query_uuid,
)
from core.uuid_utils import NameHistoryEntry

_NOTCH = "069a79f4-44e9-4726-a5be-fca90e38aaf5"


def test_normalize_query_uuid_accepts_common_formats() -> None:
    assert normalize_query_uuid(_NOTCH) == "069a79f444e94726a5befca90e38aaf5"
    assert normalize_query_uuid(
        "069A79F4-44E9-4726-A5BE-FCA90E38AAF5"
    ) == "069a79f444e94726a5befca90e38aaf5"
    assert normalize_query_uuid("069a79f444e94726a5befca90e38aaf5") == (
        "069a79f444e94726a5befca90e38aaf5"
    )


def test_normalize_query_uuid_rejects_invalid_input() -> None:
    assert normalize_query_uuid("") is None
    assert normalize_query_uuid("   ") is None
    assert normalize_query_uuid("069a79f4") is None  # 过短
    assert normalize_query_uuid("zzzz79f4-44e9-4726-a5be-fca90e38aaf5") is None
    assert normalize_query_uuid("069a79f4-44e9-4726-a5be-fca90e38aaf") is None


def test_format_name_history_query_shows_current_and_history() -> None:
    history = [
        NameHistoryEntry(name="OldName", changed_to_at=1382104614000),
        NameHistoryEntry(name="Notch"),
    ]
    text = format_name_history_query(_NOTCH, history)

    lines = text.splitlines()
    assert "UUID: 069a79f4-44e9-4726-a5be-fca90e38aaf5" in lines[0]
    assert "当前名称: Notch" in lines[1]
    assert "曾用名" in lines[2]
    assert "OldName" in text
    assert "2013-10-18" in text  # 1382104614000 ms → 2013-10-18
    # 当前名不应出现在曾用名列表中
    assert "- Notch" not in text


def test_format_name_history_query_single_entry_skips_history() -> None:
    text = format_name_history_query(
        _NOTCH,
        [NameHistoryEntry(name="Notch")],
    )

    assert "当前名称: Notch" in text
    assert "曾用名" not in text


def test_format_name_history_query_failure_returns_not_found() -> None:
    text = format_name_history_query(_NOTCH, None)

    assert "UUID: 069a79f4-44e9-4726-a5be-fca90e38aaf5" in text
    assert "未找到" in text


def test_format_name_history_query_formats_compact_uuid() -> None:
    text = format_name_history_query("069a79f444e94726a5befca90e38aaf5", None)

    # 32 位无连字符输入也会以可读的 8-4-4-4-12 形式展示
    assert "069a79f4-44e9-4726-a5be-fca90e38aaf5" in text


def test_format_name_history_query_tolerates_bad_timestamp() -> None:
    history = [
        NameHistoryEntry(name="OldName", changed_to_at=999999999999999),
        NameHistoryEntry(name="Notch"),
    ]
    text = format_name_history_query(_NOTCH, history)

    assert "OldName" in text
    assert "起）" not in text  # 超范围时间戳不回退为错误
