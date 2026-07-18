import sys

import pytest

from core.threading_runtime import configure_thread_fairness


def test_thread_fairness_caps_long_switch_interval(monkeypatch) -> None:
    configured = []
    monkeypatch.setattr(sys, "getswitchinterval", lambda: 0.005)
    monkeypatch.setattr(sys, "setswitchinterval", configured.append)

    effective = configure_thread_fairness(0.002)

    assert effective == 0.002
    assert configured == [0.002]


def test_thread_fairness_preserves_shorter_interval(monkeypatch) -> None:
    configured = []
    monkeypatch.setattr(sys, "getswitchinterval", lambda: 0.001)
    monkeypatch.setattr(sys, "setswitchinterval", configured.append)

    effective = configure_thread_fairness(0.002)

    assert effective == 0.001
    assert configured == []


def test_thread_fairness_rejects_invalid_interval() -> None:
    with pytest.raises(ValueError, match="必须大于 0"):
        configure_thread_fairness(0)
