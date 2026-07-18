"""纹理服务 - 管理 Minecraft 物品纹理的获取、缓存和提供"""
import base64
import logging
import os
import re
import threading
import tempfile
import zipfile
from collections import OrderedDict
from pathlib import Path
from typing import Callable, Dict, List, Optional

import requests

from core.texture.block_guess import (
    guess_is_block,
    resolve_texture_resource_key,
)
from core.texture.client_jar import (
    ClientJarInfo,
    download_client_jar,
    find_local_minecraft_jar,
)

__all__ = ["ClientJarInfo", "TextureService"]

logger = logging.getLogger(__name__)

_ASSET_INDEX_URL = "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json"
_RESOURCE_BASE_URL = "https://resources.download.minecraft.net"
_JAR_TEXTURE_PREFIX = "assets/minecraft/textures/"
_REQUEST_TIMEOUT = 10
_MAX_MEMORY_CACHE = 500
_MAX_TEXTURE_BYTES = 16 * 1024 * 1024
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_RESOURCE_LOCATION_RE = re.compile(r"^[a-z0-9_.-]+:[a-z0-9_./-]+$")


class TextureService:
    """纹理服务 - 管理物品纹理的获取和缓存

    优先级: 内存缓存 > 本地文件缓存 > JAR提取 > 在线API
    """

    def __init__(self) -> None:
        self._cache_dir = Path.home() / ".mc_save_helper" / "textures"
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._jar_cache_dir = Path.home() / ".mc_save_helper" / "jars"
        self._jar_cache_dir.mkdir(parents=True, exist_ok=True)
        self._memory_cache: OrderedDict[str, Path] = OrderedDict()
        self._base64_cache: OrderedDict[str, str] = OrderedDict()
        self._minecraft_jar: Optional[Path] = None
        self._asset_index: Optional[Dict[str, str]] = None
        self._asset_index_loaded = False
        self._jar_download_attempted = False
        self._lock = threading.Lock()
        self._jar_lock = threading.Lock()
        self._tried_paths: Dict[str, str] = {}

    def get_texture_path(self, item_id: str) -> Optional[Path]:
        if not self._is_safe_item_id(item_id):
            return None

        cached = self._try_memory_cache(item_id)
        if cached:
            return cached

        cached = self._try_file_cache(item_id)
        if cached:
            self._put_memory_cache(item_id, cached)
            return cached

        texture_res = self._resolve_texture_resource(item_id)

        data = self._try_extract_from_jar(texture_res)
        if data:
            path = self._save_to_cache(texture_res, data)
            self._put_memory_cache(item_id, path)
            return path

        data = self._try_fetch_from_api(texture_res)
        if data:
            path = self._save_to_cache(texture_res, data)
            self._put_memory_cache(item_id, path)
            return path

        return None

    def get_texture_base64(self, item_id: str) -> Optional[str]:
        """获取物品纹理的 base64 data URI，可直接用于 ft.Image.src"""
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
        except Exception:
            return None

    def load_textures_async(
        self,
        item_ids: List[str],
        on_loaded: Optional[Callable[[str, Optional[str]], None]] = None,
    ) -> None:
        """在后台线程中批量加载纹理，每完成一个回调 (item_id, base64_uri_or_None)"""
        def _worker() -> None:
            for item_id in item_ids:
                uri = self.get_texture_base64(item_id)
                if on_loaded is not None:
                    try:
                        on_loaded(item_id, uri)
                    except Exception:
                        pass
        threading.Thread(target=_worker, daemon=True).start()

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
        jar = self._find_or_get_jar()
        if jar is None:
            return None
        try:
            with zipfile.ZipFile(jar) as zf:
                jar_path = f"{_JAR_TEXTURE_PREFIX}{
                    texture_res.split(
                        '/', 1)[
                        -1]}"
                if jar_path in zf.namelist():
                    return zf.read(jar_path)
                full_path = f"{_JAR_TEXTURE_PREFIX}{texture_res}"
                if full_path in zf.namelist():
                    return zf.read(full_path)
        except Exception:
            pass
        return None

    def _try_fetch_from_api(self, texture_res: str) -> Optional[bytes]:
        try:
            if not self._asset_index_loaded:
                self._load_asset_index()
            if self._asset_index is None:
                return None

            mc_res_path = f"minecraft/{texture_res}"
            file_hash = self._asset_index.get(mc_res_path)
            if not file_hash:
                return None

            hash_prefix = file_hash[:2]
            url = f"{_RESOURCE_BASE_URL}/{hash_prefix}/{file_hash}"
            resp = requests.get(url, timeout=_REQUEST_TIMEOUT)
            if resp.status_code == 200 and len(resp.content) > 0:
                return resp.content
        except Exception:
            pass
        return None

    def _save_to_cache(self, texture_res: str, data: bytes) -> Path:
        if len(data) > _MAX_TEXTURE_BYTES or not data.startswith(_PNG_SIGNATURE):
            raise ValueError("纹理数据不是受支持的 PNG")
        path = self._safe_cache_path(texture_res)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
        )
        temp_path = Path(temp_name)
        try:
            with os.fdopen(fd, "wb") as texture_file:
                texture_file.write(data)
                texture_file.flush()
                os.fsync(texture_file.fileno())
            os.replace(temp_path, path)
        finally:
            temp_path.unlink(missing_ok=True)
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
        return find_local_minecraft_jar()

    def set_minecraft_jar(self, path: Path) -> None:
        self._minecraft_jar = path

    def _download_client_jar(self) -> Optional[Path]:
        """从 Mojang 官方下载客户端 JAR，并自动清理旧版本。"""
        return download_client_jar(self._jar_cache_dir)

    def _load_asset_index(self) -> None:
        try:
            resp = requests.get(_ASSET_INDEX_URL, timeout=_REQUEST_TIMEOUT)
            if resp.status_code != 200:
                self._asset_index_loaded = True
                return

            manifest = resp.json()
            latest_id = manifest.get("latest", {}).get("release")
            if not latest_id:
                self._asset_index_loaded = True
                return

            version_url = None
            for v in manifest.get("versions", []):
                if v.get("id") == latest_id:
                    version_url = v.get("url")
                    break

            if not version_url:
                self._asset_index_loaded = True
                return

            resp2 = requests.get(version_url, timeout=_REQUEST_TIMEOUT)
            if resp2.status_code != 200:
                self._asset_index_loaded = True
                return

            version_data = resp2.json()
            asset_index_url = version_data.get("assetIndex", {}).get("url")
            if not asset_index_url:
                self._asset_index_loaded = True
                return

            resp3 = requests.get(asset_index_url, timeout=_REQUEST_TIMEOUT)
            if resp3.status_code != 200:
                self._asset_index_loaded = True
                return

            asset_data = resp3.json()
            objects = asset_data.get("objects", {})
            self._asset_index = {}
            for key, info in objects.items():
                self._asset_index[key] = info.get("hash", "")

            self._asset_index_loaded = True
        except Exception:
            self._asset_index_loaded = True

    def clear_cache(self, clear_textures: bool = True,
                    clear_jars: bool = False) -> None:
        """清理缓存

        Args:
            clear_textures: 是否清理纹理缓存（默认 True）
            clear_jars: 是否清理 JAR 文件（默认 False，因为 JAR 较大且重新下载耗时）
        """
        with self._lock:
            self._memory_cache.clear()
            self._base64_cache.clear()
            self._tried_paths.clear()

        if clear_textures and self._cache_dir.exists():
            try:
                deleted_count = 0
                for f in self._cache_dir.rglob("*.png"):
                    try:
                        f.unlink()
                        deleted_count += 1
                    except Exception:
                        pass
                if deleted_count > 0:
                    logger.info(f"已清理 {deleted_count} 个纹理缓存文件")
            except Exception as e:
                logger.warning(f"清理纹理缓存失败: {e}")

        if clear_jars and self._jar_cache_dir.exists():
            try:
                deleted_count = 0
                deleted_size = 0
                for jar_file in self._jar_cache_dir.glob("*.jar"):
                    try:
                        size = jar_file.stat().st_size
                        jar_file.unlink()
                        deleted_count += 1
                        deleted_size += size
                    except Exception:
                        pass
                if deleted_count > 0:
                    logger.info(
                        f"已清理 {deleted_count} 个 JAR 文件 ({
                            deleted_size / 1024 / 1024:.1f} MB)")
            except Exception as e:
                logger.warning(f"清理 JAR 缓存失败: {e}")
