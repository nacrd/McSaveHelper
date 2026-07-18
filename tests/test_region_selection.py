from core.mca.region_selection import format_region_selection


def test_format_region_selection_includes_negative_bounds() -> None:
    text = format_region_selection((-1, 2))

    assert "r.-1.2.mca" in text
    assert "区块 X-32~-1 Z64~95" in text
    assert "方块 X-512~-1 Z1024~1535" in text


def test_format_region_selection_supports_chunk_and_block_detail() -> None:
    chunk = format_region_selection(
        (1, 2),
        {
            "level": "chunk",
            "chunk_coord": (33, 65),
            "block_range": "X528~543 Z1040~1055",
        },
    )
    block = format_region_selection(
        (1, 2),
        {
            "level": "block",
            "chunk_coord": (33, 65),
            "block_range": "X528~543 Z1040~1055",
        },
    )

    assert chunk.startswith("区块 (33, 65)")
    assert block.startswith("区块内 (33, 65)")
