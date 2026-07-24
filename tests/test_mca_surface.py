from pathlib import Path
from typing import Any, cast

import core.mca.surface as surface_module
from core.mca.surface import (
    _DECODE_WORKERS,
    _CHUNK_LRU_MAX,
    _coarse_edge,
    _build_sample_jobs,
    _decode_one,
    _needed_chunks,
    _resize_nearest,
    _downsample_surface_values,
    _sample_column,
    _sample_coarse_grid,
    _shade_color,
    _load_chunk_views,
    _lru_epoch,
    _lru_get,
    _lru_merge,
    chunk_decode_cache_evictions,
    chunk_decode_cache_hits,
    chunk_decode_cache_misses,
    clear_chunk_decode_cache,
    invalidate_chunk_decode_cache_for_world,
)


def test_nested_chunk_decode_pool_keeps_a_small_cpu_budget() -> None:
    assert 1 <= _DECODE_WORKERS <= 2
    assert _CHUNK_LRU_MAX == 4096


def test_chunk_decode_cache_reports_real_hit_and_miss_counts() -> None:
    clear_chunk_decode_cache()
    key = ("region", 1, 2, 0, 0, "")
    assert _lru_get(key)[0] is False
    _lru_merge(key, {(0, 0): "minecraft:stone"}, _lru_epoch())
    assert _lru_get(key)[0] is True
    assert chunk_decode_cache_hits() == 1
    assert chunk_decode_cache_misses() == 1
    assert chunk_decode_cache_evictions() == 0
    clear_chunk_decode_cache()


def test_chunk_decode_cache_accounts_for_empty_sample_merges() -> None:
    clear_chunk_decode_cache()
    key = ("empty-region", 1, 2, 0, 0, "")

    _lru_merge(key, {}, _lru_epoch())
    first_bytes = surface_module.chunk_decode_cache_bytes()
    samples = {(0, 0): "minecraft:stone"}
    _lru_merge(key, samples, _lru_epoch())

    assert first_bytes == surface_module._estimate_surface_samples_bytes({})
    assert (
        surface_module.chunk_decode_cache_bytes()
        == surface_module._estimate_surface_samples_bytes(samples)
    )
    clear_chunk_decode_cache()


def test_chunk_decode_cache_invalidation_is_scoped_to_one_world(tmp_path) -> None:
    clear_chunk_decode_cache()
    first_world = tmp_path / "first"
    second_world = tmp_path / "second"
    first_key = (str(first_world / "region" / "r.0.0.mca"), 1, 2, 0, 0, "")
    second_key = (
        str(second_world / "region" / "r.0.0.mca"),
        1,
        2,
        0,
        0,
        "",
    )
    _lru_merge(first_key, {(0, 0): "minecraft:stone"}, _lru_epoch())
    _lru_merge(second_key, {(0, 0): "minecraft:dirt"}, _lru_epoch())

    assert invalidate_chunk_decode_cache_for_world(first_world) == 1
    assert _lru_get(first_key)[0] is False
    assert _lru_get(second_key)[0] is True
    clear_chunk_decode_cache()


def test_world_invalidation_rejects_inflight_decode_without_cached_entry(
    tmp_path: Path,
) -> None:
    clear_chunk_decode_cache()
    world = tmp_path / "world"
    key = (str(world / "region" / "r.0.0.mca"), 1, 2, 0, 0, "")
    decode_epoch = _lru_epoch()

    assert invalidate_chunk_decode_cache_for_world(world) == 0
    _lru_merge(key, {(0, 0): "minecraft:stone"}, decode_epoch)

    assert _lru_get(key)[0] is False
    clear_chunk_decode_cache()


def test_topview_chunk_decode_uses_world_surface_view(monkeypatch) -> None:
    marker = object()
    calls = []

    class _Region:
        def read_chunk(self, _chunk_x: int, _chunk_z: int) -> object:
            return marker

    class _Blocks:
        def surface_sample(
            self,
            _local_x: int,
            _local_z: int,
        ) -> tuple[str, int, int]:
            return "minecraft:stone", 64, 0

    def fake_get_blocks(chunk: object) -> _Blocks:
        calls.append(chunk)
        return _Blocks()

    monkeypatch.setattr(surface_module, "get_world_surface_chunk_blocks", fake_get_blocks)

    key, samples = _decode_one(
        cast(Any, _Region()),
        2,
        3,
        [(0, 0)],
    )

    assert calls == [marker]
    assert key == (2, 3)
    assert samples[(0, 0)] == ("minecraft:stone", 64, 0)


def test_topview_chunk_decode_keeps_biome_and_transparent_stratum(
    monkeypatch,
) -> None:
    class _RegionWithBiome:
        def read_chunk(self, _chunk_x: int, _chunk_z: int) -> object:
            return object()

    class _BiomeBlocks:
        def surface_sample(self, _local_x: int, _local_z: int):
            return "minecraft:short_grass", 65

        def surface_strata(self, _local_x: int, _local_z: int):
            return (
                ("minecraft:short_grass", 65),
                ("minecraft:grass_block", 64),
            )

        def biome_at(self, _local_x: int, _height: int, _local_z: int) -> str:
            return "minecraft:forest"

        def block_id_at(self, _local_x: int, _height: int, _local_z: int) -> str:
            return "minecraft:dirt"

    monkeypatch.setattr(
        surface_module,
        "get_world_surface_chunk_blocks",
        lambda _chunk: _BiomeBlocks(),
    )

    _key, samples = _decode_one(
        cast(Any, _RegionWithBiome()),
        0,
        0,
        [(2, 3)],
    )

    assert samples[(2, 3)] == (
        "minecraft:grass_block",
        64,
        0,
        "minecraft:forest",
        "minecraft:short_grass",
        0.42,
    )


