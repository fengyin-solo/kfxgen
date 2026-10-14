"""Contents entries inside a file start a section only at a page break (#363).

pg3011's NCX lists every line of its title page, all in one file: an `h1`,
then `h3`, `h4` and `h3` lines with no page break between them, then an `h2`,
which Gutenberg's CSS breaks the page before. kfxgen made each entry a
section, so each line was a page of its own. A browser, and the book's own
CSS, keep the lines on one page.

An entry starts a section at the start of its file, or where the book's CSS
breaks the page (`page-break-before`/`-after`, `break-before`/`-after`).
Gatsby (pg64317) keeps its chapters, two to a file, because each starts with
an `h2` (#23). Any other entry is a place inside its section, still listed in
the contents.
"""

import zipfile
from unittest.mock import MagicMock

import pytest
from lxml import etree

from kfxgen import converter as _conv
from kfxgen.native_generator import NativeKFXGenerator
from tests._helpers import NullLog
from tests._kfx_introspect import by_type, iter_entries, load_fragments, val

BREAK = {"page-break-before": "always"}


def _doc(body):
    xhtml = f'<html xmlns="http://www.w3.org/1999/xhtml"><body>{body}</body></html>'
    return etree.fromstring(xhtml.encode())


def _resolver(rules):
    """Each element's own CSS, by class, else by tag."""

    def resolve(elem):
        own = rules.get(elem.get("class") or "")
        return dict(
            own if own is not None else rules.get(etree.QName(elem).localname, {})
        )

    return resolve


def _breaks(body, rules):
    blocks = _conv.extract_blocks_from_html(_doc(body), style_resolver=_resolver(rules))
    return [(b["text"], bool(b.get("break_before"))) for b in blocks]


# --- Where the book's CSS breaks the page ---------------------------------


@pytest.mark.unit
def test_a_page_break_before_marks_its_block():
    body = "<h3>Line</h3><h2>Next</h2>"
    assert _breaks(body, {"h2": BREAK}) == [("Line", False), ("Next", True)]


@pytest.mark.unit
@pytest.mark.parametrize("value", ["page", "always", "left", "right", "recto"])
def test_break_before_marks_its_block(value):
    body = '<p>a</p><p class="b">b</p>'
    assert _breaks(body, {"b": {"break-before": value}})[1] == ("b", True)


@pytest.mark.unit
@pytest.mark.parametrize("value", ["auto", "avoid", None])
def test_no_break_leaves_the_block_unmarked(value):
    body = '<p>a</p><h4 class="b">b</h4>'
    assert _breaks(body, {"b": {"page-break-before": value}})[1] == ("b", False)


@pytest.mark.unit
def test_a_containers_break_marks_its_first_block():
    body = '<p>a</p><div class="chap"><h3>One</h3><p>text</p></div>'
    assert _breaks(body, {"chap": BREAK}) == [
        ("a", False),
        ("One", True),
        ("text", False),
    ]


@pytest.mark.unit
@pytest.mark.parametrize(
    "rule", [{"page-break-after": "always"}, {"break-after": "page"}]
)
def test_a_break_after_marks_the_next_block(rule):
    body = '<div class="end"><p>a</p></div><p>b</p>'
    assert _breaks(body, {"end": rule}) == [("a", False), ("b", True)]


@pytest.mark.unit
def test_a_break_on_an_empty_element_marks_the_next_block():
    body = '<p>a</p><div class="pb"></div><p>b</p>'
    assert _breaks(body, {"pb": BREAK}) == [("a", False), ("b", True)]


@pytest.mark.unit
def test_a_boxed_paragraph_keeps_its_break():
    css = dict(BREAK, **{"border-top-style": "solid"})
    rules = {"box": {"border-sides": (("solid", "1", "black"),) * 4, **css}}
    body = '<p>a</p><div class="box"><p>b</p></div>'
    blocks = _conv.extract_blocks_from_html(_doc(body), style_resolver=_resolver(rules))
    assert blocks[-1].get("type") == "box"
    assert blocks[-1].get("break_before") is True


