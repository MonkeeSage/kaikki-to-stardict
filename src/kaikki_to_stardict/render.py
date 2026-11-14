"""Render wiktextract word records as StarDict HTML entries.

The markup sticks to tags every StarDict HTML reader understands (``b``,
``i``, ``small``, ``div``, ``p``, ``blockquote``, ``a`` and ``span`` with an
inline color) and numbers senses in the text ("1.", "1.2.") rather than with
nested ``<ol>`` lists, so the structure survives readers that don't indent.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from html import escape
from itertools import groupby
from typing import Any

Record = dict[str, Any]

POS_COLOR = "#2e7d32"

POS_NAMES = {
    "adj": "adjective",
    "adv": "adverb",
    "adv_phrase": "adverbial phrase",
    "conj": "conjunction",
    "det": "determiner",
    "intj": "interjection",
    "name": "proper noun",
    "num": "numeral",
    "postp": "postposition",
    "prep": "preposition",
    "prep_phrase": "prepositional phrase",
    "pron": "pronoun",
    "punct": "punctuation mark",
}

SOUND_TAGS = {
    "Received-Pronunciation": "RP",
    "General-American": "GA",
}

# Linkage lists shown with Options.synonyms, per sense and per word.
SYNONYMS = [("synonyms", "Synonyms"), ("antonyms", "Antonyms")]

# Word-level linkage lists shown with Options.related, in display order.
RELATED = [
    ("derived", "Derived terms"),
    ("related", "Related terms"),
    ("hypernyms", "Hypernyms"),
    ("hyponyms", "Hyponyms"),
    ("coordinate_terms", "Coordinate terms"),
    ("holonyms", "Holonyms"),
    ("meronyms", "Meronyms"),
    ("troponyms", "Troponyms"),
    ("proverbs", "Proverbs"),
]


@dataclass(frozen=True)
class Options:
    pronunciation: bool = True
    etymology: bool = True
    max_examples: int = 3  # per sense; 0 disables examples
    quotations: bool = False  # include dated literary quotations among examples
    synonyms: bool = False  # synonyms and antonyms
    related: bool = False  # derived terms, hyponyms, ...
    translations: bool = False
    translation_langs: frozenset[str] | None = None  # language codes; None = all
    gloss_links: bool = False  # link words inside glosses to their entries


# -- small helpers ----------------------------------------------------------


# Math markup sometimes arrives with "&" stripped from its character
# references: "#92;forall x" for "\forall x".
_BROKEN_REF = re.compile(r"(?<!&)#(\d{2,3});")


def clean(text: str) -> str:
    return _BROKEN_REF.sub(lambda m: chr(n) if 32 <= (n := int(m[1])) < 127 else m[0], text)


def e(text: str) -> str:
    return escape(clean(text), quote=False)


def link(word: str, text: str | None = None) -> str:
    return f'<a href="bword://{escape(word)}">{e(word if text is None else text)}</a>'


def label(text: str) -> str:
    return f"<small>{e(text)}:</small>"


def pos_name(pos: str) -> str:
    return POS_NAMES.get(pos, pos.replace("_", " "))


def tag_label(tag: str) -> str:
    return SOUND_TAGS.get(tag, tag.replace("-", " "))


def clean_linkage_word(word: str) -> str:
    # Taxonomic names sometimes leak in as "panther[Panthera".
    if "[" in word and not word.endswith("]"):
        word = word.split("[", 1)[0]
    return word.strip()


def split_qualifiers(text: str) -> tuple[list[str], str]:
    """Split leading parenthesized qualifiers off ``text``.

    ``"(countable, nautical) A tackle."`` gives
    ``(["countable, nautical"], "A tackle.")``. Parentheses may nest.
    """
    quals = []
    rest = text.lstrip()
    while rest.startswith("(") and (end := _closing_paren(rest)) > 0:
        quals.append(rest[1:end])
        rest = rest[end + 1 :].lstrip()
    return quals, rest


def _closing_paren(text: str) -> int:
    """Index of the ")" matching the "(" at ``text[0]``, or -1 if unbalanced."""
    depth = 0
    for i, ch in enumerate(text):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return i
    return -1


def linkify(text: str, links: Iterable[tuple[str, str]]) -> str:
    """Escape ``text``, linking the first free occurrence of each display text."""
    spans: list[tuple[int, int, str]] = []
    for shown, target in links:
        if not shown or not target:
            continue
        start = 0
        while (i := text.find(shown, start)) >= 0:
            end = i + len(shown)
            if all(end <= s or i >= t for s, t, _ in spans):
                spans.append((i, end, target))
                break
            start = i + 1
    out, pos = [], 0
    for start, end, target in sorted(spans):
        out.append(e(text[pos:start]))
        out.append(link(target, text[start:end]))
        pos = end
    out.append(e(text[pos:]))
    return "".join(out)


def bold_spans(text: str, offsets: Sequence[Sequence[int]] | None) -> str:
    """Escape ``text``, bolding the (possibly overlapping) ``offsets`` ranges."""
    ranges = sorted(
        (max(0, s), min(len(text), t)) for s, t in (offsets or []) if 0 <= s < t and s < len(text)
    )
    merged: list[list[int]] = []
    for s, t in ranges:
        if merged and s <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], t)
        else:
            merged.append([s, t])
    out, pos = [], 0
    for s, t in merged:
        out.append(e(text[pos:s]))
        out.append(f"<b>{e(text[s:t])}</b>")
        pos = t
    out.append(e(text[pos:]))
    return "".join(out)


def strip_etymology_tree(text: str, word: str) -> str:
    """Drop the "Etymology tree" listing wiktextract puts before the prose.

    The tree ends with the line "English <word>", which is often run
    together with the first sentence ("English poleFrom Middle English ...").
    """
    if not text.startswith("Etymology tree"):
        return text
    marker = f"\nEnglish {word}"
    i = text.rfind(marker)
    if i < 0:
        return text.split("\n", 1)[1] if "\n" in text else ""
    return text[i + len(marker) :].lstrip()


# -- senses -----------------------------------------------------------------


@dataclass
class SenseNode:
    key: str  # the cleaned gloss, used to match parents
    text: str  # the gloss as displayed, possibly with "(qualifiers)"
    sense: dict[str, Any] | None = None  # None for group headings with no sense of their own
    children: list[SenseNode] = field(default_factory=list)


def display_glosses(sense: dict[str, Any]) -> list[str]:
    """One display string per level of the sense's gloss path.

    ``glosses`` holds the path from the top-level sense down; ``raw_glosses``
    the same with qualifiers kept, but a qualifier-only level such as
    "(games)" may appear in it with no matching gloss.
    """
    glosses = sense.get("glosses") or []
    raw = sense.get("raw_glosses") or []
    merged: list[str] = []
    pending = ""
    for i, item in enumerate(raw):
        quals, rest = split_qualifiers(item)
        if quals and not rest and i < len(raw) - 1:
            pending += item.strip() + " "
        else:
            merged.append(pending + item.strip())
            pending = ""
    if len(merged) == len(glosses):
        return merged
    out = list(glosses)
    if merged and out and merged[-1].endswith(out[-1]):
        out[-1] = merged[-1]
    return out


def sense_tree(senses: Iterable[dict[str, Any]]) -> list[SenseNode]:
    roots: list[SenseNode] = []
    for sense in senses:
        path = sense.get("glosses")
        if not path:
            continue
        texts = display_glosses(sense)
        siblings = roots
        for level, key in enumerate(path):
            last = level == len(path) - 1
            node = siblings[-1] if siblings and siblings[-1].key == key else None
            if node is None or (last and node.sense is not None):
                node = SenseNode(key, texts[level])
                siblings.append(node)
            if last:
                node.sense = sense
                node.text = texts[level]
            siblings = node.children
    return roots


def sense_links(sense: dict[str, Any], opts: Options) -> list[tuple[str, str]]:
    links = [
        (x["word"], x["word"])
        for k in ("form_of", "alt_of")
        for x in sense.get(k, [])
        if x.get("word")
    ]
    if opts.gloss_links:
        for item in sense.get("links") or []:
            if len(item) == 2 and item[0] and item[1]:
                links.append((item[0], item[1].split("#", 1)[0]))
    return links


def render_gloss(text: str, links: list[tuple[str, str]]) -> str:
    quals, rest = split_qualifiers(text)
    out = "".join(f"<i>({e(q)})</i> " for q in quals)
    return out + linkify(rest, links)


# Untyped examples that are really quotations with the citation run into the
# text ("1879, I. T. Tregellas, Peeps Into ...") or linkage lines parsed as
# examples ("Near-synonym: utopia").
_CITATION = re.compile(
    r"(?:(?:c\.|a\.|ca\.|circa|p\.)\s*)?(?:[A-Z][a-z]+\.? \d{1,2}, )?\d{3,4}s?"
    r"(?:\s*[-–]\s*\d+)?[,:.\s]"
)
_LINKAGE_LINE = re.compile(
    r"(?:Near-)?(?:Synonym|Antonym|Hypernym|Hyponym|Meronym|Holonym|Troponym|"
    r"Coordinate term|Related term|Alternative form|Derived term|See also)s?:\s",
    re.IGNORECASE,
)


def normalize_example(ex: dict[str, Any]) -> dict[str, Any] | None:
    """``ex`` with ``type`` filled in, or None if it isn't really an example."""
    text = ex.get("text")
    if not text:
        return None
    if ex.get("type") or ex.get("ref"):
        return ex if ex.get("type") else {**ex, "type": "quotation"}
    if _LINKAGE_LINE.match(text):
        return None
    if not _CITATION.match(text):
        return {**ex, "type": "example"}
    ex = {**ex, "type": "quotation"}
    ref, sep, rest = text.partition("\n")
    if sep and rest.strip():
        shift = len(ref) + 1
        offsets = [(s - shift, t - shift) for s, t in ex.get("bold_text_offsets") or []]
        ex.update(ref=ref, text=rest, bold_text_offsets=offsets)
    return ex


