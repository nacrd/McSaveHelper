"""批量处理模块，支持同时处理多个存档"""
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import List, Dict, Any, Callable
import queue

from .config import config_manager


class BatchProcessor:
    """批量处理器"""
    
    def __init__(self, max_workers: int = None):
        self.max_workers = max_workers or config_manager.config["batch_processing"]["max_concurrent"]
        self.progress_queue = queue.Queue()
        self.results = {}
        self.is_running = False
    
    def process_batch(self, 
                     world_paths: List[Path], 
                     dest_dir: Path,
                     world_names: List[str] = None,
                     mode: str = "fast",
                     offline_mode: bool = False,
                     clean_mode: bool = True,
                     manual_names: List[str] = None,
                     log_callback: Callable = None,
                     progress_callback: Callable = None) -> Dict[str, Dict[str, Any]]:
        """
        批量处理多个世界存档
        
        Args:
            world_paths: 源世界路径列表
            dest_dir: 目标目录
            world_names: 目标世界名称列表（可选）
            mode: 处理模式（fast/full）
            offline_mode: 是否离线模式
            clean_mode: 是否清理模式
            manual_names: 手动玩家名列表
            log_callback: 日志回调函数
            progress_callback: 进度回调函数
            
        Returns:
            处理结果字典
        """
        self.is_running = True
        self.results = {}
        
        total_tasks = len(world_paths)
        
        if not world_names:
            world_names = [f"world_{i+1}" for i in range(total_tasks)]
        
        if log_callback:
            log_callback(f"开始批量处理 {total_tasks} 个存档...", "INFO")
        
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # 提交所有任务
            future_to_world = {}
            for i, (world_path, world_name) in enumerate(zip(world_paths, world_names)):
                future = executor.submit(
                    self._process_single_world,
                    world_path, dest_dir, world_name, mode, offline_mode, clean_mode,
                    manual_names, log_callback, i, total_tasks
                )
                future_to_world[future] = (world_path.name, world_name, i)
            
            # 处理完成的任务
            completed_count = 0
            for future in as_completed(future_to_world):
                world_path_name, world_name, task_index = future_to_world[future]
                
                try:
                    result = future.result()
                    self.results[world_path_name] = result
                    completed_count += 1
                    
                    if log_callback:
                        status = "成功" if result["success"] else "失败"
                        log_callback(f"任务 {task_index+1}/{total_tasks}: {world_name} - {status}", 
                                   "SUCCESS" if result["success"] else "ERROR")
                    
                    if progress_callback:
                        progress = completed_count / total_tasks
                        progress_callback(progress)
                        
                except Exception as e:
                    error_result = {
                        "success": False,
                        "error": str(e),
                        "world_name": world_name
                    }
                    self.results[world_path_name] = error_result
                    
                    if log_callback:
                        log_callback(f"任务 {task_index+1}/{total_tasks}: {world_name} - 失败: {e}", "ERROR")
        
        self.is_running = False
        
        # 统计结果
        success_count = sum(1 for r in self.results.values() if r["success"])
        if log_callback:
            log_callback(f"批量处理完成: {success_count}/{total_tasks} 个存档处理成功", 
                       "SUCCESS" if success_count == total_tasks else "WARN")
        
        return self.results
    
    def _process_single_world(self, 
                            world_path: Path, 
                            dest_dir: Path, 
                            world_name: str,
                            mode: str,
                            offline_mode: bool,
                            clean_mode: bool,
                            manual_names: List[str],
                            log_callback: Callable,
                            task_index: int,
                            total_tasks: int) -> Dict[str, Any]:
        """处理单个世界存档"""
        
        def local_log(msg: str, level: str = "INFO"):
            """本地日志函数"""
            if log_callback:
                log_callback(f"[{task_index+1}/{total_tasks}] {msg}", level)
        
        try:
            # 检测版本
            version = config_manager.detect_minecraft_version(world_path)
            if version:
                local_log(f"检测到版本: {version}", "INFO")
            
            # 导入对应的处理模块
            if mode == "fast":
                from .fast_mode import run_fast
                run_fast(world_path, dest_dir, world_name, offline_mode, clean_mode, manual_names, local_log)
            else:
                from .full_mode import run_full
                from .worker import dummy_progress
                run_full(world_path, dest_dir, world_name, offline_mode, clean_mode, manual_names, local_log, dummy_progress)
            
            return {
                "success": True,
                "world_name": world_name,
                "version": version
            }
            
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "world_name": world_name
            }
    
    def stop(self):
        """停止批量处理"""
        self.is_running = False
    
    def get_progress(self) -> float:
        """获取当前进度"""
        if not self.results:
            return 0.0
        total = len(self.results)
        completed = sum(1 for r in self.results.values() if r.get("completed", False))
        return completed / total if total > 0 else 0.0


def scan_worlds_directory(directory: Path) -> List[Path]:
    """扫描目录中的世界存档"""
    worlds = []
    
    if not directory.exists():
        return worlds
    
    # 查找包含level.dat的目录
    for item in directory.iterdir():
        if item.is_dir():
            level_dat = item / "level.dat"
            if level_dat.exists():
                worlds.append(item)
    
    return sorted(worlds)