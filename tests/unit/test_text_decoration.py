"""Strike-through and underline are carried (#237).

`<s>`, `<del>` and `<strike>` and CSS `text-decoration: line-through` came
out as plain text, so crossed-out words read as meant; `<u>`, `<ins>` and
`text-decoration: underline` lost their line. Kindle Previewer 4 writes a run
style with `$27: $328` for line-through and `$23: $328` for underline, both
for a run that has both.

A decoration is drawn through all the text inside the element that sets it,
and nothing inside can take it off, so the resolver gathers the element's own
lines and every ancestor's.
"""

from unittest.mock import MagicMock

import pytest
from lxml import etree

from kfxgen import converter as _conv
from tests._helpers import NullLog
from tests._kfx_introspect import by_type, iter_entries, load_fragments, val

UNDER, STRIKE = _conv.FLAG_UNDERLINE, _conv.FLAG_STRIKE

DECO = {
    "lt": "line-through",
    "ul": "underline",
    "both": "underline line-through",
}


def _doc(body):
    xhtml = f'<html xmlns="http://www.w3.org/1999/xhtml"><body>{body}</body></html>'
    return etree.fromstring(xhtml.encode())


def _resolver(elem):
    return {"text-decoration": DECO.get(elem.get("class") or "")}


def _runs(body, flag, resolver=None):
    (block,) = _conv.extract_blocks_from_html(_doc(body), style_resolver=resolver)
    text = block["text"]
    return [text[s : s + n] for s, n, flags in block["spans"] if flag in flags]


@pytest.mark.unit
@pytest.mark.parametrize("tag", ["s", "strike", "del"])
def test_strike_tags_give_a_strike_run(tag):
    assert _runs(f"<p>a <{tag}>gone</{tag}> b</p>", STRIKE) == ["gone"]


@pytest.mark.unit
@pytest.mark.parametrize("tag", ["u", "ins"])
def test_underline_tags_give_an_underline_run(tag):
    assert _runs(f"<p>a <{tag}>under</{tag}> b</p>", UNDER) == ["under"]


@pytest.mark.unit
def test_css_line_through_gives_a_strike_run():
    body = '<p>a <span class="lt">gone</span> b</p>'
    assert _runs(body, STRIKE, _resolver) == ["gone"]
    assert _runs(body, UNDER, _resolver) == []


@pytest.mark.unit
def test_css_with_both_lines_gives_both():
    body = '<p>a <span class="both">two</span> b</p>'
    assert _runs(body, STRIKE, _resolver) == ["two"]
    assert _runs(body, UNDER, _resolver) == ["two"]


@pytest.mark.unit
def test_a_decorated_paragraph_decorates_all_its_text():
    assert _runs('<p class="ul">all of it</p>', UNDER, _resolver) == ["all of it"]


class _Style:
    def __init__(self, own):
        self._own = own

    def get(self, k, default=None):
        return self._own.get(k, default)

    def __getitem__(self, k):
        return self._own.get(k, "none")


class _Stylizer:
    """Calibre's `.get()` is the element's own value: text-decoration does
    not inherit (calibre 9.16, measured)."""

    def __init__(self, own_by_class):
        self._own = own_by_class

    def style(self, elem):
        return _Style(self._own.get(elem.get("class") or "", {}))


def _resolve(own_by_class, body, path):
    resolver = _conv._build_style_resolver(
        None, None, None, stylizer_factory=lambda oeb, item: _Stylizer(own_by_class)
    )
    return resolver(_doc(body).find(path))["text-decoration"]


@pytest.mark.unit
def test_an_ancestors_decoration_reaches_the_text_inside():
    rules = {"ul": {"text-decoration": "underline"}}
    assert _resolve(rules, '<p class="ul"><span>x</span></p>', ".//{*}span") == (
        "underline"
    )


@pytest.mark.unit
def test_none_inside_a_decoration_does_not_remove_it():
    rules = {
        "ul": {"text-decoration": "underline"},
        "no": {"text-decoration": "none"},
    }
    body = '<div class="ul"><p class="no">x</p></div>'
    assert _resolve(rules, body, ".//{*}p") == "underline"


