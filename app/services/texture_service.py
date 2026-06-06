"""纹理服务 - 管理 Minecraft 物品纹理的获取、缓存和提供"""
import logging
import os
import platform
import threading
import zipfile
from collections import OrderedDict
from pathlib import Path
from typing import Dict, Optional, Set

import requests

logger = logging.getLogger(__name__)

_BLOCK_ITEMS: Set[str] = {
    "minecraft:dirt", "minecraft:grass_block", "minecraft:stone",
    "minecraft:cobblestone", "minecraft:oak_log", "minecraft:spruce_log",
    "minecraft:birch_log", "minecraft:jungle_log", "minecraft:acacia_log",
    "minecraft:dark_oak_log", "minecraft:oak_planks", "minecraft:glass",
    "minecraft:sand", "minecraft:gravel", "minecraft:obsidian",
    "minecraft:crying_obsidian", "minecraft:bedrock",
    "minecraft:crafting_table", "minecraft:furnace", "minecraft:chest",
    "minecraft:ender_chest", "minecraft:shulker_box", "minecraft:beacon",
    "minecraft:anvil", "minecraft:enchanting_table",
    "minecraft:brewing_stand", "minecraft:cauldron",
    "minecraft:torch", "minecraft:soul_torch", "minecraft:redstone_torch",
    "minecraft:lantern", "minecraft:soul_lantern",
    "minecraft:diamond_ore", "minecraft:iron_ore", "minecraft:gold_ore",
    "minecraft:coal_ore", "minecraft:emerald_ore", "minecraft:lapis_ore",
    "minecraft:redstone_ore", "minecraft:copper_ore",
    "minecraft:nether_gold_ore", "minecraft:nether_quartz_ore",
    "minecraft:ancient_debris",
    "minecraft:deepslate_diamond_ore", "minecraft:deepslate_iron_ore",
    "minecraft:deepslate_gold_ore", "minecraft:deepslate_coal_ore",
    "minecraft:deepslate_emerald_ore", "minecraft:deepslate_lapis_ore",
    "minecraft:deepslate_redstone_ore", "minecraft:deepslate_copper_ore",
}

_ASSET_INDEX_URL = "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json"
_RESOURCE_BASE_URL = "https://resources.download.minecraft.net"
_JAR_TEXTURE_PREFIX = "assets/minecraft/textures/"
_REQUEST_TIMEOUT = 10
_MAX_MEMORY_CACHE = 500


class TextureService:
    """纹理服务 - 管理物品纹理的获取和缓存

    优先级: 内存缓存 > 本地文件缓存 > JAR提取 > 在线API
    """

    _instance: Optional['TextureService'] = None

    def __new__(cls) -> 'TextureService':
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._init()
        return cls._instance

    def _init(self) -> None:
        self._cache_dir = Path.home() / ".mc_save_helper" / "textures"
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._memory_cache: OrderedDict[str, Path] = OrderedDict()
        self._minecraft_jar: Optional[Path] = None
        self._asset_index: Optional[Dict[str, str]] = None
        self._asset_index_loaded = False
        self._lock = threading.Lock()

    def get_texture_path(self, item_id: str) -> Optional[Path]:
        if not item_id or ":" not in item_id:
            return None

        cached = self._try_memory_cache(item_id)
        if cached:
            return cached

        cached = self._try_file_cache(item_id)
        if cached:
            self._put_memory_cache(item_id, cached)
            return cached

        texture_res = self._item_id_to_texture_resource(item_id)

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
        texture_res = self._item_id_to_texture_resource(item_id)
        path = self._cache_dir / texture_res
        if path.exists() and path.stat().st_size > 0:
            return path
        return None

    def _try_extract_from_jar(self, texture_res: str) -> Optional[bytes]:
        jar = self._find_or_get_jar()
        if jar is None:
            return None
        try:
            with zipfile.ZipFile(jar) as zf:
                jar_path = f"{_JAR_TEXTURE_PREFIX}{texture_res.split('/', 1)[-1]}"
                if jar_path in zf.namelist():
                    return zf.read(jar_path)
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
        path = self._cache_dir / texture_res
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def _item_id_to_texture_resource(self, item_id: str) -> str:
        if ":" in item_id:
            _, local_id = item_id.split(":", 1)
        else:
            local_id = item_id

        if item_id in _BLOCK_ITEMS:
            return f"textures/block/{local_id}.png"
        return f"textures/item/{local_id}.png"

    def _put_memory_cache(self, item_id: str, path: Path) -> None:
        with self._lock:
            self._memory_cache[item_id] = path
            self._memory_cache.move_to_end(item_id)
            while len(self._memory_cache) > _MAX_MEMORY_CACHE:
                self._memory_cache.popitem(last=False)

    def _find_or_get_jar(self) -> Optional[Path]:
        if self._minecraft_jar and self._minecraft_jar.exists():
            return self._minecraft_jar
        self._minecraft_jar = self.find_minecraft_jar()
        return self._minecraft_jar

    def find_minecraft_jar(self) -> Optional[Path]:
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

        jars.sort(key=lambda x: x[0], reverse=True)
        return jars[0][1]

    def set_minecraft_jar(self, path: Path) -> None:
        self._minecraft_jar = path

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

    def clear_cache(self) -> None:
        with self._lock:
            self._memory_cache.clear()
        if self._cache_dir.exists():
            for f in self._cache_dir.rglob("*.png"):
                try:
                    f.unlink()
                except Exception:
                    pass


def get_texture_service() -> TextureService:
    return TextureService()
