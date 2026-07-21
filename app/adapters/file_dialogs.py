"""Native desktop file-dialog adapter.

Tkinter roots must be created and destroyed on the same thread. The adapter
starts its Tk worker lazily so applications that never open a native picker do
not create a Tcl interpreter merely by starting. Letting process exit destroy
an interpreter elsewhere triggers::

    Tcl_AsyncDelete: async handler deleted by the wrong thread

Once needed, a single hidden Tk root stays on its dedicated worker thread and
is shut down explicitly via :meth:`close`.
"""
from __future__ import annotations

import queue
import threading
from dataclasses import dataclass
from typing import Any, Optional, Protocol, Sequence


FileType = tuple[str, str]
FileTypes = Sequence[FileType]


class FileDialogPort(Protocol):
    """应用壳层所需的平台无关文件对话框端口。"""

    def pick_directory(self, title: str) -> Optional[str]:
        """弹出目录选择对话框。

        Args:
            title: 对话框标题。

        Returns:
            选中目录路径；取消或关闭后为 None。
        """
        ...

    def pick_file(
        self,
        title: str,
        file_types: FileTypes,
    ) -> Optional[str]:
        """弹出单文件打开对话框。

        Args:
            title: 对话框标题。
            file_types: ``(说明, 扩展名)`` 过滤器序列。

        Returns:
            选中文件路径；取消时为 None。
        """
        ...

    def pick_files(
        self,
        title: str,
        file_types: FileTypes,
    ) -> Optional[list[str]]:
        """弹出多文件打开对话框。

        Args:
            title: 对话框标题。
            file_types: ``(说明, 扩展名)`` 过滤器序列。

        Returns:
            非空路径列表；取消或无有效选择时为 None。
        """
        ...

    def save_file(
        self,
        title: str,
        default_ext: str,
        file_types: FileTypes,
    ) -> Optional[str]:
        """弹出另存为对话框。

        Args:
            title: 对话框标题。
            default_ext: 默认扩展名（含或不含点均可）。
            file_types: ``(说明, 扩展名)`` 过滤器序列。

        Returns:
            目标路径；取消时为 None。
        """
        ...


@dataclass(frozen=True)
class _DialogRequest:
    """投递给 Tk 工作线程的一次对话框请求。"""

    method_name: str
    options: dict[str, Any]
    response: "queue.Queue[Any]"


