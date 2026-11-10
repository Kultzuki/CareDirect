"""SYNTHETIC DEMO DATA ONLY. Recorded outputs for the mock document-AI provider.

Each entry is the raw output a document-AI model would return for one synthetic fixture
(see `synthetic.py`), written as untrusted JSON: money, quantity and confidence are strings,
and `{document_id}` is replaced with the real document id when the mock replays it. The mock
adapter returns these unchanged; the schema validator then treats them like any other model
output.

Four outputs match their fixture exactly, with confidences between 0.920 and 0.990.
`photographed_bill` simulates what a phone photo does to OCR, to exercise the review gate:
  - the X-ray `line_total` is misread as 1700.00 (the bill says 1200.00), confidence 0.550;
  - `invoice_date` is unreadable, so it is null;
  - `provider_identifier` is read correctly but with confidence 0.700;
  - every other field is correct at confidence 0.910 or higher.

These outputs measure the validation and review pipeline. They say nothing about how well a
real model reads real documents.
"""

from __future__ import annotations

from typing import Any

from app.extraction.synthetic import PATIENT_REF, PROVIDER, PROVIDER_ID, row_text

DOCUMENT_ID = "{document_id}"
SCHEMA_VERSION = "caredirect.extraction.v1"

NULL: dict[str, Any] = {"value": None, "confidence": None, "source": None}

# Raw lines as a model would report them: quantity "1", not "1.000".
# (description, code, service_date, quantity, unit_price, line_total)
RawLine = tuple[str, str, str, str, str, str]

_CLEAN_CONFIDENCE = {
    "provider_name": "0.990",
    "provider_identifier": "0.970",
    "patient_reference": "0.960",
    "invoice_number": "0.980",
    "invoice_date": "0.970",
    "currency": "0.990",
    "description": "0.970",
    "code": "0.960",
    "service_date": "0.950",
    "quantity": "0.980",
    "unit_price": "0.970",
    "line_total": "0.980",
    "subtotal": "0.970",
    "tax_total": "0.960",
    "total": "0.980",
    "advance_paid": "0.940",
}
_PHOTO_CONFIDENCE = {
    "provider_name": "0.940",
    "provider_identifier": "0.930",
    "patient_reference": "0.920",
    "invoice_number": "0.930",
    "invoice_date": "0.920",
    "currency": "0.950",
    "description": "0.930",
    "code": "0.910",
    "service_date": "0.920",
    "quantity": "0.940",
    "unit_price": "0.930",
    "line_total": "0.940",
    "subtotal": "0.930",
    "tax_total": "0.920",
    "total": "0.940",
    "advance_paid": "0.920",
}


def _field(value: str, confidence: str, page: int, snippet: str) -> dict[str, Any]:
    return {
        "value": value,
        "confidence": confidence,
        "source": {"document_id": DOCUMENT_ID, "page": page, "snippet": snippet, "bbox": None},
    }


def _bill(
    invoice_number: str,
    invoice_date: str,
    lines: list[RawLine],
    subtotal: str,
    tax_total: str,
    total: str,
    advance_paid: str | None,
    *,
    confidence: dict[str, str],
    totals_page: int = 1,
) -> dict[str, Any]:
    c = confidence
    line_items = []
    for number, (desc, code, svc_date, qty, unit, line_total) in enumerate(lines, start=1):
        row = row_text(number, desc, code, qty, unit, line_total)
        line_items.append(
            {
                "line_number": number,
                "description": _field(desc, c["description"], 1, row),
                "code": _field(code, c["code"], 1, row),
                "service_date": _field(svc_date, c["service_date"], 1, row),
                "quantity": _field(qty, c["quantity"], 1, row),
                "unit_price": _field(unit, c["unit_price"], 1, row),
                "line_total": _field(line_total, c["line_total"], 1, row),
            }
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "document_id": DOCUMENT_ID,
        "document_type": "BILL",
        "provider_name": _field(PROVIDER, c["provider_name"], 1, PROVIDER),
        "provider_identifier": _field(
            PROVIDER_ID, c["provider_identifier"], 1, f"Registration: {PROVIDER_ID}"
        ),
        "patient_reference": _field(
            PATIENT_REF, c["patient_reference"], 1, f"Patient ref: {PATIENT_REF}"
        ),
        "invoice_number": _field(
            invoice_number, c["invoice_number"], 1, f"Invoice No: {invoice_number}"
        ),
        "invoice_date": _field(invoice_date, c["invoice_date"], 1, f"Invoice Date: {invoice_date}"),
        "currency": _field("INR", c["currency"], 1, "Currency: INR"),
        "line_items": line_items,
        "subtotal": _field(subtotal, c["subtotal"], totals_page, f"Subtotal: {subtotal}"),
        "tax_total": _field(tax_total, c["tax_total"], totals_page, f"Tax: {tax_total}"),
        "total": _field(total, c["total"], totals_page, f"Total: {total}"),
        "advance_paid": (
            NULL.copy()
            if advance_paid is None
            else _field(
                advance_paid, c["advance_paid"], totals_page, f"Advance paid: {advance_paid}"
            )
        ),
        "receipt": None,
    }


