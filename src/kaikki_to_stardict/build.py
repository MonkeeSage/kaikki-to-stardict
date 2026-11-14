"""Build a StarDict dictionary from wiktextract JSONL."""

from __future__ import annotations

import datetime
import gzip
import os
import sys
import time
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from itertools import groupby
from pathlib import Path
from typing import IO, Any

import orjson

from kaikki_to_stardict.render import Options, Record, render_entry
from kaikki_to_stardict.stardict import Writer

# Forms that aren't really word forms (inflection-table markers,
# transliterations into other scripts).
SKIP_FORM_TAGS = {"table-tags", "inflection-template", "romanization"}

LICENSE = (
    "Wiktionary content is available under the Creative Commons "
    "Attribution-ShareAlike License (CC BY-SA 4.0) and the GNU Free Documentation License."
)


def open_jsonl(path: str | Path) -> IO[bytes]:
    with open(path, "rb") as f:
        gzipped = f.read(2) == b"\x1f\x8b"
    return gzip.open(path, "rb") if gzipped else open(path, "rb")


def read_jsonl(path: str | Path) -> Iterator[Record]:
    with open_jsonl(path) as f:
        for line in f:
            if line.strip():
                yield orjson.loads(line)


def is_redirect(record: Record) -> bool:
    return "redirect" in record and "title" in record


@dataclass(frozen=True)
class BuildOptions:
    lang_code: str = "en"
    form_of: bool = True  # keep "plural of ..." style entries
    compress: bool = True


def drop_form_of(records: list[Record]) -> tuple[list[Record], list[tuple[str, str]]]:
    """Remove form-of senses; returns the remaining records and (form, lemma) pairs."""
    kept, synonyms = [], []
    for r in records:
        senses = []
        for s in r.get("senses", []):
            if s.get("form_of"):
                synonyms += [(r["word"], f["word"]) for f in s["form_of"] if f.get("word")]
            else:
                senses.append(s)
        if any(s.get("glosses") for s in senses):
            kept.append({**r, "senses": senses})
    return kept, synonyms


def word_forms(record: Record) -> Iterator[str]:
    for f in record.get("forms", []):
        form = (f.get("form") or "").strip()
        if form and form != "-" and not SKIP_FORM_TAGS.intersection(f.get("tags", [])):
            yield form


class Progress:
    def __init__(self, every: float = 5.0, stream: IO[str] = sys.stderr) -> None:
        self.start = self.last = time.monotonic()
        self.every = every
        self.stream = stream

    def update(self, message: str, force: bool = False) -> None:
        now = time.monotonic()
        if force or now - self.last >= self.every:
            self.last = now
            print(f"[{now - self.start:6.0f}s] {message}", file=self.stream, flush=True)


def build(
    records: Iterable[Record],
    base: str | Path,
    opts: Options = Options(),
    build_opts: BuildOptions = BuildOptions(),
    info: dict[str, str] | None = None,
    progress: Progress | None = None,
) -> dict[str, int]:
    """Write the dictionary for ``records`` to ``base``.ifo etc.

    Records of one headword are expected to be (mostly) adjacent, as in
    wiktextract output; stray ones are merged into the same entry.
    """
    writer = Writer(base, sametypesequence="h", joiner=b"<hr>")
    redirects: list[tuple[str, str]] = []
    count = 0

    def words() -> Iterator[Record]:
        nonlocal count
        for r in records:
            count += 1
            if is_redirect(r):
                redirects.append((r["title"], r["redirect"]))
            elif r.get("lang_code") == build_opts.lang_code and r.get("word"):
                yield r

    for word, group in groupby(words(), key=lambda r: r["word"]):
        group = list(group)
        for r in group:
            for form in word_forms(r):
                writer.add_synonym(form, word)
        if not build_opts.form_of:
            group, lemmas = drop_form_of(group)
            for form, lemma in lemmas:
                writer.add_synonym(form, lemma)
        html = render_entry(group, opts) if group else ""
        if html:
            writer.add(word, html.encode("utf-8"))
        if progress:
            progress.update(f"{count:,} records, {len(writer):,} entries, at {word!r}")

    for title, target in redirects:
        writer.add_synonym(title, target)
    if progress:
        progress.update("writing index and compressing", force=True)

    fields = {"bookname": "Wiktionary (English)"}
    fields.update(info or {})
    stats = writer.finish(fields, compress=build_opts.compress)
    stats["records"] = count
    stats["skipped"] = len(writer.skipped)
    return stats


def default_info(source: str | Path, opts: Options, build_opts: BuildOptions) -> dict[str, str]:
    """``.ifo`` metadata naming the source data and the license."""
    mtime = datetime.datetime.fromtimestamp(os.path.getmtime(source), datetime.UTC)
    today = datetime.date.today().isoformat()
    content = ["definitions"]
    if opts.pronunciation:
        content.append("pronunciation")
    if opts.etymology:
        content.append("etymology")
    if opts.translations:
        content.append("translations")
    description = (
        f"English Wiktionary ({', '.join(content)}), extracted by wiktextract "
        f"(https://github.com/tatuylonen/wiktextract) and published by https://kaikki.org/. "
        f"Source file {Path(source).name} dated {mtime.date().isoformat()}; built {today}.\n"
        f"{LICENSE}"
    )
    return {
        "bookname": "Wiktionary (English)",
        "author": "Wiktionary contributors",
        "website": "https://kaikki.org/dictionary/rawdata.html",
        "description": description,
        "date": today,
    }


def describe(stats: dict[str, Any]) -> str:
    return (
        f"{stats['records']:,} records -> {stats['words']:,} entries, "
        f"{stats['synonyms']:,} synonyms, {stats['dict_bytes'] / 1e6:,.1f} MB of entry data"
        + (f", {stats['skipped']} words too long skipped" if stats.get("skipped") else "")
    )
