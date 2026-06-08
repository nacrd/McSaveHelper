"""玩家名-UUID 映射模型"""
from dataclasses import dataclass


@dataclass
class PlayerMapping:
    """单个玩家映射条目

    用于存储玩家名称与UUID的对应关系，并提供验证和转换功能。
    """
    player_name: str
    """玩家名称"""

    uuid: str
    """玩家UUID字符串"""

    @property
    def is_valid(self) -> bool:
        """验证映射是否有效

        检查玩家名称和UUID格式是否都有效。

        Returns:
            bool: 如果玩家名不为空且UUID格式正确则返回True，否则返回False
        """
        return bool(
            self.player_name.strip() and self._validate_uuid_format(
                self.uuid.strip()))

    @staticmethod
    def _validate_uuid_format(uuid_str: str) -> bool:
        """简单 UUID 格式验证

        验证UUID字符串是否符合标准格式（xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx）。

        Args:
            uuid_str: 待验证的UUID字符串

        Returns:
            bool: 如果UUID格式正确则返回True，否则返回False
        """
        parts = uuid_str.replace("-", "")
        if len(parts) != 32:
            return False
        try:
            int(parts, 16)
            return True
        except ValueError:
            return False

    def to_tuple(self) -> tuple[str, str]:
        """将映射转换为元组格式

        Returns:
            tuple[str, str]: 包含玩家名和UUID的元组
        """
        return (self.player_name, self.uuid)

    @classmethod
    def from_tuple(cls, name: str, uuid: str) -> "PlayerMapping":
        """从元组创建PlayerMapping实例

        Args:
            name: 玩家名称
            uuid: 玩家UUID字符串

        Returns:
            PlayerMapping: 新创建的PlayerMapping实例
        """
        return cls(player_name=name, uuid=uuid)
