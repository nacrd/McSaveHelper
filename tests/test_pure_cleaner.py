import nbtlib

from core.pure_cleaner import _purge_mod_data_in_chunk


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
