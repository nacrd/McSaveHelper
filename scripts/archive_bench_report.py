#!/usr/bin/env python3
"""Run synthetic bench (optional) and archive p95 tables.

Examples
--------
  python scripts/archive_bench_report.py
  python scripts/archive_bench_report.py --sizes small --loops 1
  python scripts/archive_bench_report.py --from-json path/to/report.json
"""
from __future__ import annotations

import argparse
import json
import platform
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.bench_archive import write_bench_archive  # noqa: E402
from core.bench_samples import REFERENCE_MACHINE, SampleSize  # noqa: E402


def _default_machine_notes() -> str:
    return (
        f"os={platform.system()} {platform.release()}; "
        f"python={platform.python_version()}; "
        f"machine={platform.machine()}; "
        f"profile={REFERENCE_MACHINE.get('profile')}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Archive bench p95 report")
    parser.add_argument(
        "--sizes",
        nargs="+",
        choices=[item.value for item in SampleSize],
        default=["small"],
    )
    parser.add_argument("--loops", type=int, default=1)
    parser.add_argument(
        "--output-dir",
        default=str(ROOT / "docs" / "bench"),
    )
    parser.add_argument("--basename", default="synthetic_baseline")
    parser.add_argument("--from-json", default="")
    parser.add_argument(
        "--machine-notes",
        default="",
        help="Optional free-text hardware notes for true-machine archives",
    )
    parser.add_argument(
        "--check-budgets",
        action="store_true",
        help="Fail if synthetic budgets are violated",
    )
    args = parser.parse_args()

    if args.from_json:
        report = json.loads(Path(args.from_json).read_text(encoding="utf-8"))
    else:
        from scripts.bench_mca import evaluate_report_budgets, run_benchmark

        sizes = [SampleSize(item) for item in args.sizes]
        report = run_benchmark(sizes=sizes, loops=max(1, args.loops))
        violations = evaluate_report_budgets(report)
        report["budget_violations"] = violations
        report["budgets_ok"] = not violations
        if args.check_budgets and violations:
            print("budget violations:", *violations, sep="\n- ")
            return 2

    notes = args.machine_notes or _default_machine_notes()
    paths = write_bench_archive(
        report,
        args.output_dir,
        basename=args.basename,
        machine_notes=notes,
    )
    print(f"wrote {paths['markdown']}")
    print(f"wrote {paths['json']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
