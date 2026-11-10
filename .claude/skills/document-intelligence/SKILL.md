---
name: document-intelligence
description: Build or review CareDirect medical-bill and receipt upload, OCR/vision extraction, evidence linking, confidence handling and human correction workflows.
---

# Document Intelligence Skill

- Use synthetic or redacted medical bills only in development and demos.
- Validate uploaded file content signatures, MIME type, size, page count and SHA-256; store uploads privately.
- Extract only fields defined by the versioned Pydantic schema. Reject unknown keys.
- Keep source document ID, page number, text snippet/bounding box/crop and confidence per extracted field.
- Missing or unreadable values must be null/unknown. Never fill gaps from typical prices, medical assumptions or LLM inference.
- Preserve original extraction immutably. Human edits create a new revision with actor and timestamp.
- Low-confidence values cannot become payable without human review.
- AI may identify possible duplicates and inconsistencies, but must not decide medical necessity, fraud or malpractice.
- Evaluate extraction against a fixed synthetic fixture set. Report precision/recall or field accuracy only when actually measured.
