import re

from kaikki_to_stardict.render import (
    Options,
    bold_spans,
    clean,
    display_glosses,
    linkify,
    normalize_example,
    render_entry,
    render_pronunciation,
    render_translations,
    sense_tree,
    split_qualifiers,
    strip_etymology_tree,
)


def text(html: str) -> str:
    """The visible text of ``html``, one line per block."""
    html = re.sub(r"</?(div|p|blockquote)[^>]*>|<br>|<hr>", "\n", html)
    html = re.sub(r"<[^>]+>", "", html)
    return "\n".join(line for line in html.split("\n") if line.strip())


def record(**kw):
    base = {"word": "cat", "lang": "English", "lang_code": "en", "pos": "noun"}
    return {**base, **kw}


def test_split_qualifiers():
    assert split_qualifiers("(countable, nautical) A tackle.") == (
        ["countable, nautical"],
        "A tackle.",
    )
    assert split_qualifiers("(games) (archaic) Trap ball.") == (["games", "archaic"], "Trap ball.")
    assert split_qualifiers("(of a (big) cat) Feline.") == (["of a (big) cat"], "Feline.")
    assert split_qualifiers("No qualifier (here).") == ([], "No qualifier (here).")
    assert split_qualifiers("(unbalanced text") == ([], "(unbalanced text")


def test_display_glosses_merges_qualifier_only_levels():
    sense = {
        "glosses": ["Terms relating to things.", "A strong tackle."],
        "raw_glosses": [
            "(by extension) Terms relating to things.",
            "(nautical)",
            "A strong tackle.",
        ],
    }
    assert display_glosses(sense) == [
        "(by extension) Terms relating to things.",
        "(nautical) A strong tackle.",
    ]


def test_display_glosses_without_raw():
    assert display_glosses({"glosses": ["Abbreviation of catapult."]}) == [
        "Abbreviation of catapult."
    ]


def test_display_glosses_misaligned_uses_raw_leaf_only():
    sense = {"glosses": ["A", "B"], "raw_glosses": ["(x) B"]}
    assert display_glosses(sense) == ["A", "(x) B"]


def test_sense_tree_builds_hierarchy_from_gloss_paths():
    senses = [
        {"glosses": ["Animals.", "A mammal."]},
        {"glosses": ["Animals.", "A mammal.", "A pet."]},
        {"glosses": ["Animals.", "A big cat."]},
        {"glosses": ["People."]},
        {"glosses": ["People."]},  # a repeated gloss is a new sense
        {"tags": ["no-gloss"]},
    ]
    roots = sense_tree(senses)
    assert [n.key for n in roots] == ["Animals.", "People.", "People."]
    animals = roots[0]
    assert animals.sense is None  # a heading with no sense of its own
    assert [n.key for n in animals.children] == ["A mammal.", "A big cat."]
    assert [n.key for n in animals.children[0].children] == ["A pet."]
    assert animals.children[0].sense is senses[0]


def test_linkify():
    assert linkify("Plural of cat & dog.", [("cat", "cat")]) == (
        'Plural of <a href="bword://cat">cat</a> &amp; dog.'
    )
    # Overlapping matches are skipped; later occurrences are tried.
    assert linkify("ab ab", [("ab", "x"), ("b", "y")]) == (
        '<a href="bword://x">ab</a> a<a href="bword://y">b</a>'
    )


def test_bold_spans_merges_overlaps_and_escapes():
    assert bold_spans("a <cat> cats", [[3, 6], [8, 11], [8, 12], [50, 60]]) == (
        "a &lt;<b>cat</b>&gt; <b>cats</b>"
    )


def test_clean_broken_character_references():
    assert clean("x #92;forall y#61;1 &#92; #1234;") == "x \\forall y=1 &#92; #1234;"


def test_strip_etymology_tree():
    ety = "Etymology tree\nOld English pāl\nEnglish poleFrom Middle English pole."
    assert strip_etymology_tree(ety, "pole") == "From Middle English pole."
    assert strip_etymology_tree("From Latin.", "x") == "From Latin."
    assert strip_etymology_tree("Etymology tree\nSomething else", "x") == "Something else"


