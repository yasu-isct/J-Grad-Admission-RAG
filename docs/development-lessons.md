# Development lessons and design gates

Recorded 2026-09-27 under [ARCH-01 #191](https://github.com/yasu-isct/J-Grad-Admission-RAG/issues/191).
Derived from the user-provided retrospective, `J-Grad-Admission-RAG - M1-M8 开发复盘与经验教训.md`,
including its later M10 and duplicate-index addenda. This is a maintained synthesis, not a copy of
the private notebook. Historical counts and unresolved questions in that notebook are not current
repository status. Main and current GitHub evidence remain authoritative.

## Product and authority

- Define the user-visible outcome, assurance level, non-goals, failure experience, model-call
  ceiling, latency expectations, and cache semantics before selecting components.
- Deliver one narrow end-to-end school/program/edition journey before general infrastructure or
  broad rule coverage. Prioritize dates, ordinary eligibility, language, and materials; classify
  faculty directories, publicity and rare routes before detailed modeling.
- Physical page provenance must remain structured throughout extraction, chunks, Facts, retrieval
  and citations. Never reconstruct authority by guessing page numbers from Markdown headings.
- Reviewed rules and official evidence own authoritative conclusions. The M10 assistant remains
  lower-assurance `reference_only`; do not attempt to prove arbitrary generated prose semantically
  closed with growing word lists, sentence templates, or a second language-understanding system.
- Missing coverage remains unknown, not rejection, acceptance, exemption or eligibility.

## Diagnose mechanisms before adding exceptions

Classify each failure as source coverage, retrieval recall, applicability scope, identity,
generation/planning, provider/orchestration, interaction, or the test expectation itself. A
counterexample is diagnostic evidence, not automatically a new business rule. A mechanism fix
should cover the original failure and at least two meaningfully different examples where useful.
Stable aliases belong in reviewed centralized configuration, not answer templates.

Reviewers assess the promised product guarantee, actual user effect, cost and scalability.
Do not demand unlimited counterexample fixes outside that guarantee. Changes to model calls,
dependencies, authority or data flow return to architecture review.

## Asset ownership and costs

Ingestion owns PDF-to-KB/index construction. User features and acceptance tools consume registered
assets read-only. Milestone/workspace names are not index identities. Before work, inventory the
explicit PDF, KB, model revision, manifest and vector identities and intended consumers.

Every executable Issue includes an artifact-impact statement covering parsing, KB construction,
embedding/index construction, model/PDF downloads, large copies, external calls, expected resource
cost and rollback. Existing user authorization is carried forward: do not ask again for an
already authorized action within that scope. Download authorization does not authorize deleting,
replacing, migrating or publishing existing artifacts, paid resources, or a new production copy.

Access denied is not absence. Resolve read access or report the actual limitation; never select an
empty workspace as a workaround that triggers reconstruction. Matching identities can identify
duplicate candidates, but deletion requires a reference audit, dry run and explicit approval.

## Evidence and workflow

- Freeze an inspectable interaction prototype before a major UI integration. Technical data
  isolation does not require separate user journeys. The M15 split entry passed its implementation
  Spec but missed the user's single-page school selector and common report action; design-main
  owns that mismatch. Actual desktop/mobile layout, navigation and optional-report behavior are
  acceptance criteria alongside API correctness. Preserve historical acceptance while recording
  the superseding product decision; do not blame development for faithfully following the Spec.

- One executable Issue, one bounded current-task context and one observable state transition.
  Reuse one development agent/chat per milestone; a new Issue does not require a new chat. Refresh
  the compact task packet after each acceptance. Start a replacement chat with a checkpoint when
  scope changes substantially or context confusion repeatedly loses constraints. Release only one
  dependency-ready implementation at a time; use independent review for high-risk changes.
- Each Spec contains background, product goal, scope/non-goals, invariants, compatibility and asset
  impact, dependencies, acceptance, focused tests, real-data evidence, failure and rollback.
- Fake embeddings prove assembly, not semantic quality. Reuse pinned real model/index assets for
  semantic acceptance; paid calls require authorization separate from ordinary offline checks.
- Test UI transitions (selection, editing, filters, keyboard operation, resubmission and refresh),
  not only element presence. Screenshots support behavior assertions rather than replace them.
- Hashes protect source, build and evidence boundaries; do not require wholesale UI hash churn for
  cosmetic edits. Run tests proportional to risk, not unrelated full suites by default.
- On milestone closeout, reconcile README, architecture, roadmap, checkpoints, Issues and Project
  state. Preserve historical evidence but label it as historical.

## M14 execution lessons

- Keep one cumulative budget across retries, directories and agent handoffs; a fresh ledger never
  resets consumption. Bind each scorecard to one explicit execution generation.
- Validate the supervisor before long real runs, including verbose stdout/stderr and child cleanup.
  Process existence and a live monitoring loop are not evidence of parsing progress. Diagnose
  harness faults before attributing timeouts to parser performance.
- Keep one milestone chat, with compact checkpoints between harness validation, real evaluation
  and final scoring. Do not repeatedly rerun complete experiments while fixing report plumbing.
- Configured providers, cache occupancy and zero Python-hook network attempts do not establish
  measured providers, cumulative download bytes or OS-wide network isolation.
- A failed experiment can close honestly without parser authorization. See the
  [rejected pilot report](onboarding/mineru-4.0.7-pilot-report.md); evidence gaps remain explicit.

## Reconciled since the notebook

ART-01 / PR #184 made normal Demo startup reuse-only and added explicit-path inventory. M10-09 /
PR #181 is complete. The 334-vector `b24f85ec...` frozen semantic baseline and 391-vector
`7fa46e49...` product runtime are now documented as distinct intentional roles. Canonical registry
design and any physical deduplication remain separate work; neither has been completed by these
documentation changes. See the [release boundary](releases/single-school-portfolio-v1.md).
