import pytest

from app.bootstrap.services import (
    ServiceFactories,
    ServiceInitializationError,
    create_app_services,
)


def test_service_container_builds_in_dependency_order() -> None:
    events = []
    config = object()
    i18n = object()
    migration = object()
    uuid = object()

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

    def fail_migration(config):
        del config
        raise OSError("migration unavailable")

    def create_uuid():
        nonlocal uuid_created
        uuid_created = True
        return object()

    factories = ServiceFactories(
        config=lambda: object(),
        i18n=lambda config: object(),
        migration=fail_migration,
        uuid=create_uuid,
    )

    with pytest.raises(ServiceInitializationError) as captured:
        create_app_services(factories)

    assert captured.value.service_name == "migration"
    assert isinstance(captured.value.__cause__, OSError)
    assert "migration unavailable" in str(captured.value)
    assert uuid_created is False
