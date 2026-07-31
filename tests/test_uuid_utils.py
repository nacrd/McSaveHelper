import uuid
from pathlib import Path

import core.nbt as nbtlib
import pytest

from core.nbt_utils import patch_nbt
from core.uuid_utils import (
    NameHistoryEntry,
    UuidNameCache,
    build_mappings,
    format_uuid_with_hyphens,
    get_name_from_uuid,
    get_name_history,
    get_offline_uuid_str,
    normalize_uuid,
    uuid_to_ints,
    uuid_to_most_least,
)
from core import uuid_utils as uuid_utils_module


@pytest.fixture(autouse=True)
def _isolate_name_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """每个测试使用独立的临时缓存，避免读写真实用户目录。"""
    monkeypatch.setattr(
        uuid_utils_module,
        "_name_cache",
        UuidNameCache(tmp_path / "uuid_name_cache.json"),
    )


class _FakeResponse:
    """最小 requests 响应替身。"""

    def __init__(self, status_code: int, payload: object) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> object:
        return self._payload


class _FakeRequests:
    """记录 URL 并按请求次数返回响应的替身。"""

    def __init__(self, responses: list[_FakeResponse]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, int]] = []

    def get(self, url: str, timeout: int = 5) -> _FakeResponse:
        self.calls.append((url, timeout))
        return self.responses.pop(0)


def _install_requests(monkeypatch, responses: list[_FakeResponse]) -> _FakeRequests:
    fake = _FakeRequests(responses)
    monkeypatch.setattr(uuid_utils_module, "_ensure_session", lambda: fake)
    return fake


def minecraft_offline_uuid(name: str) -> str:
    digest = bytearray(__import__("hashlib").md5(
        f"OfflinePlayer:{name}".encode("utf-8")).digest())
    digest[6] = (digest[6] & 0x0F) | 0x30
    digest[8] = (digest[8] & 0x3F) | 0x80
    return str(uuid.UUID(bytes=bytes(digest)))


def test_offline_uuid_matches_minecraft_algorithm():
    assert get_offline_uuid_str("Steve") == minecraft_offline_uuid("Steve")
    assert uuid.UUID(get_offline_uuid_str("Steve")).version == 3


def test_normalize_uuid_and_format_helpers():
    raw = "AABBCCDD-EEFF-0011-2233-445566778899"
    assert normalize_uuid(raw) == "aabbccddeeff00112233445566778899"
    assert format_uuid_with_hyphens(raw) == (
        "aabbccdd-eeff-0011-2233-445566778899"
    )
    assert normalize_uuid("") == ""
    assert format_uuid_with_hyphens("") == ""


def test_uuid_to_ints_uses_signed_32_bit_values():
    assert uuid_to_ints(
        "ffffffff-8000-0000-7fff-ffff00000000") == [-1, -2147483648, 2147483647, 0]


def test_get_name_history_parses_entries_and_uses_normalized_uuid(monkeypatch):
    payload = [
        {"name": "OldName", "changedToAt": 1382104614000},
        {"name": "Notch"},
    ]
    fake = _install_requests(monkeypatch, [_FakeResponse(200, payload)])

    result = get_name_history(
        "069a79f4-44e9-4726-a5be-fca90e38aaf5",
        lambda message, level: None,
    )

    assert result == [
        NameHistoryEntry(name="OldName", changed_to_at=1382104614000),
        NameHistoryEntry(name="Notch", changed_to_at=None),
    ]
    url = fake.calls[0][0]
    assert url.endswith("/069a79f444e94726a5befca90e38aaf5/names")


def test_get_name_history_skips_malformed_entries(monkeypatch):
    payload = [
        {"changedToAt": 100},  # 缺少 name
        "not-a-dict",
        {"name": "  "},  # 空白名
        {"name": "Valid", "changedToAt": "1382104614000"},
    ]
    _install_requests(monkeypatch, [_FakeResponse(200, payload)])

    result = get_name_history("069a79f4-44e9-4726-a5be-fca90e38aaf5")

    assert result == [
        NameHistoryEntry(name="Valid", changed_to_at=1382104614000)
    ]


