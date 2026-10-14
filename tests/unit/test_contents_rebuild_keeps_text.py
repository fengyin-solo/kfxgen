"""The Contents rebuild keeps the text printed above the listing (#369).

kfxgen rebuilds a book's printed contents listing as its own Contents page
(#132), replacing the chapter that held it. That chapter is picked only when
it holds at most one paragraph besides the listing, taken to be the listing's
own heading. pg3011's is the title page's date line, "1883": an `h2` the NCX
names, then the listing. The rebuild replaced it, and "1883" was printed
nowhere.

A paragraph above the listing that isn't a contents heading is now a chapter
of its own, under the book's contents entry; the rebuilt page follows it.
"""

from unittest.mock import MagicMock

import pytest
from lxml import etree

from kfxgen import converter as _conv
from tests._helpers import NullLog
from tests._kfx_introspect import by_type, iter_entries, load_fragments, val

LISTING = (
    '<div class="toc"><p><a href="c.xhtml#t">Title</a></p>'
    '<p><a href="c.xhtml#p">Preface</a></p></div>'
)


def _doc(body):
    xhtml = f'<html xmlns="http://www.w3.org/1999/xhtml"><body>{body}</body></html>'
    return etree.fromstring(xhtml.encode())


def _chapters(body, toc):
    listings = []
    blocks = _conv.extract_blocks_from_html(
        _doc(body), base_href="c.xhtml", nav_listing_at=listings
    )
    assert listings, "fixture must hold a listing kfxgen discards"
    item = {"href": "c.xhtml", "text": "", "blocks": blocks, "nav_listing_at": listings}
    chapters = _conv._assemble_chapters_by_coordinate([item], toc, NullLog())
    _conv._replace_title_page(chapters, {"title": "Book", "author": "A"}, NullLog())
    return chapters


DATE_BODY = (
    '<h1 id="t">The Title</h1><p>By someone.</p>'
    '<h2 id="y">1883</h2>' + LISTING + '<h2 id="p">Preface</h2><p>Preface text.</p>'
)
DATE_TOC = [
    {"title": "The Title", "href": "c.xhtml#t"},
    {"title": "1883", "href": "c.xhtml#y"},
    {"title": "Preface", "href": "c.xhtml#p"},
]


@pytest.mark.unit
def test_a_line_above_the_listing_keeps_its_chapter():
    chapters = _chapters(DATE_BODY, DATE_TOC)
    titles = [c["title"] for c in chapters]
    assert titles == ["The Title", "1883", "Contents", "Preface"]
    (date,) = [c for c in chapters if c["title"] == "1883"]
    assert "1883" in date["text"]
    assert not date.get("toc_links")


@pytest.mark.unit
def test_the_rebuilt_page_still_lists_the_book():
    chapters = _chapters(DATE_BODY, DATE_TOC)
    (contents,) = [c for c in chapters if c.get("toc_links")]
    assert contents["title"] == "Contents"
    texts = [link["text"] for link in contents["toc_links"]]
    assert "Preface" in texts and "1883" in texts


@pytest.mark.unit
def test_each_link_opens_its_chapter():
    chapters = _chapters(DATE_BODY, DATE_TOC)
    (contents,) = [c for c in chapters if c.get("toc_links")]
    for link in contents["toc_links"]:
        assert chapters[link["target_chapter_idx"]]["title"] == link["text"]


@pytest.mark.unit
@pytest.mark.parametrize(
    "heading", ["Contents", "CONTENTS.", "Table of Contents", "Navigation", "Inhalt"]
)
def test_the_listings_own_heading_is_still_replaced(heading):
    """The usual shape: the one paragraph is the listing's heading, which
    kfxgen's page prints itself."""
    body = (
        '<h1 id="t">The Title</h1><p>By someone.</p>'
        f'<h2 id="c">{heading}</h2>' + LISTING + '<h2 id="p">Preface</h2><p>x</p>'
    )
    toc = [
        {"title": "The Title", "href": "c.xhtml#t"},
        {"title": "Navigation", "href": "c.xhtml#c"},
        {"title": "Preface", "href": "c.xhtml#p"},
    ]
    chapters = _chapters(body, toc)
    assert [c["title"] for c in chapters] == ["The Title", "Contents", "Preface"]


