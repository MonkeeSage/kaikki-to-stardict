import gzip

import orjson

from kaikki_to_stardict.build import BuildOptions, build, read_jsonl
from kaikki_to_stardict.cli import main
from kaikki_to_stardict.extract import extract
from tests.stardict_reader import Dictionary


def rec(word, gloss, lang_code="en", **kw):
    return {
        "word": word,
        "lang_code": lang_code,
        "pos": "noun",
        "senses": [{"glosses": [gloss]}],
        **kw,
    }


RECORDS = [
    rec(
        "cat",
        "A feline.",
        forms=[
            {"form": "cats", "tags": ["plural"]},
            {"form": "no-table-tags", "tags": ["table-tags"]},
            {"form": "en-noun", "tags": ["inflection-template"]},
            {"form": "-", "tags": ["comparative"]},
        ],
    ),
    rec("cat", "Short for catamaran.", pos="verb"),
    rec("chat", "Un chat.", lang_code="fr"),
    {
        "word": "cats",
        "lang_code": "en",
        "pos": "noun",
        "senses": [{"glosses": ["plural of cat"], "form_of": [{"word": "cat"}]}],
    },
    rec("dog", "A canine."),
    {"title": "moggie", "redirect": "cat", "pos": "hard-redirect"},
    {"title": "unicorns", "redirect": "unicorn", "pos": "hard-redirect"},
    rec("cat", "A stray record for cat."),  # not adjacent to the others
]


def write_jsonl(path, records, gz=False):
    data = b"".join(orjson.dumps(r) + b"\n" for r in records)
    path.write_bytes(gzip.compress(data) if gz else data)


def test_build(tmp_path):
    stats = build(RECORDS, tmp_path / "d")
    d = Dictionary(tmp_path / "d")
    assert d.words == ["cat", "cats", "dog"]
    assert stats["records"] == len(RECORDS)
    cat = d.entry("cat")
    assert "A feline." in cat and "Short for catamaran." in cat
    assert "A stray record for cat." in cat  # merged into the same entry
    assert "Un chat." not in cat
    assert d.synonym_targets("cats") == ["cat"]
    assert d.synonym_targets("moggie") == ["cat"]
    assert d.synonym_targets("unicorns") == []
    assert d.synonym_targets("no-table-tags") == []
    assert d.synonym_targets("en-noun") == []
    assert d.synonym_targets("-") == []


def test_build_without_form_of(tmp_path):
    build(RECORDS, tmp_path / "d", build_opts=BuildOptions(form_of=False))
    d = Dictionary(tmp_path / "d")
    assert d.words == ["cat", "dog"]
    assert d.synonym_targets("cats") == ["cat"]


def test_build_other_language(tmp_path):
    build(RECORDS, tmp_path / "d", build_opts=BuildOptions(lang_code="fr"))
    assert Dictionary(tmp_path / "d").words == ["chat"]


def test_read_jsonl_plain_and_gzip(tmp_path):
    write_jsonl(tmp_path / "a.jsonl", RECORDS)
    write_jsonl(tmp_path / "b.jsonl.gz", RECORDS, gz=True)
    assert list(read_jsonl(tmp_path / "a.jsonl")) == RECORDS
    assert list(read_jsonl(tmp_path / "b.jsonl.gz")) == RECORDS


def test_extract(tmp_path):
    write_jsonl(tmp_path / "raw.jsonl.gz", RECORDS, gz=True)
    counts = extract(tmp_path / "raw.jsonl.gz", tmp_path / "en.jsonl.gz")
    assert counts == {"lines": len(RECORDS), "words": 5, "redirects": 2}
    kept = list(read_jsonl(tmp_path / "en.jsonl.gz"))
    assert kept == [r for r in RECORDS if r.get("lang_code") != "fr"]
    assert not (tmp_path / "en.jsonl.gz.part").exists()


def test_cli_build(tmp_path, capsys):
    write_jsonl(tmp_path / "en.jsonl", RECORDS)
    out = tmp_path / "out"
    assert (
        main(
            [
                "build",
                str(tmp_path / "en.jsonl"),
                "-o",
                str(out),
                "--name",
                "wikt",
                "--bookname",
                "My Wiktionary",
                "--translation-langs",
                "de,fr",
                "--no-form-of",
            ]
        )
        == 0
    )
    d = Dictionary(out / "wikt")
    assert d.info["bookname"] == "My Wiktionary"
    assert "translations" in d.info["description"]
    assert "CC BY-SA" in d.info["description"]
    assert d.words == ["cat", "dog"]
    assert "-> 2 entries" in capsys.readouterr().out