def test_get_name_history_returns_none_when_both_endpoints_fail(monkeypatch):
    _install_requests(
        monkeypatch,
        [
            _FakeResponse(404, {}),  # names 端点未找到
            _FakeResponse(404, {}),  # 会话服务器回退也未找到
        ],
    )

    assert get_name_history("069a79f4-44e9-4726-a5be-fca90e38aaf5") is None


def test_get_name_history_falls_back_to_session_server(monkeypatch):
    """从未改名的玩家在 names 端点返回 404，应回退到方法一端点。"""
    session_payload = {
        "id": "008d84a2d7294dbf8fe8b3db2378d698",
        "name": "Sihab",
    }
    fake = _install_requests(
        monkeypatch,
        [
            _FakeResponse(404, {}),  # 姓名历史端点无记录
            _FakeResponse(200, session_payload),  # 会话服务器取当前名
        ],
    )

    result = get_name_history("008d84a2-d729-4dbf-8fe8-b3db2378d698")

    assert result == [NameHistoryEntry(name="Sihab")]
    assert fake.calls[0][0].endswith("008d84a2d7294dbf8fe8b3db2378d698/names")
    assert fake.calls[1][0] == (
        "https://sessionserver.mojang.com/session/minecraft/profile/"
        "008d84a2d7294dbf8fe8b3db2378d698"
    )


def test_get_name_history_falls_back_when_names_payload_empty(monkeypatch):
    _install_requests(
        monkeypatch,
        [
            _FakeResponse(200, []),  # names 返回空数组
            _FakeResponse(200, {"name": "Sihab"}),  # 回退到会话服务器
        ],
    )

    result = get_name_history("008d84a2-d729-4dbf-8fe8-b3db2378d698")

    assert result == [NameHistoryEntry(name="Sihab")]


def test_get_name_history_falls_back_when_names_payload_invalid(monkeypatch):
    _install_requests(
        monkeypatch,
        [
            _FakeResponse(200, {"error": "boom"}),  # names 返回非列表
            _FakeResponse(404, {}),  # 会话服务器也未找到
        ],
    )

    assert get_name_history("008d84a2-d729-4dbf-8fe8-b3db2378d698") is None


def test_get_name_history_rejects_invalid_uuid_without_network(monkeypatch):
    def ensure_session() -> object:
        raise AssertionError("无效 UUID 不应发起网络请求")

    monkeypatch.setattr(uuid_utils_module, "_ensure_session", ensure_session)

    assert get_name_history("not-a-uuid") is None
    assert get_name_history("") is None


def test_get_name_from_uuid_rejects_invalid_uuid_without_network(monkeypatch):
    def ensure_session() -> object:
        raise AssertionError("无效 UUID 不应发起网络请求")

    monkeypatch.setattr(uuid_utils_module, "_ensure_session", ensure_session)

    assert get_name_from_uuid("not-a-uuid") is None


def test_get_name_from_uuid_uses_normalized_session_url(monkeypatch):
    payload = {"id": "069a79f444e94726a5befca90e38aaf5", "name": "Notch"}
    fake = _install_requests(monkeypatch, [_FakeResponse(200, payload)])

    result = get_name_from_uuid(
        "069a79f4-44e9-4726-a5be-fca90e38aaf5",
        lambda message, level: None,
    )

    assert result == "Notch"
    assert fake.calls[0][0] == (
        "https://sessionserver.mojang.com/session/minecraft/profile/"
        "069a79f444e94726a5befca90e38aaf5"
    )


def test_get_name_history_uses_api_log_callback(monkeypatch) -> None:
    _install_requests(monkeypatch, [_FakeResponse(200, [{"name": "Notch"}])])
    logs: list[tuple[str, str]] = []

    result = get_name_history(
        "069a79f4-44e9-4726-a5be-fca90e38aaf5",
        lambda message, level: logs.append((message, level)),
    )

    assert result == [NameHistoryEntry(name="Notch")]
    assert any("查询成功" in message for message, _ in logs)


