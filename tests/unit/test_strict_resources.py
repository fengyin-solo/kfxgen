"""Strict resource checking (kfxgen_strict_resources).

Off by default. On, a required resource the book's own HTML or CSS references
but that is missing, unreadable, undecodable, or over an existing size cap
fails the conversion *before* any KFX is written, with an aggregated report
sorted by resource kind then normalized reference. Off, the conversion stays
best-effort: warnings, a KFX anyway. External URLs are never book resources.

Covers: missing pictures, corrupt/unsupported pictures, SVG, WOFF and TTF
fonts, several failures aggregated and sorted, healthy resources, the option
off, plugin wiring, output/temp cleanup, and external URLs not counted.
"""

import sys
import types

import pytest

from kfxgen import converter as _conv
from kfxgen.resource_check import (
    COVER,
    FONT,
    IMAGE,
    SVG,
    ResourceIssues,
    StrictResourceError,
    is_book_internal_ref,
    is_external_url,
    normalize_resource_ref,
)
from tests._helpers import MINIMAL_JPEG
from tests.fixtures.epub_builder import EpubBuilder
from tests.fixtures.oeb_shim import EpubAsOeb

pytestmark = pytest.mark.unit


# ── fixtures / helpers ──────────────────────────────────────────────────────


class _Log:
    def __init__(self):
        self.warns = []
        self.errors = []

    def info(self, m):
        pass

    def warn(self, m):
        self.warns.append(str(m))

    warning = warn

    def error(self, m):
        self.errors.append(str(m))

    def debug(self, m):
        pass


_XHTML = (
    b'<?xml version="1.0" encoding="utf-8"?>'
    b'<html xmlns="http://www.w3.org/1999/xhtml"><head><title>C</title></head>'
    b"<body>{body}</body></html>"
)


def _page(*imgs):
    """A spine page whose body holds each <img> src plus a body sentence that
    must never appear in any strict error message."""
    img_html = "".join(f'<p><img src="{s}" alt="{s}"/></p>' for s in imgs)
    body = (
        "<p>SecretBodySentence that must never leak into an error.</p>" + img_html
    ).encode()
    return _XHTML.replace(b"{body}", body)


def _book(tmp_path, name, imgs=(), pages=None, cover=None):
    """Build (epub_path, out_path) for a book with the given manifest images
    and one page referencing every one of them by its href."""
    srcs = [i[0] for i in imgs]
    builder = (
        EpubBuilder()
        .set_metadata(title=name, author="T")
        .add_chapter("C", pages if pages is not None else _page(*srcs), listed=False)
    )
    for href, media, data in imgs:
        builder.add_manifest_item(
            item_id="it_" + href.rsplit("/", 1)[-1].replace(".", "_"),
            href=href,
            media_type=media,
            data=data,
        )
    if cover is not None:
        builder.set_cover(cover, media_type="image/jpeg", href="cover.jpg")
    epub = builder.build(tmp_path, name)
    return epub, tmp_path / f"{name}.kfx"


_WEBP = b"RIFF\x00\x00\x00\x00WEBPVP8 " + b"\x00" * 60
_SVG = b'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"/>'


def _run(epub, out, *, strict, log=None):
    opts = types.SimpleNamespace(
        kfxgen_strict_resources=strict,
    )
    return _conv.convert_oeb_to_kfx(EpubAsOeb(str(epub)), str(out), opts, log or _Log())


# ── resource_check primitives ───────────────────────────────────────────────


def test_external_urls_and_schemes_are_not_book_resources():
    assert is_external_url("http://example.com/a.png")
    assert is_external_url("https://example.com/a.woff")
    assert is_external_url("data:image/png;base64,AAAA")
    assert not is_external_url("images/a.png")
    assert not is_book_internal_ref("http://example.com/a.png")
    assert not is_book_internal_ref("data:image/png;base64,AAAA")
    assert not is_book_internal_ref("/abs/path/a.png")
    assert not is_book_internal_ref("C:\\Windows\\a.ttf")
    assert is_book_internal_ref("images/a.png")
    assert is_book_internal_ref("../fonts/a.woff")


def test_a_normalized_ref_is_book_relative_only():
    assert normalize_resource_ref("OEBPS/images/a b.png") == "OEBPS/images/a b.png"
    assert normalize_resource_ref("../fonts/x.ttf") == "fonts/x.ttf"
    assert normalize_resource_ref("a.png?v=1#frag") == "a.png"
    assert normalize_resource_ref("/Users/me/book/OEBPS/a.png") == ""
    assert normalize_resource_ref("http://example.com/a.png") == ""
    assert normalize_resource_ref("C:/books/a.ttf") == ""


