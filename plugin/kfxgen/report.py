"""Optional JSON conversion report (``kfxgen_report_path``).

Batch conversions previously left the only record of what a book became in
the log: how many chapters it produced, which resources were dropped, why a
book had no page navigation. Logs are not a reliable record across a batch,
so when ``kfxgen_report_path`` is set the native converter writes one JSON
report there, atomically, after a KFX is generated successfully.

The report deliberately carries *counts and outcomes only*. It never
contains body text, image bytes, credentials, or the user's absolute paths:
every string recorded passes through `scrub_text`, and resource hrefs are
in-book relative names reduced to a basename when they are absolute.

When no path is configured nothing here runs and the conversion's return
and output are unchanged. When a path is configured and its parent
directory is missing or the file cannot be written, `write_report` raises
`KfxgenReportError` — a distinct type so the plugin wrapper reports the
failure instead of silently retrying the conversion through Kindle
Previewer.
"""

from __future__ import annotations

import json
import os
import pathlib
import re

#: Bump for any incompatible change to the JSON shape below. A reader that
#: understands only lower numbers must reject what it does not know rather
#: than misread it.
REPORT_SCHEMA_VERSION = 1


class KfxgenReportError(Exception):
    """The optional JSON report could not be written.

    Raised only for the *report* (missing parent directory, unwritable
    destination, unserializable content) — never for the KFX itself — so
    callers can distinguish "the book converted, its report did not" from a
    conversion failure and avoid a pointless Kindle Previewer retry.
    """


# --- sanitization -----------------------------------------------------------
#
# Everything that ends up in the report goes through these, defence in depth:
# call sites only ever hand over counts and in-book names, but a warning
# message is assembled from a book's own hrefs and exception text, so it is
# scrubbed rather than trusted.

_HOME = os.path.expanduser("~")

#: Windows drive path: C:\... or C:/..., from the drive letter to a boundary.
_WINDOWS_PATH_RE = re.compile(
    r"[A-Za-z]:[\\/](?:[^<>:\"|?*\n\r\t]+[\\/])*[^<>:\"|?*\n\r\t]*"
)
#: POSIX absolute path with at least one directory component: /Users/a/b.
#: A rooted in-book reference such as "/OEBPS/x.jpg" matches too; that is
#: deliberately treated as a path rather than a safe name. The lookbehind
#: keeps a slash in the middle of other text from starting a match.
_POSIX_PATH_RE = re.compile(r"(?<![\w.])/(?:[^/\s\"'<>:*?|]+/)+[^/\s\"'<>:*?|]*")


def scrub_text(value):
    """Return `value` as a string with home directories and absolute paths
    redacted. Everything free-form that enters the report passes here."""
    text = str(value)
    if _HOME and _HOME not in ("~", "/", ""):
        text = text.replace(_HOME, "<home>")
    text = _WINDOWS_PATH_RE.sub("<path>", text)
    text = _POSIX_PATH_RE.sub("<path>", text)
    return text


_DRIVE_RE = re.compile(r"^[A-Za-z]:[\\/]")


def safe_resource_name(href):
    """An in-book resource href in the safe form a report may name: a
    relative href (``images/fig_1.jpg``) is kept, since it identifies the
    book's own file rather than anything on the user's machine; an absolute,
    rooted, drive-letter or traversal form is reduced to its basename. The
    fragment and query are stripped, as elsewhere when naming a file."""
    name = str(href or "").split("#", 1)[0].split("?", 1)[0]
    if not name:
        return ""
    parts = name.replace("\\", "/").split("/")
    unsafe = (
        name.startswith(("/", "\\"))
        or bool(_DRIVE_RE.match(name))
        or any(p == ".." for p in parts)
    )
    if unsafe:
        name = parts[-1]
    return scrub_text(name)


def _classify_warning(message):
    """A stable machine code for a captured warning message. The message is
    the authoritative text; the code only lets a consumer group warnings.
    The table keys off the same stable phrases and issue tags the messages
    themselves carry."""
    text = message.lower()
    if "#248" in message or "audio or video" in text:
        return "media_omitted"
    if "#219" in message or "one paragraph per row" in text:
        return "table_flattened"
    if "#231" in message:
        return "svg_text_repositioned"
    if "skipping @font-face" in text:
        return "font_skipped"
    if "skipping the cover" in text or "skipping cover candidate" in text:
        return "cover_skipped"
    if "skipping image" in text:
        return "image_skipped"
    if "toc" in text:
        return "toc"
    if "parse failed" in text:
        return "spine_parse_failed"
    return "conversion"


