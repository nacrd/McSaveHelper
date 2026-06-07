from dataclasses import dataclass
from pathlib import Path


@dataclass
class CurrentSaveContext:
    path: Path
    name: str
    is_valid: bool
    edition: str = "unknown"
    version: str = "unknown"

    @classmethod
    def from_path(cls, path: str | Path) -> "CurrentSaveContext":
        save_path = Path(path)
        return cls(
            path=save_path,
            name=save_path.name,
            is_valid=(save_path / "level.dat").exists(),
        )

    @property
    def display_path(self) -> str:
        return str(self.path)
