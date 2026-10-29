"""Logical float/clear sides (``inline-start``/``inline-end``) resolve
through the element's effective writing direction.

float and clear name a physical side (``left``/``right``, and ``both`` for
clear); ``inline-start`` and ``inline-end`` name the line of text. They are
left/right in an LTR element and right/left in an RTL one, and the direction
is inherited: the nearest element at or above the styled one that sets CSS
``direction`` or an HTML ``dir`` attribute wins. Nothing lets kfxgen guess a
book-wide default, so a logical side with no direction anywhere above it is
unset, exactly like an unknown keyword; physical sides never change.

The same resolution reaches all four places that read a side: an inline
picture's own float, a wrapper float transferred to the lone picture inside
it, a floated box, and a clear (paragraph, picture, box, or an empty element
that passes its clear on). These tests check the blocks the converter makes
and the real KFX styles ($140/$628) the generator writes from them.
"""

import pytest
from lxml import etree

from kfxgen import converter as _conv
from kfxgen._img_tokens import IMG_TOKEN_RE
from kfxgen.native_generator import NativeKFXGenerator
from tests._helpers import jpeg_of
from tests._kfx_introspect import by_type, load_fragments, val
from tests.unit.test_floats import WORDS, _resolver

XHTML = "http://www.w3.org/1999/xhtml"

_BORDER = {
    f"border-{side}-{k}": v
    for side in ("top", "right", "bottom", "left")
    for k, v in (("style", "solid"), ("width", "0.75"), ("color", "black"))
}

CSS = {
    # Logical floats.
    "fis": {"float": "inline-start", "width": "30%"},
    "fie": {"float": "inline-end", "width": "30%"},
    # Physical controls.
    "fl": {"float": "left", "width": "30%"},
    "fr": {"float": "right", "width": "30%"},
    # Wrapper floats (#243's shape), logical.
    "pisf": {"float": "inline-start", "width": "25%"},
    "pief": {"float": "inline-end", "width": "25%"},
    # A bordered, sized box floated logically (#382).
    "boxfis": {"float": "inline-start", "width": "40%", **_BORDER},
    "w40": {"width": "100%"},
    # Logical clears.
    "cis": {"clear": "inline-start"},
    "cie": {"clear": "inline-end"},
    # Physical clear controls.
    "cl": {"clear": "left"},
    "cr": {"clear": "right"},
    "cb": {"clear": "both"},
    "bcis": {"clear": "inline-start", **_BORDER},
    "w20": {"width": "20%"},
    # Directions.
    "cssrtl": {"direction": "rtl"},
    "cssltr": {"direction": "ltr"},
    "cssauto": {"direction": "auto"},
    "cssbad": {"direction": "sideways"},
    # A logical float carrying its own explicit direction.
    "fis_rtl": {"float": "inline-start", "direction": "rtl", "width": "30%"},
    # Unknown property values.
    "fw": {"float": "sideways", "width": "30%"},
    "cw": {"clear": "sideways"},
}

PICTURE = '<img class="fis" src="i.jpg" alt="a"/>'


def _blocks(body, css=CSS, *, html_attrs="", body_attrs=""):
    xhtml = f'<html xmlns="{XHTML}"{html_attrs}><body{body_attrs}>{body}</body></html>'
    return _conv.extract_blocks_from_html(
        etree.fromstring(xhtml.encode()),
        style_resolver=_resolver(css),
        native_tables=True,
        base_href="c.xhtml",
    )


def _tokens(blocks):
    """(size, float) of each image token in the blocks, in order."""
    return [
        (m.group(3) or None, m.group(4) or None)
        for b in blocks
        for m in IMG_TOKEN_RE.finditer(b.get("text") or "")
    ]


def _clears(body, css=CSS, **attrs):
    """(type, clear) of each block the converter made."""
    return [
        (b.get("type", "text"), b.get("clear")) for b in _blocks(body, css, **attrs)
    ]


def _direction_of(xhtml, cls):
    """The resolver's effective direction for the element carrying `cls`."""
    doc = etree.fromstring(xhtml.encode())
    resolver = _resolver(CSS)
    elem = doc.find(f".//{{{XHTML}}}*[@class='{cls}']")
    return (resolver(elem) or {}).get("direction")