@pytest.mark.unit
def test_a_break_before_a_table_marks_the_table():
    """A cell's paragraphs are walked apart and taken out again; a break
    pending before the table must not be spent on them."""
    body = '<p>a</p><table class="t"><tr><td><p>x</p><p>x2</p></td><td><p>y</p></td></tr></table>'
    blocks = _conv.extract_blocks_from_html(
        _doc(body), style_resolver=_resolver({"t": BREAK}), native_tables=True
    )
    assert blocks[-1].get("type") == "table"
    assert blocks[-1].get("break_before") is True


@pytest.mark.unit
def test_the_resolver_reads_page_breaks():
    class _Style:
        def __init__(self, own):
            self._own = own

        def get(self, k, default=None):
            return self._own.get(k, default)

        def __getitem__(self, k):
            return self._own.get(k)

    class _Stylizer:
        def style(self, elem):
            return _Style({"page-break-before": "always", "break-after": "page"})

    resolve = _conv._build_style_resolver(
        None, None, None, stylizer_factory=lambda oeb, item: _Stylizer()
    )
    css = resolve(_doc("<p>x</p>").find(".//{*}p"))
    assert css["page-break-before"] == "always"
    assert css["break-after"] == "page"


# --- Which entries start a section ----------------------------------------

TITLE_PAGE = (
    '<h1 id="t">THE LADY OF THE LAKE</h1>'
    '<h3 id="e">Edited with Notes</h3>'
    '<h4 id="f">Formerly Head Master</h4>'
    '<h3 id="b">Boston</h3>'
    '<h2 id="y">1883</h2>'
    "<p>The year line.</p>"
)
TITLE_TOC = [
    {"title": "THE LADY OF THE LAKE", "href": "c.xhtml#t"},
    {"title": "Edited with Notes", "href": "c.xhtml#e"},
    {"title": "Formerly Head Master", "href": "c.xhtml#f"},
    {"title": "Boston", "href": "c.xhtml#b"},
    {"title": "1883", "href": "c.xhtml#y"},
]


def _spine_item(href, body, rules=None, breaks_known=True):
    resolver = _resolver(rules if rules is not None else {"h2": BREAK})
    listings = []
    blocks = _conv.extract_blocks_from_html(
        _doc(body),
        style_resolver=resolver if breaks_known else None,
        base_href=href,
        nav_listing_at=listings,
    )
    item = {
        "href": href,
        "text": "\n\n".join(b["text"] for b in blocks),
        "blocks": blocks,
        "nav_listing_at": listings,
    }
    if breaks_known:
        item["breaks_known"] = True
    return item


def _assemble(spine, toc):
    return _conv._assemble_chapters_by_coordinate(spine, toc, NullLog())


def _subs(ch):
    return [s["title"] for s in ch.get("sub_entries") or ()]


@pytest.mark.unit
def test_title_page_lines_without_a_break_share_a_section():
    chapters = _assemble([_spine_item("c.xhtml", TITLE_PAGE)], TITLE_TOC)
    assert [c["title"] for c in chapters] == ["THE LADY OF THE LAKE", "1883"]
    assert _subs(chapters[0]) == ["Edited with Notes", "Formerly Head Master", "Boston"]
    assert _subs(chapters[1]) == []


@pytest.mark.unit
def test_no_text_is_lost_when_entries_share_a_section():
    chapters = _assemble([_spine_item("c.xhtml", TITLE_PAGE)], TITLE_TOC)
    text = "\n\n".join(c["text"] for c in chapters)
    for line in ("Edited with Notes", "Formerly Head Master", "Boston", "1883"):
        assert line in text


