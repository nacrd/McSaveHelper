import hashlib
from pathlib import Path
from typing import Any, Iterator

from core.texture import client_jar
from core.texture.block_guess import (
    guess_is_block,
    resolve_texture_resource_key,
)
from core.texture.client_jar import ClientJarInfo


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


def test_stream_client_jar_commits_temp_file_atomically(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        client_jar.requests,
        "get",
        lambda *_args, **_kwargs: _Response(chunks=(b"abc", b"", b"def")),
    )
    target = tmp_path / "client.jar"
    info = ClientJarInfo("1.21", "client", None, 6)

    assert client_jar.stream_client_jar(info, target) is True
    assert target.read_bytes() == b"abcdef"
    assert not target.with_suffix(".jar.part").exists()


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
