"""Verified notifications only trigger authoritative GET reconciliation.

No payload amounts, statuses, links or payee fields are treated as payment proof.
Receipts contain only identifiers, a hash and bounded outcomes, never raw bodies.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app import payments
from app import services as svc
from app.errors import DomainError
from app.models import CareCase, PaymentOperation, PayPalWebhookEvent
from app.paypal_client import resource_id

SUPPORTED = frozenset(
    "INVOICING.INVOICE." + x
    for x in ("CREATED", "SENT", "CANCELLED", "PAID", "REFUNDED", "UPDATED")
)


def process(db, event, client):
    """Called only after signature verification. Return (sanitized outcome, retry)."""
    event_id, event_type = event.get("id"), event.get("event_type")
    if not isinstance(event_id, str) or not re.fullmatch(r"[A-Za-z0-9-]{1,100}", event_id):
        raise DomainError("Invalid webhook event identifier.")
    if not isinstance(event_type, str) or len(event_type) > 80:
        raise DomainError("Invalid webhook event type.")
    resource = event.get("resource")
    invoice_id = resource.get("id") if isinstance(resource, dict) else None
    if event_type in SUPPORTED:
        invoice_id = resource_id(invoice_id)
    else:
        invoice_id = None
    digest = hashlib.sha256(
        json.dumps(event, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    db.execute(
        insert(PayPalWebhookEvent)
        .values(
            event_id=event_id,
            event_type=event_type,
            invoice_id=invoice_id,
            payload_sha256=digest,
            outcome="RECEIVED",
            attempts=0,
        )
        .on_conflict_do_nothing(index_elements=["event_id"])
    )
    db.commit()
    row = db.scalar(
        select(PayPalWebhookEvent)
        .where(PayPalWebhookEvent.event_id == event_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if row.payload_sha256 != digest:
        db.rollback()
        raise DomainError("Webhook event identifier conflicts with its recorded receipt.")
    if row.outcome in ("PROCESSED", "IGNORED", "REVIEW_REQUIRED"):
        db.commit()
        return "duplicate", False
    now = datetime.now(UTC)
    if row.outcome == "PROCESSING" and row.updated_at > now - timedelta(seconds=120):
        db.commit()
        return "processing", True
    op = (
        db.scalar(select(PaymentOperation).where(PaymentOperation.paypal_invoice_id == invoice_id))
        if invoice_id
        else None
    )
    if event_type not in SUPPORTED or op is None:
        # A known event can precede local invoice persistence. Keep it retryable, so
        # a racing send callback is not permanently discarded as an unknown invoice.
        row.outcome = "RETRY" if event_type in SUPPORTED else "IGNORED"
        row.error_code = "INVOICE_NOT_YET_KNOWN" if event_type in SUPPORTED else None
        row.attempts += 1
        db.commit()
        return row.outcome.lower(), row.outcome == "RETRY"
    case_id = op.case_id
    row.outcome, row.error_code = "PROCESSING", None
    row.attempts += 1
    db.commit()  # durable reservation; a crash is reclaimed after the bounded lease
    case = db.get(CareCase, case_id)
    actor = svc.Actor(user=case.payer, label="system:paypal-webhook")
    try:
        payments.verify(db, actor, case_id, client)
        op = payments._op(db, case_id)
        retry = bool(
            op.error_code
            and op.error_code not in ("RESOURCE_MISMATCH", *payments.MANUAL_RECONCILIATION_CODES)
        )
        outcome = "RETRY" if retry else "REVIEW_REQUIRED" if op.error_code else "PROCESSED"
        error = op.error_code
    except Exception:
        db.rollback()
        outcome, error, retry = "RETRY", "REFETCH_UNAVAILABLE", True
    row = db.scalar(
        select(PayPalWebhookEvent)
        .where(PayPalWebhookEvent.event_id == event_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    row.outcome, row.error_code = outcome, error
    row.processed_at = None if retry else datetime.now(UTC)
    db.commit()
    return outcome.lower(), retry
