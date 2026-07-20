"""Player avatar (skin face) fetch + disk cache."""
from __future__ import annotations

import base64
import io
import json
import logging
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Callable, Dict, Optional

from core.io_atomic import atomic_write_bytes
from core.uuid_utils import normalize_uuid

logger = logging.getLogger(__name__)

# Lazy imports keep startup light when avatars are unused.
_requests = None
_Image = None

_SESSION_URL = (
    "https://sessionserver.mojang.com/session/minecraft/profile/{uuid}"
)
_REQUEST_TIMEOUT = 5
_MAX_MEMORY = 128
_FACE_SIZE = 64  # output face size in pixels


def _ensure_requests():
    global _requests
    if _requests is None:
        import requests as _req

        _requests = _req
    return _requests


def _ensure_image():
    global _Image
    if _Image is None:
        from PIL import Image as _pil_image

        _Image = _pil_image
    return _Image


def parse_skin_url_from_profile(profile: dict) -> Optional[str]:
    """Extract the skin texture URL from a Mojang session profile payload."""
    properties = profile.get("properties") or []
    if not isinstance(properties, list):
        return None
    for prop in properties:
        if not isinstance(prop, dict):
            continue
        if prop.get("name") != "textures":
            continue
        raw = prop.get("value")
        if not raw or not isinstance(raw, str):
            continue
        try:
            decoded = base64.b64decode(raw + "==")
            payload = json.loads(decoded.decode("utf-8"))
        except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
            return None
        textures = payload.get("textures") or {}
        skin = textures.get("SKIN") or {}
        url = skin.get("url")
        if isinstance(url, str) and url.startswith("http"):
            return url
    return None


def crop_face_png(skin_bytes: bytes, size: int = _FACE_SIZE) -> bytes:
    """Crop the classic 8×8 face from a 64×64 (or larger) skin PNG."""
    Image = _ensure_image()
    with Image.open(io.BytesIO(skin_bytes)) as img:
        img = img.convert("RGBA")
        width, height = img.size
        # Classic skins are 64x32 or 64x64; face is at (8,8) size 8x8.
        # Scale source coords if skin is a higher-res resource pack.
        scale = max(1, width // 64)
        left = 8 * scale
        top = 8 * scale
        right = 16 * scale
        bottom = 16 * scale
        face = img.crop((left, top, right, bottom))
        # Optional hat layer at (40,8)
        hat_left = 40 * scale
        hat = img.crop((hat_left, top, hat_left + 8 * scale, bottom))
        face = face.convert("RGBA")
        hat = hat.convert("RGBA")
        face.alpha_composite(hat)
        if size and (face.width != size or face.height != size):
            face = face.resize((size, size), Image.Resampling.NEAREST)
        out = io.BytesIO()
        face.save(out, format="PNG")
        return out.getvalue()


class PlayerAvatarService:
    """Fetch and cache player face avatars from Mojang session textures.

    Offline / failed lookups return ``None`` so the UI can show a placeholder.
    """

    def __init__(
        self,
        cache_dir: Optional[Path] = None,
        *,
        enabled: bool = True,
    ) -> None:
        self._enabled = enabled
        self._cache_dir = (
            cache_dir
            if cache_dir is not None
            else Path.home() / ".mc_save_helper" / "avatars"
        )
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._memory: "OrderedDict[str, Path]" = OrderedDict()
        self._lock = threading.Lock()
        self._inflight: Dict[str, list[Callable[[Optional[str]], None]]] = {}
        self._failed: set[str] = set()

    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool) -> None:
        self._enabled = bool(value)

    def get_cached_path(self, uuid: str) -> Optional[Path]:
        """Return a cached face PNG path if present on disk/memory.

        Args:
            uuid: Player UUID (any common form).

        Returns:
            Path | None: Local PNG path, or None when missing.
        """
        norm = normalize_uuid(uuid)
        if not norm:
            return None
        with self._lock:
            cached = self._memory.get(norm)
            if cached is not None and cached.is_file():
                self._memory.move_to_end(norm)
                return cached
        path = self._cache_dir / f"{norm}.png"
        if path.is_file():
            with self._lock:
                self._memory[norm] = path
                self._memory.move_to_end(norm)
                while len(self._memory) > _MAX_MEMORY:
                    self._memory.popitem(last=False)
            return path
        return None

    def load_avatar_async(
        self,
        uuid: str,
        on_loaded: Callable[[Optional[str]], None],
    ) -> None:
        """异步解析头像路径；回调收到本地路径或 ``None``。

        同一 UUID 的并发请求会合并为一次网络拉取。

        Args:
            uuid: 玩家 UUID。
            on_loaded: 完成回调 ``(path_or_none)``。
        """
        if not self._enabled:
            on_loaded(None)
            return
        norm = normalize_uuid(uuid)
        if not norm or len(norm) != 32:
            on_loaded(None)
            return

        cached = self.get_cached_path(norm)
        if cached is not None:
            on_loaded(str(cached))
            return

        with self._lock:
            if norm in self._failed:
                on_loaded(None)
                return
            if norm in self._inflight:
                self._inflight[norm].append(on_loaded)
                return
            self._inflight[norm] = [on_loaded]

        thread = threading.Thread(
            target=self._fetch_worker,
            args=(norm,),
            name=f"avatar-{norm[:8]}",
            daemon=True,
        )
        thread.start()

    def _fetch_worker(self, norm: str) -> None:
        """Background worker: fetch/cache avatar and invoke waiters."""
        path: Optional[Path] = None
        try:
            path = self._fetch_and_cache(norm)
        except (OSError, ValueError, TypeError, RuntimeError) as exc:
            logger.debug(
                "avatar fetch failed for %s: %s",
                norm[:8],
                type(exc).__name__,
            )
            path = None
        except Exception as exc:
            # Network/PIL boundary: mark failure and continue UI callbacks.
            logger.debug(
                "avatar fetch failed for %s: %s",
                norm[:8],
                type(exc).__name__,
            )
            path = None
        with self._lock:
            callbacks = self._inflight.pop(norm, [])
            if path is None:
                self._failed.add(norm)
            else:
                self._memory[norm] = path
                self._memory.move_to_end(norm)
                while len(self._memory) > _MAX_MEMORY:
                    self._memory.popitem(last=False)
        result = str(path) if path is not None else None
        for callback in callbacks:
            try:
                callback(result)
            except Exception:
                # UI callbacks must not break sibling waiters.
                pass

    def _fetch_and_cache(self, norm: str) -> Optional[Path]:
        # Re-check disk (another process may have filled cache).
        existing = self._cache_dir / f"{norm}.png"
        if existing.is_file():
            return existing

        requests = _ensure_requests()
        profile_url = _SESSION_URL.format(uuid=norm)
        response = requests.get(profile_url, timeout=_REQUEST_TIMEOUT)
        if response.status_code != 200:
            return None
        try:
            profile = response.json()
        except ValueError:
            return None
        if not isinstance(profile, dict):
            return None

        skin_url = parse_skin_url_from_profile(profile)
        if not skin_url:
            return None

        skin_resp = requests.get(skin_url, timeout=_REQUEST_TIMEOUT)
        if skin_resp.status_code != 200:
            return None
        skin_bytes = skin_resp.content
        if not skin_bytes or len(skin_bytes) > 4 * 1024 * 1024:
            return None
        if not skin_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
            return None

        face_png = crop_face_png(skin_bytes, size=_FACE_SIZE)
        atomic_write_bytes(existing, face_png)
        return existing

    def clear_failed(self) -> None:
        with self._lock:
            self._failed.clear()