def render_example(ex: dict[str, Any]) -> str:
    text = bold_spans(ex.get("text", ""), ex.get("bold_text_offsets"))
    if ex.get("roman"):
        text += f" ({e(ex['roman'])})"
    translation = ex.get("translation") or ex.get("english")
    if translation:
        text += f" ― {e(translation)}"
    ref = f"<small>{e(ex['ref'])}</small> " if ex.get("ref") else ""
    return f"<div>{ref}<i>{text}</i></div>"


def render_linkage_items(items: Iterable[dict[str, Any]], exclude: Iterable[str] = ()) -> str:
    words: list[str] = []
    seen = set(exclude)
    for item in items:
        word = clean_linkage_word(item.get("word") or "")
        if word and word not in seen:
            seen.add(word)
            words.append(word)
    return ", ".join(link(w) for w in words)


def linkage_words(sense: dict[str, Any] | None, key: str) -> set[str]:
    if sense is None:
        return set()
    return {clean_linkage_word(x.get("word") or "") for x in sense.get(key, [])}


def render_senses(
    nodes: list[SenseNode],
    opts: Options,
    word: str,
    prefix: str = "",
    parent: dict[str, Any] | None = None,
) -> str:
    out = []
    for n, node in enumerate(nodes, 1):
        number = f"{prefix}{n}."
        sense = node.sense
        parts = [f"<b>{number}</b> {render_gloss(node.text, sense_links(sense or {}, opts))}"]
        if sense is not None:
            for key, name in SYNONYMS if opts.synonyms else ():
                # Sub-senses repeat their parent's linkages; show only new ones.
                exclude = linkage_words(parent, key) | {word}
                items = render_linkage_items(sense.get(key, []), exclude)
                if items:
                    parts.append(f"<div>{label(name)} {items}</div>")
            examples = [
                ex
                for ex in map(normalize_example, sense.get("examples", []))
                if ex is not None and (opts.quotations or ex["type"] != "quotation")
            ][: opts.max_examples]
            if examples:
                parts.append(
                    "<blockquote>" + "".join(map(render_example, examples)) + "</blockquote>"
                )
        if node.children:
            parts.append(render_senses(node.children, opts, word, number, sense or parent))
        out.append(f'<div class="sense">{"".join(parts)}</div>')
    return "".join(out)


