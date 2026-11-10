"""SYNTHETIC DEMO DATA ONLY. Nothing here is, or is derived from, a real bill or receipt.

Five fixture documents for the intake and extraction tests:
  clean_bill            a two-page PDF whose figures all add up
  photographed_bill     a PNG standing in for a phone photo of a bill
  duplicate_rows        a PDF whose last two lines are identical
  arithmetic_mismatch   a PDF with a wrong line total and a wrong printed total
  upi_receipt_mismatch  a PNG UPI receipt that does not match the clean bill's advance

Each fixture records the true value of every field (`truth`), which the evaluation compares
against what the extraction pipeline produced. PDFs carry visible text. The images are blank
64x48 pictures: the marker `CAREDIRECT-SYNTHETIC-FIXTURE:<name>` (in a PDF comment or a PNG
text chunk) is what the mock adapter recognises, so no OCR happens anywhere.

Rendering is deterministic: no timestamps or random data, so output bytes are stable.

    python -m app.extraction.synthetic --out <dir>
"""

from __future__ import annotations

import argparse
import struct
import zlib
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

PDF_MIME = "application/pdf"
PNG_MIME = "image/png"
MARKER_PREFIX = "CAREDIRECT-SYNTHETIC-FIXTURE:"
BANNER = "SYNTHETIC DEMO DOCUMENT - NOT A REAL BILL"

PROVIDER = "Synthetic City Hospital (Demo)"
PROVIDER_ID = "SYN-REG-0001"
PATIENT_REF = "PT-SYN-001"


@dataclass(frozen=True)
class SyntheticFixture:
    name: str
    document_type: str
    mime_type: str
    pages: list[list[str]]
    # Expected normalised value for every field path, or None where the document shows nothing.
    truth: dict[str, str | None]

    @property
    def filename(self) -> str:
        return f"{self.name}{'.pdf' if self.mime_type == PDF_MIME else '.png'}"


# ---------------------------------------------------------------- truth builders

# (description, code, service_date, quantity, unit_price, line_total), all normalised strings
LineSpec = tuple[str, str, str, str, str, str]


def row_text(number: int, description: str, code: str, quantity: str, unit: str, total: str) -> str:
    """The printed form of one line, as it appears on the page."""
    return f"{number}  {description}  {code}  {quantity}  {unit}  {total}"


def _blank_truth() -> dict[str, str | None]:
    names = ("provider_name", "provider_identifier", "patient_reference")
    names += ("invoice_number", "invoice_date", "currency")
    names += ("subtotal", "tax_total", "total", "advance_paid")
    return dict.fromkeys(names)


def _bill_truth(
    invoice_number: str,
    invoice_date: str,
    lines: Sequence[LineSpec],
    subtotal: str,
    tax_total: str,
    total: str,
    advance_paid: str | None,
) -> dict[str, str | None]:
    truth = _blank_truth()
    truth.update(
        provider_name=PROVIDER,
        provider_identifier=PROVIDER_ID,
        patient_reference=PATIENT_REF,
        invoice_number=invoice_number,
        invoice_date=invoice_date,
        currency="INR",
        subtotal=subtotal,
        tax_total=tax_total,
        total=total,
        advance_paid=advance_paid,
    )
    for i, (desc, code, svc_date, qty, unit, line_total) in enumerate(lines):
        base = f"line_items.{i}"
        truth[f"{base}.description"] = desc
        truth[f"{base}.code"] = code
        truth[f"{base}.service_date"] = svc_date
        truth[f"{base}.quantity"] = qty
        truth[f"{base}.unit_price"] = unit
        truth[f"{base}.line_total"] = line_total
    return truth


def _header(invoice_number: str, invoice_date: str) -> list[str]:
    return [
        PROVIDER,
        f"Registration: {PROVIDER_ID}",
        f"Patient ref: {PATIENT_REF}",
        f"Invoice No: {invoice_number}",
        f"Invoice Date: {invoice_date}",
        "Currency: INR",
        "No  Description  Code  Qty  Rate  Amount",
    ]