def test_get_name_history_accepts_hyphenated_and_upper_case(monkeypatch):
    payload = [{"name": "Notch"}]
    fake = _install_requests(monkeypatch, [_FakeResponse(200, payload)])

    result = get_name_history("069A79F4-44E9-4726-A5BE-FCA90E38AAF5")

    assert result == [NameHistoryEntry(name="Notch")]
    assert fake.calls[0][0].endswith("069a79f444e94726a5befca90e38aaf5/names")


def test_get_name_history_returns_none_for_empty_payload(monkeypatch):
    _install_requests(
        monkeypatch,
        [
            _FakeResponse(200, []),  # names 返回空数组
            _FakeResponse(404, {}),  # 会话服务器回退也未找到
        ],
    )

    assert get_name_history("069a79f4-44e9-4726-a5be-fca90e38aaf5") is None


def test_get_name_history_returns_none_for_non_list_payload(monkeypatch):
    _install_requests(
        monkeypatch,
        [
            _FakeResponse(200, {"error": "x"}),  # names 返回非列表
            _FakeResponse(404, {}),  # 会话服务器回退也未找到
        ],
    )

    assert get_name_history("069a79f4-44e9-4726-a5be-fca90e38aaf5") is None


def test_patch_nbt_matches_signed_int_array_uuid():
    old_uuid = "ffffffff-8000-0000-7fff-ffff00000000"
    new_uuid = "00000000-0000-0000-0000-000000000001"
    mapping = (
        uuid_to_ints(old_uuid),
        uuid_to_ints(new_uuid),
        old_uuid,
        new_uuid,
        uuid_to_most_least(old_uuid),
        uuid_to_most_least(new_uuid),
    )

    tag = nbtlib.tag.Compound(
        {"Owner": nbtlib.tag.IntArray(uuid_to_ints(old_uuid))})
    patched, changes = patch_nbt(tag, [mapping])

    assert changes == 1
    assert list(patched["Owner"]) == uuid_to_ints(new_uuid)


def test_patch_nbt_updates_string_and_most_least_forms():
    old_uuid = "11111111-2222-3333-4444-555555555555"
    new_uuid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    mapping = (
        uuid_to_ints(old_uuid),
        uuid_to_ints(new_uuid),
        old_uuid,
        new_uuid,
        uuid_to_most_least(old_uuid),
        uuid_to_most_least(new_uuid),
    )
    old_most, old_least = mapping[4]
    new_most, new_least = mapping[5]
    tag = nbtlib.tag.Compound({
        "OwnerUUID": nbtlib.tag.String(old_uuid),
        "OwnerMost": nbtlib.tag.Long(old_most),
        "OwnerLeast": nbtlib.tag.Long(old_least),
    })

    patched, changes = patch_nbt(tag, [mapping])

    assert changes == 2
    assert str(patched["OwnerUUID"]) == new_uuid
    assert int(patched["OwnerMost"]) == new_most
    assert int(patched["OwnerLeast"]) == new_least


def test_patch_nbt_recurses_through_lists_and_respects_string_key_whitelist():
    old_uuid = "11111111-2222-3333-4444-555555555555"
    new_uuid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    mapping = (
        uuid_to_ints(old_uuid),
        uuid_to_ints(new_uuid),
        old_uuid,
        new_uuid,
        uuid_to_most_least(old_uuid),
        uuid_to_most_least(new_uuid),
    )
    tag = nbtlib.tag.Compound({
        "Trusted": nbtlib.tag.List[nbtlib.tag.String]([
            nbtlib.tag.String(old_uuid),
        ]),
        "DisplayName": nbtlib.tag.String(old_uuid),
    })

    patched, changes = patch_nbt(tag, [mapping])

    assert changes == 1
    assert str(patched["Trusted"][0]) == new_uuid
    assert str(patched["DisplayName"]) == old_uuid


