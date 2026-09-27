# EVID-01 operator preview

This optional local command implements [#202](https://github.com/yasu-isct/J-Grad-Admission-RAG/issues/202)
under the [main Spec](reviewed-source-evidence-spec.md). It inspects three historical topics;
it does not decide applicant eligibility or produce a complete material checklist.

## Inputs and authority

The unchanged `gsfs-material-evidence-seed-v1.json` is the only excerpt bundle. No generated
production copy is created. `evid01-review-pin.json` explicitly pins its **exact file bytes**,
bundle ID and revision independently of its self-described review status. This pin is a
repository pin independently accepted in [PR #204](https://github.com/yasu-isct/J-Grad-Admission-RAG/pull/204#issuecomment-5856769317).
Acceptance covers this exact revision for operator inspection, not production advice. Reviewer
kind remains `agent`; the seed retains its original design-review metadata.

Do not compute a new pin from a changed input as part of a query. A change to text, context,
relations, notes, target or source-set requires a new reviewed revision and repository review.
Even a whitespace-only file edit fails the old byte pin. Canonical UTF-8/LF sorted serialization
is also available through `canonical_bundle_bytes`; its separate digest is included in previews.
No Unicode, punctuation, number or negation normalization is performed by the tool.

`load_evidence_bytes` is pure: all JSON arrives as bytes. Source manifest and MS01 contract
references are verified by their exact-byte digests; their `file` labels are never opened.
Target fields and source-set membership/hash/page bindings are checked. The audit reads only
explicit paths for required core sources, hashes the bytes and uses PyMuPDF metadata on those
same bytes for page counts. It never extracts text, renders pages, scans directories, downloads,
calls models, builds KB/index assets or invokes the closed parser pilot.

`inspect_evidence` reloads and audits on every call. It accepts no cached audit success token.
Output describes the bytes just audited, not a permanent claim about mutable filesystem paths.
The conditional source remains in the manifest but is outside the audit and topic coverage.
The implementation has no school-name or topic-name branches. A tiny second-school synthetic
fixture with its own IDs and topic exercises the same loader, audit and preview.

## Three copyable commands

Run from the repository root with the existing environment; no dependency installation is needed.
The following PowerShell setup binds the three already-acquired core files explicitly. Replace
only the local paths if the existing files are stored elsewhere. Do not add a PDF download step.

```powershell
$env:PYTHONUTF8 = '1'
$evidenceArgs = @(
  '--bundle', 'docs/onboarding/gsfs-material-evidence-seed-v1.json',
  '--manifest', 'docs/onboarding/utokyo-gsfs-complex-2027.sources.json',
  '--target-contract', 'docs/onboarding/gsfs-source-set-contract-v0.1.examples.json',
  '--trust', 'docs/onboarding/evid01-review-pin.json',
  '--request', 'docs/onboarding/evid01-request.json',
  '--source', 'gsfs-master-2027=outputs/source-documents/utokyo-gsfs/2027/a7a87219903c333b4fe687a3231a2346a195f7a8d8e7859b3f9e902147070026.pdf',
  '--source', 'complex-guide-2027-revised=outputs/source-documents/utokyo-gsfs/2027/6063571d2ea0318d9af038340da0e8568cdabf18b03f788d41be59bf96e16fab.pdf',
  '--source', 'complex-master-a-additional=outputs/source-documents/utokyo-gsfs/2027/3539ac01805f345592ec391c7b5c7ec4c9dbf21cee738f6ac5e3dfb27592e7ae.pdf'
)
```

English score sheets:

```powershell
.venv/Scripts/python.exe -m jgrad_admission_rag.reviewed_evidence_cli @evidenceArgs --topic english-score-sheets
```

Submission of the checklist itself:

```powershell
.venv/Scripts/python.exe -m jgrad_admission_rag.reviewed_evidence_cli @evidenceArgs --topic checklist-submission
```

Work/study plan and separate enrollment-stage consent:

```powershell
.venv/Scripts/python.exe -m jgrad_admission_rag.reviewed_evidence_cli @evidenceArgs --topic work-study-plan
```

Add `--format json` for deterministic JSON. Default Markdown can be read directly in the console.
The CLI creates no output files: explicitly redirect stdout to save a preview. The acceptance run
saved JSON and Markdown to ignored `outputs/evid01/`; see [the review record](evid01-implementation-review.md).

All errors exit 2, with an error-only JSON object on stderr and empty stdout. Codes distinguish
`not_covered`, `digest_mismatch`, `revision_mismatch`, `binding_digest_mismatch`, `invalid_schema`,
`page_out_of_range`, `missing_source`, `source_hash_mismatch`, `invalid_pdf`, `page_count_mismatch`,
`invalid_request` and `input_unavailable`. Unknown topics, incomplete/mismatched targets and source
revisions never fall back to another target. No partial verified content is emitted on failure.

## Interpretation and rollback

`source_identity_verified` means file identity and review-pin integrity passed. It does **not**
prove a transcription correct. The Japanese fragments remain separate; Chinese review notes are
explicitly labeled commentary. Relations are review data, not an inferred precedence rule.
Physical page links come from the pinned manifest URL; printed page labels are distinct.
Precise bounding boxes/highlights remain unknown; parser locators, bbox, Fact IDs and KB hashes
remain null. The preview exposes full review provenance and historical/coverage limitations.

Rollback removes only these additive tooling, tests, pin/request and review-document files.
No production configuration, rule/schema, dependency, runtime pointer or 334/391 asset is changed.
M13 remains paused. Further KB/rule/API/UI work requires its own authorization and Spec.
