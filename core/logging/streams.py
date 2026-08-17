"""Reversible stdout/stderr adapters for the local logging facade."""

from __future__ import annotations

import io
import threading
from typing import Callable, TextIO


class LoggingTextStream(io.TextIOBase):
    """Buffer text writes until newline, then publish one log message."""

    def __init__(
        self,
        original: TextIO,
        publish: Callable[[str], None],
    ) -> None:
        super().__init__()
        self._original = original
        self._publish = publish
        self._buffer = ""
        self._lock = threading.RLock()
        self._encoding = getattr(original, "encoding", None) or "utf-8"
        self._errors = getattr(original, "errors", None) or "strict"

    def writable(self) -> bool:
        return True

    def isatty(self) -> bool:
        return self._original.isatty()

    @property
    def encoding(self) -> str:
        """Expose the wrapped stream encoding for library compatibility."""
        return self._encoding

    @encoding.setter
    def encoding(self, value: str) -> None:
        self._encoding = value

    @property
    def errors(self) -> str:
        """Expose the wrapped stream error policy."""
        return self._errors

    @errors.setter
    def errors(self, value: str) -> None:
        self._errors = value

    def fileno(self) -> int:
        return self._original.fileno()

    def write(self, text: str) -> int:
        if not isinstance(text, str):
            raise TypeError("text stream accepts str only")
        with self._lock:
            self._buffer += text
            while "\n" in self._buffer:
                line, self._buffer = self._buffer.split("\n", 1)
                if line.strip():
                    self._publish(line.rstrip("\r"))
        return len(text)

    def flush(self) -> None:
        with self._lock:
            if self._buffer.strip():
                self._publish(self._buffer.rstrip("\r"))
            self._buffer = ""
            self._original.flush()


__all__ = ["LoggingTextStream"]
