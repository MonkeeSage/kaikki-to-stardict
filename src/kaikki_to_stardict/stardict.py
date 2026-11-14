"""Write StarDict dictionaries: ``.ifo``, ``.idx``, ``.syn`` and ``.dict``/``.dict.dz``.

Entry data is appended to the ``.dict`` file as it arrives, so only the word
list is kept in memory. On :meth:`Writer.finish` the index files are written
in StarDict order and the data is compressed with dictzip.
"""

from __future__ import annotations

import math
import os
import struct
import sys
import time
import zlib
from collections.abc import Mapping
from pathlib import Path

# dictzip's default chunk size: small enough that a compressed chunk always
# fits the 16-bit size slots of the RA header.
DICTZIP_CHUNK = 58315
# The RA subfield (10 bytes + 2 per chunk) must fit the 16-bit gzip XLEN.
DICTZIP_MAX_CHUNKS = (0xFFFF - 10) // 2
DICTZIP_MAX_SIZE = DICTZIP_CHUNK * DICTZIP_MAX_CHUNKS

MAX_WORD_BYTES = 255  # StarDict's limit on index words, excluding the NUL


def sort_key(word: bytes) -> tuple[bytes, bytes]:
    """StarDict's ``stardict_strcmp``: ASCII case-insensitive, then byte-wise."""
    return word.lower(), word


class Writer:
    """Collects entries and synonyms for the dictionary at ``base`` (no suffix).

    Entries added more than once under the same word are merged, joined with
    ``joiner``, so callers can stream entries that are mostly but not always
    grouped by word.
    """

    def __init__(self, base: str | Path, sametypesequence: str = "h", joiner: bytes = b"") -> None:
        self.base = Path(base)
        self.base.parent.mkdir(parents=True, exist_ok=True)
        self.sametypesequence = sametypesequence
        self.joiner = joiner
        self.dict_path = self._path(".dict")
        self._dict = open(self.dict_path, "wb")
        self._size = 0
        self._entries: dict[bytes, list[tuple[int, int]]] = {}
        self._synonyms: set[tuple[bytes, bytes]] = set()
        self.skipped: list[str] = []  # words too long for the index

    def _path(self, suffix: str) -> Path:
        return self.base.with_name(self.base.name + suffix)

    def __contains__(self, word: str) -> bool:
        return word.encode("utf-8") in self._entries

    def __len__(self) -> int:
        return len(self._entries)

    def add(self, word: str, data: bytes) -> None:
        key = word.encode("utf-8")
        if len(key) > MAX_WORD_BYTES or b"\0" in key:
            self.skipped.append(word)
            return
        self._dict.write(data)
        self._entries.setdefault(key, []).append((self._size, len(data)))
        self._size += len(data)

    def add_synonym(self, synonym: str, word: str) -> None:
        """Make ``synonym`` find the entry for ``word`` (if it gets one)."""
        if synonym != word:
            self._synonyms.add((synonym.encode("utf-8"), word.encode("utf-8")))

    def _merge_duplicates(self) -> None:
        """Rewrite entries added in several pieces as one contiguous entry."""
        merged = {k: v for k, v in self._entries.items() if len(v) > 1}
        if not merged:
            return
        self._dict.flush()
        with open(self.dict_path, "rb") as f:
            for key, pieces in merged.items():
                parts = []
                for offset, size in pieces:
                    f.seek(offset)
                    parts.append(f.read(size))
                data = self.joiner.join(parts)
                self._dict.write(data)
                self._entries[key] = [(self._size, len(data))]
                self._size += len(data)

    def finish(self, info: Mapping[str, str], compress: bool = True) -> dict[str, int]:
        """Write the index files and ``.ifo``; returns some counts.

        ``info`` supplies ``.ifo`` fields such as ``bookname`` and
        ``description``; the size and count fields are filled in here.
        """
        self._merge_duplicates()
        self._dict.close()

        words = sorted(self._entries, key=sort_key)
        index = {w: i for i, w in enumerate(words)}
        offset_bits = 64 if self._size >= 1 << 32 else 32
        trailer = struct.Struct(">QI" if offset_bits == 64 else ">II")
        idx_path = self._path(".idx")
        with open(idx_path, "wb") as f:
            for w in words:
                ((offset, size),) = self._entries[w]
                f.write(w + b"\0" + trailer.pack(offset, size))

        synonyms = sorted(
            (
                (syn, index[target])
                for syn, target in self._synonyms
                if target in index and len(syn) <= MAX_WORD_BYTES and b"\0" not in syn
            ),
            key=lambda s: (*sort_key(s[0]), s[1]),
        )
        syn_path = self._path(".syn")
        if synonyms:
            with open(syn_path, "wb") as f:
                for syn, i in synonyms:
                    f.write(syn + b"\0" + struct.pack(">I", i))
        elif syn_path.exists():
            syn_path.unlink()

        dz_path = self._path(".dict.dz")
        if compress and self._size <= DICTZIP_MAX_SIZE:
            dictzip(self.dict_path, dz_path)
            self.dict_path.unlink()
        else:
            if compress:
                print(
                    f"warning: {self.dict_path.name} is too large for dictzip "
                    f"({self._size} > {DICTZIP_MAX_SIZE} bytes); leaving it uncompressed",
                    file=sys.stderr,
                )
            if dz_path.exists():
                dz_path.unlink()

        fields = {
            "version": "3.0.0",
            "bookname": "",
            "wordcount": str(len(words)),
            "synwordcount": str(len(synonyms)) if synonyms else None,
            "idxfilesize": str(idx_path.stat().st_size),
            "idxoffsetbits": "64" if offset_bits == 64 else None,
            "sametypesequence": self.sametypesequence,
        }
        fields.update(info)
        with open(self._path(".ifo"), "w", encoding="utf-8", newline="\n") as f:
            f.write("StarDict's dict ifo file\n")
            for key, value in fields.items():
                if value is not None:
                    # .ifo values are single lines; StarDict uses <br> for breaks.
                    value = value.replace("\r\n", "\n").replace("\n", "<br>")
                    f.write(f"{key}={value}\n")
        return {"words": len(words), "synonyms": len(synonyms), "dict_bytes": self._size}


