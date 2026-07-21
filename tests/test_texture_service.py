import hashlib
import io
import json
import threading
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Iterator

from core.texture import client_jar
from core.texture.block_guess import (
    guess_is_block,
    resolve_texture_resource_key,
)
from core.texture.client_jar import ClientJarInfo
from app.services.texture_service import TextureService


class _Response:
    def __init__(
        self,
        status_code: int = 200,
        json_data: Any = None,
        chunks: tuple[bytes, ...] = (),
    ) -> None:
        self.status_code = status_code
        self._json_data = json_data
        self._chunks = chunks

    def json(self) -> Any:
        return self._json_data

    def iter_content(self, chunk_size: int) -> Iterator[bytes]:
        del chunk_size
        return iter(self._chunks)


def _zip_bytes() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("assets/minecraft/example.txt", "ok")
    return buffer.getvalue()


def test_resolve_latest_client_jar_reads_manifest_and_metadata() -> None:
    responses = {
        client_jar.ASSET_INDEX_URL: {
            "latest": {"release": "1.21"},
            "versions": [{"id": "1.21", "url": "metadata"}],
        },
        "metadata": {
            "downloads": {
                "client": {"url": "client", "sha1": "abc", "size": 42},
            },
        },
    }

    def get_json(url: str, warning: str) -> dict[str, Any]:
        del warning
        return responses[url]

    assert client_jar.resolve_latest_client_jar(get_json) == ClientJarInfo(
        "1.21",
        "client",
        "abc",
        42,
    )


def test_cached_jar_validation_accepts_match_and_removes_mismatch(
    tmp_path: Path,
) -> None:
    jar_path = tmp_path / "client.jar"
    jar_path.write_bytes(b"valid")
    expected = hashlib.sha1(b"valid").hexdigest()

    assert client_jar.is_cached_jar_valid(jar_path, expected) is True
    assert jar_path.exists()
    assert client_jar.is_cached_jar_valid(jar_path, "bad") is False
    assert not jar_path.exists()


