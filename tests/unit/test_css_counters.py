"""CSS counters in generated content.

Books number chapters, steps and nested lists with counters, not with the
numbers in the text:

    body { counter-reset: chapter }
    h1 { counter-increment: chapter }
    h1::before { content: "Chapter " counter(chapter) ". " }
    li::marker { content: counters(item, ".") " " }

Strings and attr() were generated already, but counter()/counters() printed
nothing, leaving only the punctuation around them. The counter properties are
now applied in document order, with the element-tree scoping CSS gives them,
their text written into the KFX. An item's ::marker content wins over the
number derived from start/value/reversed/list-style-type; without a custom
marker the derived numbering is unchanged. State is per spine document.
"""

import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from lxml import etree

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "plugin"))

from kfxgen import converter  # noqa: E402
from kfxgen.converter import (  # noqa: E402
    _build_style_resolver,
    extract_blocks_from_html,
)
from tests._helpers import NullLog  # noqa: E402
from tests._kfx_introspect import by_type, load_fragments, val  # noqa: E402
from tests.fixtures.epub_builder import EpubBuilder  # noqa: E402
from tests.fixtures.oeb_shim import EpubAsOeb  # noqa: E402

pytestmark = [pytest.mark.tier1, pytest.mark.unit]

_NS = "http://www.w3.org/1999/xhtml"


def _doc(body):
    return etree.fromstring(f'<html xmlns="{_NS}"><body>{body}</body></html>'.encode())


def _resolver(css_by_tag, css_by_class=None):
    """A style_resolver serving css dicts by tag, or by class for an element
    carrying one in `css_by_class` (".r" matches class="r")."""
    by_class = css_by_class or {}

    def resolve(elem):
        cls = elem.get("class")
        if cls is not None and f".{cls}" in by_class:
            return by_class[f".{cls}"]
        return css_by_tag.get(etree.QName(elem).localname, {})

    return resolve


def _texts(body, resolver):
    return [
        b["text"]
        for b in extract_blocks_from_html(
            _doc(body), style_resolver=resolver, base_href="c.xhtml"
        )
    ]


# ── reset / increment ─────────────────────────────────────────────────────────


def test_reset_then_increment_numbers_chapters():
    css = {
        "body": {"counter-reset": "chapter"},
        "h1": {
            "counter-increment": "chapter",
            "gen": {"before": '"Chapter " counter(chapter) ". "'},
        },
    }
    assert _texts("<h1>First</h1><h1>Second</h1>", _resolver(css)) == [
        "Chapter 1. First",
        "Chapter 2. Second",
    ]


def test_reset_value_and_increment_step():
    css = {
        "body": {"counter-reset": "n 9"},
        "p": {
            "counter-increment": "n 2",
            "gen": {"before": 'counter(n) " "'},
        },
    }
    assert _texts("<p>a</p><p>b</p>", _resolver(css)) == ["11 a", "13 b"]


def test_negative_increment_counts_down():
    css = {
        "body": {"counter-reset": "n 3"},
        "p": {
            "counter-increment": "n -1",
            "gen": {"before": 'counter(n) " "'},
        },
    }
    assert _texts("<p>a</p><p>b</p>", _resolver(css)) == ["2 a", "1 b"]


def test_several_counters_in_one_declaration():
    css = {
        "body": {"counter-reset": "a b"},
        "p": {
            "counter-increment": "a b 3",
            "gen": {"before": 'counter(a) "/" counter(b) " "'},
        },
    }
    assert _texts("<p>x</p><p>y</p>", _resolver(css)) == ["1/3 x", "2/6 y"]


def test_reset_and_increment_on_the_same_element_increments_first():
    # The value ::before reads already reflects this element's own
    # increment: a reset to 0 on the heading would print 1, not 0.
    css = {
        "h1": {
            "counter-reset": "n",
            "counter-increment": "n",
            "gen": {"before": 'counter(n) " "'},
        },
    }
    assert _texts("<h1>x</h1>", _resolver(css)) == ["1 x"]


