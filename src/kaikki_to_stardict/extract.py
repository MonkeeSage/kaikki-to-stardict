"""Filter the raw wiktextract dump down to one language (plus redirects)."""

from __future__ import annotations

import gzip
from pathlib import Path

import orjson

from kaikki_to_stardict.build import Progress, open_jsonl


def extract(
    src: str | Path, dst: str | Path, lang_code: str = "en", progress: Progress | None = None
) -> dict[str, int]:
    """Copy the ``lang_code`` word records and all redirects from ``src`` to ``dst``.

    Lines are copied verbatim, so ``dst`` keeps the dump's record order. It is
    gzipped if its name ends in ``.gz``.
    """
    counts = {"lines": 0, "words": 0, "redirects": 0}
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.name + ".part")
    out = gzip.open(tmp, "wb", compresslevel=3) if dst.suffix == ".gz" else open(tmp, "wb")
    quoted = f'"{lang_code}"'.encode()
    with open_jsonl(src) as f, out:
        for line in f:
            counts["lines"] += 1
            # Cheap pre-filter: most lines are other languages.
            if b'"redirect"' not in line and quoted not in line:
                continue
            record = orjson.loads(line)
            if "redirect" in record and "title" in record:
                counts["redirects"] += 1
            elif record.get("lang_code") == lang_code:
                counts["words"] += 1
            else:
                continue
            out.write(line if line.endswith(b"\n") else line + b"\n")
            if progress:
                progress.update(f"{counts['lines']:,} lines, {counts['words']:,} kept")
    tmp.replace(dst)
    return counts