def test_pronunciation_groups_by_accent():
    sounds = [
        {"enpr": "kăt"},
        {"tags": ["Received-Pronunciation"], "ipa": "/ˈkæt/"},
        {"tags": ["Received-Pronunciation"], "ipa": "[ˈkʰæt]"},
        {"tags": ["US"], "note": "/æ/ raising", "ipa": "[ˈkʰeə̯t]"},
        {"audio": "En-us-cat.ogg"},
    ]
    assert text(render_pronunciation(sounds)) == (
        "IPA: (RP) /ˈkæt/, [ˈkʰæt]; (US, /æ/ raising) [ˈkʰeə̯t]\nenPR: kăt"
    )


CAT = record(
    head_templates=[{"expansion": "cat (plural cats)"}],
    sounds=[{"ipa": "/kæt/"}],
    etymology_text="Etymology tree\nEnglish catFrom Old English catt.",
    senses=[
        {
            "glosses": ["A mammal."],
            "raw_glosses": ["(countable) A mammal."],
            "synonyms": [{"word": "felid"}, {"word": "cat"}],
            "examples": [
                {"text": "The cat sat.", "bold_text_offsets": [[4, 7]], "type": "example"},
                {"text": "A cat, quoth he.", "ref": "1600, Someone:", "type": "quotation"},
                {"text": "Untyped quote.", "ref": "1700, Other:"},
            ],
        },
        {
            "glosses": ["A mammal.", "A pet."],
            "synonyms": [{"word": "felid"}, {"word": "kitty"}],
        },
    ],
    translations=[
        {
            "lang": "French",
            "lang_code": "fr",
            "sense": "animal",
            "word": "chat",
            "tags": ["masculine"],
        },
        {"lang": "French", "lang_code": "fr", "sense": "animal", "word": "chatte"},
        {"lang": "German", "lang_code": "de", "sense": "animal", "word": "Katze"},
    ],
)


def test_render_entry():
    html = render_entry([CAT])
    assert text(html) == "\n".join(
        [
            "IPA: /kæt/",
            "Etymology: From Old English catt.",
            "noun cat (plural cats)",
            "1. (countable) A mammal.",
            "The cat sat.",
            "1.1. A pet.",
        ]
    )
    assert "The <b>cat</b> sat." in html
    assert "Synonyms" not in html
    assert "Translations" not in html


def test_synonyms_option():
    html = render_entry([CAT], Options(synonyms=True))
    lines = text(html).split("\n")
    # The headword itself and the parent's synonyms are left out.
    assert lines[lines.index("1. (countable) A mammal.") + 1] == "Synonyms: felid"
    assert lines[lines.index("1.1. A pet.") + 1] == "Synonyms: kitty"
    assert '<a href="bword://kitty">kitty</a>' in html
    word_level = record(synonyms=[{"word": "moggy"}], senses=[{"glosses": ["A mammal."]}])
    assert "Synonyms" not in render_entry([word_level])
    assert "Synonyms: moggy" in text(render_entry([word_level], Options(synonyms=True)))


def test_blank_lines_between_sections():
    noun = record(sounds=[{"ipa": "/kæt/"}], senses=[{"glosses": ["A mammal."]}])
    verb = record(pos="verb", senses=[{"glosses": ["To hoist."]}])
    html = render_entry([noun, verb])
    # A <br> right after a block element makes an empty line.
    assert '/kæt/</div><br><p><span style="color:#2e7d32"><i>noun' in html
    assert 'A mammal.</div><br><p><span style="color:#2e7d32"><i>verb' in html
    assert not html.endswith("<br>")