def _footer(subtotal: str, tax: str, total: str, advance: str | None) -> list[str]:
    lines = [f"Subtotal: {subtotal}", f"Tax: {tax}", f"Total: {total}"]
    if advance is not None:
        lines.append(f"Advance paid: {advance}")
    return lines


def _rows(lines: Sequence[LineSpec], first: int = 1) -> list[str]:
    # Printed quantity is shown as a plain number, as on a real bill.
    return [
        row_text(first + i, d, c, q.split(".")[0], u, t)
        for i, (d, c, _s, q, u, t) in enumerate(lines)
    ]


# ---------------------------------------------------------------- the five fixtures

_CLEAN_LINES: tuple[LineSpec, ...] = (
    ("Consultation", "CONS-01", "2026-10-30", "1.000", "1500.00", "1500.00"),
    ("Complete blood count (CBC)", "LAB-CBC", "2026-10-30", "1.000", "2000.00", "2000.00"),
    ("Room charges (general ward)", "ROOM-GW", "2026-10-30", "2.000", "5000.00", "10000.00"),
    ("Pharmacy", "PHARM", "2026-10-30", "1.000", "11500.00", "11500.00"),
)
_PHOTO_LINES: tuple[LineSpec, ...] = (
    ("X-ray chest", "XR-CH", "2026-11-02", "1.000", "1200.00", "1200.00"),
    ("Wound dressing", "DRESS", "2026-11-02", "2.000", "250.00", "500.00"),
    ("Consultation", "CONS-01", "2026-11-02", "1.000", "2000.00", "2000.00"),
)
_DUPLICATE_LINES: tuple[LineSpec, ...] = (
    ("Consultation", "CONS-01", "2026-11-02", "1.000", "1500.00", "1500.00"),
    ("Complete blood count (CBC)", "LAB-CBC", "2026-11-02", "1.000", "2000.00", "2000.00"),
    ("Complete blood count (CBC)", "LAB-CBC", "2026-11-02", "1.000", "2000.00", "2000.00"),
)
# Line 1 is printed as 1600.00 but 2 x 750.00 is 1500.00; the printed total 2700.00 is also
# 100.00 more than the lines add up to (2600.00).
_ARITHMETIC_LINES: tuple[LineSpec, ...] = (
    ("Physiotherapy session", "PHYSIO", "2026-11-03", "2.000", "750.00", "1600.00"),
    ("Consultation", "CONS-01", "2026-11-03", "1.000", "1000.00", "1000.00"),
)


def _receipt_truth() -> dict[str, str | None]:
    """A UPI receipt: no provider, invoice or totals, only currency and payment details. The
    amount (4500.00) is more than the clean bill's printed advance (4000.00) and the payee is
    a different business, so reconciliation must not match it."""
    truth = _blank_truth()
    truth["currency"] = "INR"
    truth.update(
        {
            "receipt.amount": "4500.00",
            "receipt.paid_on": "2026-10-29",
            "receipt.transaction_reference": "SYNUPI0000123",
            "receipt.payee_name": "Synthetic Diagnostics Lab",
            "receipt.payment_method": "UPI",
        }
    )
    return truth


