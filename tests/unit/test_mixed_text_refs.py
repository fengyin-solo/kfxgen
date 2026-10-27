"""A mixed entry's words are written once, in its own content list (#567).
A paragraph holding a drawn equation (#235) or a picture in its words
(#529) also left its text in the `$145` store with nothing pointing at it;
a whole fragment of it drew kfxlib's "Unreferenced fragments" warning.
Kindle Previewer 4.0.3's files have none."""

import pytest

from kfxgen.native_generator import NativeKFXGenerator
from tests._helpers import decodable_jpeg_of
from tests._kfx_introspect import by_type, iter_entries, load_fragments, val
from tests.unit.test_mathml_native import R2, _blocks

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "body",
    [
        f"<p>The area is {R2} here.</p><p>After.</p>",
        "<p>A sign <img src='s.jpg' alt='x'/> in a line.</p><p>After.</p>",
    ],
    ids=["equation", "picture"],
)
def test_every_stored_string_is_referenced(tmp_path, body):
    out = tmp_path / "r.kfx"
    NativeKFXGenerator().generate_full_book(
        title="T",
        author="A",
        chapters=[
            {"title": "One", "text": "x", "blocks": _blocks(f"<h1>One</h1>{body}")}
        ],
        images={"s.jpg": decodable_jpeg_of(48, 48)},
        output_path=str(out),
    )
    frags = load_fragments(out)
    stored = {
        (str(f.fid), n)
        for f in by_type(frags, "$145")
        # The equations' own strings are their drawings', not the text's.
        if "math" not in str(f.fid)
        for n in range(len(val(f)["$146"]))
    }
    referenced = {
        (str(e["$145"]["name"]), int(e["$145"]["$403"]))
        for st in by_type(frags, "$259")
        for e in iter_entries(val(st)["$146"])
        if e.get("$145")
    }
    assert stored - referenced == set()
    # The words are still printed, in the mixed entry.
    assert any(
        isinstance(p, str) and "here" in p or isinstance(p, str) and "in a line" in p
        for st in by_type(frags, "$259")
        for e in iter_entries(val(st)["$146"])
        for p in (e.get("$146") or ())
    )
