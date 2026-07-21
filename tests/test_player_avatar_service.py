"""Tests for player avatar profile parsing and face crop (no network)."""
from __future__ import annotations

import base64
import io
import json
import threading
from pathlib import Path
from typing import cast

from PIL import Image

from app.services.player_avatar_service import (
    PlayerAvatarService,
    crop_face_png,
    parse_skin_url_from_profile,
)


def _profile_with_skin(url: str) -> dict:
    textures = {
        "timestamp": 0,
        "profileId": "11111111222233334444555555555555",
        "profileName": "Steve",
        "textures": {
            "SKIN": {"url": url},
        },
    }
    encoded = base64.b64encode(
        json.dumps(textures).encode("utf-8")
    ).decode("ascii")
    return {
        "id": "11111111222233334444555555555555",
        "name": "Steve",
        "properties": [
            {"name": "textures", "value": encoded},
        ],
    }


def test_parse_skin_url_from_profile() -> None:
    url = "https://textures.minecraft.net/texture/abc"
    profile = _profile_with_skin(url)
    assert parse_skin_url_from_profile(profile) == url


def test_parse_skin_url_missing() -> None:
    assert parse_skin_url_from_profile({}) is None
    assert parse_skin_url_from_profile({"properties": []}) is None
    assert parse_skin_url_from_profile({
        "properties": [{"name": "textures", "value": "%%%"}],
    }) is None


def test_crop_face_png_from_synthetic_skin() -> None:
    # 64x64 skin: face region (8,8)-(16,16) solid red, no hat overlay.
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 255))
    for x in range(8, 16):
        for y in range(8, 16):
            img.putpixel((x, y), (255, 0, 0, 255))
    # Transparent hat layer so face stays pure red after composite.
    for x in range(40, 48):
        for y in range(8, 16):
            img.putpixel((x, y), (0, 0, 0, 0))

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    face_bytes = crop_face_png(buf.getvalue(), size=32)
    assert face_bytes.startswith(b"\x89PNG")
    with Image.open(io.BytesIO(face_bytes)) as face:
        assert face.size == (32, 32)
        rgba = face.convert("RGBA")
        pixel = cast(tuple[int, int, int, int], rgba.getpixel((0, 0)))
        assert pixel[0] > 200  # red channel
        center = cast(tuple[int, int, int, int], rgba.getpixel((16, 16)))
        assert center[0] > 200


def test_get_cached_path_reads_disk(tmp_path: Path) -> None:
    service = PlayerAvatarService(cache_dir=tmp_path, enabled=True)
    uuid = "11111111222233334444555555555555"
    path = tmp_path / f"{uuid}.png"
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)
    found = service.get_cached_path(uuid)
    assert found == path
    # memory hit
    assert service.get_cached_path(uuid) == path


def test_disabled_service_skips_fetch(tmp_path: Path) -> None:
    service = PlayerAvatarService(cache_dir=tmp_path, enabled=False)
    results: list[object] = []
    service.load_avatar_async(
        "11111111222233334444555555555555",
        lambda path: results.append(path),
    )
    assert results == [None]


def test_invalid_uuid_callback_none(tmp_path: Path) -> None:
    service = PlayerAvatarService(cache_dir=tmp_path, enabled=True)
    results: list[object] = []
    service.load_avatar_async("not-a-uuid", lambda path: results.append(path))
    assert results == [None]


def test_avatar_fetch_uses_owned_fallback_runtime(
    tmp_path: Path,
    monkeypatch,
) -> None:
    service = PlayerAvatarService(cache_dir=tmp_path, enabled=True)
    fetched = threading.Event()
    worker_names: list[str] = []
    monkeypatch.setattr(
        service,
        "_fetch_and_cache",
        lambda _uuid: worker_names.append(threading.current_thread().name)
        or None,
    )
    try:
        service.load_avatar_async(
            "11111111222233334444555555555555",
            lambda _path: fetched.set(),
        )

        assert fetched.wait(1)
        assert worker_names[0].startswith("mcsavehelper-io-")
    finally:
        service.close()

    assert service._execution_runtime.is_closed is True