# --- collection -------------------------------------------------------------


class ConversionReport:
    """Accumulates what one conversion did, outside the log.

    Warnings arrive through `ReportLog` (every ``log.warn`` the conversion
    emits, in order); removed/unresolved resources and media coverage arrive
    through explicit calls at the points they happen. `payload` builds the
    final JSON shape with everything sorted deterministically.
    """

    def __init__(self):
        self._warnings = []
        self._warning_keys = set()
        self._removed = []
        self._removed_keys = set()
        self._unresolved = []
        self._unresolved_keys = set()
        self.media_coverage = {
            "read_aloud_narration_omitted": False,
            "audio_video_clips_omitted": 0,
            "audio_video_files": 0,
        }

    # -- warnings --

    def warn(self, message):
        """Record one captured warning, scrubbed and de-duplicated. Sorting
        happens at payload time so the JSON order never depends on dict or
        manifest iteration order."""
        text = scrub_text(message).strip()
        if not text:
            return
        code = _classify_warning(text)
        key = (code, text)
        if key in self._warning_keys:
            return
        self._warning_keys.add(key)
        self._warnings.append({"code": code, "message": text})

    # -- resources --

    def resource_removed(self, kind, name, reason):
        """Record a resource the book carried but the KFX does not: an
        unsupported or undecodable picture, an unusable font, an asset no
        page shows. `kind` is "image" / "cover" / "font"."""
        record = {
            "kind": str(kind),
            "name": safe_resource_name(name),
            "reason": str(reason),
        }
        key = (record["kind"], record["name"], record["reason"])
        if key in self._removed_keys:
            return
        self._removed_keys.add(key)
        self._removed.append(record)

    def resource_unresolved(self, kind, name, reason):
        """Record a reference the content makes to a resource that is not
        there (an <img src> the manifest cannot supply): the reference is
        dropped, the reader sees nothing at that point."""
        record = {
            "kind": str(kind),
            "name": safe_resource_name(name),
            "reason": str(reason),
        }
        key = (record["kind"], record["name"], record["reason"])
        if key in self._unresolved_keys:
            return
        self._unresolved_keys.add(key)
        self._unresolved.append(record)

    # -- media --

    def set_media_coverage(self, *, narration_omitted, clips_omitted, files):
        self.media_coverage = {
            "read_aloud_narration_omitted": bool(narration_omitted),
            "audio_video_clips_omitted": int(clips_omitted),
            "audio_video_files": int(files),
        }

    # -- output --

    def payload(self, stats):
        """Build the JSON-safe dict. `stats` holds the conversion outcome the
        orchestrator measured; every string is scrubbed here as well, so a
        caller cannot accidentally launder a path through the metadata."""
        book = stats.get("book") or {}
        content = stats.get("content") or {}
        navigation = stats.get("navigation") or {}
        images = stats.get("images") or {}
        fonts = stats.get("fonts") or {}
        cover = images.get("cover") or {}
        body = images.get("body") or {}

        warnings = sorted(self._warnings, key=lambda w: (w["code"], w["message"]))
        removed = sorted(
            self._removed, key=lambda r: (r["kind"], r["reason"], r["name"])
        )
        unresolved = sorted(
            self._unresolved, key=lambda r: (r["kind"], r["reason"], r["name"])
        )

        return {
            "schema_version": REPORT_SCHEMA_VERSION,
            "generator": {
                "name": "kfxgen",
                "version": scrub_text(stats.get("generator_version") or ""),
            },
            "book": {
                "title": scrub_text(book.get("title") or ""),
                "author": scrub_text(book.get("author") or ""),
                "authors": [scrub_text(a) for a in (book.get("authors") or []) if a],
                "language": scrub_text(book.get("language") or ""),
                "publisher": scrub_text(book.get("publisher") or ""),
            },
            "content": {
                "chapters": int(content.get("chapters") or 0),
                "characters": int(content.get("characters") or 0),
            },
            "navigation": {
                "toc_entries": int(navigation.get("toc_entries") or 0),
                "landmarks": int(navigation.get("landmarks") or 0),
                "page_list_entries": int(navigation.get("page_list_entries") or 0),
            },
            "images": {
                "cover": {
                    "present": bool(cover.get("present")),
                    "format": cover.get("format"),
                },
                "body": {
                    "emitted": int(body.get("emitted") or 0),
                },
            },
            "fonts": {
                "embedded_faces": int(fonts.get("embedded_faces") or 0),
                "embedding_disabled": bool(fonts.get("embedding_disabled")),
            },
            "resources_removed": removed,
            "resources_unresolved": unresolved,
            "media_coverage": dict(self.media_coverage),
            "warnings": warnings,
        }


