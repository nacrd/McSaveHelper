import base64

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
