"""纹理服务 - 管理 Minecraft 物品纹理的获取、缓存和提供"""
import base64
import logging
import os
import platform
import threading
import zipfile
from collections import OrderedDict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests

logger = logging.getLogger(__name__)

_ASSET_INDEX_URL = "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json"
_RESOURCE_BASE_URL = "https://resources.download.minecraft.net"
_JAR_TEXTURE_PREFIX = "assets/minecraft/textures/"
_REQUEST_TIMEOUT = 10
_MAX_MEMORY_CACHE = 500

_BLOCK_SUFFIXES = (
    "_block", "_ore", "_log", "_wood", "_stem", "_planks", "_stone",
    "_bricks", "_glass", "_wool", "_carpet", "_bed", "_door", "_fence",
    "_wall", "_slab", "_stairs", "_pane", "_shulker_box", "_leaves",
    "_sand", "_concrete", "_terracotta", "_glazed_terracotta",
    "_copper", "_nylium", "_basalt", "_blackstone", "_deepslate",
    "_concrete_powder",
)
_BLOCK_PREFIXES = (
    "chest", "barrel", "composter", "lectern", "beehive", "campfire",
    "torch", "lantern", "anvil", "cauldron", "brewing_stand",
    "enchanting_table", "end_rod", "observer", "piston", "hopper",
    "dispenser", "dropper", "furnace", "tnt", "note_block",
    "jukebox", "respawn_anchor", "lodestone",
)
_BLOCK_EXACT = {
    "dirt", "grass_block", "stone", "cobblestone", "glass", "sand",
    "gravel", "obsidian", "crying_obsidian", "bedrock", "crafting_table",
    "chest", "ender_chest", "beacon", "moss_block", "mud", "clay",
    "snow_block", "ice", "packed_ice", "blue_ice", "sponge", "wet_sponge",
    "melon", "pumpkin", "hay_block", "bone_block", "dried_kelp_block",
    "slime_block", "honey_block", "mushroom_stem",
    "smooth_stone", "sandstone", "red_sandstone", "prismarine",
    "netherrack", "nether_bricks", "red_nether_bricks", "end_stone",
    "purpur_block", "quartz_block", "amethyst_block", "calcite",
    "tuff", "dripstone_block", "pointed_dripstone",
    "sculk", "sculk_catalyst", "sculk_shrieker", "sculk_sensor",
    "mangrove_roots", "muddy_mangrove_roots",
    "ochre_froglight", "verdant_froglight", "pearlescent_froglight",
    "reinforced_deepslate", "frogspawn",
    "sea_lantern", "glowstone", "redstone_lamp",
    "coal_block", "iron_block", "gold_block", "diamond_block",
    "emerald_block", "lapis_block", "redstone_block", "netherite_block",
    "copper_block", "raw_iron_block", "raw_gold_block", "raw_copper_block",
    "white_wool", "orange_wool", "magenta_wool", "light_blue_wool",
    "yellow_wool", "lime_wool", "pink_wool", "gray_wool",
    "light_gray_wool", "cyan_wool", "purple_wool", "blue_wool",
    "brown_wool", "green_wool", "red_wool", "black_wool",
}


