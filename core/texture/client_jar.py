"""Pure client JAR discovery/download helpers for texture loading."""
from __future__ import annotations

import hashlib
import logging
import os
import platform
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


def find_local_minecraft_jar() -> Optional[Path]:
    """Locate the newest installed client jar under the local Minecraft dir."""
    system = platform.system()
    if system == "Windows":
        mc_dir = Path(os.environ.get("APPDATA", "")) / ".minecraft"
    elif system == "Darwin":
        mc_dir = Path.home() / "Library" / "Application Support" / "minecraft"
    else:
        mc_dir = Path.home() / ".minecraft"

    versions_dir = mc_dir / "versions"
    if not versions_dir.exists():
        return None

    jars: list[tuple[str, Path]] = []
    for version_dir in versions_dir.iterdir():
        if not version_dir.is_dir():
            continue
        jar_path = version_dir / f"{version_dir.name}.jar"
        if jar_path.exists():
            jars.append((version_dir.name, jar_path))

    if not jars:
        return None

    jars.sort(key=lambda item: item[0], reverse=True)
    return jars[0][1]


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
    """Download a client jar to jar_path atomically via a .part temp file."""
    logger.info(f"开始下载 JAR ({info.size / 1024 / 1024:.1f} MB)...")
    response = requests.get(info.url, timeout=300, stream=True)
    if response.status_code != 200:
        logger.warning(f"下载失败: HTTP {response.status_code}")
        return False
    temp_path = jar_path.with_suffix(jar_path.suffix + ".part")
    try:
        with open(temp_path, "wb") as file:
            downloaded = 0
            for chunk in response.iter_content(chunk_size=8192):
                if not chunk:
                    continue
                file.write(chunk)
                downloaded += len(chunk)
                if downloaded % (1024 * 1024) == 0:
                    logger.debug(
                        f"已下载: {downloaded / 1024 / 1024:.1f} MB"
                    )
        temp_path.replace(jar_path)
        return True
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise


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
