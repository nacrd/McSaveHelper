from typing import cast

from app.services.item_service import ItemService
from app.services.texture_service import TextureService
from app.ui.views.explorer.equipment_preview import EquipmentPreview
from app.ui.views.explorer.inventory_grid import InventoryGrid


def test_item_components_keep_injected_services() -> None:
    item_service = ItemService()
    texture_service = cast(TextureService, object())

    inventory = InventoryGrid(item_service, texture_service)
    equipment = EquipmentPreview(item_service, texture_service)

    assert inventory._item_service is item_service
    assert inventory._texture_service is texture_service
    assert equipment._item_service is item_service
    assert equipment._texture_service is texture_service
