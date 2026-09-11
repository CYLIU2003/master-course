"""Bounded compatibility reads of legacy Python JSON for desktop display only."""

from __future__ import annotations

import io
import re
from typing import BinaryIO


_SPECIAL = re.compile(rb'\\.|"|-?Infinity|NaN', re.DOTALL)
_VALUE_START = b" \t\r\n[:,"
_VALUE_END = b" \t\r\n,]}"
_CHUNK_SIZE = 64 * 1024
_LOOKAHEAD = 10  # Longest legacy constant plus its following delimiter.


class LegacyResultReader(io.RawIOBase):
    """Quote bare nonfinite constants without changing source bytes or strings.

    These values remain visibly nonnumeric in the desktop projection. They must
    never become zero, finite costs, or evidence of successful validation.
    """

    def __init__(self, source: BinaryIO):
        super().__init__()
        self._source = source
        self._tail = b""
        self._output = b""
        self._offset = 0
        self._previous: int | None = None
        self._in_string = False
        self._finished = False

    def readable(self) -> bool:
        return True

    def readinto(self, target: bytearray) -> int:
        while self._offset == len(self._output):
            if self._finished:
                return 0
            self._fill()
        count = min(len(target), len(self._output) - self._offset)
        target[:count] = self._output[self._offset : self._offset + count]
        self._offset += count
        return count

    def _fill(self) -> None:
        chunk = self._source.read(_CHUNK_SIZE)
        self._finished = not chunk
        data = self._tail + chunk
        limit = len(data) if self._finished else max(0, len(data) - _LOOKAHEAD)
        if b"Infinity" not in data and b"NaN" not in data and b"\\" not in data:
            # Ordinary trajectory chunks need only quote parity, avoiding one
            # Python regex event per key/value in very large valid JSON files.
            output = data[:limit]
            self._in_string ^= bool(output.count(b'"') % 2)
        else:
            output, limit = self._quote_constants(data, limit)
        if limit:
            self._previous = data[limit - 1]
        self._tail = data[limit:]
        self._output, self._offset = output, 0

    def _quote_constants(self, data: bytes, limit: int) -> tuple[bytes, int]:
        pieces: list[bytes] = []
        cursor = 0
        for match in _SPECIAL.finditer(data):
            start, end = match.span()
            if start >= limit:
                break
            token = match.group()
            if token == b'"':
                self._in_string = not self._in_string
            elif not self._in_string and token in {b"Infinity", b"-Infinity", b"NaN"}:
                before = data[start - 1] if start else self._previous
                after = data[end] if end < len(data) else None
                if (before is None or before in _VALUE_START) and (
                    after is None or after in _VALUE_END
                ):
                    pieces.extend((data[cursor:start], b'"', token, b'"'))
                    cursor = end
            # Never split an escaped character or a recognized token between reads.
            limit = max(limit, end)
        pieces.append(data[cursor:limit])
        return b"".join(pieces), limit
