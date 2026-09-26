# Adaptive local QA v1

M10-09 extends the lower-assurance M10-08 reference layer with model-owned retrieval planning. It
does not change the authority or validation semantics of M9 structured and grounded features.

## Runtime paths

An exact cache lookup occurs before provider work. On a miss, the online provider receives only the
user question and a non-identifying label for the selected school, degree, intake, college, and
department. It returns a strict internal planning object:

```json
{
  "draft_answer": "A user-readable general explanation",
  "needs_local_lookup": true,
  "search_queries": ["bounded query"]
}
```

The server validates only this structure and the hard query limits. It does not parse or approve
the natural-language wording. A general concept with `needs_local_lookup=false` returns the draft
as a `reference_only` answer after one provider call and performs no retrieval.

When local confirmation is requested, the server executes at most six unique queries of at most
500 characters each against only the selected local document. Existing BM25/BGE-M3 search, target
scope filtering, deduplication, and the 16-record/60,000-character bounds apply. A second and final
provider call receives the original question, target label, preliminary answer, explicit `hits` or
`no_hits` status, and bounded request-local `source:NNNN` records. It returns only `{ "answer":
"..." }`.

Zero retrieval hits do not suppress the final call. The final prompt requires an explicit statement
that the selected local material did not confirm the school-specific point and forbids converting
absence into acceptance, rejection, exemption, eligibility, or an admission guarantee.

## Privacy, failures, and cache

Neither call receives Applicant Profile values, credentials, filesystem paths, document/Fact IDs,
pages, hashes, or a complete PDF. There is no Web Search, tool call, upload, streaming, or outer
retry loop. SDK retry and timeout settings remain bounded per provider call.

Planning failure uses the existing deterministic local retrieval fallback and is not cached. Final
generation failure returns the preliminary answer, an explicit local retrieval status, and at most
three local excerpts; it is also not cached. Only successful `live` reference responses enter the
process-memory exact cache. An exact repeat reconstructs the public response without another model
call.

The public contract remains `kind=reference_answer`, `assurance=reference_only`, and
`needs_review=true`. It contains no claims, citations, evidence inventory, or reviewed disposition.

## Live acceptance

After all offline checks pass, a two-call HTTP acceptance requires a fresh explicit authorization
and the exact one-run guard:

```powershell
$env:JGRAD_ALLOW_DEEPSEEK_LIVE = "I AUTHORIZE 2 DEEPSEEK ADAPTIVE QA CALLS"
python -m jgrad_admission_rag.manual_adaptive_qa_evaluation `
  --pdf D:\J-Grad-Admission-RAG\outputs\real_pdf\isct_2027_4_2026_9_master.pdf `
  --workspace D:\J-Grad-Admission-RAG\outputs\m10-deepseek-live `
  --embedding-cache D:\J-Grad-Admission-RAG\outputs\model-cache `
  --model deepseek-flash `
  --synthetic-applicant-only
```

The harness fixes SDK retries to zero, permits at most two calls, submits one school-rule request,
then repeats the identical HTTP request and requires `cache_hit` with zero additional calls. It
reports only model, call count, bounded latency/status diagnostics, and cache outcome.

## M9 boundary

`POST /v1/grounded-answers`, reviewed rules/reports, Applicant Profile comparison, checklist,
official source views, citation closure, and the M9 release gate remain unchanged. No failure in the
reference layer can become an authoritative qualification decision.
