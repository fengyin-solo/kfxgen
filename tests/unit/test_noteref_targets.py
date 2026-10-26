"""A target an epub:type="noteref" link names is a note, though nothing
marks it as one (#482): its TOC entry, which calibre builds from the
book's links when it has no NCX, is skipped, as #203 skips a note's."""

from types import SimpleNamespace

import pytest
from lxml import etree

from kfxgen import converter as _conv

EPUB = 'xmlns:epub="http://www.idpf.org/2007/ops"'


def _item(href, body):
    xhtml = (
        f'<html xmlns="http://www.w3.org/1999/xhtml" {EPUB}><body>{body}</body></html>'
    )
    return SimpleNamespace(href=href, data=etree.fromstring(xhtml.encode()))


@pytest.mark.unit
def test_a_noteref_target_is_a_note():
    book = SimpleNamespace(
        spine=[
            _item(
                "c1.xhtml",
                '<p>Text<a epub:type="noteref" href="n.xhtml#n1">1</a> and '
                '<a href="n.xhtml#n2">2</a>.</p>',
            ),
            _item("n.xhtml", '<p id="n1"><a>1</a> First note.</p><p id="n2">2 B.</p>'),
        ]
    )
    found = _conv._note_pair_ids(book)
    assert "n1" in found.get("n.xhtml", set())
    # A plain link is not a noteref: n2 isn't a note by this rule.
    assert "n2" not in found.get("n.xhtml", set())


@pytest.mark.unit
def test_a_noteref_to_a_heading_is_not_a_note():
    book = SimpleNamespace(
        spine=[
            _item("c1.xhtml", '<p><a epub:type="noteref" href="n.xhtml#h">x</a></p>'),
            _item("n.xhtml", '<h2 id="h">Notes</h2>'),
        ]
    )
    assert "h" not in _conv._note_pair_ids(book).get("n.xhtml", set())


@pytest.mark.unit
def test_a_doc_noteref_role_counts_too():
    book = SimpleNamespace(
        spine=[
            _item("c1.xhtml", '<p>T<a role="doc-noteref" href="n.xhtml#n1">1</a>.</p>'),
            _item("n.xhtml", '<p id="n1">First note.</p>'),
        ]
    )
    assert "n1" in _conv._note_pair_ids(book).get("n.xhtml", set())
