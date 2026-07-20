from pathlib import Path

import core.nbt as nbtlib

from core.omni.nbt_loader import NbtLoader


def test_load_level_info_extracts_mods_and_extended_world_metadata(
    tmp_path: Path,
) -> None:
    data = nbtlib.Compound({
        "Version": nbtlib.Compound({
            "Id": nbtlib.Int(3465),
            "Name": nbtlib.String("1.20.1"),
        }),
        "WasModded": nbtlib.Byte(1),
        "ServerBrands": nbtlib.List[nbtlib.String]([nbtlib.String("forge")]),
        "FML": nbtlib.Compound({
            "ModList": nbtlib.List[nbtlib.Compound]([
                nbtlib.Compound({
                    "ModId": nbtlib.String("forge"),
                    "ModVersion": nbtlib.String("47.2.0"),
                }),
                nbtlib.Compound({
                    "ModId": nbtlib.String("create"),
                    "ModVersion": nbtlib.String("0.5.1"),
                    "ModName": nbtlib.String("Create"),
                }),
            ])
        }),
        "WorldGenSettings": nbtlib.Compound({
            "seed": nbtlib.Long(42),
            "generate_features": nbtlib.Byte(1),
            "bonus_chest": nbtlib.Byte(0),
        }),
        "DifficultyLocked": nbtlib.Byte(1),
        "SpawnAngle": nbtlib.Float(90.0),
        "BorderCenterX": nbtlib.Double(12.5),
        "BorderCenterZ": nbtlib.Double(-8.0),
        "BorderSize": nbtlib.Double(10000.0),
        "BorderWarningBlocks": nbtlib.Double(10.0),
    })
    nbtlib.File({"Data": data}).save(tmp_path / "level.dat")

    info = NbtLoader(tmp_path).load_level_info()

    assert info.mod_list_complete is True
    assert info.mod_loaders == ["Forge 47.2.0"]
    assert info.mods is not None
    assert [(mod.mod_id, mod.name, mod.version) for mod in info.mods] == [
        ("create", "Create", "0.5.1")
    ]
    assert bool(info.difficulty_locked) is True
    assert float(info.spawn_angle or 0) == 90.0
    assert bool(info.generate_features) is True
    assert bool(info.bonus_chest) is False
    assert float(info.border_center_x or 0) == 12.5
    assert float(info.border_center_z or 0) == -8.0
    assert float(info.border_size or 0) == 10000.0
    assert int(info.border_warning_blocks or 0) == 10
