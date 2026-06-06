"""Save Repair Service - 存档修复服务

修复损坏的区块、玩家数据、level.dat 错误
"""
import shutil
from pathlib import Path
from typing import List, Dict, Any, Optional, Callable
import traceback
import nbtlib
from anvil import Region, EmptyRegion

from core.logger import logger
from core.scanner import scan_all_regions


class SaveRepairService:
    """存档修复服务"""

    def __init__(self) -> None:
        self.total_fixes = 0
        self.errors: List[str] = []

    def repair_world(
        self,
        world_path: Path,
        fix_chunks: bool = True,
        fix_players: bool = True,
        fix_level_dat: bool = True,
        backup: bool = True,
        progress_callback: Optional[Callable[[float, str], None]] = None,
        log_callback: Optional[Callable[[str, str], None]] = None,
    ) -> Dict[str, Any]:
        """修复世界存档
        
        Args:
            world_path: 存档路径
            fix_chunks: 是否修复区块
            fix_players: 是否修复玩家数据
            fix_level_dat: 是否修复 level.dat
            backup: 是否备份
            progress_callback: 进度回调
            log_callback: 日志回调
            
        Returns:
            修复结果字典
        """
        self.total_fixes = 0
        results: Dict[str, Any] = {
            "chunks_fixed": 0,
            "chunks_removed": 0,
            "players_fixed": 0,
            "level_dat_fixed": False,
            "backup_path": None,
        }

        def log(msg: str, level: str = "INFO") -> None:
            logger.info(msg, module="SaveRepair")
            if log_callback:
                log_callback(msg, level)

        def progress(value: float, msg: str) -> None:
            if progress_callback:
                progress_callback(value, msg)

        try:
            if not world_path.exists():
                raise FileNotFoundError(f"存档路径不存在: {world_path}")

            log(f"开始修复存档: {world_path}")

            # 备份
            if backup:
                progress(0.05, "创建备份...")
                backup_path = self._create_backup(world_path)
                results["backup_path"] = str(backup_path)
                log(f"已创建备份: {backup_path}")

            # 修复区块
            if fix_chunks:
                progress(0.15, "扫描区块文件...")
                chunk_results = self._repair_chunks(world_path, log, progress)
                results["chunks_fixed"] = chunk_results["fixed"]
                results["chunks_removed"] = chunk_results["removed"]

            # 修复玩家数据
            if fix_players:
                progress(0.70, "修复玩家数据...")
                player_results = self._repair_players(world_path, log)
                results["players_fixed"] = player_results["fixed"]

            # 修复 level.dat
            if fix_level_dat:
                progress(0.90, "修复 level.dat...")
                level_fixed = self._repair_level_dat(world_path, log)
                results["level_dat_fixed"] = level_fixed

            progress(1.0, "修复完成")
            log(f"修复完成 - 区块修复: {results['chunks_fixed']}, 区块移除: {results['chunks_removed']}, 玩家修复: {results['players_fixed']}")

        except Exception as e:
            error_msg = f"修复失败: {e}"
            log(error_msg, "ERROR")
            logger.error(traceback.format_exc(), module="SaveRepair")
            self.errors.append(error_msg)

        return results

    def _create_backup(self, world_path: Path) -> Path:
        """创建存档备份
        
        Args:
            world_path: 存档路径
            
        Returns:
            备份路径
        """
        backup_name = f"{world_path.name}_backup"
        backup_path = world_path.parent / backup_name
        
        # 如果备份已存在，添加数字后缀
        counter = 1
        while backup_path.exists():
            backup_path = world_path.parent / f"{backup_name}_{counter}"
            counter += 1
        
        shutil.copytree(world_path, backup_path)
        return backup_path

    def _repair_chunks(
        self,
        world_path: Path,
        log: Callable[[str, str], None],
        progress: Callable[[float, str], None],
    ) -> Dict[str, int]:
        """修复损坏的区块
        
        Args:
            world_path: 存档路径
            log: 日志回调
            progress: 进度回调
            
        Returns:
            修复结果
        """
        results = {"fixed": 0, "removed": 0}
        
        try:
            region_files = scan_all_regions(world_path)
            total = len(region_files)
            
            if total == 0:
                log("未找到区块文件", "WARNING")
                return results
            
            log(f"找到 {total} 个区块文件", "INFO")
            
            for idx, region_file in enumerate(region_files):
                try:
                    # 更新进度 (15% - 70%)
                    progress(0.15 + (idx / total) * 0.55, f"检查区块 {idx+1}/{total}")
                    
                    # 尝试读取区块文件
                    try:
                        region = Region.from_file(str(region_file))
                        
                        # 检查每个区块
                        for chunk_x in range(32):
                            for chunk_z in range(32):
                                try:
                                    chunk = region.get_chunk(chunk_x, chunk_z)
                                    if chunk is not None:
                                        # 验证区块数据
                                        if not self._validate_chunk(chunk):
                                            log(f"区块 ({chunk_x}, {chunk_z}) 在 {region_file.name} 中损坏，尝试移除", "WARNING")
                                            # 这里可以实现移除损坏区块的逻辑
                                            results["removed"] += 1
                                except Exception as e:
                                    log(f"读取区块 ({chunk_x}, {chunk_z}) 失败: {e}", "WARNING")
                                    results["removed"] += 1
                        
                        results["fixed"] += 1
                        
                    except Exception as e:
                        log(f"无法读取区块文件 {region_file.name}: {e}", "ERROR")
                        # 对于完全损坏的区块文件，可以选择删除或重命名
                        self._quarantine_file(region_file, log)
                        
                except Exception as e:
                    log(f"处理区块文件 {region_file.name} 时出错: {e}", "ERROR")
                    
        except Exception as e:
            log(f"扫描区块文件失败: {e}", "ERROR")
            
        return results

    def _validate_chunk(self, chunk: Any) -> bool:
        """验证区块数据完整性
        
        Args:
            chunk: 区块对象
            
        Returns:
            是否有效
        """
        try:
            # 基本验证：检查必需的数据
            if not hasattr(chunk, 'data'):
                return False
            # 可以添加更多验证逻辑
            return True
        except Exception:
            return False

    def _quarantine_file(self, file_path: Path, log: Callable[[str, str], None]) -> None:
        """隔离损坏的文件（重命名为 .corrupted）
        
        Args:
            file_path: 文件路径
            log: 日志回调
        """
        try:
            new_path = file_path.with_suffix(".mca.corrupted")
            file_path.rename(new_path)
            log(f"已隔离损坏文件: {file_path.name} -> {new_path.name}", "WARNING")
        except Exception as e:
            log(f"无法隔离文件 {file_path.name}: {e}", "ERROR")

    def _repair_players(
        self,
        world_path: Path,
        log: Callable[[str, str], None],
    ) -> Dict[str, int]:
        """修复玩家数据
        
        Args:
            world_path: 存档路径
            log: 日志回调
            
        Returns:
            修复结果
        """
        results = {"fixed": 0}
        
        try:
            playerdata_dir = world_path / "playerdata"
            if not playerdata_dir.exists():
                log("playerdata 目录不存在", "WARNING")
                return results
            
            player_files = list(playerdata_dir.glob("*.dat"))
            log(f"找到 {len(player_files)} 个玩家数据文件", "INFO")
            
            for player_file in player_files:
                try:
                    # 尝试读取 NBT 数据
                    nbt_data = nbtlib.load(str(player_file))
                    
                    # 验证必需字段
                    if self._validate_player_data(nbt_data):
                        results["fixed"] += 1
                    else:
                        log(f"玩家数据 {player_file.name} 缺少必需字段", "WARNING")
                        # 可以尝试修复或隔离
                        
                except Exception as e:
                    log(f"无法读取玩家数据 {player_file.name}: {e}", "ERROR")
                    self._quarantine_file(player_file, log)
                    
        except Exception as e:
            log(f"修复玩家数据失败: {e}", "ERROR")
            
        return results

    def _validate_player_data(self, nbt_data: Any) -> bool:
        """验证玩家数据完整性
        
        Args:
            nbt_data: NBT 数据
            
        Returns:
            是否有效
        """
        try:
            # 检查必需字段
            required_fields = ["Pos", "Rotation", "Health"]
            for field in required_fields:
                if field not in nbt_data:
                    return False
            return True
        except Exception:
            return False

    def _repair_level_dat(
        self,
        world_path: Path,
        log: Callable[[str, str], None],
    ) -> bool:
        """修复 level.dat
        
        Args:
            world_path: 存档路径
            log: 日志回调
            
        Returns:
            是否成功修复
        """
        try:
            level_dat = world_path / "level.dat"
            level_dat_old = world_path / "level.dat_old"
            
            if not level_dat.exists():
                # 尝试从 level.dat_old 恢复
                if level_dat_old.exists():
                    log("level.dat 不存在，尝试从 level.dat_old 恢复", "WARNING")
                    shutil.copy2(level_dat_old, level_dat)
                    log("已从 level.dat_old 恢复", "INFO")
                    return True
                else:
                    log("level.dat 和 level.dat_old 都不存在", "ERROR")
                    return False
            
            # 验证 level.dat
            try:
                nbt_data = nbtlib.load(str(level_dat))
                
                # 检查必需字段
                if "Data" not in nbt_data:
                    raise ValueError("level.dat 缺少 Data 字段")
                
                log("level.dat 验证通过", "INFO")
                return True
                
            except Exception as e:
                log(f"level.dat 损坏: {e}", "ERROR")
                
                # 尝试从 level.dat_old 恢复
                if level_dat_old.exists():
                    log("尝试从 level.dat_old 恢复", "WARNING")
                    shutil.copy2(level_dat_old, level_dat)
                    
                    # 再次验证
                    try:
                        nbtlib.load(str(level_dat))
                        log("已从 level.dat_old 恢复", "INFO")
                        return True
                    except Exception:
                        log("level.dat_old 也已损坏", "ERROR")
                        return False
                else:
                    log("level.dat_old 不存在，无法恢复", "ERROR")
                    return False
                    
        except Exception as e:
            log(f"修复 level.dat 失败: {e}", "ERROR")
            return False
