"""Native desktop file-dialog adapter.

Tkinter roots must be created and destroyed on the same thread. Creating a
fresh ``Tk()`` on the Flet UI thread and letting process exit destroy it
elsewhere triggers::

    Tcl_AsyncDelete: async handler deleted by the wrong thread

This adapter keeps a single hidden Tk root on a dedicated worker thread for
the whole process lifetime and shuts it down explicitly via :meth:`close`.
"""
from __future__ import annotations

import queue
import threading
from dataclasses import dataclass
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


@dataclass(frozen=True)
class _DialogRequest:
    method_name: str
    options: dict[str, Any]
    response: "queue.Queue[Optional[str]]"


class TkFileDialogs:
    """Tkinter implementation isolated from Flet dialog management.

    Owns a dedicated Tk worker thread. Call :meth:`close` during app shutdown
    so the root is destroyed on the same thread that created it.
    """

    _STARTUP_TIMEOUT_S = 5.0
    # Users may leave the native dialog open for a long time.
    _DIALOG_TIMEOUT_S = 3600.0
    _JOIN_TIMEOUT_S = 5.0

    def __init__(self) -> None:
        self._closed = False
        self._ready = threading.Event()
        self._requests: "queue.Queue[Optional[_DialogRequest]]" = queue.Queue()
        self._thread = threading.Thread(
            target=self._run_worker,
            name="tk-file-dialogs",
            daemon=True,
        )
        self._thread.start()

    def close(self) -> None:
        """Stop the Tk worker and destroy its root (idempotent)."""
        if self._closed:
            return
        self._closed = True
        self._requests.put(None)
        self._thread.join(timeout=self._JOIN_TIMEOUT_S)

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

    def _show(self, method_name: str, **options: Any) -> Optional[str]:
        if self._closed:
            return None
        if not self._ready.wait(timeout=self._STARTUP_TIMEOUT_S):
            return None
        if self._closed:
            return None

        response: "queue.Queue[Optional[str]]" = queue.Queue(maxsize=1)
        self._requests.put(_DialogRequest(method_name, options, response))
        try:
            return response.get(timeout=self._DIALOG_TIMEOUT_S)
        except queue.Empty:
            return None

    def _run_worker(self) -> None:
        root = None
        try:
            from tkinter import Tk, filedialog

            root = Tk()
            root.withdraw()
            try:
                root.attributes("-topmost", True)
            except Exception:
                pass
            self._ready.set()

            while True:
                request = self._requests.get()
                if request is None:
                    break
                self._handle_request(filedialog, root, request)
        except Exception:
            # Worker failed to start or crashed; unblock any waiters.
            self._ready.set()
            self._drain_pending_with_none()
        finally:
            if root is not None:
                try:
                    root.destroy()
                except Exception:
                    pass

    def _handle_request(
        self,
        filedialog: Any,
        root: Any,
        request: _DialogRequest,
    ) -> None:
        try:
            method = getattr(filedialog, request.method_name)
            selected = method(parent=root, **request.options)
            result = str(selected) if selected else None
        except Exception:
            result = None
        try:
            request.response.put(result)
        except Exception:
            pass

    def _drain_pending_with_none(self) -> None:
        while True:
            try:
                request = self._requests.get_nowait()
            except queue.Empty:
                return
            if request is None:
                continue
            try:
                request.response.put(None)
            except Exception:
                pass
