# Document Identity v1

`DocumentIdentity` is reviewed input for the offline builder. It answers two different questions:

- `document_family_id`: which continuing publication series this document belongs to.
- `document_id` plus `edition_id`: which exact reviewed edition is being built.

The identity also records the institution, controlled degree-level coverage, one or more intake
terms, official title and public HTTPS source URL, and the exact source PDF SHA-256. Publication and
revision dates are optional because an official page may not publish them.

## Trust Boundary

Identity fields are never inferred from the local filename, title text, dates found inside the PDF,
or the URL basename. Two universities may publish `guideline.pdf`, and one family may publish a
corrected edition without changing that filename. A reviewer creates or approves the identity JSON;
the builder then hashes the supplied PDF and stops before extraction when it does not match.

IDs are stable, path-independent tokens. Degree levels use `master`, `doctoral`, or
`professional_degree`; mixed documents list each applicable value. Intake terms are explicit
year/month pairs and are sorted canonically.

## Example

```json
{
  "schema_version": "1.0",
  "document_id": "isct_2027_4_2026_9_master",
  "document_family_id": "isct-master-admission-guidelines",
  "edition_id": "2027-april-2026-september",
  "institution_id": "isct",
  "institution_name": "Institute of Science Tokyo",
  "degree_levels": ["master"],
  "intake_terms": [
    {"year": 2026, "month": 9},
    {"year": 2027, "month": 4}
  ],
  "official_title": "2027 April / 2026 September Master's Program Admission Guidelines",
  "official_source_url": "https://admissions.isct.ac.jp/ja/013/graduate/guideline",
  "source_pdf_sha256": "57fdb935ffd2f6aa759f2c77f58b45826977225239fc1576d932b891ea50c735",
  "publication_date": null,
  "revision_date": null
}
```

## KB And Migration

KB schema `0.6` embeds the complete identity under `manifest.identity`. Serialized manifests no
longer duplicate `document_id` or `pdf_sha256`; compatibility properties keep existing index and
evidence code bound to the same values.

Migration from KB `0.5` is explicit through `migrate_document_kb_v05` or
`migrate_document_kb_v05_bytes`. The caller must supply a reviewed identity whose `document_id` and
PDF hash exactly match the legacy manifest. Migration preserves entities, facts, retrieval units,
diagnostics, and all non-identity manifest fields. Older schemas, missing fields, or mismatches fail
closed and require human review.
