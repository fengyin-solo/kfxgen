"""The optional JSON conversion report (``kfxgen_report_path``).

Covers, end to end through `convert_oeb_to_kfx` and at the unit level:

- a successful report: schema/version, metadata, chapter and character
  counts, TOC/landmark/page-list counts, cover/body image results, fonts;
- a book with no pictures and no fonts;
- warnings sorted deterministically and de-duplicated;
- a repeated conversion atomically replacing the previous report;
- write failures (missing parent directory, destination is a directory),
  with the KFX still produced and a clear error raised;
- the report disabled (option absent/None/blank): unchanged behaviour;
- the KFX bytes being identical whether or not a report is configured, and
  the report containing no body text, image bytes, or absolute user paths.
"""

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from kfxgen import converter as _conv
from kfxgen.native_generator import NativeKFXGenerator
from kfxgen.report import (
    REPORT_SCHEMA_VERSION,
    ConversionReport,
    KfxgenReportError,
    ReportLog,
    report_path_from_opts,
    safe_resource_name,
    scrub_text,
    write_report,
)
from tests._helpers import NullLog, jpeg_of
from tests.fixtures.epub_builder import EpubBuilder
from tests.fixtures.oeb_shim import EpubAsOeb

pytestmark = pytest.mark.unit

XHTML = (
    '<?xml version="1.0" encoding="utf-8"?>'
    '<html xmlns="http://www.w3.org/1999/xhtml"><head><title>{t}</title></head>'
    "<body>{body}</body></html>"
)


class Opts:
    """Conversion opts the native path reads, with an optional report path."""

    def __init__(self, report_path=None, **extra):
        if report_path is not None:
            self.kfxgen_report_path = report_path
        for key, value in extra.items():
            setattr(self, key, value)


def _book_path(tmp_path, name, builder):
    return builder.build(tmp_path, name)


def _convert(epub_path, kfx_path, opts):
    _conv.convert_oeb_to_kfx(EpubAsOeb(str(epub_path)), str(kfx_path), opts, NullLog())


