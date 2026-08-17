"""Local alert rules, history, and notification orchestration."""

from __future__ import annotations

import json
import os
import smtplib
import tempfile
import uuid
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import Callable, Optional, Sequence

from core.logging.storage import JsonlLogStore, LogQuery

Notification = Callable[["AlertEvent"], None]


@dataclass(frozen=True)
class AlertRule:
    """单条错误数量告警规则。"""

    name: str
    rule_id: str = ""
    level: str = "ERROR"
    window_minutes: int = 60
    threshold: int = 10
    notification: str = "system"
    cooldown_minutes: int = 60
    enabled: bool = True
    recipients: tuple[str, ...] = ()

    def validate(self) -> None:
        """验证规则值，失败时抛出 ValueError。"""
        if not self.name.strip():
            raise ValueError("告警规则名称不能为空")
        if self.level not in {"DEBUG", "INFO", "WARN", "ERROR", "FATAL"}:
            raise ValueError("不支持的告警级别")
        if self.window_minutes <= 0 or self.threshold <= 0:
            raise ValueError("时间窗口和阈值必须为正数")
        if self.cooldown_minutes < 0:
            raise ValueError("冷却时间不能为负数")
        if self.notification not in {"system", "email", "both"}:
            raise ValueError("不支持的通知方式")
        if self.notification in {"email", "both"} and not self.recipients:
            raise ValueError("邮件通知需要至少一个收件人")


@dataclass(frozen=True)
class AlertEvent:
    """一次已触发的告警事件。"""

    event_id: str
    rule_id: str
    rule_name: str
    level: str
    count: int
    threshold: int
    window_minutes: int
    triggered_at: datetime
    notification: str
    recipients: tuple[str, ...] = ()
    notification_errors: tuple[str, ...] = ()


@dataclass(frozen=True)
class AlertCheckResult:
    """一次后台检查的汇总结果。"""

    checked_rules: int
    triggered: tuple[AlertEvent, ...]
    skipped_cooldown: int


@dataclass(frozen=True)
class SmtpSettings:
    """不包含明文密码的 SMTP 连接设置。"""

    host: str
    port: int = 587
    username: str = ""
    sender: str = ""
    password_env: str = "MCSAVEHELPER_SMTP_PASSWORD"
    use_tls: bool = True
    timeout_seconds: float = 10.0


class SmtpEmailNotifier:
    """使用标准库 smtplib 发送告警邮件。"""

    def __init__(self, settings: SmtpSettings) -> None:
        self._settings = settings

    def __call__(self, event: AlertEvent) -> None:
        if not event.recipients:
            raise ValueError("告警规则未配置邮件收件人")
        password = os.environ.get(self._settings.password_env, "")
        message = EmailMessage()
        message["Subject"] = f"[MCSaveHelper] {event.rule_name}"
        message["From"] = self._settings.sender or self._settings.username
        message["To"] = ", ".join(event.recipients)
        message.set_content(
            f"规则：{event.rule_name}\n级别：{event.level}\n"
            f"窗口：{event.window_minutes} 分钟\n数量：{event.count}\n"
            f"阈值：{event.threshold}\n触发时间：{event.triggered_at.isoformat()}\n"
        )
        with smtplib.SMTP(
            self._settings.host,
            self._settings.port,
            timeout=self._settings.timeout_seconds,
        ) as client:
            if self._settings.use_tls:
                client.starttls()
            if self._settings.username:
                client.login(self._settings.username, password)
            client.send_message(message)