# --- The effective direction -------------------------------------------------


@pytest.mark.unit
def test_no_direction_anywhere_is_none():
    # The ltr initial must not be reported as the book's choice.
    xhtml = f'<html xmlns="{XHTML}"><body><p class="cis">x</p></body></html>'
    assert _direction_of(xhtml, "cis") is None


@pytest.mark.unit
@pytest.mark.parametrize("where", ["html", "body", "div"])
def test_an_html_dir_inherits_to_the_styled_element(where):
    if where == "html":
        xhtml = (
            f'<html xmlns="{XHTML}" dir="rtl"><body><p class="cis">x</p></body></html>'
        )
    elif where == "body":
        xhtml = (
            f'<html xmlns="{XHTML}"><body dir="rtl"><p class="cis">x</p></body></html>'
        )
    else:
        xhtml = (
            f'<html xmlns="{XHTML}"><body><div dir="rtl">'
            '<p class="cis">x</p></div></body></html>'
        )
    assert _direction_of(xhtml, "cis") == "rtl"


@pytest.mark.unit
def test_css_direction_sets_and_inherits():
    xhtml = (
        f'<html xmlns="{XHTML}"><body class="cssrtl">'
        '<p><img class="fis" alt="a" src="i.jpg"/></p></body></html>'
    )
    doc = etree.fromstring(xhtml.encode())
    resolver = _resolver(CSS)
    img = doc.find(f".//{{{XHTML}}}img")
    assert (resolver(img) or {}).get("direction") == "rtl"


@pytest.mark.unit
def test_a_nested_direction_overrides_then_the_outer_comes_back():
    xhtml = (
        f'<html xmlns="{XHTML}"><body dir="rtl"><p class="cssltr">a</p>'
        '<p class="cssrtl">b</p></body></html>'
    )
    doc = etree.fromstring(xhtml.encode())
    resolver = _resolver(CSS)
    ps = doc.findall(f".//{{{XHTML}}}p")
    assert [(resolver(p) or {}).get("direction") for p in ps] == ["ltr", "rtl"]


@pytest.mark.unit
def test_dir_auto_sets_no_direction_of_its_own():
    # auto is resolved from the text by the browser; kfxgen does not do that
    # analysis, so it neither establishes nor guesses a direction.
    xhtml = (
        f'<html xmlns="{XHTML}"><body><div dir="auto">'
        '<p class="cis">x</p></div></body></html>'
    )
    assert _direction_of(xhtml, "cis") is None
    # Under an explicit rtl, auto inherits it rather than resetting to ltr.
    xhtml = (
        f'<html xmlns="{XHTML}"><body dir="rtl"><div dir="auto">'
        '<p class="cis">x</p></div></body></html>'
    )
    assert _direction_of(xhtml, "cis") == "rtl"


@pytest.mark.unit
def test_an_unknown_dir_does_not_set_one_but_inherits():
    xhtml = (
        f'<html xmlns="{XHTML}" dir="rtl"><body><div dir="bogus">'
        '<p class="cis">x</p></div></body></html>'
    )
    assert _direction_of(xhtml, "cis") == "rtl"
    xhtml = (
        f'<html xmlns="{XHTML}"><body><div dir="bogus">'
        '<p class="cis">x</p></div></body></html>'
    )
    assert _direction_of(xhtml, "cis") is None


@pytest.mark.unit
@pytest.mark.parametrize("cls", ["cssbad", "cssauto"])
def test_an_unreadable_css_direction_sets_none_and_inherits(cls):
    xhtml = (
        f'<html xmlns="{XHTML}" dir="rtl"><body><p class="{cls}">x</p></body></html>'
    )
    assert _direction_of(xhtml, cls) == "rtl"
    xhtml = f'<html xmlns="{XHTML}"><body><p class="{cls}">x</p></body></html>'
    assert _direction_of(xhtml, cls) is None


@pytest.mark.unit
def test_css_direction_beats_the_dir_attribute_on_the_same_element():
    # Author CSS outranks the presentational hint; both spellings disagree.
    xhtml = (
        f'<html xmlns="{XHTML}"><body><p class="cssrtl" dir="ltr">x</p></body></html>'
    )
    assert _direction_of(xhtml, "cssrtl") == "rtl"
    xhtml = (
        f'<html xmlns="{XHTML}"><body><p class="cssltr" dir="rtl">x</p></body></html>'
    )
    assert _direction_of(xhtml, "cssltr") == "ltr"