class TkFileDialogs:
    """与 Flet 对话框隔离的 Tkinter 实现。

    进程内独占一条 Tk 工作线程；应用关闭时必须调用 :meth:`close`，
    以便在创建 root 的同一线程上销毁，避免 Tcl 跨线程删除错误。
    """

    _STARTUP_TIMEOUT_S = 5.0
    # Users may leave the native dialog open for a long time.
    _DIALOG_TIMEOUT_S = 3600.0
    _JOIN_TIMEOUT_S = 5.0

    def __init__(self) -> None:
        """Prepare lazy Tk worker state without creating a Tcl interpreter."""
        self._closed = False
        self._ready = threading.Event()
        self._requests: "queue.Queue[Optional[_DialogRequest]]" = queue.Queue()
        self._startup_lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None

    def close(self) -> None:
        """停止 Tk 工作线程并销毁 root（幂等）。"""
        if self._closed:
            return
        self._closed = True
        thread = self._thread
        if thread is None:
            return
        self._requests.put(None)
        thread.join(timeout=self._JOIN_TIMEOUT_S)

    def pick_directory(self, title: str) -> Optional[str]:
        """在 Tk 线程上选择目录。

        Args:
            title: 对话框标题。

        Returns:
            选中目录路径；关闭后、超时或取消时为 None。
        """
        return self._as_optional_path(self._show("askdirectory", title=title))

    def pick_file(
        self,
        title: str,
        file_types: FileTypes,
    ) -> Optional[str]:
        """在 Tk 线程上选择单个文件。

        Args:
            title: 对话框标题。
            file_types: ``(说明, 扩展名)`` 过滤器序列。

        Returns:
            选中文件路径；关闭后、超时或取消时为 None。
        """
        return self._as_optional_path(
            self._show(
                "askopenfilename",
                title=title,
                filetypes=list(file_types),
            )
        )

    def pick_files(
        self,
        title: str,
        file_types: FileTypes,
    ) -> Optional[list[str]]:
        """在 Tk 线程上选择多个文件。

        Args:
            title: 对话框标题。
            file_types: ``(说明, 扩展名)`` 过滤器序列。

        Returns:
            非空路径列表；关闭后、超时或取消时为 None。
        """
        result = self._show(
            "askopenfilenames",
            title=title,
            filetypes=list(file_types),
        )
        if not result:
            return None
        if isinstance(result, (list, tuple)):
            paths = [str(item) for item in result if item]
            return paths or None
        # Some Tk builds return a single path string.
        text = str(result).strip()
        return [text] if text else None

    def save_file(
        self,
        title: str,
        default_ext: str,
        file_types: FileTypes,
    ) -> Optional[str]:
        """在 Tk 线程上选择保存路径。

        Args:
            title: 对话框标题。
            default_ext: 默认扩展名。
            file_types: ``(说明, 扩展名)`` 过滤器序列。

        Returns:
            目标路径；关闭后、超时或取消时为 None。
        """
        return self._as_optional_path(
            self._show(
                "asksaveasfilename",
                title=title,
                defaultextension=default_ext,
                filetypes=list(file_types),
            )
        )

    @staticmethod
    def _as_optional_path(result: Any) -> Optional[str]:
        """Normalize a Tk single-path result to ``str | None``."""
        if result is None:
            return None
        text = str(result).strip()
        return text or None

    def _show(self, method_name: str, **options: Any) -> Any:
        if self._closed:
            return None
        self._ensure_worker_started()
        if not self._ready.wait(timeout=self._STARTUP_TIMEOUT_S):
            return None
        if self._closed:
            return None

        response: "queue.Queue[Any]" = queue.Queue(maxsize=1)
        self._requests.put(_DialogRequest(method_name, options, response))
        try:
            return response.get(timeout=self._DIALOG_TIMEOUT_S)
        except queue.Empty:
            return None

    def _ensure_worker_started(self) -> None:
        """Create the Tk worker once, only when the first picker is opened."""
        if self._closed or self._thread is not None:
            return
        with self._startup_lock:
            if self._closed or self._thread is not None:
                return
            thread = threading.Thread(
                target=self._run_worker,
                name="tk-file-dialogs",
                daemon=True,
            )
            self._thread = thread
            thread.start()

    def _run_worker(self) -> None:
        root = None
        try:
            from tkinter import Tk, filedialog

            root = Tk()
            root.withdraw()
            try:
                root.attributes("-topmost", True)
            except Exception:
                # Some platforms/themes reject -topmost; ignore.
                pass
            self._ready.set()

            while True:
                request = self._requests.get()
                if request is None:
                    break
                self._handle_request(filedialog, root, request)
        except Exception:
            # Worker failed to start or crashed; unblock any waiters.
            # Tkinter may raise TclError (subclass of Exception).
            self._ready.set()
            self._drain_pending_with_none()
        finally:
            if root is not None:
                try:
                    root.destroy()
                except Exception:
                    # Best-effort destroy on the worker thread.
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
            if request.method_name == "askopenfilenames":
                if not selected:
                    result: Any = None
                elif isinstance(selected, (list, tuple)):
                    paths = [str(item) for item in selected if item]
                    result = paths or None
                else:
                    text = str(selected).strip()
                    result = [text] if text else None
            else:
                result = str(selected) if selected else None
        except Exception:
            # Dialog cancel/error paths vary by platform; return None.
            result = None
        try:
            request.response.put(result)
        except Exception:
            # Caller may have timed out and abandoned the queue.
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
                # Best-effort unblock of timed-out callers.
                pass
