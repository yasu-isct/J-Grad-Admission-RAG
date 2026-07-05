# Migration From flie-extract

This repository starts by reusing selected stable modules from `yasu-isct/flie-extract`.

## Migrated

- PDF extraction with PyMuPDF and pdfplumber.
- Markdown chunking.
- Category routing.
- Lightweight document index.
- Reference resolution.
- Recursive retrieval primitives.

## Not Migrated

- Profile-first pipeline orchestration.
- Applicant profile filtering.
- Local report renderer.
- Stage-specific extraction/report scripts.
- Existing embedding retriever implementation.

Those pieces remain valuable in `flie-extract`, but this repository needs a cleaner RAG-first
boundary where full-document extraction is separated from user-specific retrieval.

## First Target

```text
admission.pdf -> outputs/kb/<document>/document_kb.json
```

The next layer will add vector index construction and query-time retrieval over `retrieval_units`.
