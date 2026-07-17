"""Native desktop file-dialog adapter."""
from __future__ import annotations

from typing import Any, Optional, Protocol, Sequence


FileType = tuple[str, str]
FileTypes = Sequence[FileType]


class FileDialogPort(Protocol):
    """Platform-independent commands required by the application shell."""

    def pick_directory(self, title: str) -> Optional[str]:
        ...

    def pick_file(
        self,
        title: str,
        file_types: FileTypes,
    ) -> Optional[str]:
        ...

    def save_file(
        self,
        title: str,
        default_ext: str,
        file_types: FileTypes,
    ) -> Optional[str]:
        ...


class TkFileDialogs:
    """Tkinter implementation isolated from Flet dialog management."""

    @staticmethod
    def _show(method_name: str, **options: Any) -> Optional[str]:
        root = None
        try:
            from tkinter import Tk, filedialog

            root = Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            method = getattr(filedialog, method_name)
            selected = method(**options)
            return str(selected) if selected else None
        except Exception:
            return None
        finally:
            if root is not None:
                try:
                    root.destroy()
                except Exception:
                    pass

    def pick_directory(self, title: str) -> Optional[str]:
        return self._show("askdirectory", title=title)

    def pick_file(
        self,
        title: str,
        file_types: FileTypes,
    ) -> Optional[str]:
        return self._show(
            "askopenfilename",
            title=title,
            filetypes=list(file_types),
        )

    def save_file(
        self,
        title: str,
        default_ext: str,
        file_types: FileTypes,
    ) -> Optional[str]:
        return self._show(
            "asksaveasfilename",
            title=title,
            defaultextension=default_ext,
            filetypes=list(file_types),
        )
