from app.services.item_service import ItemService


def test_delete_custom_item_mapping_removes_non_vanilla_mapping():
    service = ItemService()
    item_id = "testmod:custom_item"

    service.set_item_mapping(item_id, "Custom Item")

    assert service.get_custom_item_mappings()[item_id] == "Custom Item"

    assert service.delete_item_mapping(item_id) is True
    assert item_id not in service.get_custom_item_mappings()


def test_delete_custom_item_mapping_restores_vanilla_override():
    service = ItemService()
    item_id = "minecraft:diamond"
    original_name = service.get_item_name(item_id)

    service.set_item_mapping(item_id, "Overridden Diamond")
    assert service.get_custom_item_mappings()[item_id] == "Overridden Diamond"

    assert service.delete_item_mapping(item_id) is True
    assert item_id not in service.get_custom_item_mappings()
    assert service.get_item_name(item_id) == original_name


def test_delete_custom_item_mapping_ignores_missing_mapping():
    service = ItemService()

    assert service.delete_item_mapping("testmod:missing") is False