@pytest.mark.unit
def test_a_sub_entry_names_the_block_it_points_at():
    chapters = _assemble([_spine_item("c.xhtml", TITLE_PAGE)], TITLE_TOC)
    by_key = {k: b["text"] for b in chapters[0]["blocks"] for k in b["anchor_keys"]}
    assert [by_key[s["key"]] for s in chapters[0]["sub_entries"]] == [
        "Edited with Notes",
        "Formerly Head Master",
        "Boston",
    ]


@pytest.mark.unit
def test_chapters_that_break_the_page_keep_their_sections():
    """Gatsby: two chapters to a file, each opening with an h2 (#23)."""
    body = (
        '<div id="c1"><h2>I</h2><p>one</p></div>'
        '<div id="c2"><h2>II</h2><p>two</p></div>'
    )
    toc = [{"title": "I", "href": "c.xhtml#c1"}, {"title": "II", "href": "c.xhtml#c2"}]
    chapters = _assemble([_spine_item("c.xhtml", body)], toc)
    assert [c["title"] for c in chapters] == ["I", "II"]
    assert [_subs(c) for c in chapters] == [[], []]


@pytest.mark.unit
def test_a_break_before_the_entrys_own_block_starts_a_section():
    """A plate on a page of its own, then the heading the entry names: the
    page break comes before the plate."""
    body = (
        '<h3 id="a">A</h3><p>text</p>'
        '<p class="plate">plate</p><h3 id="b">B</h3><p>more</p>'
    )
    toc = [{"title": "A", "href": "c.xhtml#a"}, {"title": "B", "href": "c.xhtml#b"}]
    chapters = _assemble([_spine_item("c.xhtml", body, {"plate": BREAK})], toc)
    assert [c["title"] for c in chapters] == ["A", "B"]


@pytest.mark.unit
def test_each_file_starts_a_section():
    spine = [
        _spine_item("a.xhtml", '<h3 id="a">A</h3><p>x</p>'),
        _spine_item("b.xhtml", '<h3 id="b">B</h3><p>y</p>'),
    ]
    toc = [{"title": "A", "href": "a.xhtml#a"}, {"title": "B", "href": "b.xhtml#b"}]
    assert [c["title"] for c in _assemble(spine, toc)] == ["A", "B"]


@pytest.mark.unit
def test_without_the_books_css_every_entry_starts_a_section():
    """No stylizer, no way to tell where the pages break: keep 5.12.0's
    sections rather than run chapters together."""
    spine = [_spine_item("c.xhtml", TITLE_PAGE, breaks_known=False)]
    chapters = _assemble(spine, TITLE_TOC)
    assert len(chapters) == 5
    assert all(not _subs(c) for c in chapters)


@pytest.mark.unit
@pytest.mark.parametrize("title", ["Copyright", "Contents", "Title Page", "Half Title"])
def test_an_entry_kfxgen_rewrites_keeps_its_own_section(title):
    """kfxgen replaces or restyles these pages by title; merged, they would
    take the section's other text with them."""
    body = '<h1 id="a">Opening</h1><p>x</p><h3 id="b">Name</h3><p>y</p>'
    toc = [
        {"title": "Opening", "href": "c.xhtml#a"},
        {"title": title, "href": "c.xhtml#b"},
    ]
    chapters = _assemble([_spine_item("c.xhtml", body)], toc)
    assert [c["title"] for c in chapters] == ["Opening", title]


@pytest.mark.unit
def test_nothing_merges_into_a_page_kfxgen_rewrites():
    body = '<h1 id="a">x</h1><p>Title words</p><h3 id="b">Preface</h3><p>y</p>'
    toc = [
        {"title": "Title Page", "href": "c.xhtml#a"},
        {"title": "Preface", "href": "c.xhtml#b"},
    ]
    chapters = _assemble([_spine_item("c.xhtml", body)], toc)
    assert [c["title"] for c in chapters] == ["Title Page", "Preface"]


