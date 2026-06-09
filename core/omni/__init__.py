"""Core Omni Package —— 核心扩展模块（重构版）

这个模块提供了模块化的存档会话管理功能。
所有功能按职责拆分到独立模块，主 WorldSession 类作为门面协调各模块。

模块结构：
- models.py: 数据模型（WorldInfo, Action, ChunkTarget）
- world_scanner.py: 文件扫描器
- nbt_loader.py: NBT 延迟加载器
- player_manager.py: 玩家数据管理器
- action_queue.py: 操作队列管理器
- action_executor.py: 操作执行器
- backup_manager.py: 备份和恢复管理器
- world_session_refactored.py: 主会话类（门面）

注意：为了保持向后兼容，旧的 world_session.py 仍然保留，
但推荐使用重构后的版本（从 world_session_refactored 导入）。

使用示例：
    # 推荐方式（使用重构版）
    from core.omni.world_session_refactored import WorldSession

    # 或者通过包导入（自动使用重构版）
    from core.omni import WorldSession, WorldInfo
"""

# 导出数据模型
from .models import WorldInfo, Action, ChunkTarget

# 导出主会话类（重构版）
from .world_session_refactored import WorldSession

# 向后兼容：保留旧的导入路径
__all__ = [
    'WorldSession',
    'WorldInfo',
    'Action',
    'ChunkTarget',
]
