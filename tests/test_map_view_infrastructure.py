import base64
import threading

from app.services.cache_registry import CacheRegistry
from app.ui.views.explorer.map.rebuild_scheduler import RebuildScheduler
from app.ui.views.explorer.map.tile_source_cache import TileSourceCache


def test_tile_source_cache_reuses_generation_and_invalidates() -> None:
    cache = TileSourceCache()
    calls = []

    def load(coord: tuple[int, int]) -> bytes:
        calls.append(coord)
        return f"{coord[0]}:{coord[1]}".encode()

    first = cache.get((1, 2), generation=1, load_tile=load)
    again = cache.get((1, 2), generation=1, load_tile=load)
    refreshed = cache.get((1, 2), generation=2, load_tile=load)

    assert first == base64.b64encode(b"1:2").decode("ascii")
    assert again == first
    assert refreshed == first
    assert calls == [(1, 2), (1, 2)]


def test_rebuild_scheduler_requests_immediately_only_while_active() -> None:
    calls = []
    active = True
    scheduler = RebuildScheduler(
        lambda: calls.append("rebuild"),
        is_active=lambda: active,
        min_interval=0.0,
    )

    scheduler.schedule()
    active = False
    scheduler.schedule()
    scheduler.cancel()

    assert calls == ["rebuild"]


def test_tile_source_cache_evicts_by_bytes_without_changing_generation() -> None:
    cache = TileSourceCache()
    cache.MAX_BYTES = 12

    cache.get((0, 0), generation=1, load_tile=lambda _: b"123456789")
    cache.get((1, 0), generation=1, load_tile=lambda _: b"abcdefgh")

    assert (0, 0) not in cache._sources
    assert (1, 0) in cache._sources
    assert cache._generation == 1


def test_tile_source_cache_refreshes_one_coord_when_revision_changes() -> None:
    cache = TileSourceCache()
    payload = b"preview"

    first = cache.get(
        (1, 2),
        generation=4,
        version=1,
        load_tile=lambda _coord: payload,
    )
    payload = b"detail"
    detail = cache.get(
        (1, 2),
        generation=4,
        version=2,
        load_tile=lambda _coord: payload,
    )

    assert first == base64.b64encode(b"preview").decode("ascii")
    assert detail == base64.b64encode(b"detail").decode("ascii")
    assert detail is not None
    assert cache._bytes == len(detail)


def test_tile_source_cache_unregisters_application_budget_on_close() -> None:
    registry = CacheRegistry(budget_bytes=TileSourceCache.MAX_BYTES)
    cache = TileSourceCache(registry)

    assert [item.name for item in registry.stats().regions] == [cache._name]

    cache.close()
    cache.close()

    assert registry.stats().regions == ()


def test_tile_source_cache_clear_does_not_resurrect_inflight_value() -> None:
    cache = TileSourceCache()
    started = threading.Event()
    release = threading.Event()

    def load(_coord: tuple[int, int]) -> bytes:
        started.set()
        release.wait(timeout=1.0)
        return b"tile"

    worker = threading.Thread(
        target=lambda: cache.get((0, 0), generation=1, load_tile=load),
    )
    worker.start()
    assert started.wait(timeout=1.0)

    cache.clear()
    release.set()
    worker.join(timeout=1.0)

    assert not worker.is_alive()
    assert cache.stats().entries == 0


def test_tile_source_cache_does_not_reload_after_close() -> None:
    cache = TileSourceCache()
    cache.close()

    loaded = cache.get(
        (0, 0),
        generation=1,
        load_tile=lambda _coord: b"unexpected",
    )

    assert loaded is None
    assert cache.stats().entries == 0
