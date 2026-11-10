---
name: e2e-testing
description: Test the complete CareDirect synthetic demo journey in the browser and API, including uploads, extraction review, provider responses, human approval, PayPal Sandbox confirmation and audit export.
---

# CareDirect E2E Testing Skill

- Use only synthetic fixture documents and Sandbox accounts.
- Reset to a known seed state before the demo test.
- Cover family payer, relative uploader and provider response roles separately.
- Verify exact three-bucket totals and all state transitions.
- Test expired/invalid upload and provider tokens, file-type spoofing, low-confidence fields and duplicate uploads.
- Test provider Accept/Correct/Explain; require payer review before finalising a change.
- Test no PayPal invoice/order can be created without an explicit approval record.
- Simulate checkout return, then confirm the backend GETs PayPal state. Never infer paid from redirect.
- Test invalid webhook signature, duplicate event ID and out-of-order event handling.
- Label deterministic replay and seeded rows. Never portray them as live Sandbox events.
- Report actual test results; do not claim complete coverage without test output.
