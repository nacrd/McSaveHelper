from typing import cast

import pytest

from app.bootstrap.services import (
    ServiceFactories,
    ServiceInitializationError,
    create_app_services,
)
from app.services.config_service import ConfigService
from app.services.i18n_service import I18nService
from app.services.migration_service import MigrationService
from app.services.uuid_service import UUIDService


def test_service_container_builds_in_dependency_order() -> None:
    events = []
    config = cast(ConfigService, object())
    i18n = cast(I18nService, object())
    migration = cast(MigrationService, object())
    uuid = cast(UUIDService, object())

    def create_config():
        events.append("config")
        return config

    def create_i18n(received_config):
        events.append(("i18n", received_config))
        return i18n

    def create_migration(received_config):
        events.append(("migration", received_config))
        return migration

    def create_uuid():
        events.append("uuid")
        return uuid

    services = create_app_services(
        ServiceFactories(
            config=create_config,
            i18n=create_i18n,
            migration=create_migration,
            uuid=create_uuid,
        )
    )

    assert services.config is config
    assert services.i18n is i18n
    assert services.migration is migration
    assert services.uuid is uuid
    assert events == [
        "config",
        ("i18n", config),
        ("migration", config),
        "uuid",
    ]


def test_service_container_reports_failed_service_and_stops() -> None:
    uuid_created = False

    def fail_migration(config: ConfigService) -> MigrationService:
        del config
        raise OSError("migration unavailable")

    def create_uuid() -> UUIDService:
        nonlocal uuid_created
        uuid_created = True
        return cast(UUIDService, object())

    def create_config() -> ConfigService:
        return cast(ConfigService, object())

    def create_i18n(config: ConfigService) -> I18nService:
        del config
        return cast(I18nService, object())

    factories = ServiceFactories(
        config=create_config,
        i18n=create_i18n,
        migration=fail_migration,
        uuid=create_uuid,
    )

    with pytest.raises(ServiceInitializationError) as captured:
        create_app_services(factories)

    assert captured.value.service_name == "migration"
    assert isinstance(captured.value.__cause__, OSError)
    assert "migration unavailable" in str(captured.value)
    assert uuid_created is False
