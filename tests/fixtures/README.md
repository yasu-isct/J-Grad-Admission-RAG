# Real PDF Regression Fixture

`reasoning_trace_scenarios_v1.json` is the compact reviewed RSN-06 scenario table. It
maps synthetic graph cases and the real `fact:00063` page 7 characterization to expected
typed steps without storing applicant values, official prose, or final answers.

`cited_answer_scenarios_v1.json` records the compact RSN-07 presentation matrix: the three
real `fact:00063` page 7 rule findings plus synthetic override, interaction, incomplete-review,
missing-evidence, attached-role, and multi-page citation cases. It contains no applicant values,
official prose, model output, or final eligibility verdict.

`reviewed_report_plan_isct_master_v1.json` and its `rule01a`, `rule01b`, `rule02a`, `rule02b`, `rule03a`, `rule03b`, `rule04a`, `rule04b`, `rule04c`, and `rule04d`
extensions are server-owned reviewed plans for the same exact document. The RULE-02 plans add
eligibility paths 9 through 11 and the shared individual-review process while preserving the
earlier plan coverage. RULE-03A adds the shared main application window, registration start, and
paper-material arrival deadline without treating dispatch or online steps as application completion.
RULE-04A adds the reviewed common English-test types, date and score-report requirements, plus the
department-scoped mathematics written-exam exception.
RULE-04B adds the 19 department/program score-submission paths. RULE-04C adds the reviewed appendix
3 formula, threshold, and complete four-group iBT/PBT conversion table. RULE-04D adds the 15
department-level English allocations explicitly published by the guideline without calculating an
applicant's earned score.
`rule04b_browser_acceptance_v1.json` records the RULE-04B browser acceptance matrix at 1440 px and
390 px. It covers an ordinary department, the physics exam-day path, the civil-engineering mail and
A-schedule paths, the mathematics exception, and unknown or conflicting scope input. Each record
keeps the displayed rule status, official fact/page citation, limitation, and overflow observation;
it contains no applicant identity data.
`rule04c_browser_acceptance_v1.json` records the RULE-04C appendix-conversion browser audit for six
fixed scenarios at 1440 px and 390 px, including exact result shape, p.16 evidence, limitations, and
horizontal-overflow checks.
`rule04d_browser_acceptance_v1.json` records seven department-allocation and non-published paths at
the same two widths, including exact Fact/page evidence, maximum points, limitations, and overflow.
They contain reviewed configuration and hashes, but no applicant data, query, retrieval score,
generated report, or overall eligibility state. The current plans are explicitly bound to the
canonical schema-0.6 391-Fact KB; historical M4/RET-09 schema-0.5 fixtures remain unchanged.
`retrieval_queries_rule04b_v1.json` binds the current 391-Fact KB while the signed
`retrieval_queries_v1.json` remains the frozen RET-08 semantic-gate baseline.

The real-PDF regression test uses the public Institute of Science Tokyo master's admission
guideline recorded in `real_pdf_manifest.json`.
Its `identity_file` points to the reviewed `DocumentIdentity` fixture used by every real build; the
identity hash must exactly match the manifest and local PDF.

The PDF itself is not committed because the university has not granted this repository an explicit
redistribution license. The test never downloads files and therefore remains offline and
deterministic.

## Local Setup

Download the document from the manifest's `source_page_url`, verify that its SHA-256 matches the
manifest, and make it available using one of these options:

1. Set `JGRAD_REAL_PDF` to the absolute or repository-relative PDF path.
2. Place it at `tests/fixtures/private/<filename>`.
3. Place it at `outputs/real_pdf/<filename>`.

The third option matches the artifact produced during the initial repository review.

Run only the real-PDF regression:

```powershell
.\.venv\Scripts\python.exe -m pytest -m real_pdf -v
```

When the PDF is absent, these tests skip with setup instructions. When a file is present but its
hash differs, the tests fail rather than silently testing a different guideline.

## Updating The Baseline

Change the expected counts only when an intentional builder change explains the difference:

1. Confirm the PDF hash and provenance have not changed.
2. Inspect representative extracted pages and the generated `document_kb.json`.
3. Record the reason for every expected-count change in the pull request.
4. Run the real-PDF test, the regular test suite, Ruff, and `compileall`.

Do not loosen an assertion solely to make an unexplained regression pass.
