from pathlib import Path

from app.services.world_compare_service import WorldCompareService


def test_region_comparison_keeps_same_coordinates_in_each_dimension(
    tmp_path: Path,
    monkeypatch,
) -> None:
    left = tmp_path / "left"
    right = tmp_path / "right"
    paths = []
    for world, overworld, nether in (
        (left, b"same", b"left-nether"),
        (right, b"same", b"right-nether"),
    ):
        for relative, content in (
            (Path("region/r.0.0.mca"), overworld),
            (Path("DIM-1/region/r.0.0.mca"), nether),
        ):
            path = world / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            paths.append(path)

    monkeypatch.setattr(
        "app.services.world_compare_service.scan_all_regions",
        lambda world: [path for path in paths if path.is_relative_to(world)],
    )

    compared = WorldCompareService()._compare_regions(left, right)

    assert [item.name for item in compared] == [
        "DIM-1/region/r.0.0.mca",
        "region/r.0.0.mca",
    ]
    assert [item.same for item in compared] == [False, True]