# -- word-level sections ----------------------------------------------------


def render_head(record: Record) -> str:
    word = record["word"]
    pos = f'<span style="color:{POS_COLOR}"><i>{e(pos_name(record.get("pos", "")))}</i></span>'
    heads = []
    for t in record.get("head_templates", []):
        exp = (t.get("expansion") or "").strip()
        if not exp:
            continue
        if exp.startswith(word):
            heads.append(f"<b>{e(word)}</b>{e(exp[len(word) :])}")
        else:
            heads.append(e(exp))
    head = "; ".join(heads) if heads else f"<b>{e(word)}</b>"
    return f"<p>{pos} {head}</p>"


def render_pronunciation(sounds: list[dict[str, Any]]) -> str:
    groups: dict[str, list[str]] = {}
    enpr: list[str] = []
    for s in sounds:
        if s.get("enpr") and s["enpr"] not in enpr:
            enpr.append(s["enpr"])
        ipa = s.get("ipa")
        if not ipa:
            continue
        where = ", ".join(tag_label(t) for t in s.get("tags", []))
        if s.get("note"):
            where = f"{where}, {s['note']}" if where else s["note"]
        ipas = groups.setdefault(where, [])
        if ipa not in ipas:
            ipas.append(ipa)
    parts = []
    for where, ipas in groups.items():
        qual = f"<i>({e(where)})</i> " if where else ""
        parts.append(qual + e(", ".join(ipas)))
    lines = []
    if parts:
        lines.append(f"<div>{label('IPA')} {'; '.join(parts)}</div>")
    if enpr:
        lines.append(f"<div>{label('enPR')} {e(', '.join(enpr))}</div>")
    return "".join(lines)


