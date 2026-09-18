# Reviewed Report Evidence v1

`ReviewedReportEvidenceBundle` is the exact-evidence boundary between one audited corpus selection
and the later applicant-report pipeline. APP-03A says which reviewed rules belong to a document;
APP-03B opens that exact selected KB and materializes only the official Facts named by those rules.

```text
audited CorpusManifest + revalidated one-document selection
  + unique server-owned ReviewedReportPlan + reviewed PageScopeManifest
  -> category-gated exact Fact bindings -> ReviewedReportEvidenceBundle
```

This is not ranked retrieval. A reviewed rule already names an exact `(document_id, fact_id)`, page
set, source-KB hash, source-PDF hash, and authoritative Fact-text hash. The materializer therefore
does not invent a query, rank, score, channel, or `EvidencePack` to satisfy a downstream API.

## Preparation Boundary

`prepare_reviewed_report_evidence` receives an explicit server-owned corpus root, current manifest,
reviewed version policy, saved selection result, and a finite tuple of injected reviewed plans. It:

1. detaches and revalidates every input;
2. runs `audit_corpus_manifest` over every registered artifact;
3. revalidates the saved selection against that exact audited manifest and policy;
4. requires exactly one selected ready document;
5. matches exactly one plan by complete `DocumentIdentity` equality;
6. requires one detached page-scope manifest with the same complete identity/PDF hash;
7. resolves only the selected entry's validated corpus-relative KB path beneath the audited root;
8. requires canonical current KB bytes, identity, quality, registration hash, and plan hash to agree;
9. resolves every binding to an exact Fact and verifies pages, UTF-8 text hash, accepted M4 scope,
   and reviewed page category before constructing any evidence record.

The path loader requires an independently supplied authoritative page count, and the report service
derives that count from the already audited, PDF-hash-bound KB page extent. Evidence preparation
repeats the extent comparison, so lowering `page_count` while deleting the same terminal manifest
page cannot create a self-consistent but truncated scope.

Ordinary rules and language policies may bind only `core_admission` pages. A program-language
binding may bind only `conditional_program` pages whose declared route exactly matches the policy
entry. `faculty_directory`, `general_reference`, and `irrelevant_or_appendix` are retained in the
unchanged KB but are never accepted as report-rule evidence. The Applicant Report layer then removes
conditional records unless the profile matches the exact route and intake, so an ordinary profile's
returned `evidence_bundle` remains core-only.

The manifest records a page's reviewed primary purpose, not a claim that every Fact on that page is
semantically pure. Pages 34, 41, and 61 contain mixed core/faculty Facts, and page 28 starts with a
low-frequency consultation condition before the faculty directory. The gate cannot split those
Facts; safety still depends on human review of the exact Fact binding. This change intentionally
does not re-chunk source text or renumber Facts.

Zero or duplicate plan matches fail separately. Stale selection, unsafe paths, failed audit, KB
drift, missing or duplicate Facts, and page/text/scope mismatch also fail closed. No partial bundle
is returned when a later binding fails.

The current ISCT plan and page-scope fixture bind the same fixed PDF identity while leaving all 391
Fact IDs, official text, and `source_pages` unchanged. The scope manifest is an independent reviewed
configuration artifact; it does not rewrite Fact `scope_type`, parser output, or the historical
semantic baseline.

## Bundle Contract

Version 1 is immutable, forbids unknown fields, and uses `schema_version="1.0"`. Each
`ReviewedReportEvidenceRecord` contains the selected document ID, Fact ID, exact official text,
canonical pages, section path, Fact type, scope fields, and sorted rule IDs that directly bind the
Fact. Several rules referencing one Fact produce one record with deduplicated rule IDs.

The bundle contains the plan ID, complete selected `DocumentIdentity`, existing source-KB hash,
canonical records ordered by `(document_id, fact_id)`, and recomputed record, rule, and source-page
counts. The complete identity already carries the PDF hash; no duplicate bundle-level PDF hash,
bundle hash, signature, retrieval metadata, applicant data, query, generated prose, or local path is
added.

Canonical bytes are available for deterministic in-memory handoff and tests. There is intentionally
no path loader: official text is sensitive derived material and should not become a new persisted
artifact by default. Public failures expose only an allowlisted diagnostic code and one generic
message, never the corpus root, registered path, hash, secret, or official text.

## Limits

APP-03B handles one selected document only. It does not run `ApplicantProfile`, applicability,
precedence, interaction analysis, `ReasoningTrace`, `CitedAnswer`, or Markdown rendering. It does not
modify corpus files, build indexes, load an embedding model, search, or expose an HTTP/CLI route.
APP-03C adapts this direct evidence into the existing reasoning pipeline through a typed
`DirectOfficialEvidence` boundary, without fabricating retrieval metadata or duplicating predicate
and scope logic.

Service configuration has no unscoped-report fallback: report-plan and page-scope paths must be
configured together and identity sets must match exactly. Omitting both keeps query/build-only mode
available. The library materializer also requires the reviewed manifest, so direct callers cannot
bypass the category gate.
