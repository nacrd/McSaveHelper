#!/usr/bin/env python3
"""Benchmark native MCA read path (and optional anvil comparison).

Examples
--------
  python scripts/bench_mca.py
  python scripts/bench_mca.py --region path/to/r.0.0.mca --reads 64
"""
from __future__ import annotations

import argparse
import io
import statistics
import struct
import sys
import time
import zlib
from pathlib import Path
from typing import List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import nbtlib

from core.mca import RegionFile
from core.mca.format import COMPRESSION_ZLIB, HEADER_SIZE, SECTOR_SIZE
from core.mca.region_file import local_chunk_index


def _ms(seconds: float) -> float:
    return seconds * 1000.0


def _synth_region() -> bytes:
    root = nbtlib.File({
        "DataVersion": nbtlib.Int(3463),
        "xPos": nbtlib.Int(0),
        "zPos": nbtlib.Int(0),
        "Status": nbtlib.String("full"),
    })
    buf = io.BytesIO()
    root.write(buf)
    raw = buf.getvalue()
    compressed = zlib.compress(raw)
    length = 1 + len(compressed)
    record = struct.pack(">I", length) + bytes([COMPRESSION_ZLIB]) + compressed
    sectors = (len(record) + SECTOR_SIZE - 1) // SECTOR_SIZE
    payload = record + b"\x00" * (sectors * SECTOR_SIZE - len(record))
    header = bytearray(HEADER_SIZE)
    for cx in (0, 1):
        idx = local_chunk_index(cx, 0)
        b = idx * 4
        header[b : b + 3] = (2).to_bytes(3, "big")
        header[b + 3] = sectors
    return bytes(header) + payload


def _time_reads(rf: RegionFile, coords: List[Tuple[int, int]], loops: int) -> List[float]:
    samples: List[float] = []
    for _ in range(loops):
        t0 = time.perf_counter()
        for cx, cz in coords:
            if rf.has_chunk(cx, cz):
                rf.read_chunk(cx, cz)
        samples.append(time.perf_counter() - t0)
    return samples


def _try_anvil_read(path: Path, coords: List[Tuple[int, int]], loops: int) -> Optional[List[float]]:
    try:
        import anvil
    except ImportError:
        return None
    samples: List[float] = []
    for _ in range(loops):
        t0 = time.perf_counter()
        region = anvil.Region.from_file(str(path))
        for cx, cz in coords:
            try:
                region.get_chunk(cx, cz)
            except Exception:
                pass
        samples.append(time.perf_counter() - t0)
    return samples


def _summary(name: str, samples: List[float], n_ops: int) -> None:
    xs = [_ms(s) for s in samples]
    print(
        f"  {name}: n={len(xs)}  mean={statistics.mean(xs):.2f}ms  "
        f"stdev={statistics.pstdev(xs):.2f}ms  "
        f"min={min(xs):.2f}ms  max={max(xs):.2f}ms  "
        f"(batch of {n_ops} chunk reads)"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Bench core.mca RegionFile")
    parser.add_argument("--region", type=Path, help="Optional real .mca path")
    parser.add_argument("--reads", type=int, default=32, help="Chunks to touch per batch")
    parser.add_argument("--loops", type=int, default=5, help="Batch repetitions")
    args = parser.parse_args()

    print("=== MCA bench (Phase 1 read path) ===")

    if args.region and args.region.is_file():
        path = args.region
        print(f"file: {path} ({path.stat().st_size} bytes)")
        t0 = time.perf_counter()
        rf = RegionFile.open(path)
        open_ms = _ms(time.perf_counter() - t0)
        print(f"  native open: {open_ms:.2f}ms  chunks={rf.count_chunks()}")
        coords = list(rf.iter_present_chunks())[: max(1, args.reads)]
        if not coords:
            print("  no chunks present")
            return 0
        samples = _time_reads(rf, coords, args.loops)
        _summary("native read batch", samples, len(coords))

        anvil_samples = _try_anvil_read(path, coords, args.loops)
        if anvil_samples:
            _summary("anvil  read batch", anvil_samples, len(coords))
        else:
            print("  anvil: not available (skip comparison)")
        rf.close()
    else:
        print("file: <synthetic in-memory region>")
        blob = _synth_region()
        t0 = time.perf_counter()
        rf = RegionFile.from_bytes(blob)
        print(f"  native open(synth): {_ms(time.perf_counter() - t0):.2f}ms")
        coords = [(0, 0), (1, 0)]
        samples = _time_reads(rf, coords, args.loops)
        _summary("native read batch", samples, len(coords))
        print("  tip: pass --region path/to/r.X.Z.mca for real-world numbers")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
