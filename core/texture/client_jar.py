"""Pure client JAR discovery/download helpers for texture loading."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import platform
import tempfile
import zipfile
from datetime import datetime
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Optional

import requests

logger = logging.getLogger(__name__)

ASSET_INDEX_URL = (
    "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json"
)
REQUEST_TIMEOUT = 10
JsonGetter = Callable[[str, str], Optional[Dict[str, Any]]]


@dataclass(frozen=True)
class ClientJarInfo:
    version_id: str
    url: str
    sha1: Optional[str]
    size: int


def find_local_minecraft_jar(
    minecraft_dir: Optional[Path] = None,
) -> Optional[Path]:
    """Locate the newest installed client jar under a Minecraft data dir."""
    root = Path(minecraft_dir) if minecraft_dir is not None else minecraft_directory()
    versions_dir = root / "versions"
    if not versions_dir.exists():
        return None
    jars = _find_version_jars(versions_dir)
    if not jars:
        return None
    jars.sort(key=lambda item: item[0], reverse=True)
    return jars[0][1]


def minecraft_directory() -> Path:
    """Return the platform default Minecraft data directory."""
    return _minecraft_directory()


def is_minecraft_data_dir(path: Path) -> bool:
    """Heuristic: does ``path`` look like a Minecraft data root?"""
    if not path.is_dir():
        return False
    # Custom installs may use a folder literally named ".minecraft".
    markers = (
        path / "assets" / "indexes",
        path / "assets" / "objects",
        path / "versions",
        path / "launcher_profiles.json",
        path / "launcher_accounts.json",
    )
    return any(marker.exists() for marker in markers)


def minecraft_dir_from_client_jar(jar_path: Path) -> Optional[Path]:
    """Infer ``.minecraft`` from ``versions/<id>/<id>.jar`` layout."""
    try:
        jar = Path(jar_path).resolve()
    except OSError:
        return None
    # .../.minecraft/versions/1.20.1/1.20.1.jar
    if jar.parent.name and jar.parent.parent.name == "versions":
        candidate = jar.parent.parent.parent
        if is_minecraft_data_dir(candidate):
            return candidate
    # Walk up a few levels as a looser fallback.
    current = jar.parent
    for _ in range(6):
        if is_minecraft_data_dir(current):
            return current
        if current.parent == current:
            break
        current = current.parent
    return None


def discover_minecraft_directory(
    *,
    configured: Optional[Path] = None,
    start_path: Optional[Path] = None,
    jar_path: Optional[Path] = None,
) -> Optional[Path]:
    """Resolve a Minecraft data directory from config, save path, or jar.

    Order:
    1. Explicit configured path (if valid)
    2. Inferred from a client jar path
    3. Walk up from a save/world path looking for a data root
    4. Platform default ``.minecraft`` when it looks valid
    """
    if configured is not None:
        try:
            configured_path = Path(configured).expanduser().resolve()
        except OSError:
            configured_path = None
        if configured_path is not None and is_minecraft_data_dir(configured_path):
            return configured_path

    if jar_path is not None:
        from_jar = minecraft_dir_from_client_jar(Path(jar_path))
        if from_jar is not None:
            return from_jar

    if start_path is not None:
        walked = minecraft_dir_from_start_path(Path(start_path))
        if walked is not None:
            return walked

    default = minecraft_directory()
    if is_minecraft_data_dir(default):
        return default
    return None


def minecraft_dir_from_start_path(start_path: Path) -> Optional[Path]:
    """Walk parents of a save/world path to find a Minecraft data root.

    Examples that work:
    - ``.../.minecraft/saves/World``
    - ``F:/Game/minecraft/.minecraft/saves/World``
    - MultiMC-style ``instances/foo/.minecraft/saves/World``
    """
    try:
        current = Path(start_path).expanduser().resolve()
    except OSError:
        return None
    if current.is_file():
        current = current.parent
    for _ in range(10):
        if is_minecraft_data_dir(current):
            return current
        # Also accept a parent that *contains* `.minecraft`.
        nested = current / ".minecraft"
        if is_minecraft_data_dir(nested):
            return nested
        if current.parent == current:
            break
        current = current.parent
    return None


def _minecraft_directory() -> Path:
    system = platform.system()
    if system == "Windows":
        return Path(os.environ.get("APPDATA", "")) / ".minecraft"
    if system == "Darwin":
        return Path.home() / "Library" / "Application Support" / "minecraft"
    return Path.home() / ".minecraft"


def _find_version_jars(versions_dir: Path) -> list[tuple[float, Path]]:
    jars: list[tuple[float, Path]] = []
    for version_dir in versions_dir.iterdir():
        if not version_dir.is_dir():
            continue
        jar_path = version_dir / f"{version_dir.name}.jar"
        if jar_path.exists():
            jars.append((_jar_release_time(version_dir, jar_path), jar_path))
    return jars


def _jar_release_time(version_dir: Path, jar_path: Path) -> float:
    sort_time = jar_path.stat().st_mtime
    metadata_path = version_dir / f"{version_dir.name}.json"
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        release_time = metadata.get("releaseTime") or metadata.get("time")
        if release_time:
            sort_time = datetime.fromisoformat(
                str(release_time).replace("Z", "+00:00")
            ).timestamp()
    except (OSError, ValueError, TypeError):
        pass
    return sort_time


def request_json(
    url: str,
    warning: str,
    *,
    timeout: int = REQUEST_TIMEOUT,
) -> Optional[Dict[str, Any]]:
    """GET a JSON object or return None after logging the warning."""
    response = requests.get(url, timeout=timeout)
    if response.status_code != 200:
        logger.warning(warning)
        return None
    data = response.json()
    return data if isinstance(data, dict) else None


def file_sha1(path: Path) -> str:
    """Compute the SHA-1 digest of a file."""
    digest = hashlib.sha1()
    with open(path, "rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def is_cached_jar_valid(jar_path: Path, expected_sha1: Optional[str]) -> bool:
    """Validate a cached jar; remove it when the digest mismatches."""
    if not jar_path.exists():
        return False
    if expected_sha1 and file_sha1(jar_path) == expected_sha1:
        return True
    logger.warning("缓存的 JAR SHA1 校验失败，重新下载")
    jar_path.unlink(missing_ok=True)
    return False


def resolve_latest_client_jar(
    request_json_fn: JsonGetter = request_json,
    *,
    manifest_url: str = ASSET_INDEX_URL,
) -> Optional[ClientJarInfo]:
    """Resolve the latest release client jar metadata from Mojang manifests."""
    manifest = request_json_fn(manifest_url, "无法获取版本清单")
    if manifest is None:
        return None
    latest_id = manifest.get("latest", {}).get("release")
    if not latest_id:
        logger.warning("无法获取最新版本 ID")
        return None
    logger.info(f"最新版本: {latest_id}")
    version_url = next(
        (
            version.get("url")
            for version in manifest.get("versions", [])
            if version.get("id") == latest_id
        ),
        None,
    )
    if not version_url:
        logger.warning("无法获取版本 URL")
        return None
    version_data = request_json_fn(str(version_url), "无法获取版本数据")
    if version_data is None:
        return None
    client = version_data.get("downloads", {}).get("client")
    if not client:
        logger.warning("无法获取客户端下载信息")
        return None
    jar_url = client.get("url")
    if not jar_url:
        logger.warning("无法获取 JAR 下载 URL")
        return None
    return ClientJarInfo(
        version_id=str(latest_id),
        url=str(jar_url),
        sha1=client.get("sha1"),
        size=int(client.get("size", 0)),
    )


def stream_client_jar(info: ClientJarInfo, jar_path: Path) -> bool:
    """Download, verify, and atomically publish a client JAR."""
    logger.info(f"开始下载 JAR ({info.size / 1024 / 1024:.1f} MB)...")
    response = requests.get(info.url, timeout=300, stream=True)
    if response.status_code != 200:
        logger.warning(f"下载失败: HTTP {response.status_code}")
        return False
    jar_path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{jar_path.name}.", suffix=".part", dir=jar_path.parent
    )
    os.close(fd)
    temp_path = Path(temp_name)
    try:
        downloaded, actual_sha1 = _write_client_jar(response, temp_path)
        if not _download_matches(info, downloaded, actual_sha1):
            return False
        if not _is_valid_jar(temp_path):
            return False
        os.replace(temp_path, jar_path)
        return True
    finally:
        temp_path.unlink(missing_ok=True)


def _write_client_jar(response: Any, temp_path: Path) -> tuple[int, str]:
    digest = hashlib.sha1()
    downloaded = 0
    with open(temp_path, "wb") as file:
        for chunk in response.iter_content(chunk_size=8192):
            if not chunk:
                continue
            file.write(chunk)
            digest.update(chunk)
            downloaded += len(chunk)
            if downloaded % (1024 * 1024) == 0:
                logger.debug(f"已下载: {downloaded / 1024 / 1024:.1f} MB")
    return downloaded, digest.hexdigest()


def _download_matches(
    info: ClientJarInfo,
    downloaded: int,
    actual_sha1: str,
) -> bool:
    if info.size and downloaded != info.size:
        logger.warning(f"JAR 长度校验失败: 预期 {info.size}，实际 {downloaded}")
        return False
    if info.sha1 and actual_sha1.lower() != info.sha1.lower():
        logger.warning("JAR SHA1 校验失败")
        return False
    return True


def _is_valid_jar(path: Path) -> bool:
    try:
        with zipfile.ZipFile(path) as archive:
            if archive.testzip() is not None:
                logger.warning("JAR ZIP 完整性校验失败")
                return False
    except zipfile.BadZipFile:
        logger.warning("下载内容不是有效的 JAR")
        return False
    return True


def cleanup_old_jars(jar_cache_dir: Path, keep_count: int = 1) -> None:
    """Keep only the newest N cached minecraft-*-client.jar files."""
    try:
        if not jar_cache_dir.exists():
            return
        jar_files = list(jar_cache_dir.glob("minecraft-*-client.jar"))
        if len(jar_files) <= keep_count:
            return
        jar_files.sort(key=lambda path: path.stat().st_mtime, reverse=True)
        for old_jar in jar_files[keep_count:]:
            try:
                size_mb = old_jar.stat().st_size / 1024 / 1024
                old_jar.unlink()
                logger.info(
                    f"已清理旧版本 JAR: {old_jar.name} ({size_mb:.1f} MB)"
                )
            except Exception as exc:
                logger.warning(f"清理 JAR 失败 {old_jar.name}: {exc}")
    except Exception as exc:
        logger.warning(f"清理旧 JAR 文件时出错: {exc}")


def download_client_jar(jar_cache_dir: Path) -> Optional[Path]:
    """Download the latest client jar into jar_cache_dir when needed."""
    try:
        logger.info("开始下载 Minecraft 客户端 JAR...")
        cleanup_old_jars(jar_cache_dir, keep_count=1)
        info = resolve_latest_client_jar()
        if info is None:
            return None
        jar_path = jar_cache_dir / f"minecraft-{info.version_id}-client.jar"
        if is_cached_jar_valid(jar_path, info.sha1):
            logger.info(f"使用缓存的 JAR: {jar_path}")
            return jar_path
        if stream_client_jar(info, jar_path):
            logger.info(f"JAR 下载完成: {jar_path}")
            return jar_path
    except Exception as exc:
        logger.error(f"下载 JAR 失败: {exc}")
    return None
