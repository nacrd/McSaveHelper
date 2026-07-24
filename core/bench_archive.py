"""将 bench 结果归档为可版本化的 p95 报告（合成或真机）。"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


def extract_p95_rows(report: Mapping[str, Any]) -> list[dict[str, Any]]:
    """从 bench 报告中提取每档样本的 p95 行。"""
    rows: list[dict[str, Any]] = []
    for sample in report.get("samples", []) or []:
        if not isinstance(sample, dict):
            continue
        mca = sample.get("mca") or {}
        nbt = sample.get("nbt") or {}
        index = sample.get("world_index") or {}
        topview = sample.get("topview") or {}
        session = sample.get("world_session") or {}
        backup = sample.get("backup") or {}
        source = sample.get("source") or {}
        if not isinstance(mca, dict):
            mca = {}
        if not isinstance(nbt, dict):
            nbt = {}
        if not isinstance(index, dict):
            index = {}
        if not isinstance(topview, dict):
            topview = {}
        if not isinstance(session, dict):
            session = {}
        if not isinstance(backup, dict):
            backup = {}
        if not isinstance(source, dict):
            source = {}
        level_nbt = nbt.get("level") or {}
        player_nbt = nbt.get("player") or {}
        if not isinstance(level_nbt, dict):
            level_nbt = {}
        if not isinstance(player_nbt, dict):
            player_nbt = {}
        rows.append(
            {
                "size": str(sample.get("size", "")),
                "label": str(sample.get("label", "")),
                "index_cold_p95_ms": index.get(
                    "cold_p95_ms",
                    index.get("cold_ms"),
                ),
                "index_warm_p95_ms": index.get(
                    "warm_p95_ms",
                    index.get("warm_median_ms"),
                ),
                "topview_p95_ms": topview.get(
                    "tile_p95_ms",
                    topview.get("tile_median_ms"),
                ),
                "topview_cache_p95_ms": topview.get("cache_hit_p95_ms"),
                "topview_process_warm_p95_ms": topview.get(
                    "memory_warm_p95_ms"
                ),
                "topview_tile_size": topview.get("tile_size"),
                "topview_path": topview.get("path_semantics"),
                "topview_visible_upgrade_p95_ms": topview.get(
                    "visible_upgrade_p95_ms"
                ),
                "topview_first_progress_p95_ms": topview.get(
                    "visible_first_progress_p95_ms"
                ),
                "topview_progressive_upgrade_p95_ms": topview.get(
                    "progressive_upgrade_p95_ms"
                ),
                "topview_visible_warm_p95_ms": topview.get(
                    "visible_process_warm_p95_ms"
                ),
                "topview_visible_tile_size": topview.get(
                    "visible_upgrade_tile_size"
                ),
                "topview_progressive_tile_size": topview.get(
                    "progressive_upgrade_tile_size"
                ),
                "shell_p95_ms": session.get("shell_open_p95_ms"),
                "cold_session_p95_ms": session.get("cold_open_p95_ms"),
                "warm_session_p95_ms": session.get(
                    "open_with_index_p95_ms",
                    session.get("open_with_index_median_ms"),
                ),
                "backup_p95_ms": backup.get(
                    "backup_p95_ms",
                    backup.get("backup_ms"),
                ),
                "mca_open_p95_ms": mca.get("open_p95_ms"),
                "mca_read_p95_ms": mca.get("read_batch_p95_ms"),
                "level_nbt_p95_ms": level_nbt.get("p95_ms"),
                "player_nbt_p95_ms": player_nbt.get("p95_ms"),
                "sample_size": sample.get(
                    "sample_size",
                    sample.get("scale_hint"),
                ),
                "source_file_count": source.get("file_count"),
                "source_size_bytes": source.get("size_bytes"),
                "source_region_count": source.get("region_count"),
                "read_only_verified": sample.get("read_only_verified"),
            }
        )
    return rows


def render_markdown_report(
    report: Mapping[str, Any],
    *,
    title: str = "Bench p95 archive",
    machine_notes: str = "",
) -> str:
    """渲染 Markdown 归档表。"""
    ref = report.get("reference_machine") or {}
    if not isinstance(ref, dict):
        ref = {}
    rows = extract_p95_rows(report)
    lines = [
        f"# {title}",
        "",
        f"- generated_utc: {datetime.now(timezone.utc).isoformat()}",
        f"- profile: {ref.get('profile', 'unknown')}",
        f"- budgets_ok: {_plain_cell(report.get('budgets_ok'))}",
        f"- loops: {report.get('loops', 'n/a')}",
    ]
    if machine_notes:
        lines.append(f"- machine_notes: {machine_notes}")
    lines.extend(
        [
            "",
            "## Index and session",
            "",
            "| size | index cold p95 | index warm p95 | shell p95 | "
            "cold session p95 | warm session p95 |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    for row in rows:
        lines.append(
            "| {size} | {cold} | {warm} | {shell} | {cold_session} | "
            "{warm_session} |".format(
                size=row.get("size") or row.get("label") or "?",
                cold=_cell(row.get("index_cold_p95_ms")),
                warm=_cell(row.get("index_warm_p95_ms")),
                shell=_cell(row.get("shell_p95_ms")),
                cold_session=_cell(row.get("cold_session_p95_ms")),
                warm_session=_cell(row.get("warm_session_p95_ms")),
            )
        )
    lines.extend(
        [
            "",
            "## Format and rendering",
            "",
            "| size | MCA open p95 | MCA read p95 | level NBT p95 | "
            "player NBT p95 | tile cold p95 | tile process-warm p95 | "
            "tile disk-cache p95 | progressive upgrade p95 | first partial p95 | "
            "visible upgrade p95 | "
            "visible process-warm p95 | backup p95 |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for row in rows:
        lines.append(
            "| {size} | {mca_open} | {mca_read} | {level_nbt} | "
            "{player_nbt} | {tile} | {process_warm} | {cache} | {progressive} | "
            "{first_partial} | "
            "{visible_upgrade} | {visible_warm} | {backup} |".format(
                size=row.get("size") or row.get("label") or "?",
                mca_open=_cell(row.get("mca_open_p95_ms")),
                mca_read=_cell(row.get("mca_read_p95_ms")),
                level_nbt=_cell(row.get("level_nbt_p95_ms")),
                player_nbt=_cell(row.get("player_nbt_p95_ms")),
                tile=_cell(row.get("topview_p95_ms")),
                process_warm=_cell(row.get("topview_process_warm_p95_ms")),
                cache=_cell(row.get("topview_cache_p95_ms")),
                progressive=_cell(
                    row.get("topview_progressive_upgrade_p95_ms")
                ),
                first_partial=_cell(
                    row.get("topview_first_progress_p95_ms")
                ),
                visible_upgrade=_cell(
                    row.get("topview_visible_upgrade_p95_ms")
                ),
                visible_warm=_cell(row.get("topview_visible_warm_p95_ms")),
                backup=_cell(row.get("backup_p95_ms")),
            )
        )
    if any(row.get("source_file_count") is not None for row in rows):
        lines.extend(
            [
                "",
                "## Real sample metadata",
                "",
                "| size | sample class | files | bytes | regions | read-only verified | "
                "preview size | progressive size | visible size | tile path |",
                "|---|---|---:|---:|---:|---|---:|---:|---:|---|",
            ]
        )
        for row in rows:
            if row.get("source_file_count") is None:
                continue
            lines.append(
                "| {size} | {scale} | {files} | {bytes_} | {regions} | "
                "{read_only} | {tile_size} | {progressive_size} | "
                "{visible_size} | {tile_path} |".format(
                    size=row.get("size") or row.get("label") or "?",
                    scale=_plain_cell(row.get("sample_size")),
                    files=_plain_cell(row.get("source_file_count")),
                    bytes_=_plain_cell(row.get("source_size_bytes")),
                    regions=_plain_cell(row.get("source_region_count")),
                    read_only=_plain_cell(row.get("read_only_verified")),
                    tile_size=_plain_cell(row.get("topview_tile_size")),
                    progressive_size=_plain_cell(
                        row.get("topview_progressive_tile_size")
                    ),
                    visible_size=_plain_cell(
                        row.get("topview_visible_tile_size")
                    ),
                    tile_path=_plain_cell(row.get("topview_path")),
                )
            )
    violations = report.get("budget_violations") or []
    if violations:
        lines.extend(["", "## Budget violations", ""])
        for item in violations:
            lines.append(f"- {item}")
    lines.append("")
    return "\n".join(lines)


def write_bench_archive(
    report: Mapping[str, Any],
    output_dir: Path | str,
    *,
    basename: str = "latest",
    machine_notes: str = "",
) -> dict[str, Path]:
    """写入 JSON + Markdown 归档，返回路径字典。"""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    json_path = out / f"{basename}.json"
    md_path = out / f"{basename}.md"
    payload = dict(report)
    payload["archive_machine_notes"] = machine_notes
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    md_path.write_text(
        render_markdown_report(
            report,
            machine_notes=machine_notes,
        ),
        encoding="utf-8",
    )
    return {"json": json_path, "markdown": md_path}


def _cell(value: object) -> str:
    if value is None:
        return "—"
    try:
        return f"{float(str(value)):.3f}"
    except (TypeError, ValueError):
        return str(value)


def _plain_cell(value: object) -> str:
    return "n/a" if value is None else str(value)


__all__ = [
    "extract_p95_rows",
    "render_markdown_report",
    "write_bench_archive",
]