FIXTURES: tuple[SyntheticFixture, ...] = (
    SyntheticFixture(
        name="clean_bill",
        document_type="BILL",
        mime_type=PDF_MIME,
        pages=[
            _header("INV-SYN-1001", "2026-11-01") + _rows(_CLEAN_LINES),
            _footer("25000.00", "0.00", "25000.00", "4000.00"),
        ],
        truth=_bill_truth(
            "INV-SYN-1001", "2026-11-01", _CLEAN_LINES, "25000.00", "0.00", "25000.00", "4000.00"
        ),
    ),
    SyntheticFixture(
        name="photographed_bill",
        document_type="BILL",
        mime_type=PNG_MIME,
        pages=[
            _header("INV-SYN-1002", "2026-11-02")
            + _rows(_PHOTO_LINES)
            + _footer("3700.00", "0.00", "3700.00", None)
        ],
        truth=_bill_truth(
            "INV-SYN-1002", "2026-11-02", _PHOTO_LINES, "3700.00", "0.00", "3700.00", None
        ),
    ),
    SyntheticFixture(
        name="duplicate_rows",
        document_type="BILL",
        mime_type=PDF_MIME,
        pages=[
            _header("INV-SYN-1003", "2026-11-03")
            + _rows(_DUPLICATE_LINES)
            + _footer("5500.00", "0.00", "5500.00", None)
        ],
        truth=_bill_truth(
            "INV-SYN-1003", "2026-11-03", _DUPLICATE_LINES, "5500.00", "0.00", "5500.00", None
        ),
    ),
    SyntheticFixture(
        name="arithmetic_mismatch",
        document_type="BILL",
        mime_type=PDF_MIME,
        pages=[
            _header("INV-SYN-1004", "2026-11-04")
            + _rows(_ARITHMETIC_LINES)
            + _footer("2600.00", "0.00", "2700.00", None)
        ],
        truth=_bill_truth(
            "INV-SYN-1004", "2026-11-04", _ARITHMETIC_LINES, "2600.00", "0.00", "2700.00", None
        ),
    ),
    SyntheticFixture(
        name="upi_receipt_mismatch",
        document_type="RECEIPT",
        mime_type=PNG_MIME,
        pages=[
            [
                "UPI payment receipt",
                "Amount: 4500.00 INR",
                "Paid on: 2026-10-29",
                "Transaction ref: SYNUPI0000123",
                "Paid to: Synthetic Diagnostics Lab",
                "Method: UPI",
            ]
        ],
        truth=_receipt_truth(),
    ),
)

FIXTURES_BY_NAME: dict[str, SyntheticFixture] = {f.name: f for f in FIXTURES}


# ---------------------------------------------------------------- rendering


def _pdf_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _pdf_page_stream(lines: Sequence[str]) -> bytes:
    ops = ["BT", "/F1 11 Tf", "50 790 Td", "15 TL"]
    for line in lines:
        ops += [f"({_pdf_escape(line)}) Tj", "T*"]
    ops.append("ET")
    return "\n".join(ops).encode("latin-1")


def _render_pdf(fixture: SyntheticFixture) -> bytes:
    count = len(fixture.pages)
    kids = " ".join(f"{4 + 2 * i} 0 R" for i in range(count))
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        f"<< /Type /Pages /Kids [{kids}] /Count {count} >>".encode(),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    for i, page in enumerate(fixture.pages):
        text = [BANNER, f"Page {i + 1} of {count}", "", *page]
        stream = _pdf_page_stream(text)
        objects.append(
            (
                "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
                f"/Resources << /Font << /F1 3 0 R >> >> /Contents {5 + 2 * i} 0 R >>"
            ).encode()
        )
        objects.append(f"<< /Length {len(stream)} >>\nstream\n".encode() + stream + b"\nendstream")

    out = bytearray(b"%PDF-1.4\n")
    out += f"% {MARKER_PREFIX}{fixture.name}\n".encode("ascii")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode() + b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n"
    ).encode()
    return bytes(out)


def _png_chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))


def _render_png(fixture: SyntheticFixture) -> bytes:
    width, height = 64, 48
    header = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)
    marker = b"Comment\x00" + f"{MARKER_PREFIX}{fixture.name}".encode("ascii")
    rows = (b"\x00" + b"\xff" * width) * height
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", header)
        + _png_chunk(b"tEXt", marker)
        + _png_chunk(b"IDAT", zlib.compress(rows, 9))
        + _png_chunk(b"IEND", b"")
    )


def render(fixture: SyntheticFixture) -> bytes:
    """The fixture's file bytes. Deterministic."""
    return _render_pdf(fixture) if fixture.mime_type == PDF_MIME else _render_png(fixture)


# ---------------------------------------------------------------- command line


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Write the synthetic fixture files.")
    parser.add_argument("--out", required=True, type=Path, help="directory to write into")
    args = parser.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    for fixture in FIXTURES:
        (args.out / fixture.filename).write_bytes(render(fixture))
        print(fixture.filename)


if __name__ == "__main__":
    main()
