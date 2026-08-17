"""Tests for local log alert rules and cooldown behavior."""

from __future__ import annotations

from datetime import datetime, timedelta
from email.message import EmailMessage
from pathlib import Path

import pytest

from app.services.log_alert_service import (
    AlertEvent,
    AlertRule,
    AlertService,
    SmtpEmailNotifier,
    SmtpSettings,
)
from core.logging.models import LogLevel, LogRecord
from core.logging.storage import DailyJsonlHandler, JsonlLogStore


def test_alert_rule_triggers_once_during_cooldown(tmp_path: Path) -> None:
    now = datetime.now().astimezone()
    handler = DailyJsonlHandler(tmp_path, level=LogLevel.DEBUG)
    for index in range(3):
        handler.handle(
            LogRecord(
                timestamp=now - timedelta(minutes=index),
                level=LogLevel.ERROR,
                message="repeated failure",
                module="Test",
            )
        )
    handler.close()
    notifications: list[AlertEvent] = []
    service = AlertService(JsonlLogStore(tmp_path), system_notify=notifications.append)
    rule = service.create_rule(AlertRule(name="Errors", threshold=3, cooldown_minutes=60))

    first = service.check(now=now + timedelta(seconds=1))
    second = service.check(now=now + timedelta(minutes=5))

    assert first.triggered[0].rule_id == rule.rule_id
    assert first.triggered[0].count == 3
    assert len(notifications) == 1
    assert second.triggered == ()
    assert second.skipped_cooldown == 1
    assert service.history()[0].rule_name == "Errors"


def test_alert_rule_crud_is_persisted(tmp_path: Path) -> None:
    service = AlertService(JsonlLogStore(tmp_path))
    rule = service.create_rule(AlertRule(name="Fatal", level="FATAL", threshold=1))
    assert service.list_rules() == (rule,)

    updated = service.upsert_rule(
        AlertRule(
            rule_id=rule.rule_id,
            name="Fatal updated",
            level="FATAL",
            threshold=2,
        )
    )
    assert service.list_rules() == (updated,)
    assert service.delete_rule(rule.rule_id) is True
    assert service.list_rules() == ()


def test_email_alert_requires_recipient(tmp_path: Path) -> None:
    service = AlertService(JsonlLogStore(tmp_path))

    with pytest.raises(ValueError, match="收件人"):
        service.create_rule(AlertRule(name="Email", notification="email"))


def test_smtp_notifier_uses_tls_credentials_and_recipients(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeSmtp:
        instances: list["FakeSmtp"] = []

        def __init__(self, host: str, port: int, timeout: float) -> None:
            self.connection = (host, port, timeout)
            self.tls_started = False
            self.login_args: tuple[str, str] | None = None
            self.messages: list[EmailMessage] = []
            self.instances.append(self)

        def __enter__(self) -> "FakeSmtp":
            return self

        def __exit__(self, *args: object) -> None:
            del args

        def starttls(self) -> None:
            self.tls_started = True

        def login(self, username: str, password: str) -> None:
            self.login_args = (username, password)

        def send_message(self, message: EmailMessage) -> None:
            self.messages.append(message)

    monkeypatch.setattr("app.services.log_alert_service.smtplib.SMTP", FakeSmtp)
    monkeypatch.setenv("TEST_SMTP_PASSWORD", "secret")
    notifier = SmtpEmailNotifier(SmtpSettings(
        host="smtp.example.test",
        username="sender@example.test",
        password_env="TEST_SMTP_PASSWORD",
    ))
    event = AlertEvent(
        event_id="event",
        rule_id="rule",
        rule_name="Errors",
        level="ERROR",
        count=12,
        threshold=10,
        window_minutes=60,
        triggered_at=datetime.now().astimezone(),
        notification="email",
        recipients=("owner@example.test",),
    )

    notifier(event)

    client = FakeSmtp.instances[0]
    assert client.connection == ("smtp.example.test", 587, 10.0)
    assert client.tls_started is True
    assert client.login_args == ("sender@example.test", "secret")
    assert client.messages[0]["To"] == "owner@example.test"
