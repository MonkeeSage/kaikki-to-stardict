"""A minimal StarDict reader for checking what the writer produced."""

from __future__ import annotations

import struct
import zlib
from pathlib import Path


def parse_ifo(path: Path) -> dict[str, str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "StarDict's dict ifo file"
    return dict(line.split("=", 1) for line in lines[1:])


def parse_index(data: bytes, trailer: struct.Struct) -> list[tuple[str, tuple]]:
    out, pos = [], 0
    while pos < len(data):
        end = data.index(b"\0", pos)
        word = data[pos:end].decode("utf-8")
        out.append((word, trailer.unpack_from(data, end + 1)))
        pos = end + 1 + trailer.size
    return out


def read_dictzip(path: Path) -> tuple[int, list[bytes]]:
    """The chunk length and the chunks, each inflated on its own."""
    data = path.read_bytes()
    assert data[:4] == b"\x1f\x8b\x08\x04"
    (xlen,) = struct.unpack_from("<H", data, 10)
    assert data[12:14] == b"RA"
    _sublen, ver, chlen, chcnt = struct.unpack_from("<HHHH", data, 14)
    assert ver == 1
    sizes = struct.unpack_from(f"<{chcnt}H", data, 22)
    pos = 12 + xlen
    chunks = []
    for size in sizes:
        chunks.append(zlib.decompressobj(-zlib.MAX_WBITS).decompress(data[pos : pos + size]))
        pos += size
    return chlen, chunks


class Dictionary:
    def __init__(self, base: Path) -> None:
        self.info = parse_ifo(base.with_name(base.name + ".ifo"))
        bits = int(self.info.get("idxoffsetbits", "32"))
        idx = parse_index(
            base.with_name(base.name + ".idx").read_bytes(),
            struct.Struct(">QI" if bits == 64 else ">II"),
        )
        self.words = [w for w, _ in idx]
        self.locations = [loc for _, loc in idx]
        syn_path = base.with_name(base.name + ".syn")
        self.synonyms = (
            [(w, i) for w, (i,) in parse_index(syn_path.read_bytes(), struct.Struct(">I"))]
            if syn_path.exists()
            else []
        )
        dz = base.with_name(base.name + ".dict.dz")
        if dz.exists():
            self.chunk_len, chunks = read_dictzip(dz)
            self.data = b"".join(chunks)
        else:
            self.chunk_len = 0
            self.data = base.with_name(base.name + ".dict").read_bytes()

    def entry(self, word: str) -> str:
        offset, size = self.locations[self.words.index(word)]
        return self.data[offset : offset + size].decode("utf-8")

    def synonym_targets(self, synonym: str) -> list[str]:
        return [self.words[i] for w, i in self.synonyms if w == synonym]