def test_increment_without_a_reset_instantiates_on_the_parent():
    css = {"h1": {"counter-increment": "n", "gen": {"before": '"[" counter(n) "] "'}}}
    # CSS Lists instantiates the counter on the parent at 0 and then applies
    # the increment, so the first item reads 1 and siblings continue it.
    assert _texts("<h1>x</h1><h1>y</h1>", _resolver(css)) == [
        "[1] x",
        "[2] y",
    ]


def test_counter_referenced_but_never_touched_prints_nothing():
    css = {"p": {"gen": {"before": '"[" counter(ghost) "]" counter(other) " "'}}}
    assert _texts("<p>x</p>", _resolver(css)) == ["[] x"]


def test_none_declaration_makes_no_change():
    css = {
        "body": {"counter-reset": "n 5"},
        "p": {
            "counter-reset": "none",
            "counter-increment": "none",
            "gen": {"before": 'counter(n) " "'},
        },
    }
    assert _texts("<p>x</p>", _resolver(css)) == ["5 x"]


def test_counter_names_are_case_sensitive():
    css = {
        "body": {"counter-reset": "C 2"},
        "p": {"gen": {"before": 'counter(c) "/" counter(C) " "'}},
    }
    # C is reset at 2; the differently-spelt c is unknown and prints nothing.
    assert _texts("<p>x</p>", _resolver(css)) == ["/2 x"]


# ── list styles ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("style", "expected"),
    [
        ("decimal", "3"),
        ("decimal-leading-zero", "03"),
        ("lower-alpha", "c"),
        ("lower-latin", "c"),
        ("upper-alpha", "C"),
        ("upper-latin", "C"),
        ("lower-roman", "iii"),
        ("upper-roman", "III"),
        ("lower-greek", "γ"),
        ("Upper-Roman", "III"),  # style keywords are ASCII case-insensitive
        ("cjk-ideographic", "3"),  # unknown style falls back to decimal
    ],
)
def test_counter_takes_an_optional_list_style(style, expected):
    css = {
        "body": {"counter-reset": "n 2"},
        "p": {"counter-increment": "n", "gen": {"before": f'counter(n, {style}) " "'}},
    }
    assert _texts("<p>x</p>", _resolver(css)) == [f"{expected} x"]


def test_style_out_of_range_falls_back_to_decimal():
    css = {
        "body": {"counter-reset": "n 0"},
        "p": {"gen": {"before": 'counter(n, lower-roman) " "'}},
    }
    # Roman has no zero, so the value prints in decimal, as CSS defines.
    assert _texts("<p>x</p>", _resolver(css)) == ["0 x"]


# ── nested scope and counters() ───────────────────────────────────────────────


def test_counters_joins_the_whole_nesting_chain():
    css = {
        "body": {"counter-reset": "sec"},
        "h1": {
            "counter-increment": "sec",
            "counter-reset": "sub",
            "gen": {"before": 'counters(sec, ".") " "'},
        },
        "h2": {
            "counter-increment": "sub",
            "gen": {"before": 'counters(sec, ".") "." counter(sub) " "'},
        },
    }
    body = "<h1>A</h1><h2>a1</h2><h2>a2</h2><h1>B</h1><h2>b1</h2>"
    assert _texts(body, _resolver(css)) == [
        "1 A",
        "1.1 a1",
        "1.2 a2",
        "2 B",
        "2.1 b1",
    ]


def test_a_reset_scopes_to_its_element_following_siblings_and_descendants():
    css = {
        "section": {"counter-reset": "c"},
        "div": {"counter-reset": "c"},
        "p": {
            "counter-increment": "c",
            "gen": {"before": 'counters(c, ".") " "'},
        },
    }
    body = "<section><p>a</p><div><p>b</p></div><p>c</p></section><p>d</p>"
    # The inner reset (on the <div>) is in scope for the <div> itself, its
    # descendants and its following siblings (c reads "1.2"), then dies with
    # the <section>: d reads the section's own instance alone — the inner
    # reset shielded it from b's and c's increments, so it still stands at 1
    # and steps to 2.
    assert _texts(body, _resolver(css)) == [
        "1 a",
        "1.1 b",
        "1.2 c",
        "2 d",
    ]


