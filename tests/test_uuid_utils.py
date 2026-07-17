import uuid
from pathlib import Path

import nbtlib

from core.nbt_utils import patch_nbt
from core.uuid_utils import build_mappings, get_offline_uuid_str, uuid_to_ints, uuid_to_most_least


def minecraft_offline_uuid(name: str) -> str:
    digest = bytearray(__import__("hashlib").md5(
        f"OfflinePlayer:{name}".encode("utf-8")).digest())
    digest[6] = (digest[6] & 0x0F) | 0x30
    digest[8] = (digest[8] & 0x3F) | 0x80
    return str(uuid.UUID(bytes=bytes(digest)))


def test_offline_uuid_matches_minecraft_algorithm():
    assert get_offline_uuid_str("Steve") == minecraft_offline_uuid("Steve")
    assert uuid.UUID(get_offline_uuid_str("Steve")).version == 3


def test_uuid_to_ints_uses_signed_32_bit_values():
    assert uuid_to_ints(
        "ffffffff-8000-0000-7fff-ffff00000000") == [-1, -2147483648, 2147483647, 0]


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
