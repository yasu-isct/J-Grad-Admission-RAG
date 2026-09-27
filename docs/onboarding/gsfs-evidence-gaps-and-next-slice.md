# GSFS: what we can reuse and what we must review

Design assessment after M14 / PR #200, 2026-09-27. Target remains the fixed 2027 master's
ordinary general selection A / April 2027 slice. These are historical admissions documents,
not a current application window. No new parser run, download, KB or index is needed for this assessment.

## Plain-language outcome

We have the official documents and useful extracted text, but not an approved new-school knowledge
base. Reading a sentence correctly does not establish a complete application checklist or applicant
eligibility. The rejected MinerU experiment provides observations, not an approved replacement.

The first useful slice is three material-related questions: English score sheets, whether the
checklist itself is submitted, and the work/study plan for applicants retaining employment.
An operator must be able to inspect the exact Japanese clauses, their context and their source
pages before any applicant-facing rule is built. This is a small review tool, not a new chatbot.

## Evidence gaps

The M14 scorecard is an observational sample, not exhaustive coverage. “Text reusable” below means
candidate source text for review, not production acceptance. Page numbers are physical PDF pages.

| Area | Existing evidence | Remaining problem | Treatment |
| --- | --- | --- | --- |
| Application/test dates | Common p4, department p27; legacy D03-D05 preserves schedules | Flash scrambles date tokens; mixed ordinary/special/doctoral routes | Keep legacy as review aid; review dates and route binding separately before activation |
| Eligibility | Common pp2-3 preserves selected clauses/notes C03-C05 | Gold does not cover every eligibility path, review deadline or required evidence | No eligibility conclusion or complete coverage claim in the first slice |
| English score sheets | Common p6, department p28 (printed 26), additional p1 footer | Generic sending instructions can be mistaken for a universal submission duty | First slice: explicit three-source relationship, negation and selected route |
| Checklist | Department p28 refers to checklist; p40 (printed 38) says it need not be submitted | Legacy omits notice and upper items; repeating extraction cannot certify absence | First slice: page-image-reviewed notice and context, with honest manual provenance |
| Employment-related materials | Department p28 distinguishes study/work plan and enrollment-stage consent; additional p1 has conditional row | Table header ownership and application versus enrollment timing can be lost | First slice: preserve row/header and both separate clauses, no profile inference |
| General material list | Common pp5-6, department p40, additional p1 | C13 cross-page ownership unresolved; partial overlap is not a complete list | Explicitly outside first-slice completeness; later reviewed material inventory |
| Conditional intake | Flowchart p1 and notes p5 | Text nodes alone do not preserve yes/no edges (F01/F02) | Keep unknown; no diagram-driven eligibility/intake decision |
| Faculty/research pages | Department pp3-4 | Column order problems and irrelevant content for admission rules | Excluded from the materials slice; no parser repair needed now |

The selected four page images (common p6, department pp28/40, additional p1) were visually
rechecked against the locked local sources. The [seed](gsfs-material-evidence-seed-v1.json)
records eight small excerpts, context and review provenance. No MinerU result is imported into it.
Whitespace/line wrapping may be normalized as stated; negation, punctuation and conditions remain.

## Existing implementation to reuse

- `schemas/document_identity.py`: exact source SHA-256, document family/edition, safe IDs and
  canonical serialization conventions. Source-set/target dimensions follow MS-01; a document
  can cover several targets and must not be relabeled as a single-route source.
- `parsing/contracts.py` / accepted MS02 reports: honest physical-page provenance and optional
  coarse extraction references. Preserve v0.1 unchanged; manual text is not a parser block.
- `schemas/document_kb.py`: future Facts/RetrievalUnits remain the destination. Evidence excerpts
  are pre-KB input, not a competing knowledge base or search index.
- `reasoning/reviewed_report_evidence.py`: existing downstream checks bind reviewed output to
  document/KB/Fact/text/pages. Do not bypass these with source-only references in public reports.
- Existing corpus selection, BM25/vector retrieval and citations remain the later delivery path.
  No new ranking service, vector store, rule engine or LLM extraction is needed for the first task.

Two concrete blockers make direct reuse unsafe today: `builder/kb_builder.py` invokes ISCT entity/
scope conventions, and `reasoning/application_materials.py` fixes exactly five material entries,
codes and exception behavior. Do not insert GSFS into these defaults or broaden them casually.

## Dependency order

1. **Complete in PR #204:** [EVID-01](reviewed-source-evidence-spec.md), the generic source auditor
   and three-topic operator preview. Eight reviewed records contain 23 distinct source fragments.
2. **Only Ready implementation after design merge:** [BUILD-01 #206](build-profile-isolation-spec.md),
   isolate the legacy ISCT profile and guard an explicit entry; preserve current behavior/bytes.
3. After profile acceptance, release a precise reviewed-import/KB-lineage Spec under
   [ADR 0011](../decisions/0011-explicit-build-profiles-and-reviewed-lineage.md). A new identity
   creates a distinct candidate; it never updates an existing index in place.
4. Then design reusable material/condition rules and multi-source report binding, without the
   five-item ISCT assumption; only after that expose the bounded existing API/UI journey.

Orders 3-4 remain planning boundaries, not released Issues. Do not pre-release a long framework queue. The milestone objective is the bounded materials
journey; date/eligibility completeness, additional schools, MinerU reruns and M13 are excluded.

## What the first task will visibly demonstrate

An operator chooses the exact target and one of three topic IDs. The preview shows the Japanese
clauses, Chinese review notes clearly labeled as commentary, source titles, official links and
physical pages. It shows the English-score exemption with its master's/general context; distinguishes
reading the checklist from submitting it; and displays employment conditions without claiming that
the tool has assessed an applicant. Wrong target, changed PDF, incomplete selected evidence or an
unknown topic produces an explicit refusal/coverage gap, never a guessed answer.

No product behavior decision is needed from the user now: this first task does not activate new
advice, change authoritative rules, migrate existing schemas/assets or incur external costs.
