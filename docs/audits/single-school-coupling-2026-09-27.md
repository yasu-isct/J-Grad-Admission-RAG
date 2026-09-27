# Single-school coupling audit

Baseline: GitHub main `2fd0786eabec260be999e1fc0e6cd5f12463e2c2` (PR #193), verified 2026-09-27.
The inspected local tree matched main. No production code or existing asset was changed by the
audit. Main Quality passed; local frozen semantic and grounded-RAG verifiers passed without model
or API calls. This is not a fresh semantic, browser or paid-provider evaluation.

## State and real assets

- #192 is closed; #193 merged. M1-M10 are closed; M13 has one completed research task and four
  paused implementation tasks (#187-#190). No open PR existed at audit time.
- Open Issues: #163, #177, #187-#191. #163 has Project status Todo; the others have no Project
  membership. There is no current implementation Ready assignment.
- Product: KB `7fa46e49b7949aec289746dd5ec3c839969a822874f76c26f9ad2b64bc00f5ce`,
  391 vectors, vectors `56508cad1dbf13c5e3258353676608cf4b6a174ac9c879983be9bdc8cd415df7`.
- Frozen baseline: KB `b24f85ecc0400a7d6e6e0fac94e078b2515a0c378b5bc35383efcd05977dedf6`,
  334 vectors, vectors `3aca31a683e2145fa9e24566abd3af40540bba8473b0d6a895e0cf6297f67f58`.
- Both explicit paths passed read-only inventory. PDF hash matched the release document. Initial
  sandbox access-denied results were resolved with authorized read access, not treated as absence.
- The product has 391 Facts / 26 entities / zero Facts missing physical pages / 64 unknown scopes;
  reference claims: 10 resolved, 5 ambiguous, 115 unresolved. Its existing quality gate passes.
- Reviewed page categories classify 244 Facts as core, 71 faculty-directory, 35 conditional,
  19 general-reference, and 22 appendix/irrelevant. These categories do not clean mixed Fact text.

## A: isolate or extend before enabling a second school

| Boundary | Code evidence | Consequence |
| --- | --- | --- |
| Identity | `schemas/document_identity.py`, `schemas/document_kb.py` | Institution/family/edition/intake already exist; organization/program/route coverage needs stable qualified identity rather than names and `parent_college` alone |
| Applicant target | `reasoning/applicant_profile.py`, `service/demo_requirements.py` | Target lacks institution/edition; document and profile degree enums need explicit mapping |
| Builder | `builder/kb_builder.py` | Fixed colleges/departments, 2027 text, pages 7/8/75 and Tsinghua program; `build_entities([])` actually emits 25 Science Tokyo entities |
| Parser/chunker | `builder/extractor.py`, `builder/chunker.py` | Reviewed title/banner heuristics are not a generic school contract; no common block/bbox/parser provenance interface |
| Configuration | `demo.py`, `demo_config/` | One bundle and `jgrad-demo-isct`; workspace provisioning owns one KB/index instead of referencing a common build registry |
| Specialized policies | `reasoning/application_materials.py`, `language_evaluation.py`, `language_score_conversion.py`, `program_language_condition.py` | Five fixed materials, date pairs, B schedule, fixed conversion constants and Tsinghua intake require explicit policy scope |
| Corpus ownership | `schemas/corpus_manifest.py`, `retrieval/local_index.py` | One PDF hash per manifest and one index per document; immutable output directory alone does not prevent duplicate builds in different workspaces |
| Retrieval | `service/app.py::_retrieve_natural_answer_evidence`, `_retrieved_evidence_matches_target` | Exact document selection precedes ranking, but empty metadata filters and soft department preferences precede post-filtering; page/route allowlists are missing here |
| API | `service/runtime.py`, `service/app.py` | Plans/scopes already plural; verified source PDF and intent catalog remain singletons |
| Catalog/UI | `service/demo_requirements.py::_college_catalog`, `service/static/app.html`, `app.js` | Target list inferred from rules; names act as IDs, both intakes reuse the same college list, and legacy form copy names Science Tokyo |
| Evaluation | `tests/conftest.py`, `evaluation/grounded_rag_evaluation.py` | One real-PDF fixture and an ISCT-specific release suite cannot establish new-school quality |

For the existing Information Engineering target, the current target predicate accepts 78 product
Facts, including five non-core Facts (two appendix, two faculty-directory, one general-reference).
This was a read-only predicate check, not a ranking run or proof of a generated wrong answer.
The catalog projects two intakes, six colleges and eighteen departments per intake; its construction
does not independently establish that every target/route/intake combination has reviewed coverage.

## B: keep explicit compatibility layers

- Science Tokyo identity/configuration, reviewed rules and parser behavior remain pinned to their
  exact source. Isolate rather than delete them or apply them to new schools.
- Preserve the single-school launcher and v1 API/data contracts until a versioned replacement is
  independently accepted. Do not silently reserialize or rebuild its KB.
- Keep 334-vector semantic, 391-vector product and older historical fixtures separate. Keep
  ISCT-specific suite IDs; add distinct new-school suites rather than relabel old observations.

## C: reuse without school-driven rewrites

Physical-page propagation, exact evidence/hash binding, applicability/precedence/interaction and
citation closure; embedding provider abstraction; NumPy/BM25/RRF; corpus document-qualified row
identities and active/historical selection; atomic manifest activation; immutable index publication;
privacy boundaries and in-memory cache; data-driven school dropdown scaffolding. Existing synthetic
multi-institution corpus tests are useful foundations, not evidence of real multi-school onboarding.

## Documentation corrections

The correct deployment path is `docs/deployment-architecture-v1.md`. Its pause status, Roadmap's
historical 298-Fact paragraph, two-task concurrency rule and unqualified deletion language, and
README's obsolete M2/M3/future-indexing text are corrected with this audit. The handoff now records
REL-01 completion and links the design continuation. M13 remains paused. Design and new source
acquisition do not change the shipped product's single-school claim.
