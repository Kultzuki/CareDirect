"""Pure upload validation: size, declared MIME type, content signature, page count, SHA-256.

The client's file name and declared type are never trusted. The content decides, and a file
whose content does not match the declared type is refused. Error messages never include
file bytes.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from io import BytesIO

from pypdf import PdfReader

from app.errors import ValidationFailed

# pypdf logs a warning for every small structural error it tolerates in non-strict mode;
# scanner PDFs trigger many of them. Keep real errors, drop the noise.
logging.getLogger("pypdf").setLevel(logging.ERROR)

ALLOWED_MIME = ("application/pdf", "image/jpeg", "image/png")

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_JPEG_SIGNATURE = b"\xff\xd8\xff"
_PDF_SIGNATURE = b"%PDF-"


@dataclass(frozen=True)
class ValidatedFile:
    mime_type: str
    file_size: int
    page_count: int
    sha256: str


def describe_size(num_bytes: int) -> str:
    """Human-readable size for error messages (display only)."""
    if num_bytes >= 1024 * 1024:
        return f"{num_bytes / (1024 * 1024):g} MB"
    if num_bytes >= 1024:
        return f"{num_bytes / 1024:g} KB"
    return f"{num_bytes} bytes"


def too_large(max_bytes: int) -> ValidationFailed:
    return ValidationFailed(f"file is larger than the {describe_size(max_bytes)} limit")


def normalise_mime(declared: str | None) -> str:
    """Lower-case the media type and drop parameters such as `; charset=binary`."""
    return (declared or "").split(";", 1)[0].strip().lower()


def sniff_mime(content: bytes) -> str | None:
    """Return the type the bytes really are, or None when they are none of the three."""
    if content.startswith(_PDF_SIGNATURE):
        return "application/pdf"
    if content.startswith(_PNG_SIGNATURE):
        # A real PNG starts with an IHDR chunk holding non-zero width and height.
        if len(content) < 24 or content[12:16] != b"IHDR":
            return None
        width = int.from_bytes(content[16:20], "big")
        height = int.from_bytes(content[20:24], "big")
        return "image/png" if width > 0 and height > 0 else None
    if content.startswith(_JPEG_SIGNATURE):
        return "image/jpeg"
    return None


def _pdf_page_count(content: bytes, max_pages: int) -> int:
    try:
        reader = PdfReader(BytesIO(content), strict=False)
        encrypted = bool(reader.is_encrypted)
        pages = 0 if encrypted else len(reader.pages)
    except Exception:
        # Deliberate catch-all at the untrusted-parser boundary: whatever pypdf raises on a
        # hostile or damaged file, the answer is the same refusal with no parser detail.
        raise ValidationFailed("PDF could not be read") from None
    if encrypted:
        raise ValidationFailed("encrypted PDFs are not accepted")
    if pages == 0:
        raise ValidationFailed("PDF has no pages")
    if pages > max_pages:
        raise ValidationFailed(f"PDF has {pages} pages; the limit is {max_pages}")
    return pages


def validate_upload(
    content: bytes, declared_mime: str | None, *, max_bytes: int, max_pages: int
) -> ValidatedFile:
    if not content:
        raise ValidationFailed("file is empty")
    if len(content) > max_bytes:
        raise too_large(max_bytes)

    declared = normalise_mime(declared_mime)
    if declared not in ALLOWED_MIME:
        raise ValidationFailed("only PDF, JPEG and PNG files are accepted")

    actual = sniff_mime(content)
    if actual is None or actual != declared:
        raise ValidationFailed("file content does not match the declared type")

    pages = _pdf_page_count(content, max_pages) if actual == "application/pdf" else 1
    return ValidatedFile(
        mime_type=actual,
        file_size=len(content),
        page_count=pages,
        sha256=hashlib.sha256(content).hexdigest(),
    )
