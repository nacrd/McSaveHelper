from app.presenters.mappings_view_state import (
    MappingsViewState,
    dispose_mappings_state,
    set_item_busy,
)


def test_mappings_state_blocks_item_reentry_while_busy() -> None:
    initial = MappingsViewState()
    busy = set_item_busy(initial, True)

    assert initial.can_edit_items is True
    assert busy.item_busy is True
    assert busy.can_edit_items is False
    assert set_item_busy(busy, True) == busy


def test_disposed_mappings_state_rejects_late_item_work() -> None:
    disposed = dispose_mappings_state(set_item_busy(MappingsViewState(), True))

    assert disposed.is_disposed is True
    assert disposed.item_busy is False
    assert disposed.can_edit_items is False
    assert set_item_busy(disposed, True) is disposed
