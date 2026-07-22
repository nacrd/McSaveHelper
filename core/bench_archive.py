"""将 bench 结果归档为可版本化的 p95 报告（合成或真机）。"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional


def extract_p95_rows(report: Mapping[str, Any]) -> list[dict[str, Any]]:
    """从 bench 报告中提取每档样本的 p95 行。"""
    rows: list[dict[str, Any]] = []
    for sample in report.get("samples", []) or []:
        if not isinstance(sample, dict):
            continue
        index = sample.get("world_index") or {}
        topview = sample.get("topview") or {}
        session = sample.get("world_session") or {}
        if not isinstance(index, dict):
            index = {}
        if not isinstance(topview, dict):
            topview = {}
        if not isinstance(session, dict):
            session = {}
        rows.append(
            {
                "size": str(sample.get("size", "")),
                "label": str(sample.get("label", "")),
                "index_cold_ms": index.get("cold_ms"),
                "index_warm_p95_ms": index.get(
                    "warm_p95_ms",
                    index.get("warm_median_ms"),
                ),
                "topview_p95_ms": topview.get(
                    "tile_p95_ms",
                    topview.get("tile_median_ms"),
                ),
                "session_p95_ms": session.get(
                    "open_with_index_p95_ms",
                    session.get("open_with_index_median_ms"),
                ),
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
        f"- budgets_ok: {report.get('budgets_ok', 'n/a')}",
        f"- loops: {report.get('loops', 'n/a')}",
    ]
    if machine_notes:
        lines.append(f"- machine_notes: {machine_notes}")
    lines.extend(
        [
            "",
            "| size | index cold ms | index warm p95 | topview p95 | session p95 |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for row in rows:
        lines.append(
            "| {size} | {cold} | {warm} | {tile} | {session} |".format(
                size=row.get("size") or row.get("label") or "?",
                cold=_cell(row.get("index_cold_ms")),
                warm=_cell(row.get("index_warm_p95_ms")),
                tile=_cell(row.get("topview_p95_ms")),
                session=_cell(row.get("session_p95_ms")),
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
        return f"{float(value):.3f}"
    except (TypeError, ValueError):
        return str(value)


__all__ = [
    "extract_p95_rows",
    "render_markdown_report",
    "write_bench_archive",
]