@pytest.mark.unit
def test_text_decoration_line_is_read():
    rules = {"lt": {"text-decoration-line": "line-through"}}
    assert _resolve(rules, '<p><span class="lt">x</span></p>', ".//{*}span") == (
        "line-through"
    )


@pytest.mark.unit
def test_an_undecorated_element_has_no_lines():
    assert _resolve({}, "<p><span>x</span></p>", ".//{*}span") is None


def _run_styles(directory, body):
    from tests.fixtures.epub_builder import EpubBuilder
    from tests.fixtures.golden.inputs import _xhtml_page
    from tests.fixtures.oeb_shim import EpubAsOeb

    b = EpubBuilder().set_metadata(title="Decoration", author="A")
    b.add_chapter("One", _xhtml_page("One", body).encode())
    out = directory / "deco.kfx"
    _conv.convert_oeb_to_kfx(
        EpubAsOeb(str(b.build(directory, "deco"))),
        str(out),
        opts=MagicMock(kfxgen_disable_native_tables=False),
        log=NullLog(),
    )
    frags = load_fragments(out)
    styles = {str(f.fid): val(f) for f in by_type(frags, "$157")}
    texts = {str(f.fid): list(val(f)["$146"]) for f in by_type(frags, "$145")}
    found = {}
    for st in by_type(frags, "$259"):
        for e in iter_entries(val(st)["$146"]):
            ref = e.get("$145")
            if not ref:
                continue
            text = texts[str(ref["name"])][ref["$403"]]
            for r in e.get("$142") or []:
                style = styles.get(str(r.get("$157")), {})
                word = text[r["$143"] : r["$143"] + r["$144"]]
                found[word] = (str(style.get("$27")), str(style.get("$23")))
    return found, styles


@pytest.mark.unit
def test_runs_carry_previewers_line_properties(tmp_path):
    found, _ = _run_styles(
        tmp_path, "<p>a <s>gone</s> b <u>under</u> c <del><ins>both</ins></del> d</p>"
    )
    assert found["gone"] == ("$328", "None")
    assert found["under"] == ("None", "$328")
    assert found["both"] == ("$328", "$328")


@pytest.mark.unit
def test_a_book_without_decorations_writes_no_line_properties(tmp_path):
    _, styles = _run_styles(tmp_path, "<p>a <b>bold</b> and <i>slanted</i> b</p>")
    assert not [s for s in styles.values() if "$27" in s or "$23" in s]


@pytest.mark.unit
def test_a_struck_link_keeps_its_line(tmp_path):
    """A run that is only a link gets no style; one that is also struck
    through must keep its line."""
    found, _ = _run_styles(
        tmp_path,
        '<p id="t">Target.</p><p>See <a href="chapter_1.xhtml#t"><s>old</s></a>.</p>',
    )
    assert found["old"][0] == "$328"


def _ua_resolver(rules):
    """calibre's `.get()` includes its UA sheet (html.css gives u/ins
    underline and s/strike/del line-through), and a book's rule overrides it
    (#360 review)."""
    ua = {"u": "underline", "ins": "underline", "s": "line-through"}
    ua.update({"del": "line-through", "strike": "line-through"})

    def resolve(elem):
        tag = etree.QName(elem).localname
        own = rules.get(elem.get("class") or "", ua.get(tag))
        return {"text-decoration": None if own == "none" else own}

    return resolve


@pytest.mark.unit
@pytest.mark.parametrize(
    ("tag", "flag"), [("ins", UNDER), ("u", UNDER), ("del", STRIKE), ("s", STRIKE)]
)
def test_a_tag_whose_css_says_none_has_no_line(tag, flag):
    """pg40739: `ins { text-decoration: none }`; a browser draws no line."""
    body = f'<p>a <{tag} class="no">fixed</{tag}> b</p>'
    assert _runs(body, flag, _ua_resolver({"no": "none"})) == []


@pytest.mark.unit
def test_a_bare_tag_takes_its_line_from_the_ua_sheet():
    assert _runs("<p>a <ins>new</ins> b</p>", UNDER, _ua_resolver({})) == ["new"]
