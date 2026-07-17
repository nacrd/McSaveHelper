import hashlib
from pathlib import Path
from typing import Any, Iterator

from app.services import texture_service
from app.services.texture_service import ClientJarInfo, TextureService


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


def test_resolve_latest_client_jar_reads_manifest_and_metadata(
    monkeypatch: Any,
) -> None:
    responses = {
        texture_service._ASSET_INDEX_URL: _Response(json_data={
            "latest": {"release": "1.21"},
            "versions": [{"id": "1.21", "url": "metadata"}],
        }),
        "metadata": _Response(json_data={
            "downloads": {
                "client": {"url": "client", "sha1": "abc", "size": 42},
            },
        }),
    }
    monkeypatch.setattr(
        texture_service.requests,
        "get",
        lambda url, **_kwargs: responses[url],
    )

    assert TextureService()._resolve_latest_client_jar() == ClientJarInfo(
        "1.21",
        "client",
        "abc",
        42,
    )


def test_cached_jar_validation_accepts_match_and_removes_mismatch(
    tmp_path: Path,
) -> None:
    service = TextureService()
    jar_path = tmp_path / "client.jar"
    jar_path.write_bytes(b"valid")
    expected = hashlib.sha1(b"valid").hexdigest()

    assert service._is_cached_jar_valid(jar_path, expected) is True
    assert jar_path.exists()
    assert service._is_cached_jar_valid(jar_path, "bad") is False
    assert not jar_path.exists()


def test_stream_client_jar_commits_temp_file_atomically(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        texture_service.requests,
        "get",
        lambda *_args, **_kwargs: _Response(chunks=(b"abc", b"", b"def")),
    )
    target = tmp_path / "client.jar"
    info = ClientJarInfo("1.21", "client", None, 6)

    assert TextureService._stream_client_jar(info, target) is True
    assert target.read_bytes() == b"abcdef"
    assert not target.with_suffix(".jar.part").exists()


def test_stream_client_jar_rejects_http_failure(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        texture_service.requests,
        "get",
        lambda *_args, **_kwargs: _Response(status_code=503),
    )
    target = tmp_path / "client.jar"

    assert TextureService._stream_client_jar(
        ClientJarInfo("1.21", "client", None, 0),
        target,
    ) is False
    assert not target.exists()
