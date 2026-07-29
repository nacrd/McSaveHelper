"""低内存地图 PNG 扫描行编码。"""
from __future__ import annotations

import struct
import zlib
from typing import BinaryIO


class StreamingPngWriter:
    """Write RGB PNG scanlines without retaining the full image in memory."""

    _CHUNK_SIZE = 1024 * 1024

    def __init__(self, output: BinaryIO, width: int, height: int) -> None:
        self._output = output
        self._row_bytes = width * 3
        self._expected_rows = height
        self._rows_written = 0
        self._compressor = zlib.compressobj(level=6)
        self._compressed = bytearray()
        output.write(b"\x89PNG\r\n\x1a\n")
        header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
        self._write_chunk(b"IHDR", header)

    def write_row(self, row: bytes) -> None:
        """Compress and append one unfiltered RGB scanline."""
        if len(row) != self._row_bytes:
            raise ValueError("PNG 扫描行宽度与导出图像不匹配")
        if self._rows_written >= self._expected_rows:
            raise ValueError("PNG 扫描行数量超出导出图像高度")
        self._compressed.extend(self._compressor.compress(b"\x00" + row))
        self._rows_written += 1
        self._flush_ready_chunks()

    def finish(self) -> None:
        """Finish the compressed stream and write the PNG trailer."""
        if self._rows_written != self._expected_rows:
            raise ValueError(
                "PNG 扫描行数量与导出图像高度不匹配: "
                f"{self._rows_written}/{self._expected_rows}"
            )
        self._compressed.extend(self._compressor.flush())
        while self._compressed:
            payload = bytes(self._compressed[: self._CHUNK_SIZE])
            del self._compressed[: self._CHUNK_SIZE]
            self._write_chunk(b"IDAT", payload)
        self._write_chunk(b"IEND", b"")

    def _flush_ready_chunks(self) -> None:
        while len(self._compressed) >= self._CHUNK_SIZE:
            payload = bytes(self._compressed[: self._CHUNK_SIZE])
            del self._compressed[: self._CHUNK_SIZE]
            self._write_chunk(b"IDAT", payload)

    def _write_chunk(self, chunk_type: bytes, payload: bytes) -> None:
        self._output.write(struct.pack(">I", len(payload)))
        self._output.write(chunk_type)
        self._output.write(payload)
        checksum = zlib.crc32(chunk_type)
        checksum = zlib.crc32(payload, checksum)
        self._output.write(struct.pack(">I", checksum & 0xFFFFFFFF))
