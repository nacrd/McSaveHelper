"""纹理服务 - 管理 Minecraft 物品纹理的获取、缓存和提供"""
from __future__ import annotations

import base64
import logging
import re
import threading
import zipfile
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence

import requests

from core.io_atomic import atomic_write_bytes
from core.texture.block_guess import (
    guess_is_block,
    resolve_texture_resource_key,
)
from core.texture.client_jar import (
    ClientJarInfo,
    download_client_jar,
    find_local_minecraft_jar,
)

__all__ = ["ClientJarInfo", "JarTextureImportResult", "TextureService"]

logger = logging.getLogger(__name__)

_ASSET_INDEX_URL = "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json"
_RESOURCE_BASE_URL = "https://resources.download.minecraft.net"
_JAR_TEXTURE_PREFIX = "assets/minecraft/textures/"
_REQUEST_TIMEOUT = 10
_MAX_MEMORY_CACHE = 500
_MAX_TEXTURE_BYTES = 16 * 1024 * 1024
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_RESOURCE_LOCATION_RE = re.compile(r"^[a-z0-9_.-]+:[a-z0-9_./-]+$")


@dataclass(frozen=True)
class JarTextureImportResult:
    """Outcome of bulk-importing textures from one or more jars."""

    extracted: int
    jars: int
    skipped: int = 0

    @property
    def ok(self) -> bool:
        return self.extracted > 0


def _is_valid_png_payload(data: bytes) -> bool:
    """Whether *data* looks like a bounded PNG texture payload."""
    return bool(data) and len(data) <= _MAX_TEXTURE_BYTES and data.startswith(
        _PNG_SIGNATURE
    )


