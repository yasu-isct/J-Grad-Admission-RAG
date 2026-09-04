# Real PDF Regression Fixture

`reasoning_trace_scenarios_v1.json` is the compact reviewed RSN-06 scenario table. It
maps synthetic graph cases and the real `fact:00063` page 7 characterization to expected
typed steps without storing applicant values, official prose, or final answers.

`cited_answer_scenarios_v1.json` records the compact RSN-07 presentation matrix: the three
real `fact:00063` page 7 rule findings plus synthetic override, interaction, incomplete-review,
missing-evidence, attached-role, and multi-page citation cases. It contains no applicant values,
official prose, model output, or final eligibility verdict.

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