def test_build_mappings_uses_injected_custom_mapping(tmp_path: Path):
    world = tmp_path / "world"
    playerdata = world / "playerdata"
    playerdata.mkdir(parents=True)
    old_uuid = "11111111-1111-1111-1111-111111111111"
    custom_uuid = "22222222-2222-2222-2222-222222222222"
    (playerdata / f"{old_uuid}.dat").touch()

    mappings = build_mappings(
        world,
        {old_uuid: "Alice"},
        offline_mode=True,
        manual_names=None,
        log=lambda msg, level: None,
        custom_mappings={"Alice": custom_uuid},
    )

    assert len(mappings) == 1
    assert mappings[0][2] == old_uuid
    assert mappings[0][3] == custom_uuid


def test_build_mappings_rejects_non_one_to_one_manual_names(
    tmp_path: Path,
):
    world = tmp_path / "world"
    playerdata = world / "playerdata"
    playerdata.mkdir(parents=True)
    old_uuid = "11111111-1111-1111-1111-111111111111"
    (playerdata / f"{old_uuid}.dat").touch()
    logs = []

    with pytest.raises(ValueError, match="必须一对一"):
        build_mappings(
            world,
            {},
            offline_mode=True,
            manual_names=["Alice", "Bob"],
            log=lambda message, level: logs.append((message, level)),
        )


def test_build_mappings_uses_cached_name_and_custom_uuid(tmp_path: Path):
    world = tmp_path / "world"
    playerdata = world / "playerdata"
    playerdata.mkdir(parents=True)
    old_uuid = "11111111-1111-1111-1111-111111111111"
    custom_uuid = "22222222-2222-2222-2222-222222222222"
    (playerdata / f"{old_uuid}.dat").touch()

    mappings = build_mappings(
        world,
        {old_uuid: "CachedPlayer"},
        offline_mode=True,
        manual_names=None,
        log=lambda _message, _level: None,
        custom_mappings={"CachedPlayer": custom_uuid},
    )

    assert mappings[0][2:] == (
        old_uuid,
        custom_uuid,
        uuid_to_most_least(old_uuid),
        uuid_to_most_least(custom_uuid),
    )


def test_build_mappings_rejects_duplicate_target_uuid(tmp_path: Path) -> None:
    world = tmp_path / "world"
    playerdata = world / "playerdata"
    playerdata.mkdir(parents=True)
    first = "11111111-1111-1111-1111-111111111111"
    second = "22222222-2222-2222-2222-222222222222"
    for old_uuid in (first, second):
        (playerdata / f"{old_uuid}.dat").touch()
    duplicate = "33333333-3333-3333-3333-333333333333"

    with pytest.raises(ValueError, match="同一个目标 UUID"):
        build_mappings(
            world,
            {first: "Alice", second: "Bob"},
            offline_mode=True,
            manual_names=None,
            log=lambda _message, _level: None,
            custom_mappings={"Alice": duplicate, "Bob": duplicate},
        )


def test_name_cache_hit_skips_network(monkeypatch) -> None:
    payload = [{"name": "OldName", "changedToAt": 1382104614000}, {"name": "Notch"}]
    fake = _install_requests(monkeypatch, [_FakeResponse(200, payload)])
    uuid_str = "069a79f4-44e9-4726-a5be-fca90e38aaf5"

    assert get_name_history(uuid_str) == [
        NameHistoryEntry(name="OldName", changed_to_at=1382104614000),
        NameHistoryEntry(name="Notch"),
    ]
    assert len(fake.calls) == 1

    # 第二次查询应命中本地缓存，不再发起任何网络请求
    monkeypatch.setattr(
        uuid_utils_module,
        "_ensure_session",
        lambda: (_ for _ in ()).throw(AssertionError("缓存命中不应联网")),
    )
    assert get_name_history(uuid_str) == [
        NameHistoryEntry(name="OldName", changed_to_at=1382104614000),
        NameHistoryEntry(name="Notch"),
    ]


