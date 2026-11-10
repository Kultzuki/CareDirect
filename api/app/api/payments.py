"""Payer-authorized approved Sandbox payments. GET/verify never repeats a POST."""

from __future__ import annotations

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from app import payments
from app.api.cases import DB, ActorDep
from app.paypal_client import PayPalClient, get_paypal_client

router = APIRouter(prefix="/api/cases/{case_id}/payments")
Client = Annotated[PayPalClient, Depends(get_paypal_client)]


class ApprovalBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    state_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    amount: str = Field(max_length=30)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    purpose: str = Field(min_length=1, max_length=1000)
    confirmed: Literal[True]


class InvoiceBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    approval_id: uuid.UUID


class RecoveryBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    invoice_id: str = Field(pattern=r"^[A-Za-z0-9-]{1,64}$")


@router.get("")
def summary(case_id: uuid.UUID, db: DB, actor: ActorDep, client: Client):
    return payments.workspace(db, actor, case_id, client)


@router.post("/account-binding")
def binding(case_id: uuid.UUID, db: DB, actor: ActorDep, client: Client):
    payments.verify_binding(db, actor, case_id, client)
    return payments.workspace(db, actor, case_id, client)


@router.post("/approvals")
def approve(case_id: uuid.UUID, body: ApprovalBody, db: DB, actor: ActorDep, client: Client):
    payments.approve(db, actor, case_id, client, **body.model_dump())
    return payments.workspace(db, actor, case_id, client)


@router.post("/invoice")
def create(case_id: uuid.UUID, body: InvoiceBody, db: DB, actor: ActorDep, client: Client):
    payments.start_invoice(db, actor, case_id, client, body.approval_id)
    return payments.workspace(db, actor, case_id, client)


@router.post("/verify")
def verify(case_id: uuid.UUID, db: DB, actor: ActorDep, client: Client):
    payments.verify(db, actor, case_id, client)
    return payments.workspace(db, actor, case_id, client)


@router.post("/recover")
def recover(case_id: uuid.UUID, body: RecoveryBody, db: DB, actor: ActorDep, client: Client):
    payments.verify(db, actor, case_id, client, body.invoice_id)
    return payments.workspace(db, actor, case_id, client)
