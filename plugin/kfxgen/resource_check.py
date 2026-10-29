"""Strict validation of the resources a book requires (kfxgen_strict_resources).

Off by default. With it on, the converter fails *before* writing the KFX when
a cover, an HTML-referenced raster image or SVG, or a CSS ``@font-face`` font
cannot be read, decoded, or does not pass an existing size cap. Without it,
every one of those stays the best-effort skip-and-warn it has always been, and
the output bytes are unchanged.

Failures are aggregated as ``(kind, reference, reason)`` triples,
deduplicated and reported in a fixed, stable order. The reference is the
normalized *book-internal* href only — never the binary resource itself, the
book's body text, or an absolute path from the user's machine — and external
URLs (``http:``, ``https:``, ``data:``, …) are not book resources and are
never counted as failures.
"""

import posixpath
import re
from urllib.parse import unquote

#: Resource kinds, in the fixed order the aggregated report lists them.
COVER = "cover"
IMAGE = "image"
SVG = "svg"
FONT = "font"
_KIND_ORDER = (COVER, IMAGE, SVG, FONT)
_KIND_RANK = {kind: i for i, kind in enumerate(_KIND_ORDER)}

#: Stable reason wording. Kept here so the same condition names the same
#: problem at every skip site and in the tests. None of these ever carries
#: bytes, body text, or a path: font-specific detail (a table tag, a byte
#: count) is appended by the font pipeline from non-binary values only.
REASON_MISSING = "referenced but missing from the book"
REASON_UNREADABLE = "could not be read"
REASON_UNSUPPORTED_IMAGE = (
    "unsupported image format (only JPEG, PNG and GIF are emitted)"
)
REASON_UNDECODABLE = "could not be decoded"
REASON_SVG_UNREADABLE = "SVG image could not be read"
REASON_SVG_UNRASTERISED = "SVG image could not be rasterised to PNG"
REASON_FONT_NOT_A_FONT = "not a TTF, OTF, WOFF or WOFF2 font"

_SCHEME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.\-]*:")
_DRIVE_RE = re.compile(r"^[a-zA-Z]:[\\/]")
#: Schemes that plainly name something outside the book.
_EXTERNAL_SCHEMES = {
    "http",
    "https",
    "ftp",
    "ftps",
    "file",
    "data",
    "mailto",
    "news",
    "nntp",
    "tel",
    "sms",
    "gopher",
}


def _path_part(href):
    """The href without its fragment or query."""
    return (href or "").split("#", 1)[0].split("?", 1)[0]


def is_external_url(href):
    """Whether `href` names a remote/inline resource by URL scheme.

    ``http://``/``https://`` and friends, plus ``data:`` inline payloads. A
    Windows drive path is not a URL, but it is not a book-internal href
    either — callers gate on `is_book_internal_ref` for that.
    """
    part = _path_part(href).strip()
    m = _SCHEME_RE.match(part)
    if not m:
        return False
    return m.group(0)[:-1].lower() in _EXTERNAL_SCHEMES


def is_book_internal_ref(href):
    """Whether `href` can name a file inside the book container.

    Relative, no scheme, not absolute, no Windows drive, not protocol
    relative. Mirrors what the resolver's own href defenses treat as
    non-internal, so an external URL is never mistaken for a missing book
    file.
    """
    part = _path_part(href).strip()
    if not part:
        return False
    if part.startswith(("/", "\\")) or part.startswith("//"):
        return False
    if _DRIVE_RE.match(part):
        return False
    if _SCHEME_RE.match(part):
        return False
    return True


def normalize_resource_ref(href):
    """The stable, book-relative label used for `href` in error reports.

    Backslashes become slashes, percent-encoding and ``./``/``../`` and query
    strings are normalized away. Anything that could name a location outside
    the book (absolute, drive, scheme) reduces to "" so an absolute user path
    can never reach a message. The result is an identifier, not a filesystem
    path — it is never opened.
    """
    part = _path_part(href).replace("\\", "/").strip()
    if (
        not part
        or part.startswith("//")
        or _DRIVE_RE.match(part)
        or _SCHEME_RE.match(part)
    ):
        return ""
    decoded = unquote(part)
    normalized = posixpath.normpath(decoded) if decoded else ""
    # Drop traversal segments: the label names the file the book asked for;
    # it must never be an absolute or outside-the-book path.
    while normalized.startswith("../"):
        normalized = normalized[3:]
    if normalized in (".", "..") or normalized.startswith("/"):
        return ""
    return normalized


