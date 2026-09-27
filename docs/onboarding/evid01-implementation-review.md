# EVID-01 implementation review evidence

Issue: [#202](https://github.com/yasu-isct/J-Grad-Admission-RAG/issues/202).
Authority: main `870dc28`, [Spec](reviewed-source-evidence-spec.md), ADR 0010.
Development reviewer: `evid01-development-agent`, kind **agent**, 2026-09-27.
**Independent design-main acceptance is pending.** The design reviewer must record the exact
accepted digest in the implementation PR; this document is the developer's evidence, not that acceptance.

## Checkpoint 1: contract and tests

Added the strict non-production evidence model, pure byte loader, canonical serializer,
read-only explicit-path PDF audit, exact-target/topic inspection and JSON/Markdown CLI.
Source text remains the unchanged eight-record design seed. Added explicit review pin and request.
The CLI is outside the frozen production retrieval CLI directory; no frozen manifest is modified.

Initial focused run: **96 passed**, comprising new evidence tests and MS02 adapter compatibility.
Tests exercise every target dimension (changed/missing/null), source-set/topic isolation,
required context and graph integrity, manual-only provenance, second-school portability,
byte/digest changes, PDF/hash/page errors, pure-load I/O isolation, fresh audit after file mutation,
and safe CLI errors without excerpt leakage. Full quality results are recorded at checkpoint 3.

| Identity | SHA-256 |
| --- | --- |
| Seed file bytes, revision 1 | `a5b2bc4e294c52b14c94946886e43928b46fc7f3ff7724ee08a3aa1067aa0b85` |
| Canonical bundle bytes, revision 1 | `558d8afc19880472e5e897d947d086e9c76974cee0c37fc8368f01ad48f074e3` |
| Source manifest bytes | `0065233d6179e25d1896de3252946fea82dc430c7101d872093948bef42625d7` |
| MS01 target contract bytes | `b86e7b61aa43cfc4705234a450fd8993e0c1ac86a6b730ca10d750b6427238e3` |

Remaining at checkpoint 1: real file audit, eight-record image comparison, three previews, CI and PR.

## Checkpoint 2: real audit and three previews

All three source hashes were independently recalculated from existing local bytes, with metadata-only
page-count checks. Each preview repeats this audit. Conditional intake FAQ was not read.
No source PDF, model or image was downloaded; no extraction/rendering or MinerU run was performed.

| Required source | Physical pages | SHA-256 |
| --- | ---: | --- |
| `gsfs-master-2027` | 22 | `a7a87219903c333b4fe687a3231a2346a195f7a8d8e7859b3f9e902147070026` |
| `complex-guide-2027-revised` | 45 | `6063571d2ea0318d9af038340da0e8568cdabf18b03f788d41be59bf96e16fab` |
| `complex-master-a-additional` | 1 | `3539ac01805f345592ec391c7b5c7ec4c9dbf21cee738f6ac5e3dfb27592e7ae` |

Existing PDF paths: `outputs/source-documents/utokyo-gsfs/2027/<sha256>.pdf`.
Existing images below are in that directory's `review/` subdirectory. All four complete page
images were visually inspected; parser text was not used as a correctness oracle.

| Existing image | SHA-256 |
| --- | --- |
| `gsfs-master-2027-p6.png` | `1bb210abad414166c7c2f8e8bb6024f01106f5b429db8e9fcfd7c563c1df0fea` |
| `complex-guide-2027-revised-p28.png` | `bdea9f6af94c61224f25dbb22ca3ca404b169d502426f1254b7fb381b75e5c75` |
| `complex-guide-2027-revised-p40.png` | `836734642f48e65d1542fc67082df9cd3fd487760b1220fdd4e066aec643ef9c` |
| `complex-master-a-additional-p1.png` | `665263f0f0deca737c4674d5532b9132e21912b2b58f534271e63ba1a0ace4c5` |

### Eight-record visual comparison

| Record / physical (printed) page | Compared fragments and outcome |
| --- | --- |
| E01 / common 6 (6) | Section 7 heading and two opening sentences agree: department-dependent score-sheet submission and consultation of the program guide. Cosmetic spacing/line joining only. No universal submission duty inferred. |
| E02 / department 28 (26) | Master's/general heading and first final-note bullet agree, including `提出する必要はない`. The page also discusses English questions during the oral exam; the separate Chinese note correctly avoids claiming all English assessment is exempt. |
| E03 / additional 1 | Program heading and English-score sending-method footer agree. Retained as a `cross_reference` to E01, with E01 linked to E02; not a fourth mandatory material row. |
| E04 / department 28 (26) | Master's/general heading and last final-note bullet agree: consult the checklist and submit documents listed in the guidelines. Consultation is distinct from submission of the checklist. |
| E05 / department 40 (38) | Top notice `このチェックシートの提出は不要` and master's/general checklist heading agree. The notice does not waive documents listed below. Both fragments preserved separately. |
| E06 / department 28 (26) | Master's/general context, work/study heading, and first paragraph agree. Employment **and** retaining that employment status at entry remain in the clause. No applicant evaluation. |
| E07 / department 28 (26) | Same headings and second paragraph agree: `入学手続きの際に` and employer consent remain separate from the application-stage plan. Explicit relation retains E06's employment context. |
| E08 / additional 1 | Seven separate fragments agree with the program heading, left upload group/header/note, material label, applicant-column header and conditional row. Right-hand submission-method group is empty; the neighboring `全員` cells are not copied. |

**Corrections: none identified; seed and gold files are unchanged.** The retained whitespace/line-wrap
policy does not permit punctuation/negation edits. This visual comparison is an Agent review,
not human review, a digital signature, an automated proof of transcription, or a completeness claim.

### Preview artifacts

Each JSON and Markdown preview includes the complete target/source-set, ordered separate Japanese
fragments, explicitly labeled Chinese notes, official physical-page links, review relations and
provenance, and historical/coverage limitations. All return `source_identity_verified` with an
explicit warning that independent transcription acceptance remains pending.

Ignored output directory: `outputs/evid01/`. [Copyable CLI invocations](evid01-operator-preview.md).

| File | SHA-256 |
| --- | --- |
| `english-score-sheets.json` | `2fcb3a4d9f9015ce1d60792da0a44023bc1b2b6512b5a45345cee64bdc9d0119` |
| `english-score-sheets.md` | `fab70a08f0ca00c97cf211f605ce0e542b8d4ee2ba961fa57329e0db89c201e0` |
| `checklist-submission.json` | `a335514500c805597baf8d295a8153604e604571cedbbcd26adc051ad6b2794e` |
| `checklist-submission.md` | `081331ed379d58b7ef2fb926b3b8488fe428ca29b4cd82775cb35cd5804808f7` |
| `work-study-plan.json` | `dbf087e68858adab7995dd566a6601a6cc39684f8ae9d1f6cfc51754194503af` |
| `work-study-plan.md` | `0807ee3b11bfeb380698690768fbc273f749c20b7b6f347bf40e1379660b5b37` |

The machine-readable `evidence-summary.json` in the same ignored directory records these exact
digests and source/image bindings (SHA-256
`15327791b7f6ffd01d863ddcc0ba21623e067a3dd5fc49393598c6a35ada5c6a`).
All six CLI outputs were also compared byte-for-byte with these saved UTF-8/LF artifacts in fresh
processes with imports of builder/parser/retrieval/generation/service, model and HTTP clients
explicitly blocked. No generated production artifact is committed.

Remaining at checkpoint 2: normal quality completion, one implementation PR and design-main handoff.

## Checkpoint 3: PR handoff

Final local quality: **1683 passed, 17 skipped, 283 deselected** in 41.07 seconds via
`pytest -m "not model_integration and not real_pdf"`. Private real-PDF suites were deselected to
avoid rebuilding existing KB/index assets; the three real evidence previews above were audited
separately. Synthetic temporary fixtures in the normal offline tests do not activate production
builds. Targeted evidence/MS02/semantic-gate rerun: **127 passed, 1 skipped**.
Ruff lint and format (241 Python files), source/test compilation, patch whitespace, frozen semantic
retrieval gate and grounded RAG release gate passed. Logs are in ignored `outputs/evid01/`.
The repository's unchanged normal Quality workflow will also run on the PR.

Ready for one implementation PR and handoff. Design main must independently inspect the four images
and eight records, check the three previews and fail-closed behavior, and record acceptance against
the exact seed file digest above. No merge or subsequent KB/rule/API/UI work is authorized here.

Protected tracked paths remain unchanged from main: production `config/`, `demo_config/`,
`schemas/`, `reasoning/`, `builder/`, `parsing/`, `retrieval/`, `service/`, existing `cli/`,
`pyproject.toml`, source manifest/MS01 contract, seed and MinerU gold/lock/report. The new runtime
path never accesses 334/391 assets or runtime pointers, so no model-weight or asset scan is needed.
Only synthetic temporary fixtures are constructed by tests; no production KB/index is built.