def _guess_is_block(local_id: str) -> bool:
    if local_id in _BLOCK_EXACT:
        return True
    for prefix in _BLOCK_PREFIXES:
        if local_id.startswith(prefix):
            return True
    for suffix in _BLOCK_SUFFIXES:
        if local_id.endswith(suffix):
            return True
    return False


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
        self._jar_cache_dir = Path.home() / ".mc_save_helper" / "jars"
        self._jar_cache_dir.mkdir(parents=True, exist_ok=True)
        self._memory_cache: OrderedDict[str, Path] = OrderedDict()
        self._base64_cache: OrderedDict[str, str] = OrderedDict()
        self._minecraft_jar: Optional[Path] = None
        self._asset_index: Optional[Dict[str, str]] = None
        self._asset_index_loaded = False
        self._jar_download_attempted = False
        self._lock = threading.Lock()
        self._tried_paths: Dict[str, str] = {}

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
        if not item_id or ":" not in item_id:
            return None

        with self._lock:
            if item_id in self._base64_cache:
                self._base64_cache.move_to_end(item_id)
                return self._base64_cache[item_id]

        path = self.get_texture_path(item_id)
        if path is None or not path.exists():
            return None

        try:
            data = path.read_bytes()
            if len(data) == 0:
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
        on_loaded: Optional[callable] = None,
    ) -> None:
        """在后台线程中批量加载纹理，每完成一个回调 (item_id, base64_uri_or_None)"""
        def _worker():
            for item_id in item_ids:
                uri = self.get_texture_base64(item_id)
                if on_loaded:
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
        path = self._cache_dir / texture_res
        if path.exists() and path.stat().st_size > 0:
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
        asset_keys = self._get_asset_index_keys()

        if _guess_is_block(local_id):
            block_key = f"textures/block/{local_id}.png"
            if self._asset_index_has(asset_keys, block_key):
                return block_key
            item_key = f"textures/item/{local_id}.png"
            if self._asset_index_has(asset_keys, item_key):
                return item_key
            return block_key

        item_key = f"textures/item/{local_id}.png"
        if self._asset_index_has(asset_keys, item_key):
            return item_key
        block_key = f"textures/block/{local_id}.png"
        if self._asset_index_has(asset_keys, block_key):
            return block_key
        return item_key

    def _get_asset_index_keys(self) -> Optional[Dict[str, str]]:
        if not self._asset_index_loaded:
            self._load_asset_index()
        return self._asset_index

    @staticmethod
    def _asset_index_has(asset_keys: Optional[Dict[str, str]], res_path: str) -> bool:
        if asset_keys is None:
            return False
        mc_key = f"minecraft/{res_path}"
        return mc_key in asset_keys

    def _try_extract_from_jar(self, texture_res: str) -> Optional[bytes]:
        jar = self._find_or_get_jar()
        if jar is None:
            return None
        try:
            with zipfile.ZipFile(jar) as zf:
                jar_path = f"{_JAR_TEXTURE_PREFIX}{texture_res.split('/', 1)[-1]}"
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
        path = self._cache_dir / texture_res
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def _put_memory_cache(self, item_id: str, path: Path) -> None:
        with self._lock:
            self._memory_cache[item_id] = path
            self._memory_cache.move_to_end(item_id)
            while len(self._memory_cache) > _MAX_MEMORY_CACHE:
                self._memory_cache.popitem(last=False)

    def _find_or_get_jar(self) -> Optional[Path]:
        if self._minecraft_jar and self._minecraft_jar.exists():
            return self._minecraft_jar
        
        # 尝试从本地查找
        self._minecraft_jar = self.find_minecraft_jar()
        if self._minecraft_jar:
            return self._minecraft_jar
        
        # 尝试从缓存下载的 JAR
        if not self._jar_download_attempted:
            self._minecraft_jar = self._download_client_jar()
            self._jar_download_attempted = True
        
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

    def _download_client_jar(self) -> Optional[Path]:
        """从 Mojang 官方下载客户端 JAR，并自动清理旧版本"""
        try:
            logger.info("开始下载 Minecraft 客户端 JAR...")
            
            # 0. 清理旧版本 JAR（保留最新的 1-2 个版本）
            self._cleanup_old_jars(keep_count=1)
            
            # 1. 获取版本清单
            resp = requests.get(_ASSET_INDEX_URL, timeout=_REQUEST_TIMEOUT)
            if resp.status_code != 200:
                logger.warning("无法获取版本清单")
                return None
            
            manifest = resp.json()
            latest_id = manifest.get("latest", {}).get("release")
            if not latest_id:
                logger.warning("无法获取最新版本 ID")
                return None
            
            logger.info(f"最新版本: {latest_id}")
            
            # 2. 获取版本 URL
            version_url = None
            for v in manifest.get("versions", []):
                if v.get("id") == latest_id:
                    version_url = v.get("url")
                    break
            
            if not version_url:
                logger.warning("无法获取版本 URL")
                return None
            
            # 3. 获取版本数据
            resp2 = requests.get(version_url, timeout=_REQUEST_TIMEOUT)
            if resp2.status_code != 200:
                logger.warning("无法获取版本数据")
                return None
            
            version_data = resp2.json()
            client_info = version_data.get("downloads", {}).get("client")
            if not client_info:
                logger.warning("无法获取客户端下载信息")
                return None
            
            jar_url = client_info.get("url")
            jar_sha1 = client_info.get("sha1")
            jar_size = client_info.get("size", 0)
            
            if not jar_url:
                logger.warning("无法获取 JAR 下载 URL")
                return None
            
            # 4. 检查缓存
            jar_path = self._jar_cache_dir / f"minecraft-{latest_id}-client.jar"
            if jar_path.exists():
                # 验证 SHA1
                import hashlib
                with open(jar_path, "rb") as f:
                    file_hash = hashlib.sha1(f.read()).hexdigest()
                if file_hash == jar_sha1:
                    logger.info(f"使用缓存的 JAR: {jar_path}")
                    return jar_path
                else:
                    logger.warning("缓存的 JAR SHA1 校验失败，重新下载")
                    jar_path.unlink()
            
            # 5. 下载 JAR
            logger.info(f"开始下载 JAR ({jar_size / 1024 / 1024:.1f} MB)...")
            resp3 = requests.get(jar_url, timeout=300, stream=True)
            if resp3.status_code != 200:
                logger.warning(f"下载失败: HTTP {resp3.status_code}")
                return None
            
            # 流式写入文件
            with open(jar_path, "wb") as f:
                downloaded = 0
                for chunk in resp3.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if downloaded % (1024 * 1024) == 0:  # 每 1MB 记录一次
                            logger.debug(f"已下载: {downloaded / 1024 / 1024:.1f} MB")
            
            logger.info(f"JAR 下载完成: {jar_path}")
            return jar_path
            
        except Exception as e:
            logger.error(f"下载 JAR 失败: {e}")
            return None

    def _cleanup_old_jars(self, keep_count: int = 1) -> None:
        """清理旧版本 JAR 文件，只保留最新的 N 个版本"""
        try:
            if not self._jar_cache_dir.exists():
                return
            
            # 获取所有 JAR 文件
            jar_files = list(self._jar_cache_dir.glob("minecraft-*-client.jar"))
            if len(jar_files) <= keep_count:
                return  # 文件数量未超过保留数量，无需清理
            
            # 按修改时间排序（最新的在前）
            jar_files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            
            # 删除旧文件
            for old_jar in jar_files[keep_count:]:
                try:
                    size_mb = old_jar.stat().st_size / 1024 / 1024
                    old_jar.unlink()
                    logger.info(f"已清理旧版本 JAR: {old_jar.name} ({size_mb:.1f} MB)")
                except Exception as e:
                    logger.warning(f"清理 JAR 失败 {old_jar.name}: {e}")
            
        except Exception as e:
            logger.warning(f"清理旧 JAR 文件时出错: {e}")

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

    def clear_cache(self, clear_textures: bool = True, clear_jars: bool = False) -> None:
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
                    logger.info(f"已清理 {deleted_count} 个 JAR 文件 ({deleted_size / 1024 / 1024:.1f} MB)")
            except Exception as e:
                logger.warning(f"清理 JAR 缓存失败: {e}")


def get_texture_service() -> TextureService:
    return TextureService()