# --- Floated pictures: logical sides resolve to physical tokens --------------


@pytest.mark.unit
@pytest.mark.parametrize(
    ("cls", "dir_attr", "side"),
    [
        ("fis", ' dir="ltr"', "left"),
        ("fie", ' dir="ltr"', "right"),
        ("fis", ' dir="rtl"', "right"),
        ("fie", ' dir="rtl"', "left"),
    ],
)
def test_a_picture_float_resolves_through_the_books_dir(cls, dir_attr, side):
    body = f'<p><img class="{cls}" src="i.jpg" alt="a"/>{WORDS}</p>'
    assert _tokens(_blocks(body, html_attrs=dir_attr)) == [("w=30%", side)]


@pytest.mark.unit
@pytest.mark.parametrize(
    ("cls", "body_class", "side"),
    [
        ("fis", "cssltr", "left"),
        ("fie", "cssltr", "right"),
        ("fis", "cssrtl", "right"),
        ("fie", "cssrtl", "left"),
    ],
)
def test_a_picture_float_resolves_through_css_direction(cls, body_class, side):
    body = f'<p><img class="{cls}" src="i.jpg" alt="a"/>{WORDS}</p>'
    blocks = _blocks(body, body_attrs=f' class="{body_class}"')
    assert _tokens(blocks) == [("w=30%", side)]


@pytest.mark.unit
def test_a_logical_float_uses_the_nearest_direction_nested():
    body = (
        '<div dir="rtl">'
        f'<p><img class="fis" src="i.jpg" alt="a"/>{WORDS}</p>'
        '<div dir="ltr">'
        f'<p><img class="fis" src="i.jpg" alt="b"/>{WORDS}</p>'
        "</div>"
        f'<p><img class="fie" src="i.jpg" alt="c"/>{WORDS}</p>'
        "</div>"
    )
    # start in rtl -> right; start in the ltr override -> left; back in rtl,
    # end -> left.
    assert [side for _size, side in _tokens(_blocks(body))] == [
        "right",
        "left",
        "left",
    ]


@pytest.mark.unit
@pytest.mark.parametrize(("cls", "side"), [("fl", "left"), ("fr", "right")])
def test_a_physical_float_keeps_its_side_in_rtl(cls, side):
    body = f'<p><img class="{cls}" src="i.jpg" alt="a"/>{WORDS}</p>'
    assert _tokens(_blocks(body, html_attrs=' dir="rtl"')) == [("w=30%", side)]


@pytest.mark.unit
def test_a_logical_float_with_no_direction_is_not_guessed():
    # No dir, no CSS direction: inline-start reads as unset, not left.
    body = f'<p><img class="fis" src="i.jpg" alt="a"/>{WORDS}</p>'
    assert _tokens(_blocks(body)) == [("w=30%", None)]


@pytest.mark.unit
def test_an_unknown_float_value_is_unset_even_in_rtl():
    body = f'<p><img class="fw" src="i.jpg" alt="a"/>{WORDS}</p>'
    assert _tokens(_blocks(body, html_attrs=' dir="rtl"')) == [("w=30%", None)]


@pytest.mark.unit
def test_dir_auto_alone_leaves_a_logical_float_unset():
    body = f'<div dir="auto"><p><img class="fis" src="i.jpg" alt="a"/>{WORDS}</p></div>'
    assert _tokens(_blocks(body)) == [("w=30%", None)]


@pytest.mark.unit
def test_an_elements_own_css_direction_beats_ancestor_and_attribute():
    # The class sets rtl while an ancestor and the element's own dir
    # attribute both say ltr: author CSS outranks the hint, start is right.
    body = (
        f'<div dir="ltr"><p dir="ltr"><img class="fis_rtl" '
        f'src="i.jpg" alt="a"/>{WORDS}</p></div>'
    )
    assert _tokens(_blocks(body)) == [("w=30%", "right")]