class ReportLog:
    """Wrap the conversion logger so every ``warn``/``warning`` is recorded
    in the report while still reaching the real log. ``info``/``error``/
    ``debug`` and anything else pass straight through — only warnings are
    part of the report's contract."""

    def __init__(self, log, report):
        object.__setattr__(self, "_log", log)
        object.__setattr__(self, "_report", report)

    def _forward(self, name, args, kwargs):
        try:
            getattr(self._log, name)(*args, **kwargs)
        except Exception:
            # Recording must never be able to break a conversion because the
            # downstream logger did something unexpected.
            pass

    @staticmethod
    def _render(message, args):
        if not args:
            return message
        # Support the logging-style log.warn("fmt %s", x) form as well as
        # the f-strings the converter actually passes.
        try:
            return message % args
        except Exception:
            return " ".join([str(message), *[str(a) for a in args]])

    def warn(self, message=None, *args, **kwargs):
        try:
            self._report.warn(self._render(message, args))
        finally:
            self._forward("warn", (message, *args), kwargs)

    warning = warn

    def info(self, *args, **kwargs):
        self._forward("info", args, kwargs)

    def error(self, *args, **kwargs):
        self._forward("error", args, kwargs)

    def debug(self, *args, **kwargs):
        self._forward("debug", args, kwargs)

    def __getattr__(self, name):
        # Any other attribute (calibre log objects vary) is the wrapped
        # logger's. __getattr__ only runs when normal lookup fails, so the
        # attrs set in __init__ never reach it.
        return getattr(object.__getattribute__(self, "_log"), name)


# --- configuration + writing ------------------------------------------------


def report_path_from_opts(opts):
    """The configured report path as a stripped string, or None when unset.

    Only an actual string (or a real ``pathlib`` path) counts: a
    mock/namespace that invents attributes (test doubles, some option shims)
    also implements ``__fspath__`` and must not be mistaken for a configured
    path. None and a blank string also mean "no report".
    """
    raw = getattr(opts, "kfxgen_report_path", None)
    if isinstance(raw, pathlib.PurePath):
        path = str(raw)
    elif isinstance(raw, str):
        path = raw
    else:
        return None
    return path.strip() or None


def write_report(path, payload):
    """Atomically write `payload` as UTF-8 JSON to `path` after a successful
    KFX conversion.

    The parent directory must already exist — it is never created, so a
    typo in a batch's report path is reported rather than silently invented.
    Writing goes through the generator's `_safe_write_bytes` (temp file,
    fsync, os.replace), so a repeat conversion replaces the previous report
    atomically and a crash never leaves a half-written one.

    Raises `KfxgenReportError` with a message that names the problem.
    """
    path = os.fspath(path)
    parent = os.path.dirname(os.path.abspath(path))
    if not os.path.isdir(parent):
        raise KfxgenReportError(
            f"kfxgen report not written: its directory does not exist: {parent!r}. "
            "Create the directory or correct kfxgen_report_path; the KFX was still written."
        )
    try:
        data = (
            json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        ).encode("utf-8")
    except (TypeError, ValueError) as e:
        raise KfxgenReportError(
            f"kfxgen report not written: it could not be serialized to JSON: {e}"
        ) from e
    try:
        from .native_generator import _safe_write_bytes  # noqa: PLC0415

        _safe_write_bytes(path, data)
    except KfxgenReportError:
        raise
    except (OSError, ValueError) as e:
        raise KfxgenReportError(
            f"kfxgen report not written to {path!r}: {type(e).__name__}: {e}. "
            "The KFX was still written."
        ) from e
