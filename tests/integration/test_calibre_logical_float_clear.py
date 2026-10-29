"""Logical float/clear (inline-start/inline-end) through calibre's Stylizer.

The unit tests' fake style assumes calibre reports `float: inline-start`,
`clear: inline-end` and `direction: rtl` as declared through `Style.get()`,
and that the HTML `dir` attribute reaches the tree (calibre, unlike its width
and height handling, does not fold `dir` into the CSS). This converts real
books with calibre and checks the KFX symbols: $140 $61 for a right float,
$59 left, and the same on $628 for clear; $421 stays both.

A second book with no direction anywhere is the no-guess control: the
logical values must reach neither $140 nor $628.

It needs calibre installed, so it is `slow` (run with `pytest -m slow`) and
skips when `ebook-convert` is not found. CI has no calibre, so this is
local-only, like tests/integration/test_calibre_floats.py.
"""

import sys
import zipfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "plugin"))
sys.path.insert(0, str(REPO))

from tests._helpers import decodable_jpeg_of  # noqa: E402
from tests._kfx_introspect import (  # noqa: E402
    by_type,
    load_fragments,
    val,
)
from tests.integration.test_calibre_table_rows import (  # noqa: E402
    _ebook_convert,
    calibre,  # noqa: F401  (fixture)
)

pytestmark = [pytest.mark.slow, pytest.mark.integration]

CSS = """
img.fis { float: inline-start; width: 30%; }
img.fie { float: inline-end; width: 30%; }
img.fl { float: left; width: 30%; }
img.w20 { width: 20%; }
p.pisf { float: inline-start; width: 25%; }
p.pisf img { width: 100%; }
.rtlwrap { direction: rtl; }
.cis { clear: inline-start; }
.cie { clear: inline-end; }
.cl { clear: left; }
.cb { clear: both; }
div.clearer { height: 0; }
"""

WORDS = "words that wrap beside the picture. " * 4
PIC = '<img class="fl" src="i.jpg" alt="pic"/>'

#: (alt-or-word, markup): each case's text starts with its key.
RTL_CASES = [
    ("a-start", f'<p><img class="fis" src="i.jpg" alt="a-start"/>Start {WORDS}</p>'),
    ("a-end", f'<p><img class="fie" src="i.jpg" alt="a-end"/>End {WORDS}</p>'),
    # Direction set in CSS, not the dir attribute.
    (
        "css-start",
        f'<div class="rtlwrap"><p><img class="fis" src="i.jpg" '
        f'alt="css-start"/>Cssdir {WORDS}</p></div>',
    ),
    # A nested LTR override switches the same logical value back.
    (
        "ltr-start",
        f'<div dir="ltr"><p><img class="fis" src="i.jpg" '
        f'alt="ltr-start"/>Ltroverride {WORDS}</p></div>',
    ),
    # A physical keyword is untouched by the RTL direction.
    ("phys", f'<p><img class="fl" src="i.jpg" alt="phys"/>Physical {WORDS}</p>'),
    # A wrapper float, transferred to its lone picture (#243).
    (
        "wrap",
        f'<p class="pisf"><img src="i.jpg" alt="wrap"/></p><p>Wrapcap {WORDS}</p>',
    ),
    ("c-start", f'<p>{PIC}</p><p class="cis">Clearstart {WORDS}</p>'),
    ("c-end", f'<p>{PIC}</p><p class="cie">Clearend {WORDS}</p>'),
    ("c-both", f'<p>{PIC}</p><h3 class="cb">Clearboth</h3><p>{WORDS}</p>'),
    ("c-phys", f'<p>{PIC}</p><p class="cl">Clearphys {WORDS}</p>'),
    (
        "c-empty",
        f'<p>{PIC}</p><div class="clearer cie"></div><p>Clearempty {WORDS}</p>',
    ),
    (
        "c-pic",
        f'<p>Lead {WORDS}</p><div class="cis">'
        '<img class="w20" src="i.jpg" alt="c-pic"/></div>',
    ),
]

#: No dir attribute, no CSS direction anywhere: logical values are unset.
PLAIN_CASES = [
    ("nogo", f'<p><img class="fis" src="i.jpg" alt="nogo"/>Nodir {WORDS}</p>'),
    ("nogo-c", f'<p>{PIC}</p><p class="cis">Noclear {WORDS}</p>'),
]