def test_issues_are_deduplicated_and_stably_sorted():
    issues = ResourceIssues()
    issues.add(IMAGE, "b.png", "could not be decoded")
    issues.add(IMAGE, "b.png", "could not be decoded")  # duplicate
    issues.add(SVG, "a.svg", "SVG image could not be rasterised to PNG")
    issues.add(FONT, "c.woff", "its WOFF table 'glyf' is damaged")
    issues.add(COVER, "cover.jpg", "could not be read")
    # External URLs and absolute paths are dropped, not recorded.
    issues.add(IMAGE, "https://example.com/x.png", "x")
    issues.add(IMAGE, "/etc/passwd", "x")
    kinds_refs = [(k, r) for k, r, _w in issues.sorted_issues()]
    assert kinds_refs == [
        ("cover", "cover.jpg"),
        ("image", "b.png"),
        ("svg", "a.svg"),
        ("font", "c.woff"),
    ]


def test_a_non_strict_collector_records_nothing_and_never_raises():
    issues = ResourceIssues(strict=False)
    issues.add(IMAGE, "a.png", "x")
    issues.retain(keep_cover=True, required_image_refs=["a.png"])
    assert not issues
    issues.raise_if_any()  # must not raise


# ── pipeline: missing / corrupt / SVG ───────────────────────────────────────


def test_a_missing_body_image_fails_before_writing(tmp_path):
    epub, out = _book(
        tmp_path,
        "missing",
        imgs=[("images/good.jpg", "image/jpeg", MINIMAL_JPEG)],
        pages=_page("images/good.jpg", "images/missing.jpg"),
    )
    log = _Log()
    with pytest.raises(StrictResourceError) as caught:
        _run(epub, out, strict=True, log=log)
    message = str(caught.value)
    assert "images/missing.jpg" in message
    assert "referenced but missing from the book" in message
    assert not out.exists()
    assert not (tmp_path / "missing.kfx.tmp").exists()
    # The existing per-resource warning was still emitted.
    assert any("missing" in w for w in log.warns) or message in log.errors


def test_a_corrupt_unsupported_image_fails_naming_it(tmp_path):
    epub, out = _book(
        tmp_path,
        "corrupt",
        imgs=[
            ("images/good.jpg", "image/jpeg", MINIMAL_JPEG),
            ("images/bad.webp", "image/webp", _WEBP),
        ],
        pages=_page("images/good.jpg", "images/bad.webp"),
    )
    with pytest.raises(StrictResourceError) as caught:
        _run(epub, out, strict=True)
    message = str(caught.value)
    assert "images/bad.webp" in message
    assert "unsupported image format" in message


def test_an_svg_that_cannot_be_rasterised_fails_as_svg(tmp_path):
    epub, out = _book(
        tmp_path,
        "svgbook",
        imgs=[
            ("images/good.jpg", "image/jpeg", MINIMAL_JPEG),
            ("images/logo.svg", "image/svg+xml", _SVG),
        ],
        pages=_page("images/good.jpg", "images/logo.svg"),
    )
    with pytest.raises(StrictResourceError) as caught:
        _run(epub, out, strict=True)
    message = str(caught.value)
    assert "svg 'images/logo.svg'" in message
    # Classified as an SVG failure, not a generic image one.
    lines = [ln for ln in message.splitlines() if "logo.svg" in ln]
    assert lines and lines[0].strip().startswith("svg ")


def test_a_missing_declared_cover_fails(tmp_path):
    # A declared cover manifest entry with no file behind it.
    builder = (
        EpubBuilder()
        .set_metadata(title="declared-missing-cover", author="T")
        .add_chapter("C", _page(), listed=False)
        .set_cover(b"", media_type="image/jpeg", href="cover.jpg", declare_only=True)
    )
    epub = builder.build(tmp_path, "declared-missing-cover")
    out = tmp_path / "declared-missing-cover.kfx"
    with pytest.raises(StrictResourceError) as caught:
        _run(epub, out, strict=True)
    message = str(caught.value)
    assert "cover" in message and "cover.jpg" in message
    assert not out.exists()