def test_topview_sampling_keeps_original_sampling_quality() -> None:
    assert _coarse_edge(16) == 8
    assert _coarse_edge(32) == 32
    assert _coarse_edge(64) == 64
    assert _coarse_edge(128) == 128
    assert _coarse_edge(256) == 256
    assert _coarse_edge(512) == 512


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


class _ReportedWaterDepth:
    def surface_sample(
        self,
        _local_x: int,
        _local_z: int,
    ) -> tuple[str, int, int]:
        return "minecraft:water", 64, 3

    def block_id_at(self, _local_x: int, _height: int, _local_z: int) -> str:
        return "minecraft:stone"


def test_sample_jobs_cover_region_edges_and_local_coordinates() -> None:
    jobs = _build_sample_jobs(8)

    assert len(jobs) == 64
    assert jobs[0] == (0, 0, 2, 2, 0, 0)
    assert jobs[-1] == (7, 7, 30, 30, 0, 0)
    assert all(0 <= job[4] < 16 and 0 <= job[5] < 16 for job in jobs)


def test_column_sampling_preserves_reported_water_depth() -> None:
    assert _sample_column(_ReportedWaterDepth(), 2, 3) == (
        "minecraft:water",
        64,
        3,
    )


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
        for edge in (8, 32, 64, 128, 256):
            jobs = _build_sample_jobs(edge)
            _load_chunk_views(
                region,
                _needed_chunks(region, jobs),
                "nested-region",
                1,
                jobs,
                decode_workers=1,
            )

        assert len(calls) >= 1024
        assert len(set(calls)) == 1024
    finally:
        clear_chunk_decode_cache()


def test_leaf_lod_does_not_expand_normal_lod_chunk_sampling(monkeypatch) -> None:
    sample_counts = []

    def fake_decode(_region, chunk_x, chunk_z, samples):
        sample_counts.append(len(samples))
        return (
            (chunk_x, chunk_z),
            {position: "minecraft:stone" for position in samples},
        )

    monkeypatch.setattr(surface_module, "_decode_one", fake_decode)
    region = cast(Any, _FullRegion())
    try:
        clear_chunk_decode_cache()
        jobs = _build_sample_jobs(64)
        _load_chunk_views(
            region,
            _needed_chunks(region, jobs),
            "normal-lod",
            1,
            jobs,
            decode_workers=1,
        )
        assert sample_counts
        # The focused cache merges the staggered 64/128/256 grids, but must
        # remain far below the 256 columns required by a full 512 leaf tile.
        assert max(sample_counts) <= 96

        sample_counts.clear()
        clear_chunk_decode_cache()
        jobs = _build_sample_jobs(512)
        _load_chunk_views(
            region,
            _needed_chunks(region, jobs),
            "leaf-lod",
            1,
            jobs,
            decode_workers=1,
        )
        assert max(sample_counts) == 256
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


def test_detail_samples_are_area_reduced_in_their_own_quadrants() -> None:
    source = [
        [("a", 1, 0), ("a", 1, 0), ("b", 2, 0), ("b", 2, 0)],
        [("a", 1, 0), ("a", 1, 0), ("b", 2, 0), ("b", 2, 0)],
        [("c", 3, 0), ("c", 3, 0), ("d", 4, 0), ("d", 4, 0)],
        [("c", 3, 0), ("c", 3, 0), ("d", 4, 0), ("d", 4, 0)],
    ]

    assert _downsample_surface_values(source, 2) == [
        [("a", 1, 0), ("b", 2, 0)],
        [("c", 3, 0), ("d", 4, 0)],
    ]


def test_relief_shading_preserves_material_color_but_changes_brightness() -> None:
    base = (80, 140, 60)

    assert _shade_color(base, 0.75) == (60, 105, 45)
    assert _shade_color(base, 1.25) == (100, 175, 75)


def test_surface_colors_use_local_height_gradient(monkeypatch) -> None:
    samples = [
        [("minecraft:grass_block", 60, 0)] * 3,
        [
            ("minecraft:grass_block", 60, 0),
            ("minecraft:grass_block", 72, 0),
            ("minecraft:grass_block", 72, 0),
        ],
        [("minecraft:grass_block", 72, 0)] * 3,
    ]
    monkeypatch.setattr(
        surface_module,
        "sample_region_surface_samples",
        lambda *_args, **_kwargs: samples,
    )

    colors = surface_module.sample_region_surface_colors(
        "ignored.mca",
        tile_size=3,
        color_for_block=lambda _name: (100, 100, 100),
    )

    assert colors is not None
    assert colors[1][1] != colors[0][0]


def test_surface_colors_pass_biome_and_blend_transparent_overlay(monkeypatch) -> None:
    samples = [[(
        "minecraft:grass_block",
        64,
        0,
        "minecraft:forest",
        "minecraft:short_grass",
        0.5,
    )]]
    calls = []
    monkeypatch.setattr(
        surface_module,
        "sample_region_surface_samples",
        lambda *_args, **_kwargs: samples,
    )

    def color_for_surface(name: str, biome: str | None):
        calls.append((name, biome))
        if name.endswith("short_grass"):
            return 0, 200, 0
        return 100, 100, 100

    colors = surface_module.sample_region_surface_colors(
        "ignored.mca",
        tile_size=1,
        color_for_surface=color_for_surface,
    )

    assert calls == [
        ("minecraft:grass_block", "minecraft:forest"),
        ("minecraft:short_grass", "minecraft:forest"),
    ]
    assert colors == [[(50, 150, 50)]]