def _build(path, cases, body_attrs=""):
    """An EPUB of `cases`, styled by this file's CSS."""
    body = "".join(html for _key, html in cases)
    xhtml = (
        '<?xml version="1.0" encoding="utf-8"?><html xmlns="http://www.w3.org/1999/xhtml"'
        f"{body_attrs}>"
        '<head><title>F</title><link rel="stylesheet" type="text/css" href="s.css"/>'
        f"</head><body>{body}</body></html>"
    )
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        z.writestr(
            "META-INF/container.xml",
            '<?xml version="1.0"?><container version="1.0" '
            'xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles>'
            '<rootfile full-path="content.opf" '
            'media-type="application/oebps-package+xml"/></rootfiles></container>',
        )
        z.writestr(
            "content.opf",
            '<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" '
            'version="2.0" unique-identifier="i"><metadata '
            'xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:identifier id="i">f'
            "</dc:identifier><dc:title>Logical sides</dc:title><dc:language>he"
            '</dc:language></metadata><manifest><item id="c" href="c.xhtml" '
            'media-type="application/xhtml+xml"/><item id="s" href="s.css" '
            'media-type="text/css"/><item id="i" href="i.jpg" media-type="image/jpeg"/>'
            '</manifest><spine><itemref idref="c"/></spine></package>',
        )
        z.writestr("c.xhtml", xhtml)
        z.writestr("s.css", CSS)
        z.writestr("i.jpg", decodable_jpeg_of(600, 400))


def _read(kfx):
    """{picture alt: ($140 or None, $628 or None, its container's $628)}
    and {first word of a text entry: its $628}."""
    frags = load_fragments(kfx)
    styles = {str(f.fid): val(f) for f in by_type(frags, "$157")}
    texts = {str(f.fid): list(val(f)["$146"]) for f in by_type(frags, "$145")}
    pictures, words = {}, {}

    def symbol(style, key):
        v = style.get(key)
        return None if v is None else str(v)

    def walk(entries, parent=None):
        for e in entries:
            if isinstance(e, str):
                continue
            style = styles.get(str(e.get("$157")), {})
            if str(e.get("$159")) == "$271":
                alt = str(e.get("$584"))
                container = styles.get(str(parent.get("$157")), {}) if parent else {}
                pictures[alt] = (
                    symbol(style, "$140"),
                    symbol(style, "$628"),
                    symbol(container, "$628"),
                )
            elif e.get("$145"):
                r = e["$145"]
                first = str(texts[str(r["name"])][r["$403"]]).split()[0]
                words.setdefault(first, symbol(style, "$628"))
            walk(e.get("$146") or [], e)

    for st in by_type(frags, "$259"):
        walk(val(st)["$146"])
    return pictures, words


@pytest.fixture(scope="module")
def converted(calibre):  # noqa: F811
    """The RTL book's and the directionless book's picture/text symbols."""
    tmp, _env, version = calibre
    rtl_epub, rtl_kfx = tmp / "rtl.epub", tmp / "rtl.kfx"
    plain_epub, plain_kfx = tmp / "plain.epub", tmp / "plain.kfx"
    _build(rtl_epub, RTL_CASES, body_attrs=' dir="rtl"')
    _ebook_convert(calibre, rtl_epub, rtl_kfx, True)
    _build(plain_epub, PLAIN_CASES)
    _ebook_convert(calibre, plain_epub, plain_kfx, True)
    return _read(rtl_kfx), _read(plain_kfx), version


@pytest.mark.parametrize(
    ("alt", "float_symbol"),
    [
        ("a-start", "$61"),  # inline-start in RTL is right
        ("a-end", "$59"),  # inline-end in RTL is left
        ("css-start", "$61"),  # CSS direction: rtl, dir attribute absent
        ("ltr-start", "$59"),  # nested dir="ltr" override
        ("phys", "$59"),  # physical left, unchanged in RTL
        ("wrap", "$61"),  # wrapper inline-start, lone picture
        ("pic", "$59"),  # the physical control float in the clear cases
    ],
)
def test_a_logical_float_reaches_the_kfx_float(converted, alt, float_symbol):
    rtl, _plain, version = converted
    assert rtl[0][alt][0] == float_symbol, f"calibre {version}"


@pytest.mark.parametrize(
    ("word", "clear_symbol"),
    [
        ("Clearstart", "$61"),  # inline-start in RTL
        ("Clearend", "$59"),  # inline-end in RTL
        ("Clearboth", "$421"),  # both, regardless of direction
        ("Clearphys", "$59"),  # physical left
        ("Clearempty", "$59"),  # passed on by the empty inline-end div
    ],
)
def test_a_logical_clear_reaches_the_kfx_clear(converted, word, clear_symbol):
    rtl, _plain, version = converted
    assert rtl[1][word] == clear_symbol, f"calibre {version}"


def test_a_cleared_picture_in_rtl_clears_on_the_start(converted):
    rtl, _plain, version = converted
    # Not linked, so the picture carries its wrapper's clear itself.
    assert rtl[0]["c-pic"][1] == "$61", f"calibre {version}"


def test_logical_values_with_no_direction_are_left_unset(converted):
    _rtl, plain, version = converted
    pictures, words = plain
    assert pictures["nogo"][0] is None, f"calibre {version}"
    assert pictures["nogo"][1] is None, f"calibre {version}"
    assert words["Noclear"] is None, f"calibre {version}"