def test_an_undecodable_picture_is_recorded_through_the_drop_helper(monkeypatch):
    # Stub calibre's image loader: only "good" decodes, as the existing
    # undecodable-picture tests do.
    fake = types.ModuleType("calibre.utils.img")

    def image_from_data(data):
        if data != b"good":
            raise ValueError("Not a valid image")
        return object()

    fake.image_from_data = image_from_data
    monkeypatch.setitem(sys.modules, "calibre", types.ModuleType("calibre"))
    monkeypatch.setitem(sys.modules, "calibre.utils", types.ModuleType("calibre.utils"))
    monkeypatch.setitem(sys.modules, "calibre.utils.img", fake)

    issues = ResourceIssues()
    _conv._drop_undecodable(
        b"bad", "cover.jpg", {"a.jpg": b"good", "b.png": b"bad"}, _Log(), issues
    )
    with pytest.raises(StrictResourceError) as caught:
        issues.raise_if_any()
    message = str(caught.value)
    assert "cover 'cover.jpg'" in message
    assert "image 'b.png'" in message
    assert "a.jpg" not in message  # the good one is not an issue


# ── aggregation / message hygiene ───────────────────────────────────────────


def test_several_failures_are_aggregated_sorted_and_hygienic(tmp_path):
    epub, out = _book(
        tmp_path,
        "many",
        imgs=[
            ("images/good.jpg", "image/jpeg", MINIMAL_JPEG),
            ("images/bad.webp", "image/webp", _WEBP),
            ("images/logo.svg", "image/svg+xml", _SVG),
        ],
        pages=_page(
            "images/good.jpg",
            "images/bad.webp",
            "images/logo.svg",
            "images/missing.jpg",
        ),
    )
    with pytest.raises(StrictResourceError) as caught:
        _run(epub, out, strict=True)
    message = str(caught.value)
    body_lines = [ln for ln in message.splitlines() if ln.startswith(("  "))]
    # Fixed kind order: image, image (by ref), then svg.
    assert body_lines == [
        "  image 'images/bad.webp': unsupported image format "
        "(only JPEG, PNG and GIF are emitted)",
        "  image 'images/missing.jpg': referenced but missing from the book",
        "  svg 'images/logo.svg': SVG image could not be read",
    ]
    # Hygiene: no binaries, no body text, no absolute user path.
    assert _WEBP.hex() not in message
    assert "SecretBodySentence" not in message
    assert str(tmp_path) not in message
    assert not out.exists()


def test_an_unreferenced_corrupt_manifest_image_does_not_fail(tmp_path):
    # Strict mode covers resources the written content actually requires: an
    # orphan manifest item is embedded by best effort but is not required.
    epub, out = _book(
        tmp_path,
        "orphan",
        imgs=[
            ("images/good.jpg", "image/jpeg", MINIMAL_JPEG),
            ("images/orphan.webp", "image/webp", _WEBP),
        ],
        pages=_page("images/good.jpg"),
    )
    _run(epub, out, strict=True)
    assert out.exists()


def test_external_urls_are_not_counted_as_missing(tmp_path):
    epub, out = _book(
        tmp_path,
        "external",
        imgs=[("images/good.jpg", "image/jpeg", MINIMAL_JPEG)],
        pages=_page(
            "images/good.jpg",
            "https://example.com/remote.png",
            "http://example.com/other.jpg",
            "data:image/png;base64,QUJDRA==",
        ),
    )
    _run(epub, out, strict=True)
    assert out.exists()


# ── option off keeps best-effort behaviour and output ────────────────────────


def test_off_the_same_book_converts_with_warnings_and_a_kfx(tmp_path):
    epub, out = _book(
        tmp_path,
        "off",
        imgs=[
            ("images/good.jpg", "image/jpeg", MINIMAL_JPEG),
            ("images/bad.webp", "image/webp", _WEBP),
        ],
        pages=_page("images/good.jpg", "images/bad.webp", "images/missing.jpg"),
    )
    log = _Log()
    _run(epub, out, strict=False, log=log)
    assert out.exists() and out.stat().st_size > 0
    # The corrupt picture was still warned about, by href, in best effort.
    assert any("images/bad.webp" in w for w in log.warns)


def test_on_a_healthy_book_converts_and_writes(tmp_path):
    epub, out = _book(
        tmp_path,
        "healthy",
        imgs=[("images/good.jpg", "image/jpeg", MINIMAL_JPEG)],
        pages=_page("images/good.jpg"),
    )
    _run(epub, out, strict=True)
    assert out.exists() and out.stat().st_size > 0