def test_etymology_comes_before_definitions():
    rec = record(
        sounds=[{"ipa": "/kæt/"}],
        etymology_text="From Latin.",
        senses=[{"glosses": ["A mammal."]}],
    )
    html = render_entry([rec])
    assert "/kæt/</div><br><div><small>Etymology:</small> From Latin.</div><br><p>" in html
    assert text(html).split("\n") == [
        "IPA: /kæt/",
        "Etymology: From Latin.",
        "noun cat",
        "1. A mammal.",
    ]


def test_blank_lines_around_etymology_rule():
    one = record(etymology_number="1", senses=[{"glosses": ["An animal."]}])
    two = record(etymology_number="2", senses=[{"glosses": ["A boat."]}])
    html = render_entry([one, two])
    assert "An animal.</div><br><hr><br><p><b>Etymology 2</b></p>" in html


def test_render_entry_options():
    html = render_entry(
        [CAT],
        Options(pronunciation=False, etymology=False, quotations=True, max_examples=10),
    )
    assert "IPA" not in html and "Etymology" not in html
    assert "1600, Someone:" in html and "Untyped quote." in html
    assert "The cat sat." not in render_entry([CAT], Options(max_examples=0))


def test_translations():
    assert text(render_translations(CAT, Options(translations=True))) == (
        "Translations: (animal) French: chat masculine, chatte; German: Katze"
    )
    only_de = Options(translations=True, translation_langs=frozenset({"de"}))
    assert text(render_translations(CAT, only_de)) == "Translations: (animal) German: Katze"


def test_form_of_target_is_linked():
    cats = record(
        word="cats",
        senses=[{"glosses": ["plural of cat"], "form_of": [{"word": "cat"}]}],
    )
    assert 'plural of <a href="bword://cat">cat</a>' in render_entry([cats])


def test_gloss_links_option():
    rec = record(
        senses=[{"glosses": ["A feline animal."], "links": [["feline", "feline#English"]]}]
    )
    assert "bword://feline" not in render_entry([rec])
    assert '<a href="bword://feline">feline</a>' in render_entry([rec], Options(gloss_links=True))


def test_multiple_etymologies_are_numbered():
    one = record(etymology_number="1", senses=[{"glosses": ["An animal."]}])
    two = record(etymology_number="2", pos="verb", senses=[{"glosses": ["To hoist."]}])
    out = text(render_entry([one, two]))
    assert out.startswith("Etymology 1\n")
    assert "Etymology 2\nverb cat" in out


def test_lone_etymology_heading_is_dropped():
    one = record(etymology_number="1", senses=[{"glosses": ["An animal."]}])
    empty = record(etymology_number="2", senses=[{"tags": ["no-gloss"]}])
    assert "Etymology 1" not in render_entry([one, empty])


def test_record_without_glosses_renders_nothing():
    assert render_entry([record(senses=[{"tags": ["no-gloss"]}])]) == ""


def test_html_is_escaped():
    rec = record(word="a<b", senses=[{"glosses": ["Less <than> & more."]}])
    html = render_entry([rec])
    assert "<b>a&lt;b</b>" in html
    assert "Less &lt;than&gt; &amp; more." in html


def test_normalize_example():
    assert normalize_example({"text": ""}) is None
    assert normalize_example({"text": "a free man"})["type"] == "example"
    assert normalize_example({"text": "x", "ref": "1600, A:"})["type"] == "quotation"
    assert normalize_example({"text": "Near-synonym: utopia"}) is None
    assert normalize_example({"text": "Holonym: body"}) is None
    for cited in [
        "1879, Someone, Book",
        "c. 1600, Shakespeare",
        "October 10, 1714, Pope",
        "1981-1982, Lou Sullivan",
        "1854: Thoreau, Walden",
    ]:
        assert normalize_example({"text": cited})["type"] == "quotation", cited


def test_normalize_example_splits_citation_line():
    ex = normalize_example(
        {"text": "1854: Thoreau, Walden\nThe cat sat.", "bold_text_offsets": [[26, 29]]}
    )
    assert ex["ref"] == "1854: Thoreau, Walden"
    assert ex["text"] == "The cat sat."
    assert ex["bold_text_offsets"] == [(4, 7)]
