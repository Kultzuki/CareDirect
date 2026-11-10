"""Upload validation is pure: size, declared type, content signature, page count, SHA-256.
Every file here is built in memory; none contains real data."""

import hashlib
import struct
import zlib
from io import BytesIO

import pytest
from pypdf import PdfWriter

from app.documents.validation import normalise_mime, sniff_mime, validate_upload
from app.errors import ValidationFailed

PDF = "application/pdf"
PNG = "image/png"
JPEG = "image/jpeg"
LIMITS = {"max_bytes": 1024 * 1024, "max_pages": 20}
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def make_pdf(pages: int) -> bytes:
    """A minimal PDF whose cross-reference offsets are exact."""
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>"]
    kids = " ".join(f"{3 + i} 0 R" for i in range(pages))
    objs.append(f"<< /Type /Pages /Kids [{kids}] /Count {pages} >>".encode())
    objs += [b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 72 72] >>"] * pages
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objs, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n".encode() + b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    trailer = f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n"
    return bytes(out + trailer.encode())


def _chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))


def make_png(width: int = 2, height: int = 2) -> bytes:
    header = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)
    raw = b"".join(b"\x00" + b"\xff" * width for _ in range(height))
    return (
        PNG_SIGNATURE
        + _chunk(b"IHDR", header)
        + _chunk(b"IDAT", zlib.compress(raw))
        + _chunk(b"IEND", b"")
    )


def make_jpeg() -> bytes:
    return b"\xff\xd8\xff\xe0\x00\x10JFIF\x00" + b"\x00" * 16 + b"\xff\xd9"


def encrypted_pdf() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(72, 72)
    writer.encrypt("x", algorithm="RC4-128")
    buf = BytesIO()
    writer.write(buf)
    return buf.getvalue()


# ---------------------------------------------------------------- accepted files


@pytest.mark.parametrize("pages", [1, 3])
def test_pdf_accepted_with_exact_page_count(pages):
    content = make_pdf(pages)
    result = validate_upload(content, PDF, **LIMITS)
    assert result.mime_type == PDF
    assert result.page_count == pages
    assert result.file_size == len(content)
    assert result.sha256 == hashlib.sha256(content).hexdigest()


def test_png_accepted_as_one_page():
    content = make_png()
    result = validate_upload(content, PNG, **LIMITS)
    assert (result.mime_type, result.page_count) == (PNG, 1)
    assert result.sha256 == hashlib.sha256(content).hexdigest()


def test_jpeg_accepted_as_one_page():
    content = make_jpeg()
    result = validate_upload(content, JPEG, **LIMITS)
    assert (result.mime_type, result.page_count) == (JPEG, 1)
    assert result.sha256 == hashlib.sha256(content).hexdigest()


def test_declared_type_parameters_and_case_are_ignored():
    assert validate_upload(make_pdf(1), "application/pdf; charset=binary", **LIMITS).page_count == 1
    assert validate_upload(make_png(), " IMAGE/PNG ", **LIMITS).mime_type == PNG
    assert normalise_mime(None) == ""


def test_same_bytes_give_the_same_hash():
    assert (
        validate_upload(make_pdf(2), PDF, **LIMITS).sha256
        == validate_upload(make_pdf(2), PDF, **LIMITS).sha256
    )


# ---------------------------------------------------------------- refused files


def test_empty_content_refused():
    with pytest.raises(ValidationFailed, match="empty"):
        validate_upload(b"", PDF, **LIMITS)


def test_one_byte_over_the_limit_refused_and_exact_limit_accepted():
    content = make_png()
    assert validate_upload(content, PNG, max_bytes=len(content), max_pages=20).file_size
    with pytest.raises(ValidationFailed, match="larger"):
        validate_upload(content, PNG, max_bytes=len(content) - 1, max_pages=20)


@pytest.mark.parametrize("declared", ["text/plain", "text/html", "application/zip", "", None])
def test_disallowed_declared_type_refused(declared):
    with pytest.raises(ValidationFailed, match="only PDF, JPEG and PNG"):
        validate_upload(make_pdf(1), declared, **LIMITS)


def test_png_declared_as_pdf_refused():
    with pytest.raises(ValidationFailed, match="does not match"):
        validate_upload(make_png(), PDF, **LIMITS)


def test_pdf_declared_as_png_refused():
    with pytest.raises(ValidationFailed, match="does not match"):
        validate_upload(make_pdf(1), PNG, **LIMITS)


@pytest.mark.parametrize("declared", [PDF, PNG, JPEG])
@pytest.mark.parametrize(
    "content",
    [
        b"<!doctype html><html><script>alert(1)</script></html>",
        b"MZ\x90\x00\x03\x00\x00\x00 this program cannot be run in DOS mode",
        b"plain text pretending to be a document",
    ],
    ids=["html", "exe", "text"],
)
def test_unknown_content_refused_whatever_the_declared_type(content, declared):
    with pytest.raises(ValidationFailed, match="does not match"):
        validate_upload(content, declared, **LIMITS)


def test_broken_pdf_refused_without_parser_detail():
    with pytest.raises(ValidationFailed) as caught:
        validate_upload(b"%PDF-1.4\njunk", PDF, **LIMITS)
    assert str(caught.value) == "PDF could not be read"
    assert caught.value.__cause__ is None


def test_pdf_with_more_pages_than_the_limit_refused():
    with pytest.raises(ValidationFailed, match="3 pages; the limit is 2"):
        validate_upload(make_pdf(3), PDF, max_bytes=LIMITS["max_bytes"], max_pages=2)


def test_encrypted_pdf_refused():
    with pytest.raises(ValidationFailed, match="encrypted"):
        validate_upload(encrypted_pdf(), PDF, **LIMITS)


def test_png_with_zero_width_refused():
    with pytest.raises(ValidationFailed, match="does not match"):
        validate_upload(make_png(width=0, height=2), PNG, **LIMITS)


def test_png_signature_without_header_chunk_refused():
    with pytest.raises(ValidationFailed, match="does not match"):
        validate_upload(PNG_SIGNATURE + b"\x00" * 32, PNG, **LIMITS)


def test_sniff_reports_the_real_type():
    assert sniff_mime(make_pdf(1)) == PDF
    assert sniff_mime(make_png()) == PNG
    assert sniff_mime(make_jpeg()) == JPEG
    assert sniff_mime(b"GIF89a") is None