def test_no_failures_leaves_no_kfx_nor_tmp_behind(tmp_path):
    epub, out = _book(
        tmp_path,
        "cleanup",
        imgs=[("images/good.jpg", "image/jpeg", MINIMAL_JPEG)],
        pages=_page("images/good.jpg", "images/missing.jpg"),
    )
    sentinel = tmp_path / "keep.txt"
    sentinel.write_text("unrelated file stays")
    with pytest.raises(StrictResourceError):
        _run(epub, out, strict=True)
    assert not out.exists()
    assert not list(tmp_path.glob("*.kfx.tmp"))
    assert sentinel.read_text() == "unrelated file stays"


# ── fonts: WOFF and TTF through faces_from_rules ────────────────────────────


def _font_faces(rules, manifest, issues=None, **kw):
    from kfxgen.font_table import faces_from_rules

    log = _Log()
    return faces_from_rules(rules, manifest.get, log, issues=issues, **kw), log


def test_a_good_ttf_and_a_good_woff_pass_strict_checks():
    from tests.unit.test_woff_fonts import _flavoured, _ttf

    issues = ResourceIssues()
    rules = [
        {"font-family": "Probe", "src": "url(r.ttf)"},
        {"font-family": "ProbeTwo", "src": "url(w.woff)"},
    ]
    manifest = {"r.ttf": _ttf(), "w.woff": _flavoured("woff")}
    faces, _log = _font_faces(rules, manifest, issues)
    assert len(faces) == 2
    issues.raise_if_any()  # nothing recorded -> no raise


def test_a_damaged_woff_is_a_strict_failure():
    from tests.unit.test_woff_fonts import _flavoured

    issues = ResourceIssues()
    _font_faces(
        [{"font-family": "Probe", "src": "url(f.woff)"}],
        {"f.woff": _flavoured("woff")[:200]},
        issues,
    )
    with pytest.raises(StrictResourceError) as caught:
        issues.raise_if_any()
    message = str(caught.value)
    assert "font 'f.woff'" in message
    assert "WOFF" in message


def test_a_damaged_ttf_is_a_strict_failure():
    issues = ResourceIssues()
    _font_faces(
        [{"font-family": "Probe", "src": "url(f.ttf)"}],
        {"f.ttf": b"\x00\x01\x00\x00" + b"\x5a" * 4000},
        issues,
    )
    with pytest.raises(StrictResourceError) as caught:
        issues.raise_if_any()
    assert "font 'f.ttf'" in str(caught.value)


def test_a_missing_font_src_is_a_strict_failure():
    issues = ResourceIssues()
    _font_faces(
        [{"font-family": "Probe", "src": "url(fonts/missing.woff)"}],
        {},
        issues,
    )
    with pytest.raises(StrictResourceError) as caught:
        issues.raise_if_any()
    message = str(caught.value)
    assert "font 'fonts/missing.woff'" in message
    assert "missing from the book" in message


def test_an_oversized_font_fails_the_existing_size_cap():
    from tests.unit.test_woff_fonts import _ttf

    issues = ResourceIssues()
    _font_faces(
        [{"font-family": "Probe", "src": "url(f.ttf)"}],
        {"f.ttf": _ttf()},
        issues,
        max_font_bytes=10,
    )
    with pytest.raises(StrictResourceError) as caught:
        issues.raise_if_any()
    assert "f.ttf" in str(caught.value)
    assert "cap" in str(caught.value)


def test_an_external_font_url_is_not_counted():
    issues = ResourceIssues()
    faces, _log = _font_faces(
        [
            {
                "font-family": "Probe",
                "src": "url(https://fonts.example.com/f.woff2)",
            }
        ],
        {},
        issues,
    )
    assert faces == []
    issues.raise_if_any()  # remote src is not a missing book resource