@pytest.mark.unit
def test_a_section_holding_a_contents_listing_splits_at_every_entry():
    """kfxgen rebuilds the section holding a book's contents listing (#132),
    dropping its blocks; text merged into it would go with them."""
    body = (
        '<h1 id="t">Title</h1><p>words</p>'
        '<div class="toc" id="toc"><p><a href="c.xhtml#a">Alpha</a></p>'
        '<p><a href="c.xhtml#b">Beta</a></p><p><a href="c.xhtml#t">Title</a></p></div>'
        '<h3 id="a">Alpha</h3><p>alpha text</p>'
        '<h3 id="b">Beta</h3><p>beta text</p>'
    )
    toc = [
        {"title": "Title", "href": "c.xhtml#t"},
        # Not a title kfxgen rewrites: the listing alone must split it.
        {"title": "Chapters", "href": "c.xhtml#toc"},
        {"title": "Alpha", "href": "c.xhtml#a"},
        {"title": "Beta", "href": "c.xhtml#b"},
    ]
    item = _spine_item("c.xhtml", body)
    assert item["nav_listing_at"], "fixture must hold a listing kfxgen discards"
    chapters = _assemble([item], toc)
    holder = [c for c in chapters if c.get("_had_nav_listing")]
    assert holder and all(not _subs(c) for c in holder)
    assert "alpha text" in "".join(c["text"] for c in chapters)


# --- What the KFX carries -------------------------------------------------


def _chapters_with_subs():
    chapters = _assemble([_spine_item("c.xhtml", TITLE_PAGE)], TITLE_TOC)
    return chapters


def _book(chapters, path):
    g = NativeKFXGenerator()
    g.generate_full_book(
        title="T", author="A", chapters=chapters, output_path=str(path)
    )
    return load_fragments(path)


def _texts_at(frags):
    """Each content position's text."""
    texts = {str(f.fid): list(val(f)["$146"]) for f in by_type(frags, "$145")}
    at = {}
    for st in by_type(frags, "$259"):
        for e in iter_entries(val(st)["$146"]):
            ref = e.get("$145")
            if ref:
                at[int(e["$155"])] = texts[str(ref["name"])][ref["$403"]]
    return at


def _nav(frags):
    """(label, position, offset) of each contents entry."""
    out = []

    def walk(node):
        node = getattr(node, "value", node)
        if isinstance(node, list):
            for n in node:
                walk(n)
        elif hasattr(node, "items"):
            if str(node.get("$235")) == "$212":
                for unit in node["$247"]:
                    u = getattr(unit, "value", unit)
                    target = getattr(u["$246"], "value", u["$246"])
                    label = getattr(u["$241"], "value", u["$241"])
                    out.append(
                        (str(label["$244"]), int(target["$155"]), int(target["$143"]))
                    )
                return
            for v in node.values():
                walk(v)

    for f in by_type(frags, "$389"):
        walk(val(f))
    return out


@pytest.mark.unit
def test_sub_entries_are_in_the_contents_and_land_on_their_lines(tmp_path):
    frags = _book(_chapters_with_subs(), tmp_path / "t.kfx")
    at = _texts_at(frags)
    nav = _nav(frags)
    assert [label for label, _, _ in nav] == [e["title"] for e in TITLE_TOC]
    for label, pos, off in nav:
        assert at[pos][off:].startswith(label), (label, at[pos])


@pytest.mark.unit
def test_a_sub_entry_inside_a_paragraph_lands_on_its_words(tmp_path):
    body = (
        '<h1 id="t">Opening</h1><p>First words. <a id="m"></a>Middle words follow.</p>'
    )
    toc = [
        {"title": "Opening", "href": "c.xhtml#t"},
        {"title": "Middle words", "href": "c.xhtml#m"},
    ]
    frags = _book(_assemble([_spine_item("c.xhtml", body)], toc), tmp_path / "m.kfx")
    at = _texts_at(frags)
    (label, pos, off) = _nav(frags)[1]
    assert off > 0
    assert at[pos][off:].startswith("Middle words")


