from app.presenters.settings_view_state import (
    SettingsFeedbackPhase,
    SettingsViewState,
    begin_reset,
    complete_reset,
    dispose_settings_state,
    mark_save_failed,
    mark_save_pending,
    mark_save_succeeded,
)


def test_settings_save_feedback_transitions_are_immutable() -> None:
    initial = SettingsViewState()

    pending = mark_save_pending(initial)
    saved = mark_save_succeeded(pending)
    failed = mark_save_failed(pending)

    assert initial.feedback is SettingsFeedbackPhase.AUTO
    assert pending.feedback is SettingsFeedbackPhase.PENDING
    assert saved.feedback is SettingsFeedbackPhase.SAVED
    assert failed.feedback is SettingsFeedbackPhase.FAILED


def test_settings_reset_excludes_other_operations_until_completion() -> None:
    resetting = begin_reset(SettingsViewState())

    assert resetting.operation_busy is True
    assert resetting.can_start_operation is False
    assert mark_save_pending(resetting) is resetting

    completed = complete_reset(resetting)
    assert completed.operation_busy is False
    assert completed.feedback is SettingsFeedbackPhase.SAVED


def test_disposed_settings_state_rejects_late_feedback() -> None:
    disposed = dispose_settings_state(begin_reset(SettingsViewState()))

    assert disposed.is_disposed is True
    assert disposed.operation_busy is False
    assert mark_save_succeeded(disposed) is disposed
    assert mark_save_failed(disposed) is disposed
    assert begin_reset(disposed) is disposed
