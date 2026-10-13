#!/usr/bin/env python3
"""Build a sideload A/B pair for a book of pictures only (#357).

One invented source book with no text in any page, converted twice through
the real `ebook-convert`, each plugin in its own isolated calibre config
under the output directory:

    "Picture Book New"  this checkout's plugin: no content fragments, so no
                        `kfxgen.textBlock` capability is declared
    "Picture Book Old"  an earlier plugin zip given with --old-plugin (for
                        example a build of main), which declares it anyway

The titles differ so the files get different ASINs and neither replaces the
other on the device.

    .venv/bin/python research/make_picture_book_sideload.py \\
        --old-plugin main.zip [out_dir]

Output (default `test_books/picture_book/`) is gitignored. Do not commit it.

On each device (the Voyage first), "Picture Book New" first, then "Picture
Book Old":
  1. The book opens from the library. Each page shows one picture, numbered
     "Page 1" to "Page 8", in order.
  2. Turn forward to "Page 8" and back to "Page 1": every page turns, none
     is skipped or blank.
  3. The reading progress at the bottom is one eighth per page: "Page 4"
     shows 50% and "Page 5" shows 62% (Voyage 5.13.6).
  4. Close the book and open it again: it reopens at the same page.
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "plugin"))
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "research"))

from make_image_link_sideload import _jpeg  # noqa: E402
from make_notes_table_sideload import install_zip  # noqa: E402
from make_table_sideload import (  # noqa: E402
    AUTHOR,
    CALIBRE_CUSTOMIZE,
    EBOOK_CONVERT,
    calibre_version,
    convert_with_calibre,
    install_plugin,
)

from tests._kfx_introspect import by_type, load_fragments, val  # noqa: E402
from tests.fixtures.epub_builder import EpubBuilder  # noqa: E402

PAGES = 8


def _page(n):
    # No heading and no text: the shape of a scanned picture book.
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n<!DOCTYPE html>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml">\n'
        f"<head><title>Page {n}</title></head>\n"
        f'<body><div><img src="page{n}.jpg" alt=""/></div></body>\n</html>\n'
    )


def build_source(out_dir):
    builder = EpubBuilder().set_metadata(title="Picture Book", author=AUTHOR)
    for n in range(1, PAGES + 1):
        builder.add_chapter(f"Page {n}", _page(n).encode("utf-8"))
        builder.add_manifest_item(
            item_id=f"page{n}",
            href=f"page{n}.jpg",
            media_type="image/jpeg",
            data=_jpeg(1000, f"Page {n}"),
        )
    return builder.build(out_dir, "picture-book-source")


def facts(kfx):
    """Content fragments and declared capabilities, so a wrong build shows
    before anything is copied to a device."""
    frags = load_fragments(kfx)
    return {
        "$145": len(by_type(frags, "$145")),
        "pictures": len(by_type(frags, "$164")),
        "capabilities": [
            str(c["$492"]) for f in by_type(frags, "$593") for c in val(f)
        ],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out_dir", nargs="?", default=str(ROOT / "test_books/picture_book"))
    ap.add_argument("--old-plugin", type=Path, help="plugin zip for the Old files")
    args = ap.parse_args()
    if not (EBOOK_CONVERT and CALIBRE_CUSTOMIZE):
        sys.exit("calibre not found (ebook-convert / calibre-customize)")
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / ".gitignore").write_text("*\n")
    src = build_source(out)
    envs = [("new", "New", install_plugin(out))]
    if args.old_plugin:
        envs.append(("old", "Old", install_zip(out, args.old_plugin)))
    print(f"built with: {calibre_version(envs[0][2])}, isolated configs")
    for tag, label, env in envs:
        kfx = out / f"picture-book-{tag}.kfx"
        convert_with_calibre(env, src, kfx, f"Picture Book {label}", native=True)
        print(f"  {kfx.name}: {facts(kfx)}")
    print(__doc__[__doc__.index("On each device") :])
    return 0


if __name__ == "__main__":
    sys.exit(main())