def render_word_linkages(record: Record, opts: Options) -> str:
    keys = list(SYNONYMS) if opts.synonyms else []
    if opts.related:
        keys += RELATED
    out = []
    for key, name in keys:
        items = record.get(key)
        if not items:
            continue
        # Lists often come in groups for different senses.
        groups = []
        for sense, group in groupby(items, key=lambda x: x.get("sense") or ""):
            words = render_linkage_items(group, {record["word"]})
            if words:
                groups.append((f"<i>({e(sense)})</i> " if sense else "") + words)
        if groups:
            out.append(f"<div>{label(name)} {'; '.join(groups)}</div>")
    return "".join(out)


def render_translations(record: Record, opts: Options) -> str:
    out = []
    items = [
        t
        for t in record.get("translations", [])
        if opts.translation_langs is None
        or (t.get("lang_code") or t.get("code")) in opts.translation_langs
    ]
    for sense, group in groupby(items, key=lambda t: t.get("sense") or ""):
        langs: dict[str, list[str]] = {}
        for t in group:
            if t.get("word"):
                text = e(t["word"])
                extra = [x for x in (t.get("alt"), t.get("roman")) if x]
                if extra:
                    text += f" ({e(', '.join(extra))})"
                if t.get("tags"):
                    text += f" <i>{e(' '.join(t['tags']))}</i>"
            elif t.get("note"):
                text = f"<i>{e(t['note'])}</i>"
            else:
                continue
            langs.setdefault(t.get("lang") or "?", []).append(text)
        if langs:
            body = "; ".join(f"{e(lang)}: {', '.join(words)}" for lang, words in langs.items())
            qual = f" <i>({e(sense)})</i>" if sense else ""
            out.append(f"<div>{label('Translations')}{qual} {body}</div>")
    return "".join(out)


def render_record(record: Record, opts: Options) -> str:
    senses = render_senses(sense_tree(record.get("senses", [])), opts, record["word"])
    if not senses:
        return ""
    parts = [render_head(record), senses, render_word_linkages(record, opts)]
    if opts.translations:
        parts.append(render_translations(record, opts))
    return "".join(parts)


def etymology_key(record: Record) -> str:
    return record.get("etymology_number") or ""


def render_entry(records: Sequence[Record], opts: Options = Options()) -> str:
    """HTML for all records (parts of speech, etymologies) of one headword."""
    groups = []
    for _, g in groupby(records, key=etymology_key):
        group = list(g)
        # <br> after a block gives a blank line, separating parts of speech.
        body = "<br>".join(filter(None, (render_record(r, opts) for r in group)))
        if body:
            groups.append((group, body))
    out = []
    last_pron = None
    for n, (group, body) in enumerate(groups, 1):
        section = []
        if len(groups) > 1:
            section.append(f"<p><b>Etymology {n}</b></p>")
        if opts.pronunciation:
            pron = render_pronunciation(group[0].get("sounds", []))
            if pron and pron != last_pron:
                section.append(pron + "<br>")
                last_pron = pron
        if opts.etymology:
            ety = strip_etymology_tree(group[0].get("etymology_text", ""), group[0]["word"])
            if ety.strip():
                lines = "<br>".join(e(line) for line in ety.strip().split("\n"))
                section.append(f"<div>{label('Etymology')} {lines}</div><br>")
        section.append(body)
        out.append("".join(section))
    return "<br><hr><br>".join(out)
