"""当前存档上下文值对象。"""
from dataclasses import dataclass
from pathlib import Path


@dataclass
class CurrentSaveContext:
    """侧栏/页面共享的当前世界路径与有效性快照。

    Attributes:
        path: 世界根目录。
        name: 目录名（展示用）。
        is_valid: 是否存在 ``level.dat``。
        edition / version: 可选元数据（解析后填充）。
    """

    path: Path
    name: str
    is_valid: bool
    edition: str = "unknown"
    version: str = "unknown"

    @classmethod
    def from_path(cls, path: str | Path) -> "CurrentSaveContext":
        """由路径构造上下文；以 ``level.dat`` 判定是否有效世界。

        Args:
            path: 世界目录路径。
        """
        save_path = Path(path)
        return cls(
            path=save_path,
            name=save_path.name,
            is_valid=(save_path / "level.dat").exists(),
        )

    @property
    def display_path(self) -> str:
        """UI 展示用的路径字符串。"""
        return str(self.path)
