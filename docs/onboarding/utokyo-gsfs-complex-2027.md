# University of Tokyo GSFS Complexity Science and Engineering: source lock

Recorded 2026-09-27 under [#191](https://github.com/yasu-isct/J-Grad-Admission-RAG/issues/191) and
[#177](https://github.com/yasu-isct/J-Grad-Admission-RAG/issues/177). This is source acquisition and
design evidence, not an enabled product target, reviewed rulebook or parser A/B result.

## User decision and bounded working slice

The user selected 東京大学 / 新領域創成科学研究科 / 複雑理工学専攻, authorized downloads, and
explicitly confirmed the fixed slice: 2027 admission cycle, master's ordinary general selection,
examination schedule A, April 2027 intake. This is the agreed first regression/onboarding target.
Production activation still requires the source-set contract, reviewed coverage and acceptance;
the target decision alone does not enable a new school in the current Demo.

This is a fixed historical examination sample, not an open application window. Doctoral,
special oral, fusion-program and October-intake content remains available as negative/conditional
scope samples, not promised support. Do not map citizenship directly to a selection route.

## Official discovery and acquisition

- [Graduate-school official entry](https://www.k.u-tokyo.ac.jp/exam/info/index.html).
- [Department official entry](https://www.k.u-tokyo.ac.jp/complex/html/examinee/examinee.html).
- Exact URLs, UTC retrieval timestamps, sizes, physical page counts, HTTP Last-Modified and
  SHA-256 values are in [the acquisition manifest](utokyo-gsfs-complex-2027.sources.json).
- Four original PDFs total 12,006,807 bytes (about 11.45 MiB). Local originals are Git-ignored at
  `outputs/source-documents/utokyo-gsfs/2027/<sha256>.pdf`. Existing exact bytes are reusable;
  new source versions get new hashes, never overwrite these files. No PDF binary is committed.
- Source acquisition permission is established. No MinerU/model package has been downloaded or
  installed in this step: first pin the actual release, backend/model provenance and bounded
  resource plan under #177. Permission need not be requested again for downloads within scope.
- No KB, embedding, index, corpus activation, paid request, cloud resource or old-asset migration
  was performed. Reading PDF metadata/text and rendering audit pages is not the production build.

| Source ID | Role | Physical pages | SHA-256 prefix |
| --- | --- | ---: | --- |
| gsfs-master-2027 | Graduate-school common master's guideline | 22 | a7a87219903c |
| complex-guide-2027-revised | Department guide, revised file linked by the department | 45 | 6063571d2ea0 |
| complex-master-a-additional | Department additional submission table, master's A | 1 | 3539ac01805f |
| gsfs-overseas-intake-a-20260305 | Conditional foreign-applicant intake flowchart and FAQ | 15 | ed10dd87c87f |

HTTP Last-Modified is recorded only as transport metadata. Official publication/revision dates
must not be inferred from it. The generic-named additional-material PDF is frozen by hash and its
internal 2027/A/master heading, not by filename alone. The common guideline and program guide
are complementary, not successive versions of the same document family.

## Initial source observations and priority

Manual image checks covered the common cover and physical pp.4,6; department cover and physical
pp.28,40; the additional-material table p.1; and intake flowchart p.1. Text inspection also located
department schedule/route sections. This is a bounded source review, not complete rule acceptance.

The common guideline's p.4 table distinguishes programs and routes: Complexity Science and
Engineering has no master's B recruitment. Its p.6 English-score provisions defer requirement
selection to each department. Department physical p.28 (printed p.26) states that master's general
selection does not require TOEFL/TOEIC score sheets. That specificity must not become a universal
English exemption or copy Science Tokyo's submission rule.

The additional-material table p.1 contains common and conditional rows; its English-score footer
refers readers to the common guideline. Record that reference without interpreting it as a new
submission requirement. Department physical p.40 (printed p.38) says the checklist itself need
not be submitted. Referring to a checklist and requiring its submission are different propositions.

These are source-grounded design examples, not activated applicant advice.

## Candidate pilot pages and acceptance cases

The first prototype should expose useful evidence from core pages before parsing all low-value
material into reviewed rules. The following sample is frozen in the M14 manual gold before #177 execution:

| Source | Physical pages | Evaluation purpose |
| --- | --- | --- |
| Common guideline | 2-6 | Intake, eligibility, route tables, cross-page submission tables, department-conditioned language rules |
| Department guide | 27-30 | Mixed schedule/degree/route context; master's general versus special oral and doctoral boundaries |
| Department guide | 40 | Checklist layout; physical versus printed page mapping |
| Department guide | 3-4 | Reviewed research/publicity and faculty/research content; preserve distinguishing context without treating it as admission rules |
| Additional-material table | 1 | Landscape table, merged cells and conditional addressee relationships |
| Intake flowchart | 1,5 | Reviewed diagram branches and referenced qualifications/notes; conditional intake context |

Do not fabricate an OCR comparison from text PDFs. Determine whether any selected source page is
actually scanned; otherwise mark OCR benefit untested. No whole-PDF page-purpose map is complete.
The later [M14 gold](mineru-4.0.7-pilot-gold-v1.json) freezes bounded checks for these 15 pages,
including reviewed research/publicity labels for department pp.3-4; it is not exhaustive coverage.
Keep the complete originals for physical-page reference; never renumber a sample
PDF as if it were the source. Missing web/form details remain explicit coverage limits.

## Current handoff

MS-01's source-set contract and MS-02's baseline adapter remain accepted. #177 closed in PR #200
as an accepted [failed-experiment / reject decision](mineru-4.0.7-pilot-report.md). The 15-page,
41-unit gold remains frozen; no candidate is approved for production or fallback use. Design main
has completed the [evidence-gap assessment](gsfs-evidence-gaps-and-next-slice.md) and releases
only [EVID-01 #202](reviewed-source-evidence-spec.md) for three materials topics. No parser rerun
is authorized, and M13 remains paused.
