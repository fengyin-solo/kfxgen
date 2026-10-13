#!/usr/bin/env python3
"""Build a sideload A/B pair for pictures that are links (#355).

One invented source book, converted twice through the real `ebook-convert`,
each plugin in its own isolated calibre config under the output directory:

    "Image Links New"   this checkout's plugin: `<a href><img/></a>` keeps
                        its link, written as Kindle Previewer writes it
    "Image Links Old"   an earlier plugin zip given with --old-plugin (for
                        example a build of main), where the link is dropped
                        and tapping the picture turns the page

The titles differ so the files get different ASINs and neither replaces the
other on the device.

    .venv/bin/python research/make_image_link_sideload.py \\
        --old-plugin main.zip [out_dir]

Output (default `test_books/image_links/`) is gitignored. Do not commit it.

Each small picture shows its number (1 to 6). Each one links to a page of
its own, with the large picture marked "Large 1" to "Large 4" and a line
naming it ("This is large picture 1."), so a link that lands in the wrong
place shows.

On each device (the Voyage first), "Image Links New" first, then "Image
Links Old". Open each entry from the TOC:
  1. "1. A picture on its own": tap the picture. New: the page "This is
     large picture 1." opens, and Back returns to the picture. Old: the
     page turns. The picture is centred and the same size in New and Old.
  2. "2. Pictures in a table": a 2-column table, a picture and a date in
     each cell. Tap the left picture: New opens large picture 2, the right
     one large picture 3. Old: the page turns.
  3. "3. A picture in a sentence": tap the picture inside the sentence.
     New opens large picture 4. The words before and after it are kept.
  4. "4. A picture linking into text": tap the picture. New lands on the
     paragraph starting "The marked paragraph." in chapter 5.
  5. "5. A picture with no link" is unchanged: centred, same size in both,
     and tapping it turns the page in both.
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "plugin"))
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "research"))

from make_notes_table_sideload import install_zip  # noqa: E402
from make_table_sideload import (  # noqa: E402
    AUTHOR,
    CALIBRE_CUSTOMIZE,
    EBOOK_CONVERT,
    calibre_version,
    convert_with_calibre,
    install_plugin,
)

from tests._kfx_introspect import by_type, iter_entries, load_fragments, val  # noqa: E402
from tests.fixtures.epub_builder import EpubBuilder  # noqa: E402


def _page(title, body):
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n<!DOCTYPE html>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml">\n'
        f"<head><title>{title}</title></head>\n"
        f"<body>\n<h1>{title}</h1>\n{body}\n</body>\n</html>\n"
    )


def _jpeg(size, label):
    """A real picture with `label` drawn large on it, so each one can be told
    apart on the device. (`tests._helpers.jpeg_of` only declares a size and
    shows nothing.)"""
    import io

    from PIL import Image, ImageDraw, ImageFont

    im = Image.new("RGB", (size, size), (225, 225, 225))
    draw = ImageDraw.Draw(im)
    draw.rectangle((0, 0, size - 1, size - 1), outline=(0, 0, 0), width=size // 40 + 2)
    font = ImageFont.load_default(size=size // 3)
    draw.text((size / 2, size / 2), label, fill=(0, 0, 0), font=font, anchor="mm")
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=90)
    return buf.getvalue()


def _thumb(n, target=None):
    # Chapters 1-5 are the tests; "Large picture n" is chapter 5 + n.
    target = target or f"chapter_{5 + n}.xhtml"
    return f'<a href="{target}"><img src="thumb{n}.jpg" alt=""/></a>'


FILLER = "<p>The tide went out over the flats and the gulls came down.</p>" * 12

PAGES = [
    ("1. A picture on its own", f"<p>{_thumb(1)}</p><p>Below the picture.</p>"),
    (
        "2. Pictures in a table",
        f"<table><tr><td>{_thumb(2)}<br/>4/9/2004</td>"
        f"<td>{_thumb(3)}<br/>4/10/2004</td></tr></table>"
        "<p>Below the table.</p>",
    ),
    (
        "3. A picture in a sentence",
        f"<p>Words before the picture {_thumb(4)} and words after it.</p>",
    ),
    (
        "4. A picture linking into text",
        f"<p>{_thumb(5, 'chapter_5.xhtml#marked')}</p><p>Tap the picture above.</p>",
    ),
    (
        "5. A picture with no link",
        '<p><img src="thumb6.jpg" alt=""/></p>'
        f'{FILLER}<p id="marked">The marked paragraph. A link lands here.</p>',
    ),
] + [
    # The text names the page: a page holding only a picture shows no
    # heading.
    (
        f"Large picture {n}",
        f'<p><img src="large{n}.jpg" alt=""/></p><p>This is large picture {n}.</p>',
    )
    for n in range(1, 5)
]


def build_source(out_dir):
    builder = EpubBuilder().set_metadata(title="Image Links", author=AUTHOR)
    for title, body in PAGES:
        builder.add_chapter(title, _page(title, body).encode("utf-8"))
    for n in range(1, 7):
        builder.add_manifest_item(
            item_id=f"thumb{n}",
            href=f"thumb{n}.jpg",
            media_type="image/jpeg",
            data=_jpeg(144, str(n)),
        )
    for n in range(1, 5):
        builder.add_manifest_item(
            item_id=f"large{n}",
            href=f"large{n}.jpg",
            media_type="image/jpeg",
            data=_jpeg(1000, f"Large {n}"),
        )
    return builder.build(out_dir, "image-links-source")


def facts(kfx):
    """Linked pictures and how many of their links land, so a wrong build
    shows before anything is copied to a device."""
    frags = load_fragments(kfx)
    anchors = {str(f.fid) for f in by_type(frags, "$266")}
    linked = []
    for st in by_type(frags, "$259"):
        for e in iter_entries(val(st)["$146"]):
            kids = e.get("$146") or []
            if any(str(k.get("$601")) == "$283" for k in kids):
                linked += [str(s["$179"]) for s in e.get("$142") or [] if "$179" in s]
    return {
        "linked pictures": len(linked),
        "links": f"{sum(n in anchors for n in linked)} of {len(linked)} land",
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out_dir", nargs="?", default=str(ROOT / "test_books/image_links"))
    ap.add_argument("--old-plugin", type=Path, help="plugin zip for the Old files")
    args = ap.parse_args()
    if not (EBOOK_CONVERT and CALIBRE_CUSTOMIZE):
        sys.exit("calibre not found (ebook-convert / calibre-customize)")
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / ".gitignore").write_text("*\n")
    books = [(build_source(out), "image-links", "Image Links")]
    envs = [("new", "New", install_plugin(out))]
    if args.old_plugin:
        envs.append(("old", "Old", install_zip(out, args.old_plugin)))
    print(f"built with: {calibre_version(envs[0][2])}, isolated configs")
    for src, stem, title in books:
        for tag, label, env in envs:
            kfx = out / f"{stem}-{tag}.kfx"
            convert_with_calibre(env, src, kfx, f"{title} {label}", native=True)
            print(f"  {kfx.name}: {facts(kfx)}")
    print(__doc__[__doc__.index("On each device") :])
    return 0


if __name__ == "__main__":
    sys.exit(main())
