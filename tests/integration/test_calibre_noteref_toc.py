"""A note a noteref link names gets no TOC entry, through calibre (#482).

With no NCX, calibre builds a TOC from the book's links, so a note's number
became an entry. kfxgen skipped it only when the note itself was marked
(#203). Kindle Previewer 4.0.3 has no such entry. A target an
`epub:type="noteref"` link names now counts as a note, and its paragraph
prints whole.

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

from tests._kfx_introspect import by_type, iter_entries, load_fragments, val  # noqa: E402
from tests.integration.test_calibre_table_rows import (  # noqa: E402
    _ebook_convert,
    calibre,  # noqa: F401  (fixture)
)

pytestmark = [pytest.mark.slow, pytest.mark.integration]


def _page(body):
    return (
        '<?xml version="1.0" encoding="utf-8"?><html '
        'xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">'
        f"<head><title>p</title></head><body>{body}</body></html>"
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
        z.writestr(
            "content.opf",
            '<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" '
            'version="2.0" unique-identifier="u"><metadata '
            'xmlns:dc="http://purl.org/dc/elements/1.1/">'
            '<dc:identifier id="u">nref482</dc:identifier><dc:title>N</dc:title>'
            "<dc:language>en</dc:language></metadata><manifest>"
            '<item id="c1" href="c1.xhtml" media-type="application/xhtml+xml"/>'
            '<item id="n" href="n.xhtml" media-type="application/xhtml+xml"/>'
            '</manifest><spine><itemref idref="c1"/><itemref idref="n"/></spine>'
            "</package>",
        )
        z.writestr(
            "c1.xhtml",
            _page(
                "<h1>One</h1><p>Text"
                '<a epub:type="noteref" href="n.xhtml#n1">1</a> runs on.</p>'
            ),
        )
        z.writestr("n.xhtml", _page('<p id="n1"><a>1</a> First note.</p>'))


def test_a_noteref_target_gets_no_toc_entry(calibre):  # noqa: F811
    tmp, _env, version = calibre
    epub, kfx = tmp / "nref482.epub", tmp / "nref482.kfx"
    _epub(epub)
    _ebook_convert(calibre, epub, kfx, True)
    frags = load_fragments(kfx)
    labels = []
    for f in by_type(frags, "$389"):
        for c in val(f)[0]["$392"]:
            c = getattr(c, "value", c)
            if str(c["$235"]) == "$212":
                for u in c["$247"]:
                    u = getattr(u, "value", u)
                    labels.append(str(getattr(u["$241"], "value", u["$241"])["$244"]))
    assert "1" not in labels, f"calibre {version}: {labels}"
    content = {str(f.fid): list(val(f)["$146"]) for f in by_type(frags, "$145")}
    texts = [
        str(content[str(e["$145"]["name"])][int(e["$145"]["$403"])])
        for st in by_type(frags, "$259")
        for e in iter_entries(val(st)["$146"])
        if hasattr(e, "get") and e.get("$145")
    ]
    assert "1 First note." in texts, f"calibre {version}: {texts}"
