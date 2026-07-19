from typing import Any, cast

import core.mca.surface as surface_module
from core.mca.surface import (
    _DECODE_WORKERS,
    _CHUNK_LRU_MAX,
    _coarse_edge,
    _build_sample_jobs,
    _needed_chunks,
    _resize_nearest,
    _sample_coarse_grid,
    _load_chunk_views,
    clear_chunk_decode_cache,
)


def test_nested_chunk_decode_pool_keeps_a_small_cpu_budget() -> None:
    assert 1 <= _DECODE_WORKERS <= 2
    assert _CHUNK_LRU_MAX == 4096


def test_topview_sampling_keeps_original_sampling_quality() -> None:
    assert _coarse_edge(32) == 16
    assert _coarse_edge(64) == 24
    assert _coarse_edge(128) == 32


class _Region:
    def has_chunk(self, chunk_x: int, chunk_z: int) -> bool:
        return (chunk_x, chunk_z) in {(0, 0), (31, 31)}


class _FullRegion:
    def has_chunk(self, _chunk_x: int, _chunk_z: int) -> bool:
        return True


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


def test_lod_upgrades_decode_each_sampled_chunk_only_once(monkeypatch) -> None:
    calls = []

    def fake_decode(_region, chunk_x, chunk_z, samples):
        calls.append((chunk_x, chunk_z))
        return (
            (chunk_x, chunk_z),
            {position: "minecraft:stone" for position in samples},
        )

    clear_chunk_decode_cache()
    monkeypatch.setattr(surface_module, "_decode_one", fake_decode)
    region = cast(Any, _FullRegion())
    try:
        for edge in (8, 16, 24, 32):
            jobs = _build_sample_jobs(edge)
            _load_chunk_views(
                region,
                _needed_chunks(region, jobs),
                "nested-region",
                1,
                jobs,
                decode_workers=1,
            )

        assert len(calls) == 1024
        assert len(set(calls)) == 1024
    finally:
        clear_chunk_decode_cache()


def test_mcc_signature_invalidates_only_the_changed_chunk(monkeypatch) -> None:
    calls = []

    def fake_decode(_region, chunk_x, chunk_z, samples):
        calls.append((chunk_x, chunk_z))
        return (
            (chunk_x, chunk_z),
            {position: "minecraft:stone" for position in samples},
        )

    clear_chunk_decode_cache()
    monkeypatch.setattr(surface_module, "_decode_one", fake_decode)
    region = cast(Any, _FullRegion())
    jobs = _build_sample_jobs(8)
    needed = _needed_chunks(region, jobs)
    try:
        _load_chunk_views(
            region,
            needed,
            "mcc-region",
            1,
            jobs,
            decode_workers=1,
            external_signatures={(2, 2): "old"},
        )
        first_count = len(calls)

        _load_chunk_views(
            region,
            needed,
            "mcc-region",
            1,
            jobs,
            decode_workers=1,
            external_signatures={(2, 2): "new"},
        )

        assert first_count == 64
        assert len(calls) == first_count + 1
        assert calls[-1] == (2, 2)
    finally:
        clear_chunk_decode_cache()


def test_sample_jobs_keep_evenly_spaced_centers() -> None:
    jobs = _build_sample_jobs(24)

    assert len(jobs) == 576
    assert jobs[0] == (0, 0, 0, 0, 10, 10)
    assert jobs[23] == (23, 0, 31, 0, 5, 10)
    assert jobs[-1] == (23, 23, 31, 31, 5, 5)


def test_sequential_decode_stops_at_cancellation_boundary(monkeypatch) -> None:
    calls = []

    def fake_decode(_region, chunk_x, chunk_z, samples):
        calls.append((chunk_x, chunk_z))
        return ((chunk_x, chunk_z), {samples[0]: "minecraft:stone"})

    clear_chunk_decode_cache()
    monkeypatch.setattr(surface_module, "_decode_one", fake_decode)
    region = cast(Any, _FullRegion())
    jobs = _build_sample_jobs(8)
    try:
        _load_chunk_views(
            region,
            _needed_chunks(region, jobs),
            "cancelled-region",
            1,
            jobs,
            cancel_check=lambda: len(calls) >= 3,
            decode_workers=1,
        )

        assert len(calls) == 3
    finally:
        clear_chunk_decode_cache()


def test_one_bad_chunk_isolated_without_discarding_other_samples(monkeypatch) -> None:
    calls = []

    def fake_decode(_region, chunk_x, chunk_z, samples):
        calls.append((chunk_x, chunk_z))
        if (chunk_x, chunk_z) == (1, 1):
            raise ValueError("unsupported mod palette")
        return ((chunk_x, chunk_z), {samples[0]: "minecraft:stone"})

    clear_chunk_decode_cache()
    monkeypatch.setattr(surface_module, "_decode_one", fake_decode)
    region = cast(Any, _FullRegion())
    jobs = [
        (0, 0, 0, 0, 1, 1),
        (1, 0, 1, 1, 1, 1),
    ]
    failed = set()
    try:
        views = _load_chunk_views(
            region,
            {(0, 0), (1, 1)},
            "partial-region",
            1,
            jobs,
            decode_workers=1,
            failed_chunks=failed,
        )

        assert (1, 1) in failed
        assert views[(0, 0)] is not None
        assert views.get((1, 1)) is None
    finally:
        clear_chunk_decode_cache()


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