def _safe_reason(reason):
    """Flatten a reason to one line of bounded text. Reasons are authored
    phrases, but font detail is interpolated; keep control characters and
    newlines out of the aggregated report."""
    text = " ".join(str(reason or "").split())
    return text[:300]


class StrictResourceError(Exception):
    """Raised before any KFX is written when strict resource validation
    finds required resources that cannot be used."""


class ResourceIssues:
    """Collects required-resource failures during one conversion.

    A non-strict collector accepts but discards every record, so call sites
    can report unconditionally and the option off path stays byte-identical.
    """

    def __init__(self, strict=True):
        self.strict = bool(strict)
        # (kind, normalized_ref, reason); a set dedups rules repeated per
        # chapter and a cover found through more than one discovery path.
        self._issues = set()

    def add(self, kind, ref, reason):
        """Record one unusable resource. External and non-book-internal
        references, and empty normalized labels, are ignored."""
        if not self.strict:
            return
        if not is_book_internal_ref(ref or ""):
            return
        normalized = normalize_resource_ref(ref)
        if not normalized:
            return
        self._issues.add((kind, normalized, _safe_reason(reason)))

    def retain(self, *, keep_cover=False, required_image_refs=()):
        """Drop records for resources the written book does not actually
        require. Font records always stay: a CSS ``@font-face`` rule is the
        reference, and they only get recorded while fonts are being embedded.

        Cover records stay only when no usable cover survived. Image/SVG
        records stay only for refs a surviving picture token names.
        """
        if not self.strict:
            return
        required = {normalize_resource_ref(r) for r in required_image_refs}
        required.discard("")
        kept = set()
        for kind, ref, reason in self._issues:
            if kind == FONT:
                kept.add((kind, ref, reason))
            elif kind == COVER:
                if keep_cover:
                    kept.add((kind, ref, reason))
            elif ref in required:
                kept.add((kind, ref, reason))
        self._issues = kept

    def has_ref(self, ref, kinds=None):
        """Whether any record names the normalized form of `ref`, optionally
        limited to `kinds`. Lets the gate avoid adding a generic "missing" on
        top of the specific reason (undecodable, unsupported, …) already
        recorded for the same resource."""
        normalized = normalize_resource_ref(ref)
        if not normalized:
            return False
        wanted = set(kinds) if kinds else None
        return any(
            r == normalized and (wanted is None or k in wanted)
            for k, r, _why in self._issues
        )

    def has_kind(self, kind):
        """Whether any record of this resource kind exists."""
        return any(k == kind for k, _r, _why in self._issues)

    def sorted_issues(self):
        """The records in fixed order: resource kind, then reference, then
        reason — stable across runs and input ordering."""
        return sorted(
            self._issues, key=lambda t: (_KIND_RANK.get(t[0], len(_KIND_ORDER)),) + t
        )

    def message(self):
        issues = self.sorted_issues()
        lines = [
            f"Strict resource check failed: {len(issues)} required "
            f"resource{'s' if len(issues) != 1 else ''} could not be used:"
        ]
        lines.extend(f"  {kind} {ref!r}: {reason}" for kind, ref, reason in issues)
        return "\n".join(lines)

    def raise_if_any(self, log=None):
        """Raise `StrictResourceError` with the aggregated report, logging it
        first where a logger was given."""
        if not self._issues:
            return
        message = self.message()
        if log is not None:
            try:
                log.error(message)
            except Exception:  # noqa: BLE001 - reporting must not mask the error
                pass
        raise StrictResourceError(message)

    def __bool__(self):
        return bool(self._issues)

    def __len__(self):
        return len(self._issues)
