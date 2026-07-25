"""启动时一次性数据迁移测试。"""
from __future__ import annotations

from pathlib import Path

from app.services.data_migration import migrate_legacy_home_dir


def test_migrate_renames_old_dir(tmp_path: Path, monkeypatch) -> None:
    old = tmp_path / ".mcsavehelper"
    new = tmp_path / ".mc_save_helper"
    old.mkdir()
    (old / "config.json").write_text("{}")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    migrate_legacy_home_dir()

    assert not old.exists()
    assert new.is_dir()
    assert (new / "config.json").read_text() == "{}"


def test_migrate_skips_when_new_exists(tmp_path: Path, monkeypatch) -> None:
    old = tmp_path / ".mcsavehelper"
    new = tmp_path / ".mc_save_helper"
    old.mkdir()
    new.mkdir()
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    migrate_legacy_home_dir()

    assert old.is_dir()
    assert new.is_dir()


def test_migrate_skips_when_no_old(tmp_path: Path, monkeypatch) -> None:
    new = tmp_path / ".mc_save_helper"
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    migrate_legacy_home_dir()

    assert not new.exists()