def _clean_bill() -> dict[str, Any]:
    lines: list[RawLine] = [
        ("Consultation", "CONS-01", "2026-10-30", "1", "1500.00", "1500.00"),
        ("Complete blood count (CBC)", "LAB-CBC", "2026-10-30", "1", "2000.00", "2000.00"),
        ("Room charges (general ward)", "ROOM-GW", "2026-10-30", "2", "5000.00", "10000.00"),
        ("Pharmacy", "PHARM", "2026-10-30", "1", "11500.00", "11500.00"),
    ]
    return _bill(
        "INV-SYN-1001",
        "2026-11-01",
        lines,
        "25000.00",
        "0.00",
        "25000.00",
        "4000.00",
        confidence=_CLEAN_CONFIDENCE,
        totals_page=2,
    )


def _photographed_bill() -> dict[str, Any]:
    lines: list[RawLine] = [
        ("X-ray chest", "XR-CH", "2026-11-02", "1", "1200.00", "1200.00"),
        ("Wound dressing", "DRESS", "2026-11-02", "2", "250.00", "500.00"),
        ("Consultation", "CONS-01", "2026-11-02", "1", "2000.00", "2000.00"),
    ]
    out = _bill(
        "INV-SYN-1002",
        "2026-11-02",
        lines,
        "3700.00",
        "0.00",
        "3700.00",
        None,
        confidence=_PHOTO_CONFIDENCE,
    )
    # OCR problems, as described in the module docstring.
    out["line_items"][0]["line_total"] = _field(
        "1700.00", "0.550", 1, row_text(1, "X-ray chest", "XR-CH", "1", "1200.00", "1700.00")
    )
    out["invoice_date"] = NULL.copy()
    out["provider_identifier"]["confidence"] = "0.700"
    return out


def _duplicate_rows() -> dict[str, Any]:
    lines: list[RawLine] = [
        ("Consultation", "CONS-01", "2026-11-02", "1", "1500.00", "1500.00"),
        ("Complete blood count (CBC)", "LAB-CBC", "2026-11-02", "1", "2000.00", "2000.00"),
        ("Complete blood count (CBC)", "LAB-CBC", "2026-11-02", "1", "2000.00", "2000.00"),
    ]
    return _bill(
        "INV-SYN-1003",
        "2026-11-03",
        lines,
        "5500.00",
        "0.00",
        "5500.00",
        None,
        confidence=_CLEAN_CONFIDENCE,
    )


def _arithmetic_mismatch() -> dict[str, Any]:
    lines: list[RawLine] = [
        ("Physiotherapy session", "PHYSIO", "2026-11-03", "2", "750.00", "1600.00"),
        ("Consultation", "CONS-01", "2026-11-03", "1", "1000.00", "1000.00"),
    ]
    return _bill(
        "INV-SYN-1004",
        "2026-11-04",
        lines,
        "2600.00",
        "0.00",
        "2700.00",
        None,
        confidence=_CLEAN_CONFIDENCE,
    )


def _upi_receipt_mismatch() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "document_id": DOCUMENT_ID,
        "document_type": "RECEIPT",
        "provider_name": NULL.copy(),
        "provider_identifier": NULL.copy(),
        "patient_reference": NULL.copy(),
        "invoice_number": NULL.copy(),
        "invoice_date": NULL.copy(),
        "currency": _field("INR", "0.970", 1, "Amount: 4500.00 INR"),
        "line_items": [],
        "subtotal": NULL.copy(),
        "tax_total": NULL.copy(),
        "total": NULL.copy(),
        "advance_paid": NULL.copy(),
        "receipt": {
            "amount": _field("4500.00", "0.960", 1, "Amount: 4500.00 INR"),
            "paid_on": _field("2026-10-29", "0.940", 1, "Paid on: 2026-10-29"),
            "transaction_reference": _field(
                "SYNUPI0000123", "0.930", 1, "Transaction ref: SYNUPI0000123"
            ),
            "payee_name": _field(
                "Synthetic Diagnostics Lab", "0.950", 1, "Paid to: Synthetic Diagnostics Lab"
            ),
            "payment_method": _field("UPI", "0.980", 1, "Method: UPI"),
        },
    }


MOCK_OUTPUTS: dict[str, dict[str, Any]] = {
    "clean_bill": _clean_bill(),
    "photographed_bill": _photographed_bill(),
    "duplicate_rows": _duplicate_rows(),
    "arithmetic_mismatch": _arithmetic_mismatch(),
    "upi_receipt_mismatch": _upi_receipt_mismatch(),
}