class TextureService:
    """纹理服务：物品纹理的获取、缓存与批量导入。

    查找优先级：内存缓存 → 本地文件缓存 → JAR 提取 → 在线资源 API。
    """

    def __init__(self) -> None:
        """初始化缓存目录与内存表。"""
        self._cache_dir = Path.home() / ".mc_save_helper" / "textures"
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._jar_cache_dir = Path.home() / ".mc_save_helper" / "jars"
        self._jar_cache_dir.mkdir(parents=True, exist_ok=True)
        self._memory_cache: OrderedDict[str, Path] = OrderedDict()
        self._base64_cache: OrderedDict[str, str] = OrderedDict()
        self._minecraft_jar: Optional[Path] = None
        # Extra jars (resource packs / mods) searched after the client jar.
        self._extra_jars: List[Path] = []
        self._asset_index: Optional[Dict[str, str]] = None
        self._asset_index_loaded = False
        self._jar_download_attempted = False
        self._lock = threading.Lock()
        self._jar_lock = threading.Lock()
        self._tried_paths: Dict[str, str] = {}

    def get_texture_path(self, item_id: str) -> Optional[Path]:
        """解析物品纹理文件路径。

        Args:
            item_id: 资源定位符，如 ``minecraft:stone``。

        Returns:
            Path | None: 本地 PNG 路径；ID 不安全或找不到时为 None。
        """
        if not self._is_safe_item_id(item_id):
            return None

        cached = self._try_memory_cache(item_id)
        if cached is not None:
            return cached

        cached = self._try_file_cache(item_id)
        if cached is not None:
            self._put_memory_cache(item_id, cached)
            return cached

        texture_res = self._resolve_texture_resource(item_id)

        data = self._try_extract_from_jar(texture_res)
        if data is not None:
            path = self._save_to_cache(texture_res, data)
            self._put_memory_cache(item_id, path)
            return path

        data = self._try_fetch_from_api(texture_res)
        if data is not None:
            path = self._save_to_cache(texture_res, data)
            self._put_memory_cache(item_id, path)
            return path

        return None

    def get_texture_base64(self, item_id: str) -> Optional[str]:
        """获取物品纹理的 base64 data URI（可用于 ``ft.Image.src``）。

        Args:
            item_id: 资源定位符。

        Returns:
            str | None: ``data:image/png;base64,...`` 或 None。
        """
        if not self._is_safe_item_id(item_id):
            return None

        with self._lock:
            if item_id in self._base64_cache:
                self._base64_cache.move_to_end(item_id)
                return self._base64_cache[item_id]

        path = self.get_texture_path(item_id)
        if path is None or not path.exists():
            return None

        try:
            if path.stat().st_size > _MAX_TEXTURE_BYTES:
                return None
            data = path.read_bytes()
            if not data.startswith(_PNG_SIGNATURE):
                return None
            b64 = base64.b64encode(data).decode("ascii")
            uri = f"data:image/png;base64,{b64}"
            with self._lock:
                self._base64_cache[item_id] = uri
                while len(self._base64_cache) > _MAX_MEMORY_CACHE:
                    self._base64_cache.popitem(last=False)
            return uri
        except OSError:
            return None

    def load_textures_async(
        self,
        item_ids: List[str],
        on_loaded: Optional[Callable[[str, Optional[str]], None]] = None,
    ) -> None:
        """在后台线程批量加载纹理。

        Args:
            item_ids: 物品 ID 列表。
            on_loaded: 每完成一个调用 ``(item_id, base64_uri_or_None)``；
                回调异常会被吞掉以免中断批量加载。
        """
        def _worker() -> None:
            for item_id in item_ids:
                uri = self.get_texture_base64(item_id)
                if on_loaded is None:
                    continue
                try:
                    on_loaded(item_id, uri)
                except Exception:
                    # 回调由 UI 提供，失败不影响后续纹理。
                    pass

        threading.Thread(
            target=_worker,
            name="texture-load",
            daemon=True,
        ).start()

    def import_textures_from_jars(
        self,
        jar_paths: Sequence[Path],
        *,
        set_primary: bool = True,
    ) -> JarTextureImportResult:
        """从多个 JAR 批量提取 ``assets/*/textures/**/*.png`` 到缓存。

        成功的 JAR 会注册，供后续按物品查找使用。

        Args:
            jar_paths: 客户端/模组/资源包 JAR 路径序列。
            set_primary: 是否将第一个成功 JAR 设为主客户端 JAR。

        Returns:
            JarTextureImportResult: 提取数量、成功 JAR 数与跳过数。
        """
        extracted = 0
        jars_ok = 0
        skipped = 0
        for raw in jar_paths:
            path = Path(raw)
            if not path.is_file():
                skipped += 1
                continue
            count = self._extract_all_textures_from_jar(path)
            if count <= 0:
                skipped += 1
                continue
            jars_ok += 1
            extracted += count
            self.register_texture_jar(
                path,
                primary=set_primary and jars_ok == 1,
            )
        return JarTextureImportResult(
            extracted=extracted,
            jars=jars_ok,
            skipped=skipped,
        )

    def register_texture_jar(self, path: Path, *, primary: bool = False) -> None:
        """注册供后续查找的纹理 JAR。

        Args:
            path: JAR 路径。
            primary: True 时作为主客户端 JAR。
        """
        resolved = Path(path)
        with self._jar_lock:
            if primary:
                self._minecraft_jar = resolved
            elif resolved not in self._extra_jars:
                self._extra_jars.insert(0, resolved)

    def _extract_all_textures_from_jar(self, jar_path: Path) -> int:
        count = 0
        try:
            with zipfile.ZipFile(jar_path) as archive:
                for name in archive.namelist():
                    lower = name.lower().replace("\\", "/")
                    if not lower.startswith("assets/"):
                        continue
                    if "/textures/" not in lower or not lower.endswith(".png"):
                        continue
                    parts = lower.split("/")
                    try:
                        tex_idx = parts.index("textures")
                    except ValueError:
                        continue
                    if tex_idx < 2:
                        continue
                    relative = "/".join(parts[tex_idx + 1:])
                    if not relative or ".." in relative:
                        continue
                    try:
                        data = archive.read(name)
                    except KeyError:
                        continue
                    if not _is_valid_png_payload(data):
                        continue
                    try:
                        self._save_to_cache(relative, data)
                    except (ValueError, OSError):
                        continue
                    count += 1
        except (OSError, zipfile.BadZipFile, RuntimeError):
            return 0
        return count

    def _try_memory_cache(self, item_id: str) -> Optional[Path]:
        with self._lock:
            if item_id in self._memory_cache:
                self._memory_cache.move_to_end(item_id)
                path = self._memory_cache[item_id]
                if path.exists():
                    return path
                del self._memory_cache[item_id]
        return None

    def _try_file_cache(self, item_id: str) -> Optional[Path]:
        texture_res = self._resolve_texture_resource(item_id)
        try:
            path = self._safe_cache_path(texture_res)
        except ValueError:
            return None
        if path.exists() and 0 < path.stat().st_size <= _MAX_TEXTURE_BYTES:
            return path
        return None

    def _resolve_texture_resource(self, item_id: str) -> str:
        if item_id in self._tried_paths:
            return self._tried_paths[item_id]

        if ":" in item_id:
            _, local_id = item_id.split(":", 1)
        else:
            local_id = item_id

        result = self._find_texture_resource(item_id, local_id)
        self._tried_paths[item_id] = result
        return result

    def _find_texture_resource(self, item_id: str, local_id: str) -> str:
        del item_id
        asset_keys = self._get_asset_index_keys()
        return resolve_texture_resource_key(
            local_id,
            prefer_block=guess_is_block(local_id),
            asset_keys=asset_keys,
        )

    def _get_asset_index_keys(self) -> Optional[Dict[str, str]]:
        if not self._asset_index_loaded:
            self._load_asset_index()
        return self._asset_index

    def _try_extract_from_jar(self, texture_res: str) -> Optional[bytes]:
        for jar in self._iter_texture_jars():
            data = self._read_texture_from_jar(jar, texture_res)
            if data:
                return data
        return None

    def _iter_texture_jars(self) -> List[Path]:
        jars: List[Path] = []
        primary = self._find_or_get_jar()
        if primary is not None:
            jars.append(primary)
        with self._jar_lock:
            extras = list(self._extra_jars)
        for path in extras:
            if path not in jars and path.exists():
                jars.append(path)
        return jars

    @staticmethod
    def _read_texture_from_jar(jar: Path, texture_res: str) -> Optional[bytes]:
        leaf = texture_res.split("/", 1)[-1]
        candidates = (
            f"{_JAR_TEXTURE_PREFIX}{leaf}",
            f"{_JAR_TEXTURE_PREFIX}{texture_res}",
        )
        try:
            with zipfile.ZipFile(jar) as zf:
                names = set(zf.namelist())
                for candidate in candidates:
                    if candidate in names:
                        return zf.read(candidate)
                suffix = f"/textures/{leaf}"
                for name in names:
                    lower = name.replace("\\", "/").lower()
                    if lower.endswith(suffix):
                        return zf.read(name)
        except (OSError, zipfile.BadZipFile, RuntimeError, KeyError):
            return None
        return None

    def _try_fetch_from_api(self, texture_res: str) -> Optional[bytes]:
        """从 Mojang 资源 CDN 按 asset index 哈希下载纹理。"""
        try:
            asset_index = self._get_asset_index_keys()
            if asset_index is None:
                return None

            mc_res_path = f"minecraft/{texture_res}"
            file_hash = asset_index.get(mc_res_path)
            if not file_hash:
                return None

            hash_prefix = file_hash[:2]
            url = f"{_RESOURCE_BASE_URL}/{hash_prefix}/{file_hash}"
            resp = requests.get(url, timeout=_REQUEST_TIMEOUT)
            if resp.status_code == 200 and len(resp.content) > 0:
                return resp.content
        except (OSError, ValueError, TypeError, requests.RequestException):
            return None
        return None

    def _save_to_cache(self, texture_res: str, data: bytes) -> Path:
        if not _is_valid_png_payload(data):
            raise ValueError("纹理数据不是受支持的 PNG")
        path = self._safe_cache_path(texture_res)
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_bytes(path, data)
        return path

    def _safe_cache_path(self, texture_res: str) -> Path:
        relative = Path(texture_res)
        if relative.is_absolute() or ".." in relative.parts or relative.suffix != ".png":
            raise ValueError(f"无效纹理资源路径: {texture_res}")
        root = self._cache_dir.resolve()
        path = (root / relative).resolve()
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise ValueError(f"纹理资源越过缓存目录: {texture_res}") from exc
        return path

    @staticmethod
    def _is_safe_item_id(item_id: str) -> bool:
        if not item_id or not _RESOURCE_LOCATION_RE.fullmatch(item_id):
            return False
        _namespace, local_id = item_id.split(":", 1)
        return ".." not in Path(local_id).parts

    def _put_memory_cache(self, item_id: str, path: Path) -> None:
        with self._lock:
            self._memory_cache[item_id] = path
            self._memory_cache.move_to_end(item_id)
            while len(self._memory_cache) > _MAX_MEMORY_CACHE:
                self._memory_cache.popitem(last=False)

    def _find_or_get_jar(self) -> Optional[Path]:
        with self._jar_lock:
            if self._minecraft_jar and self._minecraft_jar.exists():
                return self._minecraft_jar

            self._minecraft_jar = self.find_minecraft_jar()
            if self._minecraft_jar:
                return self._minecraft_jar

            if not self._jar_download_attempted:
                self._jar_download_attempted = True
                self._minecraft_jar = self._download_client_jar()

            return self._minecraft_jar

    def find_minecraft_jar(self) -> Optional[Path]:
        """在本机常见路径查找 Minecraft 客户端 JAR。

        Returns:
            Path | None: 找到的 JAR 路径。
        """
        return find_local_minecraft_jar()

    def set_minecraft_jar(self, path: Path) -> None:
        """设置主客户端 JAR 路径。

        Args:
            path: 客户端 JAR。
        """
        self._minecraft_jar = path

    def _download_client_jar(self) -> Optional[Path]:
        """从 Mojang 官方下载客户端 JAR，并自动清理旧版本。"""
        return download_client_jar(self._jar_cache_dir)

    def _load_asset_index(self) -> None:
        """懒加载最新正式版 asset index（失败时标记已加载以免重试风暴）。"""
        try:
            version_url = self._find_latest_version_url()
            if version_url is None:
                return
            asset_index_url = self._find_asset_index_url(version_url)
            if asset_index_url is None:
                return
            asset_index = self._download_asset_index(asset_index_url)
            if asset_index is not None:
                self._asset_index = asset_index
        except (OSError, ValueError, TypeError, requests.RequestException):
            # 网络/JSON 失败时保持空索引，由调用方走 JAR 回退。
            pass
        finally:
            self._asset_index_loaded = True

    def _find_latest_version_url(self) -> Optional[str]:
        manifest = self._request_json(_ASSET_INDEX_URL)
        if manifest is None:
            return None
        latest = self._as_json_object(manifest.get("latest"))
        latest_id = latest.get("release") if latest is not None else None
        if not isinstance(latest_id, str) or not latest_id:
            return None
        versions = manifest.get("versions")
        if not isinstance(versions, list):
            return None
        return self._find_version_url(versions, latest_id)

    def _find_version_url(
        self,
        versions: List[object],
        latest_id: str,
    ) -> Optional[str]:
        for version_value in versions:
            version = self._as_json_object(version_value)
            if version is None or version.get("id") != latest_id:
                continue
            url = version.get("url")
            return url if isinstance(url, str) and url else None
        return None

    def _find_asset_index_url(self, version_url: str) -> Optional[str]:
        version_data = self._request_json(version_url)
        if version_data is None:
            return None
        asset_index = self._as_json_object(version_data.get("assetIndex"))
        if asset_index is None:
            return None
        url = asset_index.get("url")
        return url if isinstance(url, str) and url else None

    def _download_asset_index(self, asset_index_url: str) -> Optional[Dict[str, str]]:
        asset_data = self._request_json(asset_index_url)
        if asset_data is None:
            return None
        objects = self._as_json_object(asset_data.get("objects")) or {}
        asset_index: Dict[str, str] = {}
        for key, value in objects.items():
            info = self._as_json_object(value)
            digest = info.get("hash") if info is not None else None
            if isinstance(digest, str):
                asset_index[key] = digest
        return asset_index

    @staticmethod
    def _request_json(url: str) -> Optional[Dict[str, object]]:
        response = requests.get(url, timeout=_REQUEST_TIMEOUT)
        if response.status_code != 200:
            return None
        return TextureService._as_json_object(response.json())

    @staticmethod
    def _as_json_object(value: object) -> Optional[Dict[str, object]]:
        if isinstance(value, dict):
            return {str(key): item for key, item in value.items()}
        return None

    def clear_cache(self, clear_textures: bool = True,
                    clear_jars: bool = False) -> None:
        """清理缓存

        Args:
            clear_textures: 是否清理纹理缓存（默认 True）
            clear_jars: 是否清理 JAR 文件（默认 False，因为 JAR 较大且重新下载耗时）
        """
        self._clear_memory_cache()
        if clear_textures:
            self._clear_texture_files()
        if clear_jars:
            self._clear_jar_files()

    def _clear_memory_cache(self) -> None:
        with self._lock:
            self._memory_cache.clear()
            self._base64_cache.clear()
            self._tried_paths.clear()

    def _clear_texture_files(self) -> None:
        if not self._cache_dir.exists():
            return
        try:
            deleted_count = self._delete_texture_files()
            if deleted_count > 0:
                logger.info(f"已清理 {deleted_count} 个纹理缓存文件")
        except OSError as exc:
            logger.warning(f"清理纹理缓存失败: {exc}")

    def _delete_texture_files(self) -> int:
        deleted_count = 0
        for texture_file in self._cache_dir.rglob("*.png"):
            try:
                texture_file.unlink()
                deleted_count += 1
            except OSError:
                continue
        return deleted_count

    def _clear_jar_files(self) -> None:
        if not self._jar_cache_dir.exists():
            return
        try:
            deleted_count, deleted_size = self._delete_jar_files()
            if deleted_count > 0:
                size_mb = deleted_size / 1024 / 1024
                logger.info(
                    f"已清理 {deleted_count} 个 JAR 文件 ({size_mb:.1f} MB)"
                )
        except OSError as exc:
            logger.warning(f"清理 JAR 缓存失败: {exc}")

    def _delete_jar_files(self) -> tuple[int, int]:
        deleted_count = 0
        deleted_size = 0
        for jar_file in self._jar_cache_dir.glob("*.jar"):
            try:
                size = jar_file.stat().st_size
                jar_file.unlink()
                deleted_count += 1
                deleted_size += size
            except OSError:
                continue
        return deleted_count, deleted_size
