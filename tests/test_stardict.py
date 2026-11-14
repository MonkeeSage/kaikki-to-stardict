import gzip
import os
import random

import pytest

from kaikki_to_stardict import stardict
from kaikki_to_stardict.stardict import Writer, dictzip, sort_key
from tests.stardict_reader import Dictionary, read_dictzip


def test_sort_key_matches_stardict_order():
    words = ["b", "B", "a", "ab", "Ab", "é", "_x", "Z", "aB"]
    ordered = sorted(words, key=lambda w: sort_key(w.encode()))
    # ASCII case-insensitive first, then byte order (upper case first).
    assert ordered == ["_x", "a", "Ab", "aB", "ab", "B", "b", "Z", "é"]


def test_round_trip(tmp_path):
    w = Writer(tmp_path / "out" / "test")
    w.add("cat", b"<b>cat</b>")
    w.add("Cat", b"Cat")
    w.add("dog", b"dog")
    w.add_synonym("cats", "cat")
    w.add_synonym("kitty", "cat")
    w.add_synonym("cat", "cat")  # same as the headword: ignored
    w.add_synonym("unicorns", "unicorn")  # no such entry: dropped
    stats = w.finish({"bookname": "Test", "description": "line 1\nline 2"})
    assert stats == {"words": 3, "synonyms": 2, "dict_bytes": 16}

    d = Dictionary(tmp_path / "out" / "test")
    assert d.words == ["Cat", "cat", "dog"]
    assert d.entry("cat") == "<b>cat</b>"
    assert d.entry("Cat") == "Cat"
    assert d.synonym_targets("cats") == ["cat"]
    assert d.synonym_targets("kitty") == ["cat"]
    assert d.info["bookname"] == "Test"
    assert d.info["wordcount"] == "3"
    assert d.info["synwordcount"] == "2"
    assert d.info["sametypesequence"] == "h"
    assert d.info["description"] == "line 1<br>line 2"
    assert int(d.info["idxfilesize"]) == (tmp_path / "out" / "test.idx").stat().st_size
    assert "idxoffsetbits" not in d.info
    assert not (tmp_path / "out" / "test.dict").exists()


def test_duplicate_words_are_merged(tmp_path):
    w = Writer(tmp_path / "test", joiner=b"|")
    w.add("a", b"one")
    w.add("b", b"bee")
    w.add("a", b"two")
    w.finish({})
    d = Dictionary(tmp_path / "test")
    assert d.words == ["a", "b"]
    assert d.entry("a") == "one|two"
    assert d.entry("b") == "bee"


def test_overlong_words_are_skipped(tmp_path):
    w = Writer(tmp_path / "test")
    w.add("x" * 256, b"long")
    w.add("ok", b"fine")
    w.finish({})
    assert w.skipped == ["x" * 256]
    assert Dictionary(tmp_path / "test").words == ["ok"]


def test_no_synonyms_no_syn_file(tmp_path):
    w = Writer(tmp_path / "test")
    w.add("a", b"a")
    w.finish({})
    assert not (tmp_path / "test.syn").exists()
    assert "synwordcount" not in Dictionary(tmp_path / "test").info


def test_uncompressed(tmp_path):
    w = Writer(tmp_path / "test")
    w.add("a", b"data")
    w.finish({}, compress=False)
    assert (tmp_path / "test.dict").read_bytes() == b"data"
    assert not (tmp_path / "test.dict.dz").exists()


def test_too_big_for_dictzip_stays_uncompressed(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(stardict, "DICTZIP_MAX_SIZE", 3)
    w = Writer(tmp_path / "test")
    w.add("a", b"data")
    w.finish({})
    assert (tmp_path / "test.dict").exists()
    assert "too large for dictzip" in capsys.readouterr().err


@pytest.mark.parametrize("size", [0, 1, stardict.DICTZIP_CHUNK, 3 * stardict.DICTZIP_CHUNK + 17])
def test_dictzip(tmp_path, size):
    rng = random.Random(size)
    # Mix compressible text with random bytes.
    data = (b"the quick brown fox " * (size // 40 + 1))[: size // 2] + rng.randbytes(size)[
        : size - size // 2
    ]
    src, dst = tmp_path / "data", tmp_path / "data.dz"
    src.write_bytes(data)
    dictzip(src, dst)
    assert gzip.decompress(dst.read_bytes()) == data  # valid gzip, CRC and size
    chlen, chunks = read_dictzip(dst)
    assert chlen == stardict.DICTZIP_CHUNK
    assert all(len(c) == chlen for c in chunks[:-1])
    assert b"".join(chunks) == data  # every chunk inflates on its own


def test_dictzip_incompressible_chunks_fit(tmp_path):
    src, dst = tmp_path / "data", tmp_path / "data.dz"
    src.write_bytes(os.urandom(2 * stardict.DICTZIP_CHUNK))
    dictzip(src, dst)
    _, chunks = read_dictzip(dst)
    assert b"".join(chunks) == src.read_bytes()
