from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

from app.controllers.region_delete_controller import (
    RegionDeleteOutcome,
    RegionDeleteRequest,
    RegionDeleteStatus,
)
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


def test_stale_region_delete_outcome_does_not_touch_current_world(
    tmp_path: Path,
) -> None:
    logs: list[tuple[str, str]] = []
    dialogs: list[tuple[str, str]] = []
    tab = RegionTabMixin()
    tab.app = cast(Any, SimpleNamespace(
        log=lambda message, level: logs.append((level, message)),
        warn_dialog=lambda title, message: dialogs.append((title, message)),
        info_dialog=lambda title, message: dialogs.append((title, message)),
        handle_exception=lambda error, title=None: dialogs.append(
            (str(title), str(error))
        ),
        translate=lambda key, default="", **kwargs: default.format(**kwargs),
    ))
    current_world = tmp_path / "current"
    old_world = tmp_path / "old"
    tab.world_session = cast(Any, SimpleNamespace(world_path=current_world))
    tab._world_load_generation = 2
    tab._selected_region_coord = (3, 4)
    outcome = RegionDeleteOutcome(
        request=RegionDeleteRequest(
            world_path=old_world,
            region_path=old_world / "region" / "r.3.4.mca",
            coord=(3, 4),
            generation=1,
        ),
        status=RegionDeleteStatus.SUCCEEDED,
    )

    tab._apply_region_delete_outcome(outcome)

    assert dialogs == []
    assert tab._selected_region_coord == (3, 4)
    assert logs == [
        ("INFO", f"丢弃过期区域删除回调: {outcome.request.region_path}")
    ]
