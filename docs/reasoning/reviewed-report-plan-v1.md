# Reviewed Report Plan v1

`ReviewedReportPlan` is the trusted configuration boundary between one reviewed corpus selection
and the existing M4 reasoning pipeline. It says which human-reviewed rules belong to one exact
`DocumentIdentity`, how those rules share subjects, which direct overrides and interactions have
been reviewed, and which query-intent categories the plan intentionally covers.

```text
reviewed selected DocumentIdentity
  + reviewed ApplicabilityRules
  + RulePrecedencePolicy
  + RuleInteractionPolicy
  + explicit partial coverage
  -> ReviewedReportPlan
```

The plan does not run an `ApplicantProfile`, retrieve evidence, materialize official Fact text,
construct a `ReasoningTrace`, or render a report. APP-03B materializes the exact bound Facts after
matching one selected audited document; APP-03C separately runs the reviewed M4 report chain.

## Contract

Version 1 uses `schema_version="1.0"` and is immutable with unknown fields forbidden. A plan contains:

- one stable plan ID and one complete reviewed document-identity snapshot;
- a non-empty, rule-ID-sorted tuple of existing `ApplicabilityRule` snapshots;
- one existing precedence policy whose subject assignments cover exactly those rules;
- one existing interaction policy whose endpoints and subjects reconcile with that precedence policy;
- a non-empty, sorted tuple of covered `IntentCategory` values;
- the only supported status, `partial_reviewed_rules`, plus bounded reviewed-coverage and limitation
  statements.

Every evidence binding must match the identity's exact document ID and PDF hash. All bindings must
also share one current KB hash. That KB hash remains in the existing rule binding; the plan does not
duplicate it as another serialized provenance field. Override endpoints must be included rules and
retain the existing narrower-scope proof. Empty override and interaction tuples are valid for one
rule, while subject assignments remain non-empty and exact.

`canonical_reviewed_report_plan_bytes` emits deterministic finite JSON with one trailing LF.
`load_reviewed_report_plan_bytes` accepts only the supported schema, and
`load_reviewed_report_plan` accepts only a regular non-symlink file. Public failures use one generic
`ReviewedReportPlanError` message and do not echo supplied content.

## Ownership And Selection

Plans are reviewed, server-owned configuration. They are not request payloads and must not be loaded
from a caller-selected path. A later APP-03 registry will map the exact selected
`DocumentIdentity` to an allowlisted plan. It must reject zero matches and duplicate plans for the
same exact identity rather than guessing. The registry and HTTP route are outside APP-03A.

The plan is single-document because rule evidence currently binds one exact document, KB, and PDF.
Cross-document reasoning requires a separate reviewed contract; it must not emerge from combining
retrieval results or plan files opportunistically.

## Honest Coverage

The committed real plan contains only the accepted `fact:00063`, page 7 individual-review age
criterion and covers the `eligibility` intent category only. This is deliberately partial. A
confirmed atomic rule says that rule applies to the supplied facts; it does not mean that the
applicant is eligible, has passed review, will be admitted, or should apply. Completeness requires a
separate reviewed rule-coverage decision and is not representable in v1.

For current corpus execution, that plan's nested rule binding uses the independently recomputed
canonical schema-0.6 298-Fact KB hash. Historical M4/RET-09 schema-0.5 fixtures remain frozen and are
not treated as an alternate runtime binding.

Retrieval rank is evidence discovery metadata, not a reviewed admission rule. A durable build-job
status describes processing progress, not an applicant conclusion. Neither may be promoted into a
plan or reasoning outcome.

Official Fact text is also absent from the plan. APP-03B resolves each exact evidence binding
against the audited selected KB, verifies its Fact ID, pages, and authoritative text hash, and only
then materializes evidence for APP-03C's cited report.
