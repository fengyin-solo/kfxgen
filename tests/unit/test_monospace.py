"""Inline code and monospace text keep a monospace font (#242).

`<code>`, `<kbd>`, `<samp>`, `<tt>` and `font-family: monospace` came out in
the body font, so `list` (a Python builtin) read the same as "the list".
Kindle Previewer 4 writes the run's CSS family as `$11` ("monospace", or
"courier new,monospace"), and a `<pre>` or monospace paragraph's at block
level. kfxgen writes "monospace" unless an embedded face matches the run's
family, which then wins (#15).
"""

import pytest
from lxml import etree

from kfxgen import converter as _conv
from kfxgen.inline_style import FLAG_BOLD, make_mono_flag, mono_families
from kfxgen.native_generator import NativeKFXGenerator
from kfxgen.kfxlib_minimal.ion import IS

#: The parts of calibre's UA sheet these tests use (templates/html.css).
UA = {t: "monospace" for t in ("code", "kbd", "samp", "tt", "pre")}
CSS = {
    "mono": "monospace",
    "cour": '"Courier New", monospace',
    "consolas": "Consolas",
    "serif": "serif",
}


def _resolver(elem):
    """font-family inherits; a class or the UA sheet sets it."""
    for e in [elem, *elem.iterancestors()]:
        fam = CSS.get(e.get("class") or "") or UA.get(etree.QName(e).localname)
        if fam:
            return {"font-family": fam}
    return {"font-family": "Georgia, serif"}


def _doc(body):
    xhtml = f'<html xmlns="http://www.w3.org/1999/xhtml"><body>{body}</body></html>'
    return etree.fromstring(xhtml.encode())


def _mono_runs(body, resolver=_resolver):
    (block,) = _conv.extract_blocks_from_html(_doc(body), style_resolver=resolver)
    text = block["text"]
    return [
        (text[s : s + n], mono_families(flags))
        for s, n, flags in block["spans"]
        if mono_families(flags)
    ]


@pytest.mark.unit
@pytest.mark.parametrize("tag", ["code", "kbd", "samp", "tt"])
def test_code_tags_are_monospace_runs(tag):
    assert _mono_runs(f"<p>Call <{tag}>foo()</{tag}> now.</p>") == [
        ("foo()", ("monospace",))
    ]


@pytest.mark.unit
def test_code_tags_are_monospace_without_a_stylizer():
    assert _mono_runs("<p>Call <code>foo()</code> now.</p>", resolver=None) == [
        ("foo()", ("monospace",))
    ]


@pytest.mark.unit
@pytest.mark.parametrize(
    ("cls", "families"),
    [
        ("mono", ("monospace",)),
        ("cour", ("courier new", "monospace")),
        ("consolas", ("consolas",)),
    ],
)
def test_a_monospace_css_family_is_a_monospace_run(cls, families):
    body = f'<p>a <span class="{cls}">x = 1</span> b</p>'
    assert _mono_runs(body) == [("x = 1", families)]


@pytest.mark.unit
def test_var_is_not_monospace():
    assert _mono_runs("<p>Let <var>n</var> be.</p>") == []


@pytest.mark.unit
def test_a_monospace_block_has_no_monospace_run():
    """A <pre>'s own family is the block's, like a paragraph's own bold."""
    assert _mono_runs("<pre>x = 1\n<b>y</b> = 2</pre>") == []


@pytest.mark.unit
def test_a_proportional_span_inside_code_ends_the_run():
    runs = _mono_runs('<p><code>a <span class="serif">b</span> c</code></p>')
    assert "b" not in "".join(t for t, _ in runs)
    assert "".join(t for t, _ in runs).split() == ["a", "c"]


def _styles(blocks, font_table=None):
    g = NativeKFXGenerator()
    text = "".join(b["text"] for b in blocks)
    chapter = {"title": "C1", "text": text, "blocks": blocks}
    g.generate_full_book(
        title="T", author="A", chapters=[chapter], font_table=font_table
    )
    return [f.value for f in g.fragments if str(f.ftype) == "$157"]


def _families(styles):
    return {str(s[IS("$11")]) for s in styles if IS("$11") in s}


@pytest.mark.unit
def test_a_monospace_run_is_written_monospace():
    span = (5, 5, frozenset({make_mono_flag(("monospace",))}))
    styles = _styles([{"text": "Call foo() now.", "spans": [span]}])
    assert _families(styles) == {"monospace"}


@pytest.mark.unit
def test_a_bold_monospace_run_is_bold_and_monospace():
    span = (5, 5, frozenset({make_mono_flag(("monospace",)), FLAG_BOLD}))
    styles = _styles([{"text": "Call foo() now.", "spans": [span]}])
    (style,) = [s for s in styles if IS("$11") in s]
    assert str(style[IS("$13")]) == "$361"


@pytest.mark.unit
def test_a_monospace_block_is_written_monospace():
    block = {
        "text": "x = 1",
        "spans": [],
        "block_style": {"font_family": ["monospace"]},
    }
    assert _families(_styles([block])) == {"monospace"}


@pytest.mark.unit
def test_an_embedded_monospace_face_wins():
    from kfxgen.font_table import Face, FontTable

    face = Face("inconsolata", 400, False, b"\x00\x01\x00\x00r", "inc-400", "r/f0")
    flag = make_mono_flag(("inconsolata", "monospace"))
    styles = _styles(
        [{"text": "Call foo() now.", "spans": [(5, 5, frozenset({flag}))]}],
        font_table=FontTable([face]),
    )
    assert "inc-400" in _families(styles)
    assert "monospace" not in _families(styles)


@pytest.mark.unit
def test_a_book_without_monospace_writes_no_family():
    styles = _styles([{"text": "Plain words.", "spans": []}])
    assert _families(styles) == set()


@pytest.mark.unit
def test_linked_code_keeps_its_monospace():
    """`<a href><code>foo</code></a>`, common in API references: a run that
    is only a link gets no style, one that is also monospace must keep it."""
    from kfxgen.inline_style import make_link_flag

    flags = frozenset({make_link_flag("c.xhtml#t"), make_mono_flag(("monospace",))})
    blocks = [
        {"text": "See foo.", "spans": [(4, 3, flags)]},
        {
            "text": "Target.",
            "spans": [],
            "anchor_keys": ["c.xhtml#t"],
            "anchor_offsets": {"c.xhtml#t": 0},
        },
    ]
    assert _families(_styles(blocks)) == {"monospace"}
