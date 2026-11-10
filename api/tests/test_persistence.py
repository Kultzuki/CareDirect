"""Persistence tests against real Postgres: NUMERIC round-trips, immutability,
append-only enforcement (ORM guard and database triggers), and audit coverage."""

from decimal import Decimal

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app import services as svc
from app.errors import ImmutableRecordError
from app.models import AuditEvent, Bill, BillLineItem, ExternalPayment, LedgerEntry
from app.seed import seed
from app.states import LedgerEntryType


@pytest.fixture
def demo(db):
    return seed(db)


def test_money_columns_are_numeric_14_2(db, demo):
    rows = db.execute(
        text(
            "SELECT table_name, column_name, numeric_precision, numeric_scale "
            "FROM information_schema.columns WHERE table_schema='public' "
            "AND data_type = 'numeric' "
            "AND column_name NOT IN ('quantity','extraction_confidence')"
        )
    ).all()
    # 8 money columns from 0001; 9 from 0002 (approval snapshot 5, invoice ref 2,
    # payment ref 1, provider corrected amount 1); 5 from0006 (link amount1,
    # immutable payer decision original/previous/recognized/adjustment4).
    assert len(rows) == 24  # Includes internal family contributions and allocation source amounts.
    for table, col, precision, scale in rows:
        assert (precision, scale) == (14, 2), f"{table}.{col}"


def test_decimal_round_trip_is_exact(db, demo):
    db.expire_all()
    totals = db.scalars(select(BillLineItem.line_total)).all()
    assert all(isinstance(t, Decimal) for t in totals)
    assert sum(totals) == Decimal("25000.00")
    assert db.scalar(text("SELECT sum(line_total)::text FROM bill_line_items")) == "25000.00"


def test_seed_persists_expected_buckets(db, demo):
    db.expire_all()
    b = svc.get_buckets(db, svc.get_case(db, demo.id))
    assert (b.bill_total, b.payable_now, b.queried, b.already_paid) == (
        Decimal("25000.00"),
        Decimal("19000.00"),
        Decimal("2000.00"),
        Decimal("4000.00"),
    )
    assert b.consistent


def test_seed_is_idempotent(db, demo):
    again = seed(db)
    assert again.id == demo.id
    assert len(svc.case_lines(db, demo.id)) == 6


def test_query_keeps_charge_on_bill_and_in_ledger(db, demo):
    lines = {li.line_number: li for li in svc.case_lines(db, demo.id)}
    queried = lines[4]
    assert queried.line_total == Decimal("2000.00")  # still on the bill, unchanged
    types = [e.entry_type for e in svc.case_ledger(db, demo.id) if e.line_item_id == queried.id]
    assert types == [LedgerEntryType.BILL_CHARGE, LedgerEntryType.QUERY_HOLD]


def test_every_ledger_entry_has_an_audit_event(db, demo):
    ledger_ids = {e.id for e in svc.case_ledger(db, demo.id)}
    audited = {
        a.ledger_entry_id for a in svc.case_audit(db, demo.id) if a.ledger_entry_id is not None
    }
    assert ledger_ids and ledger_ids == audited


def test_every_status_change_is_audited(db, demo):
    events = [a.event_type for a in svc.case_audit(db, demo.id)]
    assert events.count("LINE_ITEM_QUERIED") == 1
    assert events.count("LINE_ITEM_ACCEPTED") == 5
    assert "EXTERNAL_PAYMENT_MATCHED" in events
    assert "FLAG_CREATED" in events
    assert "CASE_STATUS_CHANGED" in events


# ---- ORM guard


def test_orm_blocks_changing_extracted_line_values(db, demo):
    li = svc.case_lines(db, demo.id)[0]
    li.line_total = Decimal("1.00")
    with pytest.raises(ImmutableRecordError):
        db.flush()
    db.rollback()


def test_orm_blocks_changing_bill(db, demo):
    bill = db.scalar(select(Bill).where(Bill.case_id == demo.id))
    bill.printed_total = Decimal("1.00")
    with pytest.raises(ImmutableRecordError):
        db.flush()
    db.rollback()


def test_orm_blocks_changing_payment_evidence(db, demo):
    p = db.scalar(select(ExternalPayment).where(ExternalPayment.case_id == demo.id))
    p.amount = Decimal("1.00")
    with pytest.raises(ImmutableRecordError):
        db.flush()
    db.rollback()


def test_orm_blocks_ledger_update_and_delete(db, demo):
    entry = svc.case_ledger(db, demo.id)[0]
    entry.amount = Decimal("1.00")
    with pytest.raises(ImmutableRecordError):
        db.flush()
    db.rollback()
    entry = svc.case_ledger(db, demo.id)[0]
    db.delete(entry)
    with pytest.raises(ImmutableRecordError):
        db.flush()
    db.rollback()


# ---- database triggers (bypass the ORM with raw SQL)


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE ledger_entries SET amount = 1",
        "DELETE FROM ledger_entries",
        "UPDATE audit_events SET event_type = 'X'",
        "DELETE FROM audit_events",
        "UPDATE bills SET printed_total = 1",
        "DELETE FROM bill_line_items",
        "UPDATE bill_line_items SET line_total = 1",
        "UPDATE bill_line_items SET description_raw = 'edited'",
        "UPDATE external_payments SET amount = 1",
        "DELETE FROM external_payments",
    ],
)
def test_database_triggers_block_mutation(db, demo, sql):
    nested = db.begin_nested()
    with pytest.raises(DBAPIError, match="immutable|append-only"):
        db.execute(text(sql))
    nested.rollback()


def test_database_allows_review_status_update(db, demo):
    # Review status is the only mutable part of a line item.
    nested = db.begin_nested()
    db.execute(text("UPDATE bill_line_items SET status_note = 'ok' WHERE line_number = 1"))
    nested.rollback()


def test_check_constraint_rejects_non_positive_ledger_amount(db, demo):
    nested = db.begin_nested()
    with pytest.raises(DBAPIError):
        db.execute(
            text(
                "INSERT INTO ledger_entries (id, case_id, entry_type, amount, currency, reason, "
                "actor_label, created_at) VALUES (gen_random_uuid(), :c, 'BILL_CHARGE', 0, 'INR', "
                "'x', 'x', now())"
            ),
            {"c": demo.id},
        )
    nested.rollback()


def test_check_constraint_rejects_unknown_enum_value(db, demo):
    nested = db.begin_nested()
    with pytest.raises(DBAPIError):
        db.execute(text("UPDATE bill_line_items SET status = 'PAID' WHERE line_number = 1"))
    nested.rollback()


def test_audit_rows_survive(db, demo):
    count = db.scalar(select(text("count(*)")).select_from(AuditEvent))
    assert count > 0
    assert db.scalar(select(text("count(*)")).select_from(LedgerEntry)) == 8