@pytest.mark.unit
@pytest.mark.parametrize(("cls", "side"), [("pisf", "right"), ("pief", "left")])
def test_a_floated_wrapper_resolves_through_its_own_dir(cls, side):
    body = f'<p class="{cls}" dir="rtl"><img src="i.jpg" alt="a"/></p><p>{WORDS}</p>'
    assert _tokens(_blocks(body)) == [("w=25%", side)]


@pytest.mark.unit
def test_a_floated_wrapper_inherits_the_ancestors_dir():
    body = (
        '<div dir="rtl">'
        '<p class="pisf"><img src="i.jpg" alt="a"/></p>'
        f"<p>{WORDS}</p></div>"
    )
    assert _tokens(_blocks(body)) == [("w=25%", "right")]


@pytest.mark.unit
def test_a_floated_wrapper_in_ltr_floats_start_left():
    body = f'<p class="pisf" dir="ltr"><img src="i.jpg" alt="a"/></p><p>{WORDS}</p>'
    assert _tokens(_blocks(body)) == [("w=25%", "left")]


@pytest.mark.unit
def test_a_logically_floated_box_floats_on_the_resolved_side():
    # Bordered, sized wrapper of a picture and a caption keeps the box's
    # float (#382); inline-start lands right in RTL, left in LTR.
    body_rtl = (
        '<div class="boxfis"><img class="w40" src="i.jpg" alt="a"/><p>Caption</p></div>'
    )
    box = _blocks(body_rtl, html_attrs=' dir="rtl"')[0]
    assert box["type"] == "box" and box["box"]["float"] == "right"
    assert box["box"]["width"] == 40.0
    box = _blocks(body_rtl, html_attrs=' dir="ltr"')[0]
    assert box["type"] == "box" and box["box"]["float"] == "left"


# --- clear: logical sides resolve on the clearing element --------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    ("cls", "dir_attr", "side"),
    [
        ("cis", ' dir="ltr"', "left"),
        ("cie", ' dir="ltr"', "right"),
        ("cis", ' dir="rtl"', "right"),
        ("cie", ' dir="rtl"', "left"),
        ("cl", ' dir="rtl"', "left"),
        ("cr", ' dir="rtl"', "right"),
        ("cb", ' dir="rtl"', "both"),
    ],
)
def test_a_cleared_paragraph_resolves_through_the_dir(cls, dir_attr, side):
    body = f'<p class="{cls}">{WORDS}</p>'
    assert _clears(body, html_attrs=dir_attr) == [("text", side)]


@pytest.mark.unit
def test_a_logical_clear_with_no_direction_is_unset():
    assert _clears(f'<p class="cis">{WORDS}</p>') == [("text", None)]


@pytest.mark.unit
def test_an_unknown_clear_value_is_unset_even_in_rtl():
    assert _clears(f'<p class="cw">{WORDS}</p>', html_attrs=' dir="rtl"') == [
        ("text", None)
    ]


@pytest.mark.unit
def test_an_empty_clearer_passes_the_resolved_side_on():
    body = f'<p>{PICTURE}Short.</p><div class="cie"></div><p>{WORDS}</p>'
    # inline-end in RTL is the physical left, and the empty div hands it to
    # the next paragraph (#381).
    assert _clears(body, html_attrs=' dir="rtl"') == [
        ("text", None),
        ("text", "left"),
    ]


@pytest.mark.unit
def test_a_chain_of_empty_clearers_keeps_the_side():
    body = (
        f'<p>{PICTURE}Short.</p><div class="cis"></div>'
        f'<div class="cis"></div><p>{WORDS}</p>'
    )
    assert [c for _t, c in _clears(body, html_attrs=' dir="rtl"')] == [
        None,
        "right",
    ]


@pytest.mark.unit
def test_a_clear_uses_the_clearing_elements_dir_not_the_next_blocks():
    # Outer RTL; the empty clearer sits in an LTR override; the paragraph it
    # reaches is RTL again. inline-start resolves at the clearer: left.
    body = (
        '<div dir="rtl"><div dir="ltr"><div class="cis"></div></div>'
        f"<p>{WORDS}</p></div>"
    )
    assert _clears(body) == [("text", "left")]


@pytest.mark.unit
def test_a_cleared_container_clears_its_first_block_on_its_side():
    body = f'<div class="cis" dir="rtl"><p>{WORDS}</p><p>{WORDS}</p></div>'
    assert _clears(body) == [("text", "right"), ("text", None)]