def test_a_reset_reaches_the_originators_following_siblings():
    css = {
        "h1": {
            "counter-increment": "c",
            "gen": {"before": 'counter(c) " "'},
        },
    }
    css = _resolver(css, {".r": {"counter-reset": "c", **css["h1"]}})
    assert _texts('<h1 class="r">a</h1><h1>b</h1>', css) == ["1 a", "2 b"]


@pytest.mark.parametrize(
    ("sep", "style", "a", "b"),
    [
        (".", "decimal", "1", "1.1"),
        (" > ", "decimal", "1", "1 > 1"),
        (".", "upper-roman", "I", "I.I"),
        ("-", "lower-alpha", "a", "a-a"),
    ],
)
def test_counters_separator_and_style(sep, style, a, b):
    css = {
        "div": {"counter-reset": "c"},
        "p": {
            "counter-increment": "c",
            "gen": {"before": f'counters(c, "{sep}", {style}) " "'},
        },
    }
    body = "<div><p>a</p><div><p>b</p></div></div>"
    assert _texts(body, _resolver(css)) == [f"{a} a", f"{b} b"]


def test_counters_with_an_unknown_name_prints_nothing():
    css = {"p": {"gen": {"before": 'counters(nope, ".") "|"'}}}
    assert _texts("<p>x</p>", _resolver(css)) == ["|x"]


# ── strings, attr() and quotes mixed with counters ────────────────────────────


def test_attr_falls_back_to_empty_when_the_attribute_is_absent():
    css = {
        "body": {"counter-reset": "n"},
        "h1": {
            "counter-increment": "n",
            "gen": {"before": 'attr(id) "(" counter(n) ")" attr(title) " "'},
        },
    }
    assert _texts('<h1 id="ttl">x</h1><h1>y</h1>', _resolver(css)) == [
        "ttl(1) x",
        "(2) y",
    ]


def test_inline_generated_content_runs_inside_the_paragraph():
    css = {
        "p": {"counter-reset": "n"},
        "span": {
            "counter-increment": "n",
            "gen": {"before": '"[" counter(n) " "', "after": '"]" attr(role)'},
        },
    }
    body = '<p><span role="r">one</span> and <span>two</span></p>'
    assert _texts(body, _resolver(css)) == ["[1 one]r and [2 two]"]


def test_generated_after_reads_the_descendants_counters():
    body = '<div class="s"><p>a</p><p>b</p></div>'
    resolver = _resolver(
        {"p": {"counter-increment": "n", "gen": {"before": 'counter(n) " "'}}},
        {".s": {"counter-reset": "n", "gen": {"after": '" [" counter(n) "]"'}}},
    )
    assert _texts(body, resolver) == ["1 a", "2 b [2]"]


def test_q_content_mixes_quotes_strings_attr_and_counters():
    css = {
        "body": {"counter-reset": "n"},
        "q": {
            "counter-increment": "n",
            "q-css": {
                "before": 'counter(n) " [" attr(role) "] "',
                "after": "none",
            },
        },
    }
    body = '<p>x <q role="a">one</q> y <q>two</q></p>'
    assert _texts(body, _resolver(css)) == ["x 1 [a] one y 2 [] two"]


def test_q_open_quote_keyword_beside_a_counter_prints_the_counter():
    # The keyword prints no mark beside other tokens (Previewer's rule), but
    # the counter beside it prints; the keyword still moves the quote depth.
    css = {
        "body": {"counter-reset": "n"},
        "q": {
            "counter-increment": "n",
            "q-css": {"before": 'open-quote counter(n) " "', "after": "none"},
        },
    }
    assert _texts("<p><q>x</q></p>", _resolver(css)) == ["1 x"]