@pytest.mark.unit
def test_a_line_after_the_listing_is_not_moved_above_it():
    """Only text printed above the listing is kept apart: a line after it is
    the chapter's, and the page is rebuilt as before."""
    body = (
        '<h1 id="t">The Title</h1><p>By someone.</p>'
        + LISTING.replace('<div class="toc">', '<div class="toc" id="y">')
        + "<p>Printed after.</p>"
        '<h2 id="p">Preface</h2><p>x</p>'
    )
    toc = [
        {"title": "The Title", "href": "c.xhtml#t"},
        {"title": "Navigation", "href": "c.xhtml#y"},
        {"title": "Preface", "href": "c.xhtml#p"},
    ]
    titles = [c["title"] for c in _chapters(body, toc)]
    assert titles == ["The Title", "Contents", "Preface"]


def _epub(path):
    import zipfile

    page = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<html xmlns="http://www.w3.org/1999/xhtml"><head><title>t</title></head>'
        f"<body>{DATE_BODY}</body></html>"
    )
    points = "".join(
        f'<navPoint id="n{i}" playOrder="{i}"><navLabel><text>{e["title"]}</text>'
        f'</navLabel><content src="{e["href"]}"/></navPoint>'
        for i, e in enumerate(DATE_TOC, start=1)
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
            'version="2.0" unique-identifier="id"><metadata '
            'xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>Book</dc:title>'
            '<dc:creator>A</dc:creator><dc:identifier id="id">d</dc:identifier>'
            "<dc:language>en</dc:language></metadata><manifest>"
            '<item id="c" href="c.xhtml" media-type="application/xhtml+xml"/>'
            '<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>'
            '</manifest><spine toc="ncx"><itemref idref="c"/></spine></package>',
        )
        z.writestr(
            "toc.ncx",
            '<?xml version="1.0"?><ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" '
            'version="2005-1"><head/><docTitle><text>Book</text></docTitle>'
            f"<navMap>{points}</navMap></ncx>",
        )
        z.writestr("c.xhtml", page)
    return path


def _nav_labels(frags):
    out = []

    def walk(units):
        for u in units:
            u = getattr(u, "value", u)
            out.append(str(getattr(u["$241"], "value", u["$241"])["$244"]))
            walk(u.get("$247") or [])

    for f in by_type(frags, "$389"):
        for c in val(f)[0]["$392"]:
            c = getattr(c, "value", c)
            if str(c["$235"]) == "$212":
                walk(c["$247"])
    return out


@pytest.mark.unit
def test_converting_keeps_the_date_line(tmp_path):
    from tests.fixtures.oeb_shim import EpubAsOeb

    out = tmp_path / "d.kfx"
    _conv.convert_oeb_to_kfx(
        EpubAsOeb(str(_epub(tmp_path / "d.epub"))),
        str(out),
        opts=MagicMock(kfxgen_disable_native_tables=False),
        log=NullLog(),
    )
    frags = load_fragments(out)
    texts = {str(f.fid): list(val(f)["$146"]) for f in by_type(frags, "$145")}
    shown = []
    for st in by_type(frags, "$259"):
        for e in iter_entries(val(st)["$146"]):
            ref = e.get("$145")
            if ref:
                shown.append(texts[str(ref["name"])][ref["$403"]])
    assert "1883" in shown
    assert "Contents" in shown
    labels = _nav_labels(frags)
    assert "1883" in labels and "Contents" in labels


@pytest.mark.unit
def test_a_picture_above_the_listing_is_shown_once():
    """The Contents page keeps the pictures of the chapter it replaces (#117);
    one printed above the listing now goes with that text, not there too."""
    body = DATE_BODY.replace(
        '<h2 id="y">1883</h2>', '<h2 id="y">1883 <img src="seal.png" alt=""/></h2>'
    )
    chapters = _chapters(body, DATE_TOC)
    (date,) = [c for c in chapters if c["title"] == "1883"]
    (contents,) = [c for c in chapters if c.get("toc_links")]
    assert "seal.png" in date["text"]
    assert not contents.get("preserved_images")
