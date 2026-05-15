"""玩家名-UUID 映射模型"""
from dataclasses import dataclass


@dataclass
class PlayerMapping:
    """单个玩家映射条目"""
    player_name: str
    uuid: str

    @property
    def is_valid(self) -> bool:
        """验证映射是否有效"""
        return bool(self.player_name.strip() and self._validate_uuid_format(self.uuid.strip()))

    @staticmethod
    def _validate_uuid_format(uuid_str: str) -> bool:
        """简单 UUID 格式验证（xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx）"""
        parts = uuid_str.replace("-", "")
        if len(parts) != 32:
            return False
        try:
            int(parts, 16)
            return True
        except ValueError:
            return False

    def to_tuple(self) -> tuple[str, str]:
        return (self.player_name, self.uuid)

    @classmethod
    def from_tuple(cls, name: str, uuid: str) -> "PlayerMapping":
        return cls(player_name=name, uuid=uuid)
