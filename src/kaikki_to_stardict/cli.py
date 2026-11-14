"""Command line interface: ``kaikki2stardict download|extract|build``."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from kaikki_to_stardict import __version__
from kaikki_to_stardict.build import (
    BuildOptions,
    Progress,
    build,
    default_info,
    describe,
    read_jsonl,
)
from kaikki_to_stardict.download import DEFAULT_URL, download
from kaikki_to_stardict.extract import extract
from kaikki_to_stardict.render import Options

DATA = Path("data")
RAW = DATA / "raw-wiktextract-data.jsonl.gz"


def cmd_download(args: argparse.Namespace) -> int:
    if download(args.url, args.output, force=args.force, progress=Progress()):
        print(f"downloaded {args.output}")
    else:
        print(f"{args.output} is up to date")
    return 0


def cmd_extract(args: argparse.Namespace) -> int:
    output = args.output or DATA / f"{args.lang}-extract.jsonl.gz"
    counts = extract(args.source, output, args.lang, progress=Progress())
    print(
        f"{output}: {counts['words']:,} {args.lang} records and {counts['redirects']:,} "
        f"redirects out of {counts['lines']:,} lines"
    )
    return 0


def cmd_build(args: argparse.Namespace) -> int:
    langs = None
    if args.translation_langs:
        langs = frozenset(c.strip() for c in args.translation_langs.split(",") if c.strip())
    opts = Options(
        pronunciation=not args.no_pronunciation,
        etymology=not args.no_etymology,
        max_examples=args.max_examples,
        quotations=args.quotations,
        synonyms=args.synonyms,
        related=args.related,
        translations=args.translations or langs is not None,
        translation_langs=langs,
        gloss_links=args.gloss_links,
    )
    build_opts = BuildOptions(
        lang_code=args.lang, form_of=not args.no_form_of, compress=not args.no_compress
    )
    base = Path(args.output_dir) / args.name
    info = default_info(args.source, opts, build_opts)
    if args.bookname:
        info["bookname"] = args.bookname
    stats = build(read_jsonl(args.source), base, opts, build_opts, info, Progress())
    print(f"{base}.ifo: {describe(stats)}")
    return 0


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="kaikki2stardict",
        description="Convert kaikki.org Wiktionary data to StarDict dictionaries.",
    )
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    d = sub.add_parser("download", help="download the raw wiktextract dump")
    d.add_argument("--url", default=DEFAULT_URL)
    d.add_argument("-o", "--output", type=Path, default=RAW, help="default: %(default)s")
    d.add_argument("--force", action="store_true", help="download even if up to date")
    d.set_defaults(func=cmd_download)

    x = sub.add_parser("extract", help="filter the dump to one language (speeds up builds)")
    x.add_argument("source", nargs="?", type=Path, default=RAW, help="default: %(default)s")
    x.add_argument("-o", "--output", type=Path, help="default: data/<lang>-extract.jsonl.gz")
    x.add_argument("--lang", default="en", help="language code (default: %(default)s)")
    x.set_defaults(func=cmd_extract)

    b = sub.add_parser("build", help="build a StarDict dictionary")
    b.add_argument("source", type=Path, help="raw dump or extract (.jsonl or .jsonl.gz)")
    b.add_argument(
        "-o", "--output-dir", default=DATA / "stardict", type=Path, help="default: %(default)s"
    )
    b.add_argument("--name", default="wiktionary-en", help="file name (default: %(default)s)")
    b.add_argument("--bookname", help="dictionary title shown by readers")
    b.add_argument("--lang", default="en", help="language code (default: %(default)s)")
    g = b.add_argument_group("content")
    g.add_argument(
        "--max-examples",
        type=int,
        default=3,
        metavar="N",
        help="usage examples per sense (default: %(default)s)",
    )
    g.add_argument(
        "--quotations", action="store_true", help="count dated literary quotations as examples"
    )
    g.add_argument("--synonyms", action="store_true", help="add synonyms and antonyms")
    g.add_argument(
        "--related", action="store_true", help="add derived/related terms, hyponyms, etc."
    )
    g.add_argument("--translations", action="store_true", help="add translations")
    g.add_argument(
        "--translation-langs",
        metavar="CODES",
        help="only these comma-separated language codes (implies --translations)",
    )
    g.add_argument(
        "--gloss-links", action="store_true", help="link words inside definitions to their entries"
    )
    g.add_argument("--no-pronunciation", action="store_true")
    g.add_argument("--no-etymology", action="store_true")
    g.add_argument(
        "--no-form-of",
        action="store_true",
        help='drop "plural of ..." style entries; their words become synonyms',
    )
    b.add_argument("--no-compress", action="store_true", help="write .dict instead of .dict.dz")
    b.set_defaults(func=cmd_build)
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