def test_quote_content_survives_next_to_counters():
    # counters() with a separator then a string, counter never named: only
    # the string remains.
    css = {"q": {"q-css": {"before": 'counters(c, ".") "|"'}}}
    assert _texts("<p><q>x</q></p>", _resolver(css)) == ["|x"]


# ── ::marker on list items ────────────────────────────────────────────────────


def test_custom_marker_overrides_start_value_and_reversed():
    css = {
        "ol": {"counter-reset": "step"},
        "li": {
            "counter-increment": "step",
            "display": "list-item",
            "gen": {"marker": '"Step " counter(step) ": "'},
        },
    }
    body = '<ol start="99" reversed=""><li value="5">a</li><li>b</li></ol>'
    assert _texts(body, _resolver(css)) == ["Step 1: a", "Step 2: b"]


def test_custom_marker_overrides_list_style_type_none():
    css = {
        "ol": {"counter-reset": "n"},
        "li": {
            "counter-increment": "n",
            "display": "list-item",
            "list-style-type": "none",
            "gen": {"marker": '"# " counter(n) " "'},
        },
    }
    assert _texts("<ol><li>a</li></ol>", _resolver(css)) == ["# 1 a"]


def test_empty_marker_content_suppresses_the_number():
    css = {
        "ol": {"counter-reset": "n"},
        "li": {
            "counter-increment": "n",
            "display": "list-item",
            "gen": {"marker": "none"},
        },
    }
    assert _texts("<ol><li>a</li><li>b</li></ol>", _resolver(css)) == ["a", "b"]


def test_normal_marker_falls_back_to_the_derived_number():
    css = {"li": {"display": "list-item", "gen": {"marker": "normal"}}}
    assert _texts('<ol start="3"><li>a</li></ol>', _resolver(css)) == ["3. a"]


def test_without_a_marker_the_current_numbering_is_kept():
    assert _texts('<ol start="4"><li>a</li><li>b</li></ol>', _resolver({})) == [
        "4. a",
        "5. b",
    ]


def test_marker_counters_number_nested_lists():
    css = {
        "ol": {"counter-reset": "item"},
        "li": {
            "counter-increment": "item",
            "display": "list-item",
            "list-style-type": "decimal",
            "gen": {"marker": 'counters(item, ".") " "'},
        },
    }
    body = "<ol><li>a<ol><li>c</li><li>d</li></ol></li><li>b</li></ol>"
    assert _texts(body, _resolver(css)) == [
        "1 a",
        "1.1 c",
        "1.2 d",
        "2 b",
    ]


def test_marker_takes_a_roman_style():
    css = {
        "ol": {"counter-reset": "n 0"},
        "li": {
            "counter-increment": "n",
            "display": "list-item",
            "gen": {"marker": 'counter(n, upper-roman) ". "'},
        },
    }
    assert _texts("<ol><li>a</li><li>b</li></ol>", _resolver(css)) == [
        "I. a",
        "II. b",
    ]


# ── scope boundaries ──────────────────────────────────────────────────────────


def test_counter_state_does_not_leak_to_the_next_spine_document():
    css = {
        "body": {"counter-reset": "n"},
        "h1": {
            "counter-increment": "n",
            "gen": {"before": 'counter(n) " "'},
        },
    }
    first = [
        b["text"]
        for b in extract_blocks_from_html(
            _doc("<h1>A</h1><h1>B</h1>"),
            style_resolver=_resolver(css),
            base_href="a.xhtml",
        )
    ]
    second = [
        b["text"]
        for b in extract_blocks_from_html(
            _doc("<h1>C</h1>"),
            style_resolver=_resolver(css),
            base_href="b.xhtml",
        )
    ]
    assert first == ["1 A", "2 B"]
    assert second == ["1 C"]


def test_a_hidden_subtree_changes_no_counter():
    css = {
        "body": {"counter-reset": "n"},
        "h1": {
            "counter-increment": "n",
            "gen": {"before": 'counter(n) " "'},
        },
    }
    body = '<h1 hidden="">hidden</h1><div hidden=""><h1>hidden too</h1></div><h1>shown</h1>'
    assert _texts(body, _resolver(css)) == ["1 shown"]