def dictzip(src: str | Path, dst: str | Path, level: int = 9) -> None:
    """Compress ``src`` into the dictzip file ``dst``.

    A dictzip file is gzip whose deflate stream is fully flushed every
    ``DICTZIP_CHUNK`` uncompressed bytes, with the compressed size of each
    chunk listed in an ``RA`` extra field, so readers can inflate any chunk
    on its own.
    """
    size = os.path.getsize(src)
    if size > DICTZIP_MAX_SIZE:
        raise ValueError(f"{src}: too large for dictzip ({size} > {DICTZIP_MAX_SIZE} bytes)")
    chunks = max(1, math.ceil(size / DICTZIP_CHUNK))
    xlen = 4 + 6 + 2 * chunks

    def header(sizes: list[int]) -> bytes:
        return (
            b"\x1f\x8b\x08\x04"  # magic, deflate, FEXTRA
            + struct.pack("<I", int(time.time()) & 0xFFFFFFFF)
            + b"\x02\x03"  # XFL: best compression, OS: Unix
            + struct.pack("<H", xlen)
            + b"RA"
            + struct.pack("<HHHH", xlen - 4, 1, DICTZIP_CHUNK, chunks)
            + struct.pack(f"<{chunks}H", *sizes)
        )

    sizes: list[int] = []
    crc = 0
    compressor = zlib.compressobj(level, zlib.DEFLATED, -zlib.MAX_WBITS, 9)
    with open(src, "rb") as fin, open(dst, "wb") as fout:
        fout.write(header([0] * chunks))
        for n in range(chunks):
            data = fin.read(DICTZIP_CHUNK)
            crc = zlib.crc32(data, crc)
            last = n == chunks - 1
            out = compressor.compress(data) + compressor.flush(
                zlib.Z_FINISH if last else zlib.Z_FULL_FLUSH
            )
            if len(out) > 0xFFFF:  # can't happen with DICTZIP_CHUNK, but be safe
                raise ValueError("dictzip chunk too large")
            sizes.append(len(out))
            fout.write(out)
        fout.write(struct.pack("<II", crc, size & 0xFFFFFFFF))
        fout.seek(0)
        fout.write(header(sizes))
