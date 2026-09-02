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

Retrieval has already selected official evidence. RSN-03 does not rank evidence, parse Japanese
rules, call a model, or generate prose. A reviewer must author each rule after inspecting the bound
Fact locally.

## Rule Contract

Every immutable rule contains:

- a stable rule ID and exact schema version;
- `all` or `any` aggregation;
- allowlisted typed profile predicates;
- global or explicit college/department/program scope;
- one or more document, KB, PDF, Fact, page, and text-hash bindings;
- a short reviewed paraphrase.

Supported operations are exact equality/inequality, collection containment, numeric minimum or
maximum, date boundaries, and explicit empty/non-empty checks. Field and operator combinations are
closed and validated. There is no expression language or arbitrary dotted traversal.

Canonical rule and decision JSON is UTF-8, sorted, single-line JSON ending in LF. File loaders
accept only regular, non-symlinked files and expose generic errors that do not repeat supplied data
or filesystem paths.

## Evaluation

Each public input is serialized and fully revalidated before use, including Pydantic objects made
with `model_construct` or unsafe copies. Query text must match the EvidencePack request exactly.
Each rule binding must match the pack's runtime document, KB, and PDF identity; the bound evidence
must be present as primary or attached evidence with exact Fact ID, pages, text hash, and compatible
scope.

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
identity-, page-, hash-, or scope-mismatched Fact is an invalid input and fails with a generic
`ApplicabilityError`.

## Decision Contract

The immutable output records the rule ID, status, per-predicate statuses, sorted missing field paths,
stable diagnostics, scope status, runtime source identity, and detached evidence references. An
evidence reference identifies primary versus one-hop attached evidence, but carries no retrieval
credit or score.

The decision deliberately omits raw applicant values, the complete profile or query, official text,
retrieval scores, generated explanations, and eligibility conclusions.

## Audited Real Scenarios

The versioned fixture binds the existing 85-page corpus to `fact:00063`, page 7. A reviewer checked
the professional-degree individual-review clause before recording its age and review predicates.
No PDF or long official passage is committed.

| Scenario | Known/missing profile facts | Expected and actual | Diagnostic |
| --- | --- | --- | --- |
| confirmed | age 22; review completed; explicit matching program/college | `confirmed` | none |
| not-applicable | age 21; review completed; explicit matching program/college | `not_applicable` | none |
| needs-information | age missing; review completed; explicit matching program/college | `needs_information` | `missing_profile_fact` |

The fixture pins Fact ID, page, evidence text hash, source KB hash, and source PDF hash. It is a
contract characterization, not comprehensive admissions advice.

## Deliberate Limits

RSN-03 evaluates one independent reviewed rule. Rule specificity and overrides belong to RSN-04;
multi-rule conflicts belong to RSN-05; reasoning traces and cited answers belong to RSN-06/07.
Automatic Japanese rule extraction, profile inference, retrieval changes, persistence, API, UI,
and final eligibility are outside this contract.
