"""The `kfxgen.textBlock` capability is declared only with text (#357).

KFX Input's structure check requires the capability and the content (`$145`)
fragments to come together: `textBlock=True content_fragment=False` is an
error. A book of pictures only has no `$145`, so it must not declare the
capability. `$593` is still written, empty, as kfxlib's own KPF-to-KFX
conversion writes it for such a book.
"""

from unittest.mock import MagicMock

import pytest

from kfxgen import converter as _conv
from tests._helpers import NullLog, jpeg_of
from tests._kfx_introspect import by_type, load_fragments, val


def _page(body):
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml">\n'
        f"<head><title>p</title></head><body>{body}</body></html>\n"
    ).encode()


def _convert(directory, body):
    from tests.fixtures.epub_builder import EpubBuilder
    from tests.fixtures.oeb_shim import EpubAsOeb

    b = EpubBuilder().set_metadata(title="Capabilities", author="A")
    b.add_chapter("One", _page(body))
    for n in (1, 2):
        b.add_manifest_item(
            item_id=f"pic{n}",
            href=f"pic{n}.jpg",
            media_type="image/jpeg",
            data=jpeg_of(600, 800),
        )
    out = directory / "caps.kfx"
    _conv.convert_oeb_to_kfx(
        EpubAsOeb(str(b.build(directory, "caps"))),
        str(out),
        opts=MagicMock(kfxgen_disable_native_tables=False),
        log=NullLog(),
    )
    return load_fragments(out)


def _capabilities(frags):
    (fc,) = by_type(frags, "$593")
    return [str(c["$492"]) for c in val(fc)]


PICTURES = (
    '<div><img src="pic1.jpg" alt=""/></div><div><img src="pic2.jpg" alt=""/></div>'
)


@pytest.mark.unit
def test_a_picture_only_book_declares_no_text_block(tmp_path):
    frags = _convert(tmp_path, PICTURES)
    assert by_type(frags, "$145") == []
    assert _capabilities(frags) == []


@pytest.mark.unit
def test_a_book_with_text_declares_text_block(tmp_path):
    frags = _convert(tmp_path, f"<p>Some words.</p>{PICTURES}")
    assert by_type(frags, "$145")
    assert _capabilities(frags) == ["kfxgen.textBlock"]