def _read_report(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


# ── option resolution ──────────────────────────────────────────────────────


def test_report_path_from_opts():
    assert report_path_from_opts(Opts("/tmp/r.json")) == "/tmp/r.json"
    assert report_path_from_opts(Opts("  /tmp/r.json ")) == "/tmp/r.json"
    assert report_path_from_opts(Opts("")) is None
    assert report_path_from_opts(Opts("   ")) is None
    assert report_path_from_opts(Opts(None)) is None
    assert report_path_from_opts(object()) is None  # attribute absent


def test_a_non_string_option_value_never_enables_a_report(tmp_path):
    # A mock/namespace that invents attributes must not be read as a
    # configured path (a MagicMock opts used to make the converter write a
    # report to a file named after the mock's repr in the working dir).
    assert report_path_from_opts(MagicMock()) is None
    assert report_path_from_opts(MagicMock(kfxgen_report_path=1234)) is None
    # A real path-like value still counts.
    assert report_path_from_opts(Opts(Path("/tmp/r.json"))) == "/tmp/r.json"

    builder = (
        EpubBuilder()
        .set_metadata(title="P", author="A")
        .add_chapter("One", XHTML.format(t="One", body="<p>x</p>").encode())
    )
    epub = builder.build(tmp_path, "p")
    kfx_path = tmp_path / "p.kfx"
    _conv.convert_oeb_to_kfx(
        EpubAsOeb(str(epub)), str(kfx_path), MagicMock(), NullLog()
    )
    assert kfx_path.exists()
    assert not list(tmp_path.glob("*.json"))
    # Nothing landed in the working directory either.
    assert not [p for p in Path.cwd().glob("*MagicMock*")]


# ── successful report ──────────────────────────────────────────────────────


def _illustrated_book(tmp_path, name="ill"):
    builder = (
        EpubBuilder()
        .set_metadata(title="Illustrated", author="Jane Doe", language="en")
        .set_cover(jpeg_of(400, 600), href="cover.jpg")
        .add_chapter(
            "Chapter One",
            XHTML.format(t="Chapter One", body="<p>First chapter prose.</p>").encode(),
        )
        .add_chapter(
            "Chapter Two",
            XHTML.format(
                t="Chapter Two",
                body='<p>A plate:</p><img src="images/plate.jpg" alt="plate"/>',
            ).encode(),
        )
        .add_image_page("Plate", image=jpeg_of(300, 200), href="images/plate.jpg")
    )
    return _book_path(tmp_path, name, builder)


def test_a_successful_report_carries_every_section(tmp_path):
    epub = _illustrated_book(tmp_path)
    report_path = tmp_path / "report.json"
    kfx_path = tmp_path / "book.kfx"
    _convert(epub, kfx_path, Opts(str(report_path)))

    assert kfx_path.exists() and kfx_path.stat().st_size > 0
    report = _read_report(report_path)

    assert report["schema_version"] == REPORT_SCHEMA_VERSION
    assert report["generator"]["name"] == "kfxgen"
    assert report["generator"]["version"].count(".") == 2

    assert report["book"] == {
        "title": "Illustrated",
        "author": "Jane Doe",
        "authors": ["Jane Doe"],
        "language": "en",
        "publisher": "kfxgen",
    }

    assert report["content"]["chapters"] == 3
    assert report["content"]["characters"] > 0

    nav = report["navigation"]
    assert set(nav) == {"toc_entries", "landmarks", "page_list_entries"}
    assert nav["toc_entries"] == 3
    assert nav["landmarks"] == 0
    assert nav["page_list_entries"] == 0

    assert report["images"]["cover"] == {"present": True, "format": "jpeg"}
    assert report["images"]["body"]["emitted"] == 1

    assert report["fonts"]["embedded_faces"] == 0
    assert report["fonts"]["embedding_disabled"] is False

    assert isinstance(report["resources_removed"], list)
    assert isinstance(report["resources_unresolved"], list)
    assert report["media_coverage"] == {
        "read_aloud_narration_omitted": False,
        "audio_video_clips_omitted": 0,
        "audio_video_files": 0,
    }
    assert isinstance(report["warnings"], list)
    for warning in report["warnings"]:
        assert set(warning) == {"code", "message"}
        assert warning["code"] and isinstance(warning["message"], str)

    # Valid, pretty-printed JSON ending in a newline; no temp file left.
    raw = report_path.read_text(encoding="utf-8")
    json.loads(raw)
    assert raw.endswith("\n")
    assert not list(tmp_path.glob("*.tmp"))


def test_the_report_never_carries_text_bytes_or_user_paths(tmp_path):
    secret_sentence = "THE QUICK BROWN FOX JUMPS OVER THE LAZY DOG 1857"
    builder = (
        EpubBuilder()
        .set_metadata(title="Secret Prose", author="A. U. Thor")
        .set_cover(jpeg_of(120, 180), href="cover.jpg")
        .add_chapter(
            "Chapter",
            XHTML.format(t="Chapter", body=f"<p>{secret_sentence}</p>").encode(),
        )
    )
    epub = _book_path(tmp_path, "secret", builder)
    report_path = tmp_path / "report.json"
    _convert(epub, tmp_path / "book.kfx", Opts(str(report_path)))

    raw = report_path.read_text(encoding="utf-8")
    # No body text.
    assert secret_sentence not in raw
    # No image bytes (the JPEG's JFIF marker would appear if bytes leaked).
    assert "JFIF" not in raw
    # No credentials marker, and no absolute user/KFX path: counts and
    # in-book relative names only.
    assert str(tmp_path) not in raw
    assert "book.kfx" not in raw
    assert "\x00IMG\x01" not in raw


# ── book with no images and no fonts ───────────────────────────────────────


def test_a_text_only_book_reports_zero_media(tmp_path):
    builder = (
        EpubBuilder()
        .set_metadata(title="Plain", author="Pat")
        .add_chapter(
            "Only Chapter",
            XHTML.format(t="Only Chapter", body="<p>Just words.</p>").encode(),
        )
    )
    epub = _book_path(tmp_path, "plain", builder)
    report_path = tmp_path / "report.json"
    _convert(epub, tmp_path / "plain.kfx", Opts(str(report_path)))

    report = _read_report(report_path)
    assert report["images"]["cover"] == {"present": False, "format": None}
    assert report["images"]["body"]["emitted"] == 0
    assert report["fonts"]["embedded_faces"] == 0
    assert report["resources_removed"] == []
    assert report["resources_unresolved"] == []


def test_font_embedding_disabled_is_reported(tmp_path, monkeypatch):
    from kfxgen.font_table import FontTable

    # No Calibre in CI, so a real @font-face cannot be extracted; stub the
    # table to prove the count and the disabled flag cross the wire.
    monkeypatch.setattr(
        _conv,
        "build_font_table",
        lambda *a, **k: FontTable([]),
        raising=False,
    )
    builder = (
        EpubBuilder()
        .set_metadata(title="F", author="A")
        .add_chapter("One", XHTML.format(t="One", body="<p>x</p>").encode())
    )
    epub = _book_path(tmp_path, "f", builder)
    report_path = tmp_path / "r.json"
    _convert(
        epub,
        tmp_path / "f.kfx",
        Opts(str(report_path), kfxgen_disable_font_embedding=True),
    )
    report = _read_report(report_path)
    assert report["fonts"] == {"embedded_faces": 0, "embedding_disabled": True}


def test_embedded_face_count_crosses_the_wire(tmp_path, monkeypatch):
    import kfxgen.font_table as _ft
    from kfxgen.font_table import Face, FontTable
    from tests._helpers import sfnt_of

    faces = [
        Face(
            css_family="serif",
            weight=400,
            italic=False,
            data=sfnt_of(),
            emitted_family=f"serif-{i}-regular",
            location=f"resource/font{i}",
        )
        for i in range(2)
    ]
    # _font_table_for imports build_font_table from the font_table module, so
    # the patch has to live there.
    monkeypatch.setattr(_ft, "build_font_table", lambda *a, **k: FontTable(faces))
    builder = (
        EpubBuilder()
        .set_metadata(title="F2", author="A")
        .add_chapter("One", XHTML.format(t="One", body="<p>x</p>").encode())
    )
    epub = _book_path(tmp_path, "f2", builder)
    report_path = tmp_path / "r.json"
    _convert(epub, tmp_path / "f2.kfx", Opts(str(report_path)))
    report = _read_report(report_path)
    assert report["fonts"]["embedded_faces"] == 2


# ── removed / unresolved resources and media coverage, end to end ──────────


def test_removed_and_unresolved_resources_and_media_are_reported(tmp_path):
    page = XHTML.format(
        t="One",
        body=(
            "<p>Clips: "
            "<audio src='a.mp3' controls='controls'></audio>"
            "<audio src='a.mp3'/>"
            "<video src='v.mp4'><p>fallback</p></video>"
            "</p>"
            '<p><img src="images/missing.jpg" alt="gone"/></p>'
            '<p><img src="images/bad.gif" alt="bad"/></p>'
        ),
    ).encode()
    builder = (
        EpubBuilder()
        .set_metadata(title="Media", author="A")
        .add_chapter("One", page)
        .add_manifest_item(
            item_id="bad",
            href="images/bad.gif",
            media_type="image/gif",
            data=b"GIF89a" + b"\x00" * 200,
        )
    )
    epub = _book_path(tmp_path, "media", builder)
    report_path = tmp_path / "r.json"
    log = MagicMock(wraps=NullLog())
    _conv.convert_oeb_to_kfx(
        EpubAsOeb(str(epub)),
        str(tmp_path / "media.kfx"),
        Opts(str(report_path)),
        log,
    )
    report = _read_report(report_path)

    removed = report["resources_removed"]
    assert {
        "kind": "image",
        "name": "images/bad.gif",
        "reason": "unsupported_format",
    } in removed

    unresolved = report["resources_unresolved"]
    missing_names = {r["name"] for r in unresolved}
    assert {"images/bad.gif", "images/missing.jpg"} <= missing_names
    assert all(r["reason"] == "referenced_in_content_but_missing" for r in unresolved)

    media = report["media_coverage"]
    assert media["audio_video_clips_omitted"] == 3
    assert media["audio_video_files"] == 1
    assert any(w["code"] == "media_omitted" for w in report["warnings"])
    assert any(w["code"] == "image_skipped" for w in report["warnings"])

    # The warnings also still reached the real log (output unchanged).
    assert log.warn.called


# ── warning sorting, de-duplication, classification ───────────────────────


def test_warnings_are_sorted_and_deduped():
    report = ConversionReport()
    messages = [
        "  Skipping image 'z.jpg': it can't be decoded",
        "  Left out, since kfxgen writes no audio or video: 1 clip (#248)",
        "  Skipping image 'a.jpg': it can't be decoded",
        "  Skipping image 'a.jpg': it can't be decoded",  # exact duplicate
        "  TOC entry 'x' dropped: not in spine",
    ]
    for message in messages:
        report.warn(message)

    payload = report.payload({})
    warnings = payload["warnings"]
    assert warnings == sorted(warnings, key=lambda w: (w["code"], w["message"]))
    # Four distinct records: the duplicate image warning is one.
    assert len(warnings) == 4
    # Leading whitespace is trimmed when recorded.
    assert all(not w["message"].startswith(" ") for w in warnings)
    # Code groups come out in code order regardless of arrival order.
    codes = [w["code"] for w in warnings]
    assert codes == sorted(codes)
    assert "image_skipped" in codes and "media_omitted" in codes
    assert "toc" in codes
    # Sorted inside the image group too.
    image_messages = [w["message"] for w in warnings if w["code"] == "image_skipped"]
    assert image_messages == sorted(image_messages)
    assert image_messages[0].startswith("Skipping image 'a.jpg'")


def test_warning_codes_are_classified():
    report = ConversionReport()
    report.warn("  2 tables in 1 file written as one paragraph per row (#219)")
    report.warn(
        "  Words drawn in SVG pictures in 1 file are written after the "
        "picture, not over it (#231)"
    )
    report.warn("  Spine item 2 parse failed (ch2.xhtml): boom")
    report.warn("  Skipping @font-face 'Serif': no embeddable TTF, OTF src")
    report.warn("  Something else entirely")
    codes = [w["code"] for w in report.payload({})["warnings"]]
    assert codes == sorted(codes)
    assert set(codes) == {
        "conversion",
        "font_skipped",
        "spine_parse_failed",
        "svg_text_repositioned",
        "table_flattened",
    }


# ── sanitization ───────────────────────────────────────────────────────────


def test_scrub_text_redacts_home_and_absolute_paths():
    message = "failed reading /Users/someone/Library/book.epub on disk"
    scrubbed = scrub_text(message)
    assert "/Users/someone" not in scrubbed
    assert "book.epub" not in scrubbed
    assert "<path>" in scrubbed

    rooted = scrub_text("cover at C:\\Users\\someone\\cover.jpg gone")
    assert "someone" not in rooted and "<path>" in rooted

    # In-book relative hrefs and issue tags are not paths.
    assert scrub_text("Skipping image 'images/a.jpg' (#248)") == (
        "Skipping image 'images/a.jpg' (#248)"
    )


def test_safe_resource_name_keeps_relative_reduces_absolute():
    assert safe_resource_name("OEBPS/fonts/a.ttf") == "OEBPS/fonts/a.ttf"
    assert safe_resource_name("/OEBPS/fonts/a.ttf") == "a.ttf"
    assert safe_resource_name("../secret.ttf") == "secret.ttf"
    assert safe_resource_name("C:\\Windows\\x.ttf") == "x.ttf"
    assert safe_resource_name("images/a.jpg#frag") == "images/a.jpg"
    assert safe_resource_name("") == ""


def test_an_absolute_path_in_a_captured_warning_is_redacted_in_payload(tmp_path):
    # The conversion captures warnings itself; emulate one carrying an
    # absolute user path (a href a hostile book rooted at the filesystem)
    # and check the assembled payload can never carry it.
    report = ConversionReport()
    report.warn(f"  Spine item 1 parse failed ({tmp_path}/secret/file.jpg): boom")
    payload = report.payload({})
    raw = json.dumps(payload)
    assert str(tmp_path) not in raw
    assert "<path>" in raw


# ── atomic overwrite on repeated conversion ────────────────────────────────


def test_a_repeated_conversion_replaces_the_report(tmp_path):
    def build(title):
        return (
            EpubBuilder()
            .set_metadata(title=title, author="A")
            .add_chapter("One", XHTML.format(t="One", body="<p>words</p>").encode())
            .build(tmp_path, f"{title}.epub".lower())
        )

    report_path = tmp_path / "report.json"
    kfx_path = tmp_path / "book.kfx"

    _convert(build("First"), kfx_path, Opts(str(report_path)))
    first = _read_report(report_path)
    assert first["book"]["title"] == "First"
    mtime = report_path.stat().st_mtime_ns

    # A second conversion of a different book to the same paths overwrites
    # the report atomically with current content (no stale merge).
    _convert(build("Second"), kfx_path, Opts(str(report_path)))
    second = _read_report(report_path)
    assert second["book"]["title"] == "Second"
    assert first != second
    assert report_path.stat().st_mtime_ns >= mtime
    # Exactly one report, no temp file beside it.
    assert list(tmp_path.glob("report.json*")) == [report_path]


# ── write failures ─────────────────────────────────────────────────────────


def test_a_missing_report_directory_raises_and_keeps_the_kfx(tmp_path):
    builder = (
        EpubBuilder()
        .set_metadata(title="P", author="A")
        .add_chapter("One", XHTML.format(t="One", body="<p>x</p>").encode())
    )
    epub = _book_path(tmp_path, "p", builder)
    kfx_path = tmp_path / "p.kfx"
    bad_report = tmp_path / "no" / "such" / "dir" / "report.json"

    with pytest.raises(KfxgenReportError) as excinfo:
        _convert(epub, kfx_path, Opts(str(bad_report)))
    assert "directory does not exist" in str(excinfo.value)
    # The book itself converted: report failure never loses the KFX.
    assert kfx_path.exists()
    assert not bad_report.exists()


def test_a_report_path_that_is_a_directory_raises(tmp_path):
    builder = (
        EpubBuilder()
        .set_metadata(title="P", author="A")
        .add_chapter("One", XHTML.format(t="One", body="<p>x</p>").encode())
    )
    epub = _book_path(tmp_path, "p2", builder)
    target = tmp_path / "report.json"
    target.mkdir()
    with pytest.raises(KfxgenReportError):
        _convert(epub, tmp_path / "p2.kfx", Opts(str(target)))
    assert (tmp_path / "p2.kfx").exists()


def test_write_report_reports_serialization_and_parent_errors(tmp_path):
    payload = {"ok": True}

    with pytest.raises(KfxgenReportError):
        write_report(str(tmp_path / "missing" / "r.json"), payload)

    (tmp_path / "dir.json").mkdir()
    with pytest.raises(KfxgenReportError):
        write_report(str(tmp_path / "dir.json"), payload)

    with pytest.raises(KfxgenReportError):
        write_report(str(tmp_path / "r.json"), {"bad": object()})


def test_the_report_path_cannot_be_the_kfx_path(tmp_path):
    builder = (
        EpubBuilder()
        .set_metadata(title="P", author="A")
        .add_chapter("One", XHTML.format(t="One", body="<p>x</p>").encode())
    )
    epub = _book_path(tmp_path, "p3", builder)
    same = tmp_path / "same.kfx"
    with pytest.raises(KfxgenReportError):
        _convert(epub, same, Opts(str(same)))
    assert not same.exists()


# ── disabled report: unchanged behaviour ───────────────────────────────────


@pytest.mark.parametrize("opts", [object(), Opts(None), Opts(""), Opts("   ")])
def test_no_report_path_changes_nothing(tmp_path, opts):
    builder = (
        EpubBuilder()
        .set_metadata(title="Plain", author="Pat")
        .add_chapter("One", XHTML.format(t="One", body="<p>Hi there.</p>").encode())
    )
    epub = _book_path(tmp_path, "plain", builder)
    kfx_path = tmp_path / "plain.kfx"
    result = _conv.convert_oeb_to_kfx(
        EpubAsOeb(str(epub)), str(kfx_path), opts, NullLog()
    )
    assert result is None
    assert kfx_path.exists()
    assert not list(tmp_path.glob("*.json"))
    assert not list(tmp_path.glob("*.tmp"))


# ── the KFX is independent of the report ───────────────────────────────────


def test_the_kfx_is_identical_with_and_without_a_report(tmp_path):
    builder = (
        EpubBuilder()
        .set_metadata(title="Same Book", author="A")
        .set_cover(jpeg_of(100, 150), href="cover.jpg")
        .add_chapter(
            "One",
            XHTML.format(t="One", body='<p>Words <img src="cover.jpg"/></p>').encode(),
        )
    )
    epub = _book_path(tmp_path, "same", builder)
    without = tmp_path / "without.kfx"
    with_report = tmp_path / "with.kfx"
    _convert(epub, without, object())
    _convert(epub, with_report, Opts(str(tmp_path / "r.json")))
    assert without.read_bytes() == with_report.read_bytes()


def test_generator_stats_are_not_serialized_into_the_kfx(tmp_path):
    # The generator's report stats are instance data; asking for them must
    # not change one byte of the container.
    block = {
        "text": "Before after.",
        "spans": [],
        "anchor_keys": ["c1.xhtml#p1"],
        "anchor_offsets": {"c1.xhtml#p1": 7},
    }
    chapters = [{"title": "One", "text": block["text"], "blocks": [block]}]
    a = tmp_path / "a.kfx"
    b = tmp_path / "b.kfx"
    gen_a = NativeKFXGenerator()
    gen_a.generate_full_book(
        "T",
        "A",
        chapters,
        output_path=str(a),
        landmarks=[("toc", "Contents", "c1.xhtml#p1")],
        page_list=[("1", "c1.xhtml#p1"), ("2", "gone.xhtml#x")],
    )
    NativeKFXGenerator().generate_full_book(
        "T",
        "A",
        [
            {
                "title": "One",
                "text": block["text"],
                "blocks": [dict(block)],
            }
        ],
        output_path=str(b),
        landmarks=[("toc", "Contents", "c1.xhtml#p1")],
        page_list=[("1", "c1.xhtml#p1"), ("2", "gone.xhtml#x")],
    )
    assert a.read_bytes() == b.read_bytes()
    # Counts reflect what actually landed: one each, one page dropped.
    nav = gen_a.generation_stats["navigation"]
    assert nav == {"toc_entries": 1, "landmarks": 1, "page_list_entries": 1}
    assert gen_a.generation_stats["body_images_emitted"] == 0


# ── ReportLog wrapper ──────────────────────────────────────────────────────


def test_report_log_forwards_and_captures_warnings():
    report = ConversionReport()
    log = MagicMock()
    wrapped = ReportLog(log, report)

    wrapped.info("an info line")
    wrapped.error("an error line")
    wrapped.debug("debug")
    # logging-style % formatting is supported
    wrapped.warn("count %d in %s", 3, "1 file")
    wrapped.warning("plain warning")
    wrapped.warn("plain warning")  # de-duped

    log.info.assert_called_once_with("an info line")
    log.error.assert_called_once_with("an error line")
    # Every call still reaches the wrapped log, including the duplicate:
    # de-duplication only shapes what the report records.
    assert log.warn.call_count == 3

    messages = [w["message"] for w in report.payload({})["warnings"]]
    assert messages == ["count 3 in 1 file", "plain warning"]


def test_report_log_unknown_attributes_delegate():
    log = MagicMock()
    wrapped = ReportLog(log, ConversionReport())
    # A calibre-specific method the wrapper does not know about.
    wrapped.some_other_handler("x")
    log.some_other_handler.assert_called_once_with("x")


# ── plugin wiring (static: calibre is not importable in CI) ────────────────


PLUGIN_INIT = Path("plugin/__init__.py").read_text()
CONFIG = Path("plugin/config.py").read_text()
PREFS = Path("plugin/prefs.py").read_text()


def test_plugin_declares_the_report_option():
    assert 'name="kfxgen_report_path"' in PLUGIN_INIT
    assert "JSON report" in PLUGIN_INIT


def test_plugin_does_not_fallback_after_a_report_error():
    assert "KfxgenReportError" in PLUGIN_INIT
    # The report error is re-raised inside the native attempt's handler,
    # before the Kindle Previewer fallback.
    assert PLUGIN_INIT.index("KfxgenReportError") < PLUGIN_INIT.index(
        "Attempting Kindle Previewer fallback..."
    )


def test_prefs_and_config_hold_the_report_path():
    assert 'prefs.defaults["report_path"]' in PREFS
    assert "report_path" in CONFIG
    assert "QLineEdit" in CONFIG
