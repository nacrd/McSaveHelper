"""Process-wide safeguards for responsive Python thread scheduling."""
from __future__ import annotations

import sys


DEFAULT_MAX_SWITCH_INTERVAL = 0.002


def configure_thread_fairness(
    max_switch_interval: float = DEFAULT_MAX_SWITCH_INTERVAL,
) -> float:
    """Cap the GIL switch interval and return the effective value.

    CPU-heavy NBT parsing can run in several background threads at once.  A
    short upper bound prevents those workers from starving Flet's event loop.
    Existing runtimes configured with a shorter interval are left unchanged.
    """
    if max_switch_interval <= 0:
        raise ValueError("线程切换间隔必须大于 0")

    current = sys.getswitchinterval()
    if current > max_switch_interval:
        sys.setswitchinterval(max_switch_interval)
        return max_switch_interval
    return current
