"""Private payer dashboard/export and signature-verified public notification route."""

import json
import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from starlette.concurrency import run_in_threadpool

from app import evidence, webhooks
from app.api.cases import DB, ActorDep
from app.errors import DomainError
from app.paypal_client import PayPalClient, PayPalError, get_paypal_client

router = APIRouter(prefix="/api")
Client = Annotated[PayPalClient, Depends(get_paypal_client)]
PRIVATE = {
    "Cache-Control": "no-store",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
}


@router.get("/dashboard")
def dashboard(db: DB, actor: ActorDep):
    return JSONResponse(evidence.dashboard(db, actor), headers=PRIVATE)


@router.get("/cases/{case_id}/evidence")
def export(case_id: uuid.UUID, db: DB, actor: ActorDep, format: Literal["json", "html"] = "json"):
    payload = evidence.pack(db, actor, case_id)
    headers = {
        **PRIVATE,
        "Content-Disposition": f'attachment; filename="caredirect-evidence-{case_id}.{format}"',
        "Content-Security-Policy": (
            "default-src 'none'; style-src 'unsafe-inline'; sandbox; "
            "base-uri 'none'; form-action 'none'"
        ),
    }
    if format == "html":
        return HTMLResponse(evidence.as_html(payload), headers=headers)
    return JSONResponse(payload, headers=headers)


@router.post("/paypal/webhooks")
async def receive(request: Request, db: DB, client: Client):
    # Bound the streamed body before allocation/JSON decoding (Content-Length alone
    # does not bound chunked uploads). Reject malformed/ambiguous JSON before postback.
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 256 * 1024:
            raise HTTPException(413, "Webhook body exceeds the limit.")

    def unique(pairs):
        out = {}
        for k, v in pairs:
            if k in out:
                raise ValueError("duplicate JSON key")
            out[k] = v
        return out

    try:
        event = json.loads(
            bytes(body),
            object_pairs_hook=unique,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError()),
        )
        if not isinstance(event, dict):
            raise ValueError()
    except (ValueError, RecursionError):
        raise HTTPException(400, "Invalid webhook body.") from None

    def verified_process():
        # Keep blocking HTTPX/SQLAlchemy work off the ASGI event loop. The session
        # is used sequentially by this single worker, never by concurrent tasks.
        try:
            verified = client.verify_webhook(request.headers, bytes(body))
        except (PayPalError, DomainError):
            return JSONResponse(
                {"status": "verification_unavailable"}, status_code=503, headers=PRIVATE
            )
        if not verified:
            return JSONResponse({"status": "invalid_signature"}, status_code=400, headers=PRIVATE)
        outcome, retry = webhooks.process(db, event, client)
        return JSONResponse({"status": outcome}, status_code=503 if retry else 200, headers=PRIVATE)

    return await run_in_threadpool(verified_process)
