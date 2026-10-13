#!/usr/bin/env python3
"""Build sideload A/B pairs for text styles: CSS bold and italic (#312, #362),
strike-through and underline (#237), and monospace (#242).

One invented source book, made twice: once with no fonts, and once embedding
Charis SIL on <body>. A bold or italic run has to match an embedded face, so
the two can differ. Each source is converted twice through the real
`ebook-convert`, each plugin in its own isolated calibre config under the
output directory:

    "Text Styles New" / "Text Styles Fonts New"   this checkout's plugin
    "Text Styles Old" / "Text Styles Fonts Old"   an earlier plugin zip given
                                                  with --old-plugin (for
                                                  example a build of main)

The titles differ so the files get different ASINs and none replaces another
on the device.

    .venv/bin/python research/make_text_style_sideload.py \\
        --old-plugin main.zip [out_dir]

Output (default `test_books/text_styles/`) is gitignored. Do not commit it.

On each device (the Voyage first), the New books first, then the Old. Open
each entry from the TOC:
  1. "1. Bold and italic from CSS":
     - In the first paragraph, "these words bold" are bold and "these words
       italic" are italic, the same as "a b tag" and "an i tag" next to them.
       Old: the CSS words are regular.
     - In the second paragraph, each "NOT BOLD" is regular between bold
       words. Old: the tag line is all bold, and the CSS line is all regular.
     - "A Cited Title" is italic. Old: regular.
     - "b normal", "strong normal", "i upright" and "em upright" are all
       regular (#362). Old: the first two bold, the last two italic.
     - "weight seven hundred" is bold. Old: regular.
     - "A paragraph at weight six hundred." is regular in Text Styles and
       bold in Text Styles Fonts. Old: regular in both.
     - The paragraph "A whole bold paragraph..." is one weight throughout,
       "a span" included: regular in Text Styles, bold in Text Styles Fonts.
     - In the table, the header cells "Harbour" and "Lamps" are bold, and
       the cell "slanted note" is italic. Old: all regular.
  2. "2. Strike-through and underline":
     - "struck with s" and "deleted with del" have a line through them;
       "underlined with u" and "inserted with ins" are underlined, and
       "an ins set to none" is not.
     - "struck by CSS" has a line through it, "underlined by CSS" is
       underlined, and "both lines" has both.
     - The whole paragraph "A whole underlined paragraph..." is underlined,
       "a span set to none" included.
     - "Plain text with no lines." has none.
     - Links: "underlined by CSS" is underlined. "a plain link" looks as
       links always do on this Kindle. "a struck link" has a line through
       it (Kindle Previewer drops that line; kfxgen keeps it). Tapping each
       one goes to "Plain text with no lines.".
     Old: no lines anywhere in this chapter.
  3. "3. Monospace":
     - "len(items)", "Ctrl", "OK" and "teletype text" are in a fixed-width
       font, like a typewriter's; "n" is italic, not fixed-width.
     - "monospace by CSS" and "courier by CSS" are fixed-width.
     - The two-line "def greet(name):" block is fixed-width, its second
       line indented by four spaces.
     - "bold code" is bold and fixed-width. "a linked function" is
       fixed-width, and tapping it goes to the "def greet" block.
     - "For comparison: list and the list." is in the body font.
     - The two verse lines "The tide went out..." are fixed-width, as
       Gutenberg's `.pgmonospaced` CSS asks. Many Gutenberg books set
       verse this way, so judge whether it reads well.
     Old: everything in the body font, except that "n" is italic in New
     only (#312).
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
    FONT_DIR,
    FONTS,
    calibre_version,
    convert_with_calibre,
    install_plugin,
)

from tests._kfx_introspect import by_type, iter_entries, load_fragments, val  # noqa: E402
from tests.fixtures.epub_builder import EpubBuilder  # noqa: E402

CSS_HREF = "styles.css"

CSS = """
span.sb { font-weight: bold; }
span.si { font-style: italic; }
span.nw { font-weight: normal; }
p.hb { font-weight: bold; }
p.hi { font-style: italic; }
p.wb { font-weight: bold; }
b.plain, strong.plain { font-weight: normal; }
i.plain, em.plain { font-style: normal; }
span.n700 { font-weight: 700; }
p.n600 { font-weight: 600; }
span.lt { text-decoration: line-through; }
.ul { text-decoration: underline; }
span.both { text-decoration: underline line-through; }
span.none { text-decoration: none; }
ins.plain { text-decoration: none; }
span.mono { font-family: monospace; }
span.cour { font-family: "Courier New", monospace; }
.pgmonospaced { font-family: monospace; font-size: 0.9em; }
"""

FONT_CSS = (
    "\n".join(
        f'@font-face {{ font-family: "Charis SIL"; font-weight: {weight}; '
        f"font-style: {style}; src: url(fonts/{name}); }}"
        for name, weight, style in FONTS
    )
    + '\nbody { font-family: "Charis SIL", serif; }\n'
)

PAGES = [
    (
        "1. Bold and italic from CSS",
        '<p>Text with <span class="sb">these words bold</span> and '
        '<span class="si">these words italic</span>, then <b>a b tag</b> and '
        "<i>an i tag</i>.</p>"
        '<p><b>Bold <span class="nw">NOT BOLD</span> bold</b> with a tag, and '
        '<span class="sb">bold <span class="nw">NOT BOLD</span> bold</span> '
        "with CSS.</p>"
        "<p>A book: <cite>A Cited Title</cite>.</p>"
        '<p>Tags set to normal by CSS: <b class="plain">b normal</b>, '
        '<strong class="plain">strong normal</strong>, '
        '<i class="plain">i upright</i> and <em class="plain">em upright</em>.</p>'
        '<p>A number: <span class="n700">weight seven hundred</span>.</p>'
        '<p class="n600">A paragraph at weight six hundred.</p>'
        '<p class="wb">A whole bold paragraph with <span>a span</span> in it.</p>'
        '<table><tr><td><p class="hb">Harbour</p></td>'
        '<td><p class="hb">Lamps</p></td></tr>'
        '<tr><td>north wall</td><td><p class="hi">slanted note</p></td></tr>'
        "<tr><td>south wall</td><td>twelve</td></tr></table>"
        "<p>Below the table.</p>",
    ),
    (
        "2. Strike-through and underline",
        "<p>Tags: <s>struck with s</s>, <del>deleted with del</del>, "
        "<u>underlined with u</u>, <ins>inserted with ins</ins>, and "
        '<ins class="plain">an ins set to none</ins>.</p>'
        '<p>CSS: <span class="lt">struck by CSS</span>, '
        '<span class="ul">underlined by CSS</span> and '
        '<span class="both">both lines</span>.</p>'
        '<p class="ul">A whole underlined paragraph with '
        '<span class="none">a span set to none</span> inside it.</p>'
        '<p id="plain">Plain text with no lines.</p>'
        '<p>Links: <a class="ul" href="chapter_2.xhtml#plain">underlined by CSS</a>, '
        '<a href="chapter_2.xhtml#plain">a plain link</a> and '
        '<a href="chapter_2.xhtml#plain"><s>a struck link</s></a>.</p>',
    ),
    (
        "3. Monospace",
        "<p>Inline: call <code>len(items)</code>, press <kbd>Ctrl</kbd>, "
        "the output <samp>OK</samp>, old <tt>teletype text</tt>, and "
        "<var>n</var>.</p>"
        '<p>CSS: <span class="mono">monospace by CSS</span> and '
        '<span class="cour">courier by CSS</span>.</p>'
        '<pre id="code">def greet(name):\n    return "hello " + name</pre>'
        "<p>Bold code: <b><code>bold code</code></b>. Linked code: "
        '<a href="chapter_3.xhtml#code"><code>a linked function</code></a>.</p>'
        "<p>For comparison: list and the list.</p>"
        '<div class="pgmonospaced">     The tide went out across the flats,\n<br/>'
        "       and gulls came down to feed.</div>",
    ),
]


def _page(title, body):
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n<!DOCTYPE html>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml">\n'
        f'<head><title>{title}</title><link rel="stylesheet" type="text/css" '
        f'href="{CSS_HREF}"/></head>\n'
        f"<body>\n<h1>{title}</h1>\n{body}\n</body>\n</html>\n"
    )


def build_source(out_dir, fonts):
    builder = EpubBuilder().set_metadata(title="Text Styles", author=AUTHOR)
    for title, body in PAGES:
        builder.add_chapter(title, _page(title, body).encode("utf-8"))
    css = (FONT_CSS if fonts else "") + CSS
    builder.add_manifest_item(
        item_id="css", href=CSS_HREF, media_type="text/css", data=css.encode()
    )
    if fonts:
        for i, (name, _, _) in enumerate(FONTS):
            builder.add_manifest_item(
                item_id=f"font{i}",
                href=f"fonts/{name}",
                media_type="font/ttf",
                data=(FONT_DIR / name).read_bytes(),
            )
    stem = "text-styles-fonts" if fonts else "text-styles"
    return builder.build(out_dir, f"{stem}-source")


def _styled_text(kfx):
    """{"bold": [...], ...}: the text of each run whose applied style is
    bold, italic, underlined, struck through or monospace, in reading
    order."""
    frags = load_fragments(kfx)
    styles = {str(f.fid): val(f) for f in by_type(frags, "$157")}
    texts = {}
    for f in by_type(frags, "$145"):
        texts[str(f.fid)] = list(val(f)["$146"])
    out = {"bold": [], "italic": [], "underline": [], "strike": [], "mono": []}
    for st in by_type(frags, "$259"):
        for e in iter_entries(val(st)["$146"]):
            ref = e.get("$145")
            if not ref:
                continue
            text = texts[str(ref["name"])][ref["$403"]]
            runs = [(0, len(text), e.get("$157"))]
            runs += [(r["$143"], r["$144"], r.get("$157")) for r in e.get("$142") or []]
            for start, length, style in runs:
                s = styles.get(str(style), {})
                if str(s.get("$13")) == "$361":
                    out["bold"].append(text[start : start + length])
                if str(s.get("$12")) == "$382":
                    out["italic"].append(text[start : start + length])
                if str(s.get("$23")) == "$328":
                    out["underline"].append(text[start : start + length])
                if str(s.get("$27")) == "$328":
                    out["strike"].append(text[start : start + length])
                if str(s.get("$11")) == "monospace":
                    out["mono"].append(text[start : start + length])
    return out


def facts(kfx):
    """The bold and the italic text, so a wrong build shows before anything
    is copied to a device."""
    return _styled_text(kfx)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out_dir", nargs="?", default=str(ROOT / "test_books/text_styles"))
    ap.add_argument("--old-plugin", type=Path, help="plugin zip for the Old files")
    args = ap.parse_args()
    if not (EBOOK_CONVERT and CALIBRE_CUSTOMIZE):
        sys.exit("calibre not found (ebook-convert / calibre-customize)")
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / ".gitignore").write_text("*\n")
    books = [
        (build_source(out, fonts=False), "text-styles", "Text Styles"),
        (build_source(out, fonts=True), "text-styles-fonts", "Text Styles Fonts"),
    ]
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
