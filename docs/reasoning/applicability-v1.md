# Applicability v1

`ApplicabilityRule` v1 is a small, human-reviewed executable annotation over official evidence.
`evaluate_applicability` compares that annotation with explicit applicant facts and returns one of:

- `confirmed`: this annotated rule's applicability conditions are satisfied;
- `not_applicable`: a known predicate or explicit scope does not match;
- `needs_information`: required profile, scope, or official evidence is unavailable.

These statuses do not mean eligible, admitted, rejected, or likely to be accepted.

## Pipeline Position

```text
ApplicantProfile + QueryIntent + EvidencePack + reviewed ApplicabilityRule
  -> source/evidence/scope validation
  -> typed three-valued predicates
  -> ApplicabilityDecision
  -> later RSN-04/05 rule ordering and conflict handling
```

APP-03C adds a second typed entry for evidence that a reviewed plan already binds exactly:

```text
ApplicantProfile + QueryIntent + DirectOfficialEvidence + reviewed ApplicabilityRule
  -> the same typed three-valued predicate/scope core
```

`DirectOfficialEvidence` contains only exact document/KB/PDF identity and primary Fact/page
references. It has no retrieval request, query, rank, score, channel, row, or embedding metadata.
The existing `EvidencePack` entry retains its original query-consistency and primary/attached
binding behavior; both entries delegate to the same implementation of predicate truth tables,
missing-profile fields, scope diagnostics, and decision status.

Retrieval has already selected official evidence. RSN-03 does not rank evidence, parse Japanese
rules, call a model, or generate prose. A reviewer must author each rule after inspecting the bound
Fact locally.

## Rule Contract

Every immutable rule contains:

- a stable rule ID and exact schema version;
- `all` or `any` aggregation;
- allowlisted typed profile predicates;
- global or explicit college/department/program scope;
- one or more document, KB, PDF, Fact, page, and authoritative Fact-text-hash bindings;
- a short reviewed paraphrase.

Supported operations are exact equality/inequality, collection containment, numeric minimum or
maximum, date boundaries, and explicit empty/non-empty checks. Field and operator combinations are
closed and validated. There is no expression language or arbitrary dotted traversal.
For `all`, obviously impossible combinations such as a minimum above a maximum, equality plus the
same inequality, or `contains` plus `is_empty` are rejected at rule load time. The same predicates
remain valid alternatives under `any`.

Canonical rule and decision JSON is UTF-8, sorted, single-line JSON ending in LF. File loaders
accept only regular, non-symlinked files and expose generic errors that do not repeat supplied data
or filesystem paths.

## Evaluation

Each public input is serialized and fully revalidated before use, including Pydantic objects made
with `model_construct` or unsafe copies. Query text must match the EvidencePack request exactly.
Each rule binding must match the pack's validated runtime document, KB, and PDF identity; the bound
evidence must be present as primary or attached evidence with exact Fact ID, pages, and compatible
scope. `EvidencePack.text` is a derived embedding projection, so online evaluation never treats its
hash as the authoritative Fact-text hash. The real-KB regression independently verifies
`authoritative_fact_text_sha256` against `ScopedFact.text`; the validated source-KB hash then closes
the runtime trust chain without changing the frozen retrieval contract.

Atomic semantics are fixed:

| Profile value | Predicate result |
| --- | --- |
| Unknown/null | `needs_information` |
| Known and satisfied | `confirmed` |
| Known and unsatisfied | `not_applicable` |

`all` returns false on any false, true only when all are true, and otherwise unknown. `any` returns
true on any true, false only when all are false, and otherwise unknown. Scope is a separate required
precondition. Conflicting explicit profile and query scopes produce `needs_information` with
`scope_input_conflict`; neither input silently wins.

A missing bound Fact produces `needs_information` with `missing_official_evidence`. A present but
identity-, page-, or scope-mismatched Fact is an invalid input and fails with a generic
`ApplicabilityError`. Authoritative text-hash mismatch is detected only by the offline real-KB
audit described above, because EvidencePack v1 does not carry `ScopedFact.text` separately.

## Decision Contract

The immutable output records the rule ID, status, per-predicate statuses, sorted missing field paths,
stable diagnostics, scope status, runtime source identity, and detached evidence references. An
evidence reference identifies primary versus one-hop attached evidence, but carries no retrieval
credit or score.

The decision deliberately omits raw applicant values, the complete profile or query, official text,
retrieval scores, generated explanations, and eligibility conclusions.
Its model validator recomputes the aggregate predicate/scope status and rejects mismatched missing
fields, diagnostics, evidence presence, or final status, including unsafe Pydantic copies.

## Audited Real Scenarios

The versioned fixture binds the existing 85-page corpus to `fact:00063`, page 7. A reviewer narrowed
the annotation to one necessary but insufficient age criterion for the named individual-review
route. `confirmed` therefore means only that this atomic criterion applies; it does not mean the
review was approved, later alternatives were satisfied, or the complete route applies. No PDF or
long official passage is committed.

| Scenario | Known/missing profile facts | Expected and actual | Diagnostic |
| --- | --- | --- | --- |
| confirmed | review route; age 22; explicit matching program/college | `confirmed` | none |
| not-applicable | review route; age 21; explicit matching program/college | `not_applicable` | none |
| needs-information | review route; age missing; explicit matching program/college | `needs_information` | `missing_profile_fact` |

The fixture pins Fact ID, page, authoritative Fact-text hash, source KB hash, and source PDF hash.
It is a contract characterization, not comprehensive admissions advice.

## Deliberate Limits

RSN-03 evaluates one independent reviewed rule. Rule specificity and overrides belong to RSN-04;
multi-rule conflicts belong to RSN-05; reasoning traces and cited answers belong to RSN-06/07.
Automatic Japanese rule extraction, profile inference, retrieval changes, persistence, API, UI,
and final eligibility are outside this contract.
