import nbtlib
from pathlib import Path

from core.pure_cleaner import _purge_mod_data_in_chunk
from core.scanner import scan_all_entity_regions


def test_purge_mod_data_replaces_palette_and_filters_entities() -> None:
    vanilla_block = nbtlib.Compound({
        "Name": nbtlib.String("minecraft:stone"),
    })
    modded_block = nbtlib.Compound({
        "Name": nbtlib.String("example:machine"),
        "Properties": nbtlib.Compound({"active": nbtlib.String("true")}),
    })
    vanilla_entity = nbtlib.Compound({
        "id": nbtlib.String("minecraft:pig"),
    })
    modded_entity = nbtlib.Compound({
        "id": nbtlib.String("example:robot"),
    })
    unknown_entity = nbtlib.Compound({"Health": nbtlib.Float(10)})
    modded_block_entity = nbtlib.Compound({
        "id": nbtlib.String("example:machine"),
    })
    data = nbtlib.Compound({
        "sections": nbtlib.List[nbtlib.Compound]([
            nbtlib.Compound({
                "palette": nbtlib.List[nbtlib.Compound]([
                    vanilla_block,
                    modded_block,
                ]),
            }),
        ]),
        "entities": nbtlib.List[nbtlib.Compound]([
            vanilla_entity,
            modded_entity,
            unknown_entity,
        ]),
        "block_entities": nbtlib.List[nbtlib.Compound]([
            modded_block_entity,
        ]),
    })

    blocks_replaced, entities_removed = _purge_mod_data_in_chunk(data)

    assert blocks_replaced == 1
    assert entities_removed == 2
    assert str(modded_block["Name"]) == "minecraft:air"
    assert "Properties" not in modded_block
    assert list(data["entities"]) == [vanilla_entity, unknown_entity]
    assert list(data["block_entities"]) == []


def test_purge_mod_data_handles_modern_block_states_palette() -> None:
    modded = nbtlib.Compound({"Name": nbtlib.String("example:ore")})
    data = nbtlib.Compound({
        "sections": nbtlib.List[nbtlib.Compound]([
            nbtlib.Compound({
                "block_states": nbtlib.Compound({
                    "palette": nbtlib.List[nbtlib.Compound]([modded]),
                }),
            }),
        ]),
    })

    blocks, entities = _purge_mod_data_in_chunk(data)

    assert (blocks, entities) == (1, 0)
    assert str(modded["Name"]) == "minecraft:air"


def test_purge_mod_data_handles_legacy_level_schema() -> None:
    modded = nbtlib.Compound({"Name": nbtlib.String("example:ore")})
    mod_entity = nbtlib.Compound({"id": nbtlib.String("example:mob")})
    level = nbtlib.Compound({
        "Sections": nbtlib.List[nbtlib.Compound]([
            nbtlib.Compound({
                "Palette": nbtlib.List[nbtlib.Compound]([modded]),
            }),
        ]),
        "Entities": nbtlib.List[nbtlib.Compound]([mod_entity]),
    })

    blocks, entities = _purge_mod_data_in_chunk(
        nbtlib.Compound({"Level": level})
    )

    assert (blocks, entities) == (1, 1)


def test_entity_region_scan_does_not_require_chunk_region(tmp_path: Path) -> None:
    entity_file = tmp_path / "entities" / "r.0.0.mca"
    entity_file.parent.mkdir()
    entity_file.write_bytes(b"")

    assert scan_all_entity_regions(tmp_path) == [entity_file]
