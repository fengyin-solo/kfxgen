"""Pictures inside a paragraph's words through calibre (#529), entry for
entry as Kindle Previewer 4.0.3 writes them (probed 2026-10-27): one entry
holding the words and the picture, the picture at its pixels / 16 in em in
the paragraph's own em, a width the markup gives converted as Previewer
converts it, and a picture alone on its line or in its paragraph an entry
of its own.

It needs calibre installed, so it is `slow` (run with `pytest -m slow`) and
skips when `ebook-convert` is not found. CI has no calibre, so this is
local-only.
"""

import sys
import zipfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "plugin"))
sys.path.insert(0, str(REPO))

from tests._helpers import decodable_jpeg_of  # noqa: E402
from tests._kfx_introspect import by_type, load_fragments, val  # noqa: E402
from tests.integration.test_calibre_cover_in_text import _page  # noqa: E402
from tests.integration.test_calibre_table_rows import (  # noqa: E402
    _ebook_convert,
    calibre,  # noqa: F401  (fixture)
)

pytestmark = [pytest.mark.slow, pytest.mark.integration]

BODY = (
    "<h1>One</h1>"
    "<p>P1 A sign <img src='s.jpg' alt='x'/> in a line.</p>"
    "<p>P4 two <img src='s.jpg' alt='x'/> and <img src='b.jpg' alt='y'/> here.</p>"
    "<p>P5 a <a href='#t'>linked <img src='s.jpg' alt='x'/> picture</a> here.</p>"
    "<h2>P6 heading <img src='s.jpg' alt='x'/> with it</h2>"
    "<p>Q1 pct <img src='b.jpg' style='width:20%' alt='x'/> after.</p>"
    "<p>Q2 em <img src='b.jpg' style='width:2em' alt='x'/> after.</p>"
    "<div><img src='b.jpg' alt='a'/><br/>R3 caption after a break.</div>"
    "<p id='t'>Target.</p>"
)

#: Kindle Previewer 4.0.3's entries for BODY, read from its own file.
PREVIEWER = [
    ("text", "One"),
    ("mixed", ["P1 A sign ", "3emx3em", " in a line."], []),
    ("mixed", ["P4 two ", "3emx3em", " and ", "18.75emx13.75em", " here."], []),
    ("mixed", ["P5 a linked ", "3emx3em", " picture here."], [(5, 16)]),
    ("mixed", ["P6 heading ", "2emx2em", " with it"], []),
    ("mixed", ["Q1 pct ", "6.4emx4.69333em", " after."], []),
    ("mixed", ["Q2 em ", "2emx1.46667em", " after."], []),
    ("picture", "58.594%"),
    ("text", "R3 caption after a break."),
    ("text", "Target."),
]


def _epub(path):
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
            'version="2.0" unique-identifier="u"><metadata '
            'xmlns:dc="http://purl.org/dc/elements/1.1/">'
            '<dc:identifier id="u">ip529</dc:identifier><dc:title>P</dc:title>'
            "<dc:language>en</dc:language></metadata><manifest>"
            '<item id="c" href="c.xhtml" media-type="application/xhtml+xml"/>'
            '<item id="s" href="s.jpg" media-type="image/jpeg"/>'
            '<item id="b" href="b.jpg" media-type="image/jpeg"/>'
            '<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>'
            '</manifest><spine toc="ncx"><itemref idref="c"/></spine></package>',
        )
        z.writestr(
            "toc.ncx",
            '<?xml version="1.0"?><ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" '
            'version="2005-1"><head/><docTitle><text>P</text></docTitle><navMap>'
            '<navPoint id="n" playOrder="1"><navLabel><text>One</text></navLabel>'
            '<content src="c.xhtml"/></navPoint></navMap></ncx>',
        )
        z.writestr("c.xhtml", _page(BODY))
        z.writestr("s.jpg", decodable_jpeg_of(48, 48))
        z.writestr("b.jpg", decodable_jpeg_of(300, 220))


def _shape(kfx):
    frags = load_fragments(kfx)
    styles = {str(f.fid): val(f) for f in by_type(frags, "$157")}
    content = {str(f.fid): list(val(f)["$146"]) for f in by_type(frags, "$145")}

    def size(style_name):
        style = styles.get(str(style_name)) or {}
        return "x".join(
            f"{style[k]['$307']}{'em' if str(style[k]['$306']) == '$308' else '%'}"
            for k in ("$56", "$57")
            if k in style
        ).replace(".0%", "%")

    out = []
    for st in by_type(frags, "$259"):
        for e in val(st)["$146"]:
            if e.get("$145"):
                ref = e["$145"]
                out.append(("text", str(content[str(ref["name"])][int(ref["$403"])])))
            elif str(e.get("$159")) == "$269" and e.get("$146"):
                parts = [
                    p if isinstance(p, str) else size(p["$157"]) for p in e["$146"]
                ]
                links = [
                    (int(r["$143"]), int(r["$144"]))
                    for r in e.get("$142") or ()
                    if "$179" in r
                ]
                out.append(("mixed", [str(p) for p in parts], links))
            elif e.get("$175") is not None:
                out.append(("picture", size(e["$157"])))
    return out


def test_pictures_in_words_are_written_as_previewer_writes_them(calibre):  # noqa: F811
    tmp, _env, version = calibre
    epub, kfx = tmp / "ip529.epub", tmp / "ip529.kfx"
    _epub(epub)
    _ebook_convert(calibre, epub, kfx, True)
    assert _shape(kfx) == PREVIEWER, f"calibre {version}"