def test_name_cache_persists_to_disk(tmp_path: Path) -> None:
    cache_path = tmp_path / "caches" / "uuid_name_cache.json"
    first = UuidNameCache(cache_path)
    first.remember(
        "008d84a2d7294dbf8fe8b3db2378d698",
        [NameHistoryEntry(name="Sihab")],
    )

    second = UuidNameCache(cache_path)
    entry = second.get("008d84a2d7294dbf8fe8b3db2378d698")

    assert entry is not None
    assert entry.current_name == "Sihab"
    assert entry.history == (NameHistoryEntry(name="Sihab"),)


def test_name_cache_tolerates_corrupt_file(tmp_path: Path) -> None:
    cache_path = tmp_path / "uuid_name_cache.json"
    cache_path.write_text("{broken json", encoding="utf-8")

    cache = UuidNameCache(cache_path)

    assert cache.get("069a79f444e94726a5befca90e38aaf5") is None
    # 之后仍可正常写入
    cache.remember(
        "069a79f444e94726a5befca90e38aaf5",
        [NameHistoryEntry(name="Notch")],
    )
    entry = cache.get("069a79f444e94726a5befca90e38aaf5")
    assert entry is not None
    assert entry.current_name == "Notch"


def test_name_cache_skips_malformed_entries(tmp_path: Path) -> None:
    cache_path = tmp_path / "uuid_name_cache.json"
    cache_path.write_text(
        '{"version": 1, "entries": {'
        '"bad1": {"history": [{"name": ""}]},'
        '"bad2": {"history": "not-a-list"},'
        '"good": {"history": [{"name": "Notch"}]}'
        "}}",
        encoding="utf-8",
    )

    cache = UuidNameCache(cache_path)

    assert cache.get("bad1") is None
    assert cache.get("bad2") is None
    good = cache.get("good")
    assert good is not None
    assert good.current_name == "Notch"


def test_get_name_from_uuid_uses_cached_name(monkeypatch) -> None:
    payload = {"id": "069a79f444e94726a5befca90e38aaf5", "name": "Notch"}
    _install_requests(monkeypatch, [_FakeResponse(200, payload)])
    uuid_str = "069a79f4-44e9-4726-a5be-fca90e38aaf5"

    assert get_name_from_uuid(uuid_str) == "Notch"

    # 缓存已写入；第二次不再发起网络请求
    monkeypatch.setattr(
        uuid_utils_module,
        "_ensure_session",
        lambda: (_ for _ in ()).throw(AssertionError("缓存命中不应联网")),
    )
    assert get_name_from_uuid(uuid_str) == "Notch"


def test_name_cache_fallback_result_is_cached(monkeypatch) -> None:
    """回退到会话服务器得到的当前名也应写入缓存。"""
    session_payload = {"id": "008d84a2d7294dbf8fe8b3db2378d698", "name": "Sihab"}
    _install_requests(
        monkeypatch,
        [
            _FakeResponse(404, {}),
            _FakeResponse(200, session_payload),
        ],
    )
    uuid_str = "008d84a2-d729-4dbf-8fe8-b3db2378d698"

    assert get_name_history(uuid_str) == [NameHistoryEntry(name="Sihab")]

    monkeypatch.setattr(
        uuid_utils_module,
        "_ensure_session",
        lambda: (_ for _ in ()).throw(AssertionError("缓存命中不应联网")),
    )
    assert get_name_history(uuid_str) == [NameHistoryEntry(name="Sihab")]


def test_name_cache_clear_removes_disk_file(tmp_path: Path) -> None:
    cache = UuidNameCache(tmp_path / "uuid_name_cache.json")
    cache.remember("069a79f444e94726a5befca90e38aaf5", [NameHistoryEntry("Notch")])
    assert cache.get("069a79f444e94726a5befca90e38aaf5") is not None

    cache.clear()

    assert cache.get("069a79f444e94726a5befca90e38aaf5") is None
    assert not (tmp_path / "uuid_name_cache.json").exists()