@pytest.mark.unit
def test_sub_entries_add_no_sections(tmp_path):
    frags = _book(_chapters_with_subs(), tmp_path / "t.kfx")
    assert len(by_type(frags, "$260")) == 2


@pytest.mark.unit
def test_the_rebuilt_contents_page_links_to_sub_entries(tmp_path):
    chapters = _chapters_with_subs()
    contents = {"title": "Contents", "text": "Contents", "blocks": []}
    chapters.insert(1, contents)
    _conv._rebuild_contents_page(contents, chapters, NullLog())
    frags = _book(chapters, tmp_path / "t.kfx")
    at = _texts_at(frags)
    anchors = {str(f.fid): val(f) for f in by_type(frags, "$266")}
    landed = {}
    for st in by_type(frags, "$259"):
        for e in iter_entries(val(st)["$146"]):
            ref = e.get("$145")
            for run in e.get("$142") or []:
                if "$179" in run and ref:
                    target = anchors[str(run["$179"])]["$183"]
                    landed[at[int(e["$155"])]] = at[int(target["$155"])][
                        int(target.get("$143", 0)) :
                    ]
    for title in ("Edited with Notes", "Formerly Head Master", "Boston"):
        assert landed[title].startswith(title)


# --- End to end, through the converter ------------------------------------

CSS = {"h2": BREAK}


class _Style:
    def __init__(self, own):
        self._own = own

    def get(self, k, default=None):
        return self._own.get(k, default)

    def __getitem__(self, k):
        return self._own.get(k)


class _Stylizer:
    def style(self, elem):
        return _Style(CSS.get(etree.QName(elem).localname, {}))


def _epub(path, body):
    page = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<html xmlns="http://www.w3.org/1999/xhtml"><head><title>t</title></head>'
        f"<body>{body}</body></html>"
    )
    points = "".join(
        f'<navPoint id="n{i}" playOrder="{i}"><navLabel><text>{e["title"]}</text>'
        f'</navLabel><content src="{e["href"]}"/></navPoint>'
        for i, e in enumerate(TITLE_TOC, start=1)
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
            'xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>P</dc:title>'
            '<dc:creator>A</dc:creator><dc:identifier id="id">x</dc:identifier>'
            "<dc:language>en</dc:language></metadata><manifest>"
            '<item id="c" href="c.xhtml" media-type="application/xhtml+xml"/>'
            '<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>'
            '</manifest><spine toc="ncx"><itemref idref="c"/></spine></package>',
        )
        z.writestr(
            "toc.ncx",
            '<?xml version="1.0"?><ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" '
            'version="2005-1"><head/><docTitle><text>P</text></docTitle>'
            f"<navMap>{points}</navMap></ncx>",
        )
        z.writestr("c.xhtml", page)
    return path


@pytest.mark.unit
def test_converting_the_title_page_gives_one_section(tmp_path, monkeypatch):
    from tests.fixtures.oeb_shim import EpubAsOeb

    monkeypatch.setattr(_conv, "_default_stylizer", lambda oeb, item: _Stylizer())
    src = _epub(tmp_path / "t.epub", TITLE_PAGE + "<p>More words.</p>")
    out = tmp_path / "t.kfx"
    _conv.convert_oeb_to_kfx(
        EpubAsOeb(str(src)),
        str(out),
        opts=MagicMock(kfxgen_disable_native_tables=False),
        log=NullLog(),
    )
    frags = load_fragments(out)
    at = _texts_at(frags)
    nav = _nav(frags)
    labels = [label for label, _, _ in nav]
    for entry in TITLE_TOC:
        assert entry["title"] in labels
    for label, pos, off in nav:
        assert at[pos][off:].lower().startswith(label.lower()), (label, at[pos])
    # The title page and the 1883 page; no section for each line.
    assert len(by_type(frags, "$260")) == 2
