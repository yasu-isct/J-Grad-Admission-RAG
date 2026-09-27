# Experimental legacy parser adapter

This package implements parser pilot contract v0.1 by wrapping the unchanged
`builder.extractor.extract_pdf` function. It emits one coarse `legacy_page` block per requested
physical page. The Markdown and legacy `char_count`, `table_count`, and `scanned` values are copied
without reinterpretation. Physical page identity comes from `ExtractedPage.page`, never from a
Markdown heading.

The output is experimental comparison evidence only. It has no native bounding boxes, printed-page
labels, heading graph, table-cell structure, OCR, rule/entity metadata, or clause-level locator.
It does not call the KB builder, embeddings, indexes, models, or the network.

Create an ignored destination explicitly, then run against one entry in the reviewed source lock:

```powershell
New-Item -ItemType Directory -Force outputs/parser-pilot/ms02 | Out-Null
python -m jgrad_admission_rag.cli.parse_legacy_pilot `
  --source-lock docs/onboarding/utokyo-gsfs-complex-2027.sources.json `
  --source-id complex-guide-2027-revised `
  --pdf outputs/source-documents/utokyo-gsfs/2027/6063571d2ea0318d9af038340da0e8568cdabf18b03f788d41be59bf96e16fab.pdf `
  --output outputs/parser-pilot/ms02/complex-guide-2027-revised.json
```

Omit `--pages` for full-document context or pass a sorted unique list such as `--pages 28 40`.
Full and subset contexts have different run identities. The command refuses missing, mismatched,
or unreadable sources, invalid selections, a missing output parent, and every existing output path.
Local paths and elapsed time are reported outside the canonical document and its digest.
