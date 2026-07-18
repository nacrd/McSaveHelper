import json
from pathlib import Path

import pytest

from app.services.config_service import ConfigService


def test_invalid_nested_types_are_replaced_with_defaults(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"ui_settings": "broken", "batch_processing": []}),
        encoding="utf-8",
    )

    service = ConfigService(tmp_path)

    assert service.ui_settings["show_log_panel"] is True
    assert service.batch_processing["max_concurrent"] == 2


def test_nested_property_results_do_not_mutate_internal_config(tmp_path: Path) -> None:
    service = ConfigService(tmp_path)
    ui = service.ui_settings
    batch = service.batch_processing
    patterns = service.cleanup_patterns
    ui["theme"] = "changed"
    batch["max_concurrent"] = 99
    patterns.append("outside")

    assert service.ui_settings["theme"] == "dark"
    assert service.batch_processing["max_concurrent"] == 2
    assert "outside" not in service.cleanup_patterns


def test_failed_config_serialization_preserves_existing_file(tmp_path: Path) -> None:
    service = ConfigService(tmp_path)
    service.save()
    config_path = tmp_path / "config.json"
    original = config_path.read_bytes()
    service._config["invalid"] = object()

    with pytest.raises(TypeError):
        service.save()

    assert config_path.read_bytes() == original
    assert not list(tmp_path.glob(".config.json.*.tmp"))
