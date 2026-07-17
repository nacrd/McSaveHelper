from app.ui.feedback import FeedbackCollector
from app.ui.keyboard_shortcuts import KeyboardShortcutManager
from app.ui.performance.monitor import PerformanceMonitor


def test_infra_managers_are_independent_instances() -> None:
    left_shortcut = KeyboardShortcutManager()
    right_shortcut = KeyboardShortcutManager()
    left_shortcut.enabled = False
    assert right_shortcut.enabled is True

    left_feedback = FeedbackCollector()
    right_feedback = FeedbackCollector()
    left_feedback.enabled = False
    assert right_feedback.enabled is True

    left_perf = PerformanceMonitor()
    right_perf = PerformanceMonitor()
    left_perf.enable()
    assert right_perf.enabled is False