def test_multiple_font_failures_are_sorted_and_deduped():
    from tests.unit.test_woff_fonts import _flavoured

    issues = ResourceIssues()
    rules = [
        # Three distinct faces, one broken each way; the WOFF rule repeats per
        # chapter as shared CSS does and must be recorded once.
        {"font-family": "Bbb", "src": "url(b.woff)"},
        {"font-family": "Bbb", "src": "url(b.woff)"},
        {"font-family": "Aaa", "src": "url(a.ttf)"},
        {"font-family": "Ccc", "src": "url(missing.ttf)"},
    ]
    manifest = {
        "b.woff": _flavoured("woff")[:200],
        "a.ttf": b"\x00\x01\x00\x00" + b"\x5a" * 4000,
    }
    _font_faces(rules, manifest, issues)
    refs = [r for k, r, _w in issues.sorted_issues()]
    assert refs == ["a.ttf", "b.woff", "missing.ttf"]
    with pytest.raises(StrictResourceError):
        issues.raise_if_any()


# ── plugin wiring ───────────────────────────────────────────────────────────


@pytest.fixture
def plugin_module(monkeypatch):
    import importlib

    conversion = types.ModuleType("calibre.customize.conversion")

    class OptionRecommendation:
        LOW, MED, HIGH = 1, 2, 3

        def __init__(self, **kw):
            self.__dict__.update(kw)

    class OutputFormatPlugin:
        pass

    conversion.OptionRecommendation = OptionRecommendation
    conversion.OutputFormatPlugin = OutputFormatPlugin
    for name in ("calibre", "calibre.customize"):
        monkeypatch.setitem(sys.modules, name, types.ModuleType(name))
    monkeypatch.setitem(sys.modules, "calibre.customize.conversion", conversion)
    monkeypatch.delitem(sys.modules, "plugin", raising=False)
    monkeypatch.syspath_prepend(".")
    return importlib.import_module("plugin")


def test_the_plugin_offersthe_option_off_by_default(plugin_module):
    recs = {r.name: r for r in plugin_module.KFXGenOutputPlugin.options}
    assert "kfxgen_strict_resources" in recs
    assert recs["kfxgen_strict_resources"].recommended_value is False


def _prefs(monkeypatch, **values):
    mod = types.ModuleType("calibre_plugins.kfxgen.prefs")
    mod.prefs = {
        "disable_font_embedding": False,
        "disable_native_tables": False,
        "open_at_cover": False,
        "strict_resources": False,
        **values,
    }
    for name in ("calibre_plugins", "calibre_plugins.kfxgen"):
        monkeypatch.setitem(sys.modules, name, types.ModuleType(name))
    monkeypatch.setitem(sys.modules, "calibre_plugins.kfxgen.prefs", mod)


class _PluginLog:
    def __init__(self):
        self.lines = []

    def __getattr__(self, level):
        return lambda msg: self.lines.append((level, str(msg)))


def test_the_customize_setting_turns_strict_on(plugin_module, monkeypatch):
    _prefs(monkeypatch, strict_resources=True)
    opts = types.SimpleNamespace(kfxgen_strict_resources=False)
    plugin_module.KFXGenOutputPlugin()._apply_prefs(opts, _PluginLog())
    assert opts.kfxgen_strict_resources is True


def test_the_setting_off_leaves_the_option(plugin_module, monkeypatch):
    _prefs(monkeypatch)
    opts = types.SimpleNamespace(kfxgen_strict_resources=False)
    plugin_module.KFXGenOutputPlugin()._apply_prefs(opts, _PluginLog())
    assert opts.kfxgen_strict_resources is False


def test_a_strict_failure_is_not_masked_by_the_previewer_fallback(
    plugin_module, monkeypatch
):
    import importlib

    converter = importlib.import_module("plugin.kfxgen.converter")
    # The class the plugin actually compares against, under its package name.
    plugin_strict_error = importlib.import_module(
        "plugin.kfxgen.resource_check"
    ).StrictResourceError

    def native(*a, **k):
        raise plugin_strict_error("boom")

    monkeypatch.setattr(converter, "convert_oeb_to_kfx", native)
    kp = types.ModuleType("plugin.kfxgen.kp_calibre_converter")

    def fallback(*a, **k):
        raise AssertionError("the Kindle Previewer fallback must not run")

    kp.convert_oeb_to_kfx = fallback
    monkeypatch.setitem(sys.modules, "plugin.kfxgen.kp_calibre_converter", kp)
    plugin = plugin_module.KFXGenOutputPlugin()
    monkeypatch.setattr(plugin, "_apply_prefs", lambda opts, log: None)
    # Raised unchanged — the plugin's own class instance — with no fallback.
    with pytest.raises(plugin_strict_error):
        plugin.convert(None, "out.kfx", None, types.SimpleNamespace(), _PluginLog())
