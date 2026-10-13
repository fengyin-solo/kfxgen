"""A link around a picture is kept (#355).

`<a href><img/></a>` lost its link: tapping the picture turned the page. It is
now written as Kindle Previewer 4.0.3 writes it: a `$269` container whose
`$142` link covers the one position of an inline (`$601 $283`) `$271` inside.
"""

from unittest.mock import MagicMock

import pytest

from kfxgen import converter as _conv
from tests._helpers import NullLog, jpeg_of
from tests._kfx_introspect import by_type, iter_entries, load_fragments, val

TABLE = (
    "<table><tr><td>{img}<br/>4/9/2004</td><td>Second column.</td></tr>"
    "<tr><td>a2</td><td>b2</td></tr></table>"
)


def _book(directory, body):
    from tests.fixtures.epub_builder import EpubBuilder
    from tests.fixtures.golden.inputs import _xhtml_page
    from tests.fixtures.oeb_shim import EpubAsOeb

    b = EpubBuilder().set_metadata(title="Image links", author="A")
    b.add_chapter("One", _xhtml_page("One", body).encode())
    b.add_chapter(
        "Two", _xhtml_page("Two", '<p id="big">The large picture.</p>').encode()
    )
    b.add_manifest_item(
        item_id="small",
        href="small.jpg",
        media_type="image/jpeg",
        data=jpeg_of(144, 144),
    )
    return EpubAsOeb(str(b.build(directory, "imglink")))


def _entries(directory, body):
    out = directory / "imglink.kfx"
    _conv.convert_oeb_to_kfx(
        _book(directory, body),
        str(out),
        opts=MagicMock(kfxgen_disable_native_tables=False),
        log=NullLog(),
    )
    frags = load_fragments(out)
    entries = [
        e for st in by_type(frags, "$259") for e in iter_entries(val(st)["$146"])
    ]
    targets = {str(f.fid): val(f)["$183"]["$155"] for f in by_type(frags, "$266")}
    return entries, targets


def _linked_pictures(entries):
    """(wrapper, picture) for each `$269` whose link covers an image in it."""
    found = []
    for e in entries:
        kids = e.get("$146") or []
        pics = [k for k in kids if str(k.get("$159")) == "$271"]
        spans = [sp for sp in e.get("$142") or [] if "$179" in sp]
        if str(e.get("$159")) == "$269" and pics and spans:
            found.append((e, pics[0]))
    return found


LINKED = '<a href="chapter_2.xhtml#big"><img src="small.jpg" alt=""/></a>'


@pytest.mark.unit
@pytest.mark.parametrize(
    "body",
    [
        f"<p>{LINKED}</p>",
        f"<div>{LINKED}</div>",
        TABLE.format(img=LINKED),
    ],
    ids=["paragraph", "div", "table-cell"],
)
def test_a_linked_picture_keeps_its_link(tmp_path, body):
    entries, targets = _entries(tmp_path, body)
    linked = _linked_pictures(entries)
    assert len(linked) == 1
    wrapper, picture = linked[0]
    (span,) = wrapper["$142"]
    assert (span["$143"], span["$144"]) == (0, 1)
    assert str(picture.get("$601")) == "$283"
    assert str(span["$179"]) in targets


@pytest.mark.unit
def test_the_link_lands_on_its_target(tmp_path):
    entries, targets = _entries(tmp_path, f"<p>{LINKED}</p>")
    ((wrapper, _),) = _linked_pictures(entries)
    landed = targets[str(wrapper["$142"][0]["$179"])]
    texts = [e for e in entries if e["$155"] == landed]
    assert texts, "the link's anchor names no entry"


@pytest.mark.unit
def test_a_picture_with_no_link_is_unchanged(tmp_path):
    entries, _ = _entries(tmp_path, '<p><img src="small.jpg" alt=""/></p>')
    pictures = [e for e in entries if str(e.get("$159")) == "$271"]
    assert len(pictures) == 1
    assert "$601" not in pictures[0]
    assert not _linked_pictures(entries)


@pytest.mark.unit
@pytest.mark.parametrize("cell", [False, True], ids=["paragraph", "table-cell"])
def test_the_container_and_its_picture_share_one_position(tmp_path, cell):
    # kfxlib counts a container whose first child is inline as length 0, and
    # Kindle Previewer lists both at one $265 offset, container first. A
    # length of 1 shifted every later position ("position_id content extra").
    body = TABLE.format(img=LINKED) if cell else f"<p>{LINKED}</p><p>After.</p>"
    out = tmp_path / "imglink.kfx"
    _conv.convert_oeb_to_kfx(
        _book(tmp_path, body),
        str(out),
        opts=MagicMock(kfxgen_disable_native_tables=False),
        log=NullLog(),
    )
    frags = load_fragments(out)
    entries = [
        e for st in by_type(frags, "$259") for e in iter_entries(val(st)["$146"])
    ]
    ((wrapper, picture),) = _linked_pictures(entries)
    (map_265,) = by_type(frags, "$265")
    pairs = [(m["$184"], m["$185"]) for m in val(map_265)]
    eids = [eid for _, eid in pairs]
    w, p = eids.index(wrapper["$155"]), eids.index(picture["$155"])
    assert p == w + 1
    assert pairs[w][0] == pairs[p][0]
    assert pairs[p + 1][0] == pairs[p][0] + 1
