from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

from app.ui.views.explorer.region_tab import RegionTabMixin


def test_current_region_dir_rejects_missing_mapping(tmp_path: Path) -> None:
    tab = RegionTabMixin()
    tab._current_dimension = "overworld"
    tab._dimension_region_dirs = {}

    assert tab._get_current_region_dir() is None

    region_dir = tmp_path / "region"
    tab._dimension_region_dirs["overworld"] = str(region_dir)
    assert tab._get_current_region_dir() == region_dir


def test_origin_region_is_treated_as_selected() -> None:
    warnings = []
    tab = RegionTabMixin()
    tab.app = cast(Any, SimpleNamespace(
        warn_dialog=lambda _title, message: warnings.append(message),
        handle_exception=lambda *_args, **_kwargs: None,
    ))
    tab.world_session = cast(Any, object())
    tab._selected_region_coord = (0, 0)
    tab._current_dimension = "overworld"
    tab._dimension_region_dirs = {}

    tab._fill_selected_region_for_nbt()

    assert warnings == ["当前维度没有可用的 region 目录。"]
