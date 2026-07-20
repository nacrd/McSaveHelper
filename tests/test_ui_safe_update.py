"""Tests for UI safe_update helpers."""
from __future__ import annotations

from types import SimpleNamespace

from app.ui.utils import (
    is_control_update_error,
    safe_update,
    set_app_closing,
)


def test_is_control_update_error_recognizes_runtime_and_markers() -> None:
    assert is_control_update_error(RuntimeError("must be added to the page first"))
    assert is_control_update_error(AssertionError("control disposed"))
    assert is_control_update_error(AttributeError("object has no attribute 'page'"))
    assert not is_control_update_error(ValueError("bad value"))


def test_safe_update_skips_when_closing_and_swallows_unmounted() -> None:
    set_app_closing(True)
    try:
        calls = {"n": 0}

        def update() -> None:
            calls["n"] += 1

        control = SimpleNamespace(update=update)
        assert safe_update(control) is False  # type: ignore[arg-type]
        assert calls["n"] == 0
    finally:
        set_app_closing(False)

    def boom() -> None:
        raise RuntimeError("Control must be added to the page first")

    assert safe_update(SimpleNamespace(update=boom)) is False  # type: ignore[arg-type]

    def ok() -> None:
        return None

    assert safe_update(SimpleNamespace(update=ok)) is True  # type: ignore[arg-type]