class AlertService:
    """持久化规则、扫描 JSONL 窗口并执行注入的通知端口。"""

    def __init__(
        self,
        store: JsonlLogStore,
        system_notify: Optional[Notification] = None,
        email_notify: Optional[Notification] = None,
    ) -> None:
        self._store = store
        self._system_notify = system_notify
        self._email_notify = email_notify
        self._directory = store.log_root / "alerts"
        self._rules_path = self._directory / "rules.json"
        self._history_path = self._directory / "history.jsonl"

    def list_rules(self) -> tuple[AlertRule, ...]:
        """按名称稳定返回规则。"""
        if not self._rules_path.exists():
            return ()
        try:
            payload = json.loads(self._rules_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError):
            return ()
        rules = []
        for item in payload if isinstance(payload, list) else ():
            try:
                rule = AlertRule(
                    rule_id=str(item["rule_id"]),
                    name=str(item["name"]),
                    level=str(item.get("level", "ERROR")),
                    window_minutes=int(item.get("window_minutes", 60)),
                    threshold=int(item.get("threshold", 10)),
                    notification=str(item.get("notification", "system")),
                    cooldown_minutes=int(item.get("cooldown_minutes", 60)),
                    enabled=bool(item.get("enabled", True)),
                    recipients=tuple(str(value) for value in item.get("recipients", ())),
                )
                rule.validate()
            except (KeyError, TypeError, ValueError):
                continue
            rules.append(rule)
        return tuple(sorted(rules, key=lambda rule: (rule.name.casefold(), rule.rule_id)))

    def configure_notifications(
        self,
        system_notify: Optional[Notification],
        email_notify: Optional[Notification],
    ) -> None:
        """替换通知端口；端口由 Qt 组合根注入。"""
        self._system_notify = system_notify
        self._email_notify = email_notify

    def upsert_rule(self, rule: AlertRule) -> AlertRule:
        """新增或更新规则并原子保存。"""
        rule.validate()
        active = [item for item in self.list_rules() if item.rule_id != rule.rule_id]
        active.append(rule)
        self._atomic_write_json([asdict(item) for item in active])
        return rule

    def create_rule(self, rule: AlertRule) -> AlertRule:
        """创建带新 ID 的规则。"""
        candidate = rule if rule.rule_id else replace(rule, rule_id=uuid.uuid4().hex)
        return self.upsert_rule(candidate)

    def delete_rule(self, rule_id: str) -> bool:
        """删除规则，返回是否存在。"""
        active = list(self.list_rules())
        remaining = [item for item in active if item.rule_id != rule_id]
        if len(remaining) == len(active):
            return False
        self._atomic_write_json([asdict(item) for item in remaining])
        return True

    def history(self, limit: int = 100) -> tuple[AlertEvent, ...]:
        """读取最近告警历史，损坏行会被跳过。"""
        events: list[AlertEvent] = []
        if not self._history_path.exists():
            return ()
        try:
            with self._history_path.open("r", encoding="utf-8") as source:
                for line in source:
                    try:
                        events.append(_event_from_dict(json.loads(line)))
                    except (json.JSONDecodeError, TypeError, ValueError, KeyError):
                        continue
        except OSError:
            return ()
        return tuple(events[-max(1, limit):][::-1])

    def check(self, now: Optional[datetime] = None) -> AlertCheckResult:
        """检查所有启用规则并执行冷却后的通知。"""
        current = (now or datetime.now().astimezone())
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        recent = self.history(limit=1000)
        triggered: list[AlertEvent] = []
        skipped = 0
        rules = self.list_rules()
        for rule in rules:
            if not rule.enabled:
                continue
            start = current - timedelta(minutes=rule.window_minutes)
            count = sum(
                1
                for _ in self._store.iter_filtered(
                    LogQuery(levels=frozenset({rule.level}), start=start, end=current, limit=1)
                )
            )
            if count < rule.threshold:
                continue
            last = _last_rule_event(recent, rule.rule_id)
            if last and current - last.triggered_at < timedelta(minutes=rule.cooldown_minutes):
                skipped += 1
                continue
            event = AlertEvent(
                event_id=uuid.uuid4().hex,
                rule_id=rule.rule_id,
                rule_name=rule.name,
                level=rule.level,
                count=count,
                threshold=rule.threshold,
                window_minutes=rule.window_minutes,
                triggered_at=current,
                notification=rule.notification,
                recipients=rule.recipients,
            )
            event = self._notify(event)
            self._append_history(event)
            triggered.append(event)
        return AlertCheckResult(len(rules), tuple(triggered), skipped)

    def _notify(self, event: AlertEvent) -> AlertEvent:
        errors: list[str] = []
        callbacks: list[Optional[Notification]] = []
        if event.notification in {"system", "both"}:
            callbacks.append(self._system_notify)
        if event.notification in {"email", "both"}:
            callbacks.append(self._email_notify)
        for callback in callbacks:
            if callback is None:
                errors.append("通知端口未配置")
                continue
            try:
                callback(event)
            except (OSError, RuntimeError, ValueError, smtplib.SMTPException) as exc:
                errors.append(str(exc))
        return replace(event, notification_errors=tuple(errors))

    def _append_history(self, event: AlertEvent) -> None:
        try:
            self._directory.mkdir(parents=True, exist_ok=True)
            with self._history_path.open("a", encoding="utf-8", newline="\n") as output:
                output.write(json.dumps(_event_to_dict(event), ensure_ascii=False))
                output.write("\n")
                output.flush()
                os.fsync(output.fileno())
        except OSError:
            # History failure must not hide the already evaluated alert result.
            pass

    def _atomic_write_json(self, payload: object) -> None:
        temp_path: Optional[Path] = None
        try:
            self._directory.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=self._directory,
                prefix=".rules.", suffix=".tmp", delete=False,
            ) as output:
                temp_path = Path(output.name)
                json.dump(payload, output, ensure_ascii=False, indent=2)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temp_path, self._rules_path)
            temp_path = None
        finally:
            if temp_path is not None:
                try:
                    temp_path.unlink(missing_ok=True)
                except OSError:
                    pass


def _event_to_dict(event: AlertEvent) -> dict[str, object]:
    payload = asdict(event)
    payload["triggered_at"] = event.triggered_at.isoformat()
    payload["notification_errors"] = list(event.notification_errors)
    return payload


def _event_from_dict(payload: object) -> AlertEvent:
    if not isinstance(payload, dict):
        raise TypeError("告警历史不是对象")
    triggered = datetime.fromisoformat(str(payload["triggered_at"]))
    return AlertEvent(
        event_id=str(payload["event_id"]),
        rule_id=str(payload["rule_id"]),
        rule_name=str(payload["rule_name"]),
        level=str(payload["level"]),
        count=int(payload["count"]),
        threshold=int(payload["threshold"]),
        window_minutes=int(payload["window_minutes"]),
        triggered_at=triggered,
        notification=str(payload["notification"]),
        recipients=tuple(str(item) for item in payload.get("recipients", ())),
        notification_errors=tuple(str(item) for item in payload.get("notification_errors", ())),
    )


def _last_rule_event(events: Sequence[AlertEvent], rule_id: str) -> Optional[AlertEvent]:
    for event in events:
        if event.rule_id == rule_id:
            return event
    return None


__all__ = [
    "AlertCheckResult", "AlertEvent", "AlertRule", "AlertService",
    "SmtpEmailNotifier", "SmtpSettings",
]
