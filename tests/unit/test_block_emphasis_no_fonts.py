"""Whole paragraphs keep CSS bold and italic in books without embedded fonts (#367).

#34 wrote a paragraph's own bold or italic only when the book embeds fonts, to
keep no-font books' output unchanged. So a paragraph made bold by its class
or `style`, an in-chapter `<h3>` (bold through calibre's UA sheet), and a
bold table cell all read as regular text. Kindle Previewer 4 (kpr4, decoded)
writes `$13: $361` and `$12: $382` on those paragraphs' styles with no fonts
and no `$11`. kfxgen now does the same.

Also with fonts embedded: a bold paragraph in a family the book doesn't
embed lost its bold the same way, because the weight was written only with
an embedded family.
"""

import pytest
from lxml import etree

from kfxgen import converter as _conv
from kfxgen.font_table import Face, FontTable
from kfxgen.native_generator import NativeKFXGenerator
from tests._kfx_introspect import by_type, iter_entries, load_fragments, val

#: Each element's own CSS, by class or tag, with calibre's UA sheet for the
#: tags these tests use (b/strong bold, i/em italic, h3 bold).
CSS = {
    "hb": {"font-weight": "bold"},
    "hi": {"font-style": "italic"},
    "tb": {"font-weight": "bold"},
    "other": {"font-weight": "bold", "font-family": "not embedded"},
    "foo": {"font-weight": "bold", "font-family": "foo"},
    "bolder": {"font-weight": "bolder"},
    "nw": {"font-weight": "normal"},
    "light": {"font-weight": "lighter"},
    "ns": {"font-style": "normal"},
    "charname": {"font-style": "normal", "font-variant": "small-caps"},
}
UA = {
    "b": {"font-weight": "bold"},
    "strong": {"font-weight": "bold"},
    "i": {"font-style": "italic"},
    "em": {"font-style": "italic"},
    "h3": {"font-weight": "bold"},
}


def _own(elem):
    own = CSS.get(elem.get("class") or "")
    return dict(own if own is not None else UA.get(etree.QName(elem).localname, {}))


def _resolve(elem):
    """As calibre reports them: font-weight and font-style inherit, the
    element's own value first; everything else is the element's own."""
    css = _own(elem)
    for prop in ("font-weight", "font-style"):
        for e in [elem, *elem.iterancestors()]:
            if prop in _own(e):
                css[prop] = _own(e)[prop]
                break
        else:
            css[prop] = "normal"
    return css


def _book(tmp_path, body, font_table=None):
    xhtml = f'<html xmlns="http://www.w3.org/1999/xhtml"><body>{body}</body></html>'
    blocks = _conv.extract_blocks_from_html(
        etree.fromstring(xhtml.encode()),
        style_resolver=_resolve,
        native_tables=True,
        base_href="c.xhtml",
    )
    text = "\n\n".join(b["text"] for b in blocks)
    g = NativeKFXGenerator()
    out = tmp_path / "b.kfx"
    g.generate_full_book(
        title="T",
        author="A",
        chapters=[{"title": "One", "text": text, "blocks": blocks}],
        font_table=font_table,
        output_path=str(out),
    )
    return load_fragments(out)


def _styles_by_text(frags):
    """Each paragraph's text: (its entry $157, [(run text, run $157)])."""
    styles = {str(f.fid): val(f) for f in by_type(frags, "$157")}
    texts = {str(f.fid): list(val(f)["$146"]) for f in by_type(frags, "$145")}
    out = {}
    for st in by_type(frags, "$259"):
        for e in iter_entries(val(st)["$146"]):
            ref = e.get("$145")
            if not ref:
                continue
            text = texts[str(ref["name"])][ref["$403"]]
            runs = [
                (
                    text[r["$143"] : r["$143"] + r["$144"]],
                    styles.get(str(r.get("$157")), {}),
                )
                for r in e.get("$142") or []
            ]
            out[text] = (styles.get(str(e.get("$157")), {}), runs)
    return out


def _bold(style):
    return str(style.get("$13")) == "$361"


def _italic(style):
    return str(style.get("$12")) == "$382"


BODY = (
    '<p class="hb">Classbold paragraph.</p>'
    '<p class="hi">Classitalic paragraph.</p>'
    "<h3>Unlisted heading</h3>"
    "<p>Plain paragraph.</p>"
)


@pytest.mark.unit
def test_css_emphasised_paragraphs_are_written_without_fonts(tmp_path):
    found = _styles_by_text(_book(tmp_path, BODY))
    assert _bold(found["Classbold paragraph."][0])
    assert _italic(found["Classitalic paragraph."][0])


@pytest.mark.unit
def test_an_in_chapter_heading_is_bold_without_fonts(tmp_path):
    found = _styles_by_text(_book(tmp_path, BODY))
    assert _bold(found["Unlisted heading"][0])


@pytest.mark.unit
def test_a_plain_paragraph_stays_regular(tmp_path):
    style, _ = _styles_by_text(_book(tmp_path, BODY))["Plain paragraph."]
    assert not _bold(style) and not _italic(style)


@pytest.mark.unit
def test_runs_in_a_bold_paragraph_are_bold(tmp_path):
    """A run's style names the run's whole face, so an italic word in a bold
    paragraph says bold too."""
    body = '<p class="hb">A bold paragraph with a <i>slanted</i> word.</p>'
    _, runs = _styles_by_text(_book(tmp_path, body))[
        "A bold paragraph with a slanted word."
    ]
    (style,) = [s for t, s in runs if t == "slanted"]
    assert _bold(style) and _italic(style)


