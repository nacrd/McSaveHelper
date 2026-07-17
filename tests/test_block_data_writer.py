from app.services.block_data_service import BlockDataService


class _FixedArray:
    def __init__(self, values: list[int]) -> None:
        self.values = values

    def __len__(self) -> int:
        return len(self.values)

    def __setitem__(self, index: int, value: int) -> None:
        self.values[index] = value


def test_existing_fixed_array_is_updated_in_place() -> None:
    current = _FixedArray([1, 2, 3])

    updated = BlockDataService._update_existing_data(current, [4, 5, 6])

    assert updated is True
    assert current.values == [4, 5, 6]


def test_existing_resizable_array_changes_length_in_place() -> None:
    current = [1]

    updated = BlockDataService._update_existing_data(current, [2, 3, 4])

    assert updated is True
    assert current == [2, 3, 4]


def test_immutable_existing_data_uses_typed_replacement() -> None:
    block_states = {"data": (1, 2)}

    BlockDataService()._set_block_states_data(block_states, [3, 4, 5])

    assert [int(value) for value in block_states["data"]] == [3, 4, 5]


def test_plain_array_fallback_handles_mapping() -> None:
    block_states = {}

    BlockDataService._set_plain_long_array(block_states, [7, 8])

    assert block_states == {"data": [7, 8]}
