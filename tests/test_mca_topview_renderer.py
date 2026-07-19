"""Top-view cache completeness tests."""
from pathlib import Path
from typing import Any

from core.mca import topview_renderer


def test_partial_mod_tile_is_returned_but_not_persisted(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    region_path = tmp_path / "r.0.0.mca"
    region_path.write_bytes(b"placeholder")
    stored = []

    def partial_grid(_path, tile_size, **kwargs):
        kwargs["status_out"].append(False)
        return [[(30, 40, 50)] * tile_size for _ in range(tile_size)]

    monkeypatch.setattr(topview_renderer, "_load_cached_tile", lambda *_args: None)
    monkeypatch.setattr(topview_renderer, "_sample_surface_grid", partial_grid)
    monkeypatch.setattr(
        topview_renderer,
        "_store_cached_tile",
        lambda *args: stored.append(args),
    )

    status = []
    png = topview_renderer.render_region_topview(
        region_path,
        tile_size=32,
        status_out=status,
    )

    assert png is not None
    assert status == [False]
    assert stored == []