TABLE = (
    '<table><tr><td class="tb">Cellbold</td><td>Plaincell</td></tr>'
    "<tr><td>x</td><td>y</td></tr></table>"
)


@pytest.mark.unit
def test_a_bold_table_cell_is_written_without_fonts(tmp_path):
    found = _styles_by_text(_book(tmp_path, "<p>Before.</p>" + TABLE))
    assert _bold(found["Cellbold"][0])
    assert not _bold(found["Plaincell"][0])


@pytest.mark.unit
def test_bold_paragraphs_in_a_cell_are_written_without_fonts(tmp_path):
    body = (
        '<p>Before.</p><table><tr><td><p class="hb">Firstbold</p>'
        '<p class="hb">Secondbold</p></td><td>z</td></tr></table>'
    )
    found = _styles_by_text(_book(tmp_path, body))
    assert _bold(found["Firstbold"][0])
    assert _bold(found["Secondbold"][0])


@pytest.mark.unit
def test_a_bold_paragraph_in_a_family_not_embedded_stays_bold(tmp_path):
    face = Face("embedded", 400, False, b"\x00\x01\x00\x00r", "emb-400", "r/f0")
    body = '<p class="other">Other family bold.</p><p>Plain.</p>'
    found = _styles_by_text(_book(tmp_path, body, FontTable([face])))
    assert _bold(found["Other family bold."][0])


@pytest.mark.unit
def test_an_embedded_bold_face_still_names_its_family(tmp_path):
    """#34's case with fonts is unchanged: the real bold face is named."""
    r = Face("foo", 400, False, b"\x00\x01\x00\x00r", "foo-400", "r/f0")
    b = Face("foo", 700, False, b"\x00\x01\x00\x00b", "foo-700", "r/f1")
    body = '<p class="foo">Embedded bold.</p><p>Plain.</p>'
    style, _ = _styles_by_text(_book(tmp_path, body, FontTable([r, b])))[
        "Embedded bold."
    ]
    assert str(style.get("$11")) == "foo-700"
    assert _bold(style)


@pytest.mark.unit
def test_runs_in_an_italic_paragraph_are_italic(tmp_path):
    body = '<p class="hi">An italic paragraph with a <b>strong</b> word.</p>'
    _, runs = _styles_by_text(_book(tmp_path, body))[
        "An italic paragraph with a strong word."
    ]
    (style,) = [s for t, s in runs if t == "strong"]
    assert _bold(style) and _italic(style)


# --- A run set back to normal inside an emphasised paragraph (#372 review) --


@pytest.mark.unit
@pytest.mark.parametrize("cls", ["nw", "light"])
def test_a_run_set_to_normal_weight_in_a_bold_paragraph_is_not_bold(tmp_path, cls):
    body = f'<p class="hb">Bold words then <span class="{cls}">plain</span> ones.</p>'
    _, runs = _styles_by_text(_book(tmp_path, body))["Bold words then plain ones."]
    (style,) = [s for t, s in runs if t == "plain"]
    assert not _bold(style)


@pytest.mark.unit
def test_a_run_set_upright_in_an_italic_paragraph_is_upright(tmp_path):
    body = '<p class="hi">Slanted words then <span class="ns">upright</span> ones.</p>'
    _, runs = _styles_by_text(_book(tmp_path, body))["Slanted words then upright ones."]
    (style,) = [s for t, s in runs if t == "upright"]
    assert not _italic(style)


@pytest.mark.unit
def test_a_character_name_in_a_stage_direction_stays_upright(tmp_path):
    """pg100: `p.scenedesc` is italic and its `span.charname` names are
    `font-style: normal` in small caps (#359)."""
    body = '<p class="hi">Enter <span class="charname">Helena</span> and others.</p>'
    _, runs = _styles_by_text(_book(tmp_path, body))["Enter Helena and others."]
    (style,) = [s for t, s in runs if t == "Helena"]
    assert not _italic(style)


@pytest.mark.unit
def test_bold_inside_a_reset_run_is_bold_again(tmp_path):
    body = '<p class="hb">A <span class="nw">plain <b>strong</b> part</span> here.</p>'
    _, runs = _styles_by_text(_book(tmp_path, body))["A plain strong part here."]
    found = {t: _bold(s) for t, s in runs}
    assert found.get("strong") is True
    assert found.get("plain ") is False or found.get("plain") is False


@pytest.mark.unit
def test_an_unstyled_span_in_a_bold_paragraph_stays_bold(tmp_path):
    body = '<p class="hb">Bold <span>still bold</span> words.</p>'
    style, runs = _styles_by_text(_book(tmp_path, body))["Bold still bold words."]
    assert _bold(style)
    assert all(_bold(s) for _, s in runs)


@pytest.mark.unit
def test_a_bolder_paragraph_is_bold(tmp_path):
    style, _ = _styles_by_text(_book(tmp_path, '<p class="bolder">Bolder.</p>'))[
        "Bolder."
    ]
    assert _bold(style)


@pytest.mark.unit
def test_a_link_set_to_normal_weight_in_a_bold_paragraph_is_not_bold(tmp_path):
    """A run that is only a link gets no style of its own (#53), so it would
    take the paragraph's bold; set to normal, it needs one that says so."""
    body = (
        '<p class="hb">See <a class="nw" href="c.xhtml#t">the note</a> here.</p>'
        '<p id="t">The note.</p>'
    )
    _, runs = _styles_by_text(_book(tmp_path, body))["See the note here."]
    (style,) = [s for t, s in runs if t == "the note"]
    assert str(style.get("$13")) == "$350"
