"""Readable, native USD synthetic documents and explicitly recorded extraction output.

No OCR is performed. Markers select replay output; document text remains readable.
Historical INR quality fixtures and their evaluation denominator stay unchanged.
"""

from copy import deepcopy
from io import BytesIO

from PIL import Image, ImageDraw, ImageFont, PngImagePlugin

from app.extraction.mock_outputs import _CLEAN_CONFIDENCE, _bill, _upi_receipt_mismatch
from app.extraction.synthetic import SyntheticFixture, _render_pdf

PROVIDER = "Synthetic Harbor Clinic"
LINES = [
    ("Outpatient consultation", "CONS-01", "2026-11-09", "1", "210.00", "210.00"),
    ("Laboratory panel", "LAB-01", "2026-11-09", "1", "20.00", "20.00"),
    ("Laboratory panel", "LAB-01", "2026-11-09", "1", "20.00", "20.00"),
]


def _usd_bill(kind):
    data = _bill(
        "SYN-USD-250",
        "2026-11-09",
        LINES,
        "250.00",
        "0.00",
        "250.00",
        "40.00",
        confidence=_CLEAN_CONFIDENCE,
    )
    data["document_type"] = kind
    data["provider_name"].update(value=PROVIDER)
    data["provider_name"]["source"]["snippet"] = PROVIDER
    data["currency"].update(value="USD")
    data["currency"]["source"]["snippet"] = "Currency: USD (native synthetic amounts)"
    # Deliberate low-confidence provider identifier invites an explicit human review.
    if kind == "BILL":
        data["provider_identifier"]["confidence"] = "0.700"
        data["provider_identifier"]["value"] = "SYN-REG-OOO1"
    return data


def _usd_receipt():
    data = deepcopy(_upi_receipt_mismatch())
    data["currency"].update(value="USD")
    data["currency"]["source"]["snippet"] = "Currency: USD"
    for key, value, snippet in [
        ("amount", "40.00", "Amount: USD 40.00"),
        ("paid_on", "2026-11-09", "Paid on: 2026-11-09"),
        ("transaction_reference", "SYN-USD-PRIOR-40", "Reference: SYN-USD-PRIOR-40"),
        ("payee_name", PROVIDER, f"Paid to: {PROVIDER}"),
        ("payment_method", "OTHER", "Method: OTHER (synthetic prior payment evidence)"),
    ]:
        data["receipt"][key].update(value=value)
        data["receipt"][key]["source"]["snippet"] = snippet
    return data


RECORDED_OUTPUTS = {
    "usd_bill": _usd_bill("BILL"),
    "usd_estimate": _usd_bill("ESTIMATE"),
    "usd_receipt": _usd_receipt(),
}
SAMPLE_NAMES = ("usd_bill.pdf", "usd_estimate.pdf", "usd_receipt.pdf", "usd_bill.png")


def sample_lines(name):
    title = (
        "Prior payment receipt"
        if name == "usd_receipt"
        else ("Itemized estimate" if name == "usd_estimate" else "Itemized outpatient bill")
    )
    heading = [
        title,
        PROVIDER,
        "Registration: SYN-REG-0001",
        "Patient ref: PT-SYN-001",
        "Date: 2026-11-09",
        "Currency: USD (native synthetic amounts)",
        "",
    ]
    if name == "usd_receipt":
        return heading + [
            "Amount: USD 40.00",
            "Paid on: 2026-11-09",
            "Reference: SYN-USD-PRIOR-40",
            f"Paid to: {PROVIDER}",
            "Method: OTHER (synthetic prior payment evidence)",
            "",
            "Evidence for review only. This is not a verified bank transaction.",
        ]
    return heading + [
        "Invoice No: SYN-USD-250",
        "Description                         Qty    Rate USD    Amount USD",
        "Outpatient consultation              1      210.00        210.00",
        "Laboratory panel / LAB-01            1       20.00         20.00",
        "Laboratory panel / LAB-01            1       20.00         20.00",
        "",
        "Subtotal: USD 250.00",
        "Tax: USD 0.00",
        "Total: USD 250.00",
        "Advance paid: USD 40.00",
        "",
        "Repeated row is a question for review, not a medical conclusion.",
        "A proposed USD 20 credit needs provider response and payer acceptance.",
        "Then: net USD 230 - prior USD 40 = USD 190 to collect.",
        "",
        "Extraction uses a labelled recorded replay, not real OCR.",
    ]


def sample_bytes(filename):
    if filename not in SAMPLE_NAMES:
        raise ValueError("unknown sample")
    name, extension = filename.rsplit(".", 1)
    lines = sample_lines(name)
    if extension == "pdf":
        fixture = SyntheticFixture(
            name, RECORDED_OUTPUTS[name]["document_type"], "application/pdf", [lines], {}
        )
        return _render_pdf(fixture), "application/pdf"
    image = Image.new("RGB", (1600, 1800), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=27)
    draw.multiline_text(
        (65, 60),
        "SYNTHETIC DEMO - NOT A REAL BILL\n\n" + "\n".join(lines),
        fill="#12303a",
        font=font,
        spacing=16,
    )
    metadata = PngImagePlugin.PngInfo()
    metadata.add_text("Comment", f"CAREDIRECT-SYNTHETIC-FIXTURE:{name}")
    output = BytesIO()
    image.save(output, format="PNG", pnginfo=metadata)
    return output.getvalue(), "image/png"
