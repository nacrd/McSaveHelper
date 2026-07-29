from pathlib import Path

import pytest

from core.scanner import scan_all_regions
from core.utils import (
    replace_directory_tree,
    safe_destination_world,
    update_server_properties,
    validate_world_name,
)
from core.worker import process_regions_parallel


def test_validate_world_name_rejects_path_traversal_and_newlines():
    for name in ["..", ".", "foo/bar", "foo\\bar", "foo\nlevel-seed=1"]:
        with pytest.raises(ValueError):
            validate_world_name(name)


def test_safe_destination_rejects_source_inside_destination(tmp_path: Path):
    src = tmp_path / "world"
    src.mkdir()
    dest_dir = src / "nested"
    dest_dir.mkdir()

    with pytest.raises(ValueError):
        safe_destination_world(src, dest_dir, "copy")


def test_update_server_properties_rejects_newline_injection(tmp_path: Path):
    props = tmp_path / "server.properties"
    original = b"level-name=old\r\ngamemode=survival\r\n"
    props.write_bytes(original)

    with pytest.raises(ValueError):
        update_server_properties(
            tmp_path,
            "world\nop=true",
            lambda msg,
            level: None)

    assert props.read_bytes() == original


def test_update_server_properties_preserves_file_when_publish_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    props = tmp_path / "server.properties"
    original = "level-name=old\ngamemode=survival\n"
    props.write_text(original, encoding="utf-8")
    messages: list[tuple[str, str]] = []

    def fail_replace(source: Path, destination: Path) -> None:
        raise OSError(f"cannot replace {destination} from {source}")

    monkeypatch.setattr("core.io_atomic.os.replace", fail_replace)

    update_server_properties(
        tmp_path,
        "new-world",
        lambda message, level: messages.append((message, level)),
    )

    assert props.read_text(encoding="utf-8") == original
    assert messages[-1][1] == "ERROR"
    assert list(tmp_path.glob(".server.properties.*.tmp")) == []


def test_scan_all_regions_filters_and_sorts(tmp_path: Path):
    region = tmp_path / "region"
    region.mkdir()
    valid_b = region / "r.2.0.mca"
    valid_a = region / "r.-1.0.mca"
    invalid = region / "not-a-region.mca"
    valid_b.touch()
    valid_a.touch()
    invalid.touch()

    assert scan_all_regions(tmp_path) == [valid_a, valid_b]


def test_process_regions_parallel_accepts_empty_input():
    progress_values = []
    logs = []

    process_regions_parallel(
        [], [], progress_values.append, lambda msg, level: logs.append(
            (msg, level)))

    assert progress_values == [1.0]
    assert logs[-1] == ("区块总计修改: 0 处", "INFO")


def test_replace_directory_tree_rejects_non_world_destination(tmp_path: Path):
    src = tmp_path / "src_world"
    src.mkdir()
    (src / "level.dat").touch()
    dst = tmp_path / "important"
    dst.mkdir()
    (dst / "notes.txt").write_text("keep", encoding="utf-8")

    with pytest.raises(ValueError):
        replace_directory_tree(src, dst)

    assert (dst / "notes.txt").read_text(encoding="utf-8") == "keep"


def test_replace_directory_tree_allows_existing_world_destination(
        tmp_path: Path):
    src = tmp_path / "src_world"
    src.mkdir()
    (src / "level.dat").write_text("new", encoding="utf-8")
    dst = tmp_path / "old_world"
    dst.mkdir()
    (dst / "level.dat").write_text("old", encoding="utf-8")

    replace_directory_tree(src, dst)

    assert (dst / "level.dat").read_text(encoding="utf-8") == "new"