# ── the resolver hands the CSS to the counter walk ────────────────────────────


class _Style:
    """Calibre's Style: `.get` the element's own value, `[prop]` the computed
    one, `pseudo_classes(())` the ::before/::after/::marker rules."""

    def __init__(self, own=None, pseudo=None, computed=None):
        self._own = own or {}
        self._pseudo = pseudo or {}
        self._computed = computed or {}

    def get(self, k, default=None):
        return self._own.get(k, default)

    def __getitem__(self, k):
        if k in self._computed:
            return self._computed[k]
        raise KeyError(k)

    def pseudo_classes(self, filter_css):
        return self._pseudo


class _Stylizer:
    def __init__(self, by_tag):
        self._by_tag = by_tag

    def style(self, elem):
        tag = etree.QName(elem).localname if isinstance(elem.tag, str) else ""
        return self._by_tag.get(tag, _Style())


def test_resolver_exposes_counter_properties_and_pseudo_content():
    by_tag = {
        "body": _Style(own={"counter-reset": "chapter"}),
        "h1": _Style(
            own={"counter-increment": "chapter"},
            # Spelt "Before": pseudo names arrive as the selector spelt them.
            pseudo={"Before": {"content": '"Chapter " counter(chapter)'}},
        ),
        "li": _Style(
            own={"display": "list-item"},
            pseudo={"marker": {"content": "counters(item, '.')"}},
        ),
    }
    resolver = _build_style_resolver(
        None,
        None,
        NullLog(),
        stylizer_factory=lambda oeb, item: _Stylizer(by_tag),
    )
    body = resolver(etree.fromstring(f'<body xmlns="{_NS}"/>'))
    h1 = etree.fromstring(f'<h1 xmlns="{_NS}"/>')
    li = etree.fromstring(f'<li xmlns="{_NS}"/>')
    assert body["counter-reset"] == "chapter"
    h1css = resolver(h1)
    assert h1css["counter-increment"] == "chapter"
    assert h1css["gen"]["before"] == '"Chapter " counter(chapter)'
    assert resolver(li)["gen"]["marker"] == "counters(item, '.')"


# ── real KFX output ───────────────────────────────────────────────────────────


def test_counter_text_reaches_the_kfx_content_strings(tmp_path, monkeypatch):
    by_tag = {
        "body": _Style(own={"counter-reset": "chapter"}),
        "h2": _Style(
            own={"counter-increment": "chapter"},
            pseudo={"before": {"content": '"Chapter " counter(chapter) ". "'}},
        ),
        "ol": _Style(own={"counter-reset": "item"}),
        "li": _Style(
            own={"counter-increment": "item", "display": "list-item"},
            computed={"list-style-type": "decimal"},
            pseudo={"marker": {"content": 'counters(item, ".") " "'}},
        ),
    }
    monkeypatch.setattr(
        converter, "_default_stylizer", lambda oeb, item: _Stylizer(by_tag)
    )
    page = (
        '<?xml version="1.0" encoding="utf-8"?>'
        f'<html xmlns="{_NS}"><body>'
        "<h2>First</h2><h2>Second</h2>"
        "<ol><li>Open it<ol><li>Inside</li></ol></li>"
        "<li>Close it</li></ol>"
        "</body></html>"
    ).encode()
    epub = (
        EpubBuilder()
        .set_metadata(title="Counted", author="A")
        .add_chapter("One", page)
        .build(tmp_path, "book")
    )
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "book.kfx"
        converter.convert_oeb_to_kfx(
            EpubAsOeb(str(epub)),
            str(out),
            opts=MagicMock(kfxgen_disable_native_tables=False),
            log=NullLog(),
        )
        texts = [
            str(t) for f in by_type(load_fragments(out), "$145") for t in val(f)["$146"]
        ]
    for expected in (
        "Chapter 1. First",
        "Chapter 2. Second",
        "1 Open it",
        "1.1 Inside",
        "2 Close it",
    ):
        assert expected in texts, expected
