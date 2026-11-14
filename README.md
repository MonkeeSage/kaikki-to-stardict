# kaikki-to-stardict

Convert the English Wiktionary data extracted by
[wiktextract](https://github.com/tatuylonen/wiktextract) and published on
[kaikki.org](https://kaikki.org/dictionary/rawdata.html) into a rich-text (HTML)
StarDict dictionary.

## Usage

```sh
uv sync
uv run kaikki2stardict download   # data/raw-wiktextract-data.jsonl.gz (~3 GB)
uv run kaikki2stardict extract    # data/en-extract.jsonl.gz (~500 MB, ~1.5 min)
uv run kaikki2stardict build data/en-extract.jsonl.gz   # data/stardict/wiktionary-en.*
```

`download` resumes interrupted downloads and does nothing if the file on
kaikki.org hasn't changed (kaikki.org updates it about weekly). `extract` is
optional — `build` also reads the raw dump directly — but it makes repeated
builds quicker. `build` takes under a minute.

The default build has about 1.4 million entries and 870,000 synonyms (82 MB
`.dict.dz`). Copy the four `wiktionary-en.*` files to your reader's dictionary
directory.

### Build options

| Option | Effect |
|---|---|
| `--max-examples N` | usage examples per sense (default 3; 0 for none) |
| `--quotations` | also use dated literary quotations as examples |
| `--synonyms` | add synonyms and antonyms, per sense and per word |
| `--related` | add derived and related terms, hyponyms, hypernyms, ... |
| `--translations` | add translations (much larger) |
| `--translation-langs fr,de` | only these languages' translations (implies `--translations`) |
| `--gloss-links` | link words inside definitions to their entries |
| `--no-pronunciation`, `--no-etymology` | leave those sections out |
| `--no-form-of` | drop entries like "cats: plural of cat"; "cats" still finds "cat" |
| `--name`, `--bookname`, `-o` | file name, displayed title, output directory |
| `--no-compress` | write `.dict` instead of `.dict.dz` |

With everything enabled the entry data is about 830 MB (240 MB compressed).

## What the dictionary contains

One entry per headword, covering all its parts of speech and etymologies:

- the headword line with inflections ("cat (countable and uncountable, plural cats)")
- IPA and enPR pronunciation grouped by accent
- the etymology
- senses numbered like Wiktionary's own references (1., 1.1., 1.1.1.), with
  qualifiers such as *(countable, nautical)* and examples with the headword in
  bold (synonyms and antonyms with `--synonyms`)

Inflected forms, alternative forms and redirects ("ran", "cats", "grain of
salt") go in the `.syn` file, so looking them up finds the main entry.
Cross-references are `bword://` links.

The HTML uses only basic tags (`b`, `i`, `small`, `div`, `p`, `blockquote`,
`a`, and `span` with an inline color). Senses are numbered in the text instead
of with nested lists, so the hierarchy also shows in readers that don't indent.

## Data license

The dictionaries this produces contain Wiktionary content, which is under
CC BY-SA 4.0 and the GFDL; keep the attribution if you share them. The `.ifo`
description credits Wiktionary, wiktextract and kaikki.org, and records the
source file date.

## Development

```sh
uv run pytest
uv run ruff check . && uv run ruff format --check .
```
