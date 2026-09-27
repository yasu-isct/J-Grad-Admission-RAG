# Single-school Portfolio Release v1

Status verified: 2026-09-27. This document describes the current local product after M10,
ART-01, and the M13 deployment-architecture investigation. It is a truthful release boundary, not
a claim of public hosting or complete Japanese graduate-admission coverage.

## Supported product slice

The product currently supports one hash-verified official document:

- institution: Institute of Science Tokyo;
- degree level: master's program;
- edition: April 2027 / September 2026 admission;
- official PDF SHA-256: `57fdb935ffd2f6aa759f2c77f58b45826977225239fc1576d932b891ea50c735`;
- interface: a Chinese-language local Demo served on loopback;
- persistence: no account, upload, Applicant Profile persistence, or telemetry.

An applicant can select the reviewed target, inspect dates and materials, enter a bounded profile,
receive reviewed comparisons and a preparation checklist, open Japanese official evidence and PDF
pages, and optionally ask Chinese or Japanese questions. The application does not decide final
eligibility, document receipt/completeness, acceptance, or admission.

## Concrete data flow and authority

```text
exact official PDF
  -> page-traceable ScopedFacts in DocumentKnowledgeBase
  -> immutable local BGE-M3 index plus BM25/RRF retrieval
  -> target- and document-bounded EvidencePack
  -> reviewed rules plus in-memory Applicant Profile
  -> authoritative structured comparison/report with server-owned citations
  -> optional lower-assurance reference-only natural-language answer
```

Official facts, reviewed scope/rules, and server-owned citations are authoritative inside the
shipped review coverage. Retrieval proposes evidence but does not decide rule applicability.
DeepSeek, when explicitly configured, may plan a bounded lookup and word a natural answer; it does
not own eligibility decisions, Fact IDs, citations, or Applicant Profile evaluation. A local miss
must remain visible as unconfirmed coverage.

## Local runtime boundary

Normal startup is reuse-only. It audits an existing PDF, runtime, corpus, policy, reviewed configs,
KB, index, and embedding identity without writing, parsing, building, downloading, or calling a
generation provider. Initial provisioning requires `--allow-runtime-build`; replacement requires
`--rebuild` and the existing owned-runtime safety checks.

The service is intentionally bound to `127.0.0.1`. M13 public deployment is deferred after its
architecture/cost study; no public URL or production SLA exists.

## Artifact roles

| Role | KB/index identity | Count | Meaning |
| --- | --- | ---: | --- |
| Historical | schema 0.5, KB prefix `8223fb91...` | 298 | Earlier semantic history; not the current product or release gate |
| Frozen semantic release baseline | schema 0.6, KB `b24f85ec...`, vector `3aca31a6...` | 334 | Fixed retrieval benchmark and regression identity |
| Current product runtime | schema 0.6, KB `7fa46e49...`, vector `56508cad...` | 391 | Local Demo knowledge/index identity |

The 334- and 391-vector artifacts use the same official PDF and pinned BGE-M3 revision but contain
different KB projections and hashes. They are not interchangeable. The additional product rows
include later pages and conditional/reference material; more vectors do not by themselves imply
better retrieval. Page scope and selected target must prevent faculty directories, special routes,
or general references from competing with ordinary admission rules indiscriminately.

ART-01's explicit-path inventory may identify byte-compatible duplicate candidates, but it does not
authorize deletion, migration, linking, or replacement of any runtime.

## Golden user journeys

| Journey | Expected visible behavior | Authority |
| --- | --- | --- |
| Select target | Choose Science Tokyo, master's, supported intake, college and department; unsupported combinations fail closed | Reviewed product configuration |
| Review dates/materials | Show normalized application dates and common materials, not only a raw excerpt | Reviewed structured presentation |
| Compare Applicant Profile | Display applicable, not-applicable, unknown, and missing-information outcomes plus a session checklist | Reviewed rules over in-memory inputs |
| Inspect official basis | Open exact Japanese evidence, physical page number, local verified PDF route, and official source page | Official evidence; browser controls exact PDF jump behavior |
| Ask a school-specific question | Perform bounded local BM25/BGE-M3 retrieval and word a natural answer with an explicit local-coverage status | `reference_only`, lower assurance than the structured report |
| Handle miss/repeat | A partial or zero hit says the local guideline did not confirm the point; an identical successful repeat may use the bounded process-local cache with zero new provider calls | Transparent limitation/cost behavior |

Existing browser screenshots are
[`m9-grounded-rag-1440.png`](../assets/m9-grounded-rag-1440.png) and
[`m9-grounded-rag-390.png`](../assets/m9-grounded-rag-390.png). Automated anchors include the UX
browser tests, applicant-report API/UI tests, source-PDF route tests, grounded-answer tests, and
adaptive natural-language/cache tests.

## Known limitations and accepted debt

- Only one official guideline edition and its reviewed target/rule subset are shipped.
- JLPT, J.TEST, and some score-conversion authority remain incomplete under
  [GitHub issue #163](https://github.com/yasu-isct/J-Grad-Admission-RAG/issues/163).
- The complete 391-row product KB contains conditional programs, reference pages, and some layout
  noise; scope selection is therefore part of correctness, not merely ranking optimization.
- Exact in-PDF `#page=N` navigation depends on the browser's PDF viewer; the UI also shows the page
  number and official source link.
- The natural-language cache is process-local and disappears on restart.
- Online generation requires an explicitly configured server-side key and remains optional.
- No public authentication, abuse protection, public hosting, or availability guarantee is shipped.
- The current parser remains PyMuPDF/pdfplumber based. MinerU 4.x is only a future A/B pilot under
  [issue #177](https://github.com/yasu-isct/J-Grad-Admission-RAG/issues/177) and is not assumed to
  be superior.

## Closeout evidence

- [ART-01 PR #184](https://github.com/yasu-isct/J-Grad-Admission-RAG/pull/184): GitHub Quality
  passed; the real 391-vector runtime returned `/app` HTTP 200 and retained the same 12-file
  fingerprint before and after reuse-only startup.
- [DEPLOY-01 PR #186](https://github.com/yasu-isct/J-Grad-Admission-RAG/pull/186): GitHub Quality
  passed; read-only startup reported 391 payloads/vectors, with no model download, index rebuild,
  DeepSeek call, cloud resource, or asset upload.
- This closeout changes documentation only. It performs no PDF parsing, KB/index build, embedding or
  generation call, model download, artifact migration, or deletion.

## Next boundary

Public deployment remains paused at
[#187](https://github.com/yasu-isct/J-Grad-Admission-RAG/issues/187). Future cross-milestone design
starts from the long-lived design-agent charter in
[#191](https://github.com/yasu-isct/J-Grad-Admission-RAG/issues/191). Multi-school work must first
audit single-school coupling and then execute the bounded MinerU/Tokyo University parser experiment
in [#177](https://github.com/yasu-isct/J-Grad-Admission-RAG/issues/177) before choosing a parser or
onboarding multiple graduate schools.
