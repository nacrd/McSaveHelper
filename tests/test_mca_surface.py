from typing import Any, cast

from core.mca.surface import (
    _DECODE_WORKERS,
    _build_sample_jobs,
    _needed_chunks,
    _resize_nearest,
    _sample_coarse_grid,
)


def test_nested_chunk_decode_pool_keeps_a_small_cpu_budget() -> None:
    assert 1 <= _DECODE_WORKERS <= 2


class _Region:
    def has_chunk(self, chunk_x: int, chunk_z: int) -> bool:
        return (chunk_x, chunk_z) in {(0, 0), (31, 31)}


class _View:
    def __init__(self, prefix: str, fail: bool = False) -> None:
        self.prefix = prefix
        self.fail = fail

    def surface_block_id(self, local_x: int, local_z: int) -> str:
        if self.fail:
            raise ValueError("broken chunk")
        return f"{self.prefix}:{local_x},{local_z}"


def test_sample_jobs_cover_region_edges_and_local_coordinates() -> None:
    jobs = _build_sample_jobs(8)

    assert len(jobs) == 64
    assert jobs[0] == (0, 0, 2, 2, 0, 0)
    assert jobs[-1] == (7, 7, 30, 30, 0, 0)
    assert all(0 <= job[4] < 16 and 0 <= job[5] < 16 for job in jobs)


def test_needed_chunks_filters_missing_region_entries() -> None:
    jobs = [
        (0, 0, 0, 0, 1, 1),
        (1, 0, 1, 0, 1, 1),
        (2, 0, 31, 31, 1, 1),
    ]

    assert _needed_chunks(cast(Any, _Region()), jobs) == {(0, 0), (31, 31)}


def test_coarse_sampling_isolates_missing_and_broken_chunks() -> None:
    jobs = [
        (0, 0, 0, 0, 2, 3),
        (1, 0, 1, 0, 4, 5),
        (0, 1, 2, 0, 6, 7),
    ]
    views = {
        (0, 0): _View("stone"),
        (1, 0): _View("broken", fail=True),
    }

    assert _sample_coarse_grid(2, jobs, views) == [
        ["stone:2,3", None],
        [None, None],
    ]


def test_nearest_resize_expands_each_source_cell() -> None:
    source = [["a", "b"], ["c", "d"]]

    assert _resize_nearest(source, 4) == [
        ["a", "a", "b", "b"],
        ["a", "a", "b", "b"],
        ["c", "c", "d", "d"],
        ["c", "c", "d", "d"],
    ]
    assert _resize_nearest(source, 2) == source
