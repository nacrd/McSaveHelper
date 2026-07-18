from core.omni.mod_metadata import detect_mod_metadata


def test_detects_explicit_forge_mod_list_and_loader_version() -> None:
    data = {
        "FML": {
            "ModList": [
                {
                    "ModId": "minecraft",
                    "ModVersion": "1.20.1",
                },
                {
                    "ModId": "forge",
                    "ModVersion": "47.2.0",
                },
                {
                    "ModId": "jei",
                    "ModVersion": "15.3.0",
                    "ModName": "Just Enough Items",
                },
            ]
        }
    }

    metadata = detect_mod_metadata({}, data)

    assert metadata.list_complete is True
    assert metadata.loaders == ("Forge 47.2.0",)
    assert len(metadata.mods) == 1
    assert metadata.mods[0].mod_id == "jei"
    assert metadata.mods[0].name == "Just Enough Items"
    assert metadata.mods[0].version == "15.3.0"


def test_infers_mod_ids_from_enabled_data_packs_without_claiming_completeness() -> None:
    metadata = detect_mod_metadata(
        {},
        {},
        data_packs={
            "enabled": ["vanilla", "mod:sodium", "mod:lithium"],
            "disabled": [],
        },
        server_brands=["fabric"],
    )

    assert metadata.list_complete is False
    assert metadata.loaders == ("Fabric Loader",)
    assert [mod.mod_id for mod in metadata.mods] == ["lithium", "sodium"]


def test_deduplicates_explicit_and_inferred_mod_entries() -> None:
    data = {
        "fml": {
            "nested": {
                "mods": {
                    "example": {
                        "version": "2.0",
                        "displayName": "Example Mod",
                    }
                }
            }
        }
    }

    metadata = detect_mod_metadata(
        {},
        data,
        data_packs={"enabled": ["mod:example"], "disabled": []},
    )

    assert metadata.list_complete is True
    assert metadata.mods[0].mod_id == "example"
    assert metadata.mods[0].name == "Example Mod"
    assert metadata.mods[0].version == "2.0"


def test_vanilla_metadata_has_no_mod_or_loader_evidence() -> None:
    metadata = detect_mod_metadata(
        {},
        {},
        data_packs={"enabled": ["vanilla"], "disabled": []},
        server_brands=["vanilla"],
    )

    assert metadata.mods == ()
    assert metadata.loaders == ()
    assert metadata.list_complete is False