@pytest.mark.unit
def test_a_cleared_picture_takes_the_resolved_side():
    body = (
        f'<p>{WORDS}</p><div class="cie" dir="rtl">'
        '<img class="w20" src="i.jpg" alt="a"/></div>'
    )
    blocks = _blocks(body)
    assert blocks[-1]["text"].startswith("\x00IMG")
    assert blocks[-1]["clear"] == "left"


@pytest.mark.unit
def test_a_cleared_box_takes_the_resolved_side_not_its_paragraphs():
    body = f'<div class="bcis" dir="rtl"><p>{WORDS}</p><p>{WORDS}</p></div>'
    (box,) = _blocks(body)
    assert box["type"] == "box" and box["clear"] == "right"
    assert [b.get("clear") for b in box["blocks"]] == [None, None]


# --- The generator writes the physical KFX symbols ---------------------------


def _kfx(blocks, tmp_path):
    """(type, style, text) for every storyline entry, nested ones walked."""
    out = tmp_path / "b.kfx"
    NativeKFXGenerator().generate_full_book(
        title="T",
        author="A",
        chapters=[
            {
                "title": "One",
                "text": "\n\n".join(b["text"] for b in blocks),
                "blocks": blocks,
            }
        ],
        output_path=str(out),
        images={"i.jpg": jpeg_of(600, 400)},
    )
    frags = load_fragments(out)
    styles = {str(f.fid): val(f) for f in by_type(frags, "$157")}
    texts = {str(f.fid): list(val(f)["$146"]) for f in by_type(frags, "$145")}
    found = []

    def walk(entries):
        for e in entries:
            if isinstance(e, str):
                continue
            text = None
            if e.get("$145"):
                r = e["$145"]
                text = str(texts[str(r["name"])][r["$403"]])
            elif any(isinstance(k, str) for k in e.get("$146") or ()):
                text = "".join(k for k in e["$146"] if isinstance(k, str))
            found.append((str(e.get("$159")), styles.get(str(e.get("$157")), {}), text))
            walk(e.get("$146") or [])

    for st in by_type(frags, "$259"):
        walk(val(st)["$146"])
    return found


@pytest.mark.unit
@pytest.mark.parametrize(
    ("dir_attr", "cls", "symbol"),
    [
        (' dir="rtl"', "fis", "$61"),
        (' dir="rtl"', "fie", "$59"),
        (' dir="ltr"', "fis", "$59"),
        (' dir="ltr"', "fie", "$61"),
    ],
)
def test_a_logical_float_is_written_as_the_real_kfx_float(
    tmp_path, dir_attr, cls, symbol
):
    body = f'<p><img class="{cls}" src="i.jpg" alt="a"/>{WORDS}</p>'
    found = _kfx(_blocks(body, html_attrs=dir_attr), tmp_path)
    (picture,) = [s for t, s, _ in found if t == "$271"]
    assert str(picture["$140"]) == symbol


@pytest.mark.unit
def test_an_unresolved_logical_float_is_written_unfloated(tmp_path):
    body = f'<p><img class="fis" src="i.jpg" alt="a"/>{WORDS}</p>'
    found = _kfx(_blocks(body), tmp_path)
    (picture,) = [s for t, s, _ in found if t == "$271"]
    assert "$140" not in picture


@pytest.mark.unit
@pytest.mark.parametrize(
    ("dir_attr", "cls", "symbol"),
    [
        (' dir="rtl"', "cis", "$61"),
        (' dir="rtl"', "cie", "$59"),
        (' dir="ltr"', "cis", "$59"),
        (' dir="ltr"', "cie", "$61"),
        (' dir="rtl"', "cb", "$421"),
    ],
)
def test_a_logical_clear_is_written_as_the_real_kfx_clear(
    tmp_path, dir_attr, cls, symbol
):
    body = f'<p>{PICTURE}Short.</p><p class="{cls}">Below. {WORDS}</p>'
    found = _kfx(_blocks(body, html_attrs=dir_attr), tmp_path)
    by_text = {txt.split(".")[0]: s for t, s, txt in found if txt}
    assert str(by_text["Below"]["$628"]) == symbol
    assert "$628" not in by_text["Short"]
