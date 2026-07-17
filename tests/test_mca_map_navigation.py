from core.mca.map_navigation import McaMapNavigator


def test_map_navigator_builds_region_and_chunk_notifications() -> None:
    navigator = McaMapNavigator()
    sizes = {(-2, 3): 4096}

    region_notice = navigator.select_region((-2, 3), sizes)
    assert region_notice.region == (-2, 3)
    assert region_notice.size == 4096
    assert region_notice.detail == {
        "level": "region",
        "block_range": "X -1024~-513, Z 1536~2047",
    }

    chunk_notice = navigator.select_chunk((-33, 127), sizes, "block")
    assert chunk_notice.region == (-2, 3)
    assert chunk_notice.detail == {
        "level": "block",
        "chunk_coord": (-33, 127),
        "block_range": "X -528~-513, Z 2032~2047",
    }


def test_map_navigator_reports_transition_direction_and_steps_back() -> None:
    navigator = McaMapNavigator()
    sizes = {(0, 0): 10}
    navigator.select_chunk((2, 3), sizes, "block")

    transition = navigator.transition_to("chunk")
    assert transition.changed is True
    assert transition.going_out is True
    assert transition.going_deeper is False

    region_notice = navigator.step_back(sizes)
    assert region_notice.detail["level"] == "region"
    assert navigator.selection.chunk is None

    world_notice = navigator.step_back(sizes)
    assert world_notice.region is None
    assert world_notice.detail == {"level": "world"}
