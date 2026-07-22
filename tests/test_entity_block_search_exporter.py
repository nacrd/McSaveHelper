"""实体/方块搜索结果导出的原子写入回归测试。"""
from pathlib import Path

import pytest

from app.services.entity_block_search import exporter
from app.services.entity_block_search.models import SearchResult, SearchSummary


def test_export_results_uses_atomic_text_publish(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "results.txt"
    writes: list[tuple[Path, str]] = []
    monkeypatch.setattr(
        exporter,
        "atomic_write_text",
        lambda path, content: writes.append((path, content)),
    )

    exporter.export_results_to_text(
        output,
        SearchSummary(scanned_regions=2, scanned_chunks=3),
        [
            SearchResult(
                "block",
                "minecraft:stone",
                (1, 64, 2),
                "overworld",
            )
        ],
    )

    assert writes and writes[0][0] == output
    assert "minecraft:stone" in writes[0][1]
    assert "扫描区域: 2" in writes[0][1]


def test_export_results_propagates_atomic_publish_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_write(path: Path, content: str) -> None:
        del path, content
        raise OSError("disk full")

    monkeypatch.setattr(exporter, "atomic_write_text", fail_write)

    with pytest.raises(OSError, match="disk full"):
        exporter.export_results_to_text(
            tmp_path / "results.txt",
            SearchSummary(),
            [],
        )
