"""A TOC entry with an empty label (#459) gets no line on kfxgen's rebuilt
Contents page (#562). Its line had no text, so the position map listed the
next line's id with no offset of its own, which upstream kfxlib grades an
ERROR ("position_map has extra eids").

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

from tests._kfx_introspect import by_type, load_fragments, val  # noqa: E402
from tests.integration.test_calibre_cover_in_text import _page  # noqa: E402
from tests.integration.test_calibre_table_rows import (  # noqa: E402
    _ebook_convert,
    calibre,  # noqa: F401  (fixture)
)

pytestmark = [pytest.mark.slow, pytest.mark.integration]

FILES = {
    "contents.xhtml": "<h1>Contents</h1><p><a href='c1.xhtml'>One</a></p>"
    "<p><a href='c2.xhtml'>Two</a></p>",
    "c1.xhtml": "<h1>One</h1><p>First.</p><p id='mid'>Middle.</p>",
    "c2.xhtml": "<h1>Two</h1><p>Second.</p>",
}


def _point(n, label, src, kids=""):
    return (
        f'<navPoint id="n{n}" playOrder="{n}"><navLabel><text>{label}</text>'
        f'</navLabel><content src="{src}"/>{kids}</navPoint>'
    )


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
        items = "".join(
            f'<item id="f{n}" href="{f}" media-type="application/xhtml+xml"/>'
            for n, f in enumerate(FILES)
        )
        refs = "".join(f'<itemref idref="f{n}"/>' for n in range(len(FILES)))
        z.writestr(
            "content.opf",
            '<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" '
            'version="2.0" unique-identifier="u"><metadata '
            'xmlns:dc="http://purl.org/dc/elements/1.1/">'
            '<dc:identifier id="u">bl562</dc:identifier><dc:title>B</dc:title>'
            f"<dc:language>en</dc:language></metadata><manifest>{items}"
            '<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>'
            f'</manifest><spine toc="ncx">{refs}</spine></package>',
        )
        points = (
            _point(1, "Contents", "contents.xhtml")
            + _point(2, "One", "c1.xhtml", _point(3, "", "c1.xhtml#mid"))
            + _point(4, "Two", "c2.xhtml")
        )
        z.writestr(
            "toc.ncx",
            '<?xml version="1.0"?><ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" '
            'version="2005-1"><head/><docTitle><text>B</text></docTitle>'
            f"<navMap>{points}</navMap></ncx>",
        )
        for name, body in FILES.items():
            z.writestr(name, _page(body))


def test_every_listed_position_has_an_offset(calibre):  # noqa: F811
    tmp, _env, version = calibre
    epub, kfx = tmp / "bl562.epub", tmp / "bl562.kfx"
    _epub(epub)
    _ebook_convert(calibre, epub, kfx, True)
    frags = load_fragments(kfx)
    listed = {
        int(e)
        for f in by_type(frags, "$264")
        for section in val(f)
        for e in getattr(section, "value", section).get("$181") or ()
    }
    placed = {int(r["$185"]) for f in by_type(frags, "$265") for r in val(f)}
    assert listed - placed == set(), f"calibre {version}"
