"""
类型定义模块

定义项目中使用的通用类型别名，提高代码可读性和类型安全。
"""
from typing import Any, Callable, Dict, List, Optional, TYPE_CHECKING, Tuple, Union
from pathlib import Path

# 日志回调类型
LogCallback = Callable[[str, str], None]

# 进度回调类型
ProgressCallback = Callable[[float], None]

# UUID 映射类型 (实际结构)
# (旧 UUID 整数列表, 新 UUID 整数列表, 旧 UUID 字符串, 新 UUID 字符串, 旧 UUID (Most, Least), 新 UUID (Most, Least))
UUIDMapping = Tuple[
    List[int],           # 旧 UUID 整数列表 (uuid_to_ints 结果)
    List[int],           # 新 UUID 整数列表 (uuid_to_ints 结果)
    str,                 # 旧 UUID 字符串（用于字符串匹配）
    str,                 # 新 UUID 字符串（用于字符串匹配）
    Tuple[int, int],     # 旧 UUID (Most, Least)
    Tuple[int, int]      # 新 UUID (Most, Least)
]

# 处理结果类型
ProcessResult = Dict[str, Any]

# 玩家名列表
PlayerNameList = List[str]

# 批量处理结果
BatchResult = Dict[str, Dict[str, Any]]

# 文件扫描结果
FileScanResult = List[Path]

# NBT 标签类型（延迟导入：避免 types 模块在启动期就拉入 nbtlib 重库。
# 类型注解在运行时无需真实类型，用 TYPE_CHECKING 守卫即可。）
if TYPE_CHECKING:
    import nbtlib
    NBTTag = Union[
        "nbtlib.tag.Compound",
        "nbtlib.tag.List",
        "nbtlib.tag.String",
        "nbtlib.tag.IntArray",
        "nbtlib.tag.Long",
        "nbtlib.tag.Int",
        "nbtlib.tag.Byte",
        "nbtlib.tag.Short",
        "nbtlib.tag.Float",
        "nbtlib.tag.Double",
        Any
    ]
else:
    NBTTag = Any

# 配置字典类型
ConfigDict = Dict[str, Any]

# 玩家数据字典
PlayerDataDict = Dict[str, str]  # UUID -> 玩家名

# 区域文件处理结果
RegionProcessResult = Tuple[str, int, Optional[str]]  # (文件路径, 修改次数, 错误信息)

# 缓存加载结果
CacheLoadResult = Dict[str, str]  # UUID -> 玩家名

# API 响应类型
APIResponse = Dict[str, Any]

# 版本映射类型
VersionMap = Dict[str, int]