def test_import_textures_from_jars_bulk_extracts_pngs(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    cache_dir = tmp_path / "cache"
    jar_dir = tmp_path / "jars"
    cache_dir.mkdir()
    jar_dir.mkdir()

    # Minimal valid-looking PNG signature payload.
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
    jar_path = jar_dir / "pack.jar"
    with zipfile.ZipFile(jar_path, "w") as archive:
        archive.writestr("assets/minecraft/textures/item/apple.png", png)
        archive.writestr("assets/examplemod/textures/item/widget.png", png)
        archive.writestr("assets/minecraft/lang/zh_cn.json", "{}")

    service = TextureService()
    monkeypatch.setattr(service, "_cache_dir", cache_dir)
    # Avoid network / local MC discovery side effects.
    monkeypatch.setattr(service, "find_minecraft_jar", lambda: None)
    monkeypatch.setattr(service, "_download_client_jar", lambda: None)

    result = service.import_textures_from_jars([jar_path])
    assert result.extracted == 2
    assert result.jars == 1
    assert (cache_dir / "item" / "apple.png").is_file()
    assert (cache_dir / "item" / "widget.png").is_file()
    # Registered jar remains available for later lookups.
    assert service._minecraft_jar == jar_path or jar_path in service._extra_jars


def test_stream_client_jar_commits_temp_file_atomically(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    payload = _zip_bytes()
    monkeypatch.setattr(
        client_jar.requests,
        "get",
        lambda *_args, **_kwargs: _Response(chunks=(payload[:10], b"", payload[10:])),
    )
    target = tmp_path / "client.jar"
    info = ClientJarInfo(
        "1.21",
        "client",
        hashlib.sha1(payload).hexdigest(),
        len(payload),
    )

    assert client_jar.stream_client_jar(info, target) is True
    assert target.read_bytes() == payload
    assert not list(tmp_path.glob(".*.part"))


def test_stream_client_jar_rejects_http_failure(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        client_jar.requests,
        "get",
        lambda *_args, **_kwargs: _Response(status_code=503),
    )
    target = tmp_path / "client.jar"

    assert client_jar.stream_client_jar(
        ClientJarInfo("1.21", "client", None, 0),
        target,
    ) is False
    assert not target.exists()


def test_stream_client_jar_rejects_invalid_integrity(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        client_jar.requests,
        "get",
        lambda *_args, **_kwargs: _Response(chunks=(b"not-a-jar",)),
    )
    target = tmp_path / "client.jar"

    assert client_jar.stream_client_jar(
        ClientJarInfo("1.21", "client", "wrong", 9),
        target,
    ) is False
    assert not target.exists()
    assert not list(tmp_path.glob(".*.part"))


def test_find_local_jar_uses_release_time_not_version_string(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(client_jar.platform, "system", lambda: "Windows")
    monkeypatch.setenv("APPDATA", str(tmp_path))
    versions = tmp_path / ".minecraft" / "versions"
    for version, release_time in (
        ("1.9", "2016-02-29T00:00:00Z"),
        ("1.21", "2024-06-13T00:00:00Z"),
    ):
        version_dir = versions / version
        version_dir.mkdir(parents=True)
        (version_dir / f"{version}.jar").write_bytes(_zip_bytes())
        (version_dir / f"{version}.json").write_text(
            json.dumps({"releaseTime": release_time}),
            encoding="utf-8",
        )

    assert client_jar.find_local_minecraft_jar() == versions / "1.21" / "1.21.jar"


def test_texture_cache_rejects_item_id_path_traversal(tmp_path: Path) -> None:
    service = TextureService()
    service._cache_dir = tmp_path / "cache"
    service._cache_dir.mkdir()
    outside = tmp_path / "review_probe.png"
    outside.write_bytes(b"\x89PNG\r\n\x1a\nprobe")

    assert service.get_texture_base64("minecraft:../../../review_probe") is None


def test_client_jar_download_is_single_flight(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    service = TextureService()
    service._jar_cache_dir = tmp_path
    target = tmp_path / "client.jar"
    entered = threading.Event()
    release = threading.Event()
    calls = 0
    monkeypatch.setattr(service, "find_minecraft_jar", lambda: None)

    def download() -> Path:
        nonlocal calls
        calls += 1
        entered.set()
        release.wait(timeout=2)
        target.write_bytes(_zip_bytes())
        return target

    monkeypatch.setattr(service, "_download_client_jar", download)
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(service._find_or_get_jar)
        assert entered.wait(timeout=2)
        second = executor.submit(service._find_or_get_jar)
        release.set()
        assert first.result() == target
        assert second.result() == target

    assert calls == 1


def test_block_guess_and_resource_resolution_are_pure() -> None:
    assert guess_is_block("stone") is True
    assert guess_is_block("diamond_sword") is False
    assert resolve_texture_resource_key(
        "stone",
        prefer_block=True,
        asset_keys={"minecraft/textures/item/stone.png": "hash"},
    ) == "textures/item/stone.png"
    assert resolve_texture_resource_key(
        "diamond_sword",
        prefer_block=False,
        asset_keys=None,
    ) == "textures/item/diamond_sword.png"


def test_async_texture_load_uses_owned_fallback_runtime(
    monkeypatch: Any,
) -> None:
    service = TextureService()
    loaded = threading.Event()
    worker_names: list[str] = []
    monkeypatch.setattr(
        service,
        "get_texture_base64",
        lambda item_id: worker_names.append(threading.current_thread().name)
        or f"data:{item_id}",
    )
    try:
        service.load_textures_async(
            ["minecraft:stone"],
            lambda _item_id, _uri: loaded.set(),
        )

        assert loaded.wait(1)
        assert worker_names[0].startswith("mcsavehelper-io-")
    finally:
        service.close()

    assert service._execution_runtime.is_closed is True
