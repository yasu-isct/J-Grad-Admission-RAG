# Rule Resolution v1

RSN-04 resolves multiple already-evaluated `ApplicabilityRule` records without evaluating their
predicates again. It consumes one matching `ApplicabilityDecision` per rule and a separately
reviewed `RulePrecedencePolicy`, then emits a deterministic `RuleResolution`.

```text
ApplicabilityRule + ApplicabilityDecision + RulePrecedencePolicy
    -> RuleResolution(active | overridden | pending | not_applicable)
```

This is rule ordering, not a final eligibility decision. Conflict synthesis belongs to RSN-05;
reasoning traces and cited answer prose remain later layers.

## Explicit Policy

`RulePrecedencePolicy` v1 is immutable, closed, and canonically serialized. It contains:

- a stable `policy_id`;
- exactly one `subject_key` assignment for every supplied rule;
- one or more direct `OverrideEdge` records;
- a short reviewed rationale on every edge.

An edge names the narrower `overrider_rule_id`, broader `overridden_rule_id`, and their shared
subject. The policy cannot contain profile values, free-form predicates, regular expressions,
retrieval scores, raw queries, or applicant text. It also cannot infer an edge from Fact order,
similarity, model output, or scope rank.

Self-edges, duplicates, cycles, missing subject assignments, and cross-subject edges are rejected.
The resolver additionally requires policy assignments to match the supplied rule set exactly.

## Specificity And Containment

The frozen specificity order is:

```text
global < college < department < program
```

Specificity validates whether a reviewed edge is structurally plausible; it never creates an
edge. Supported containment proofs are deliberately small:

- any targeted scope may override `global`;
- `department` or `program` may override a named `college` only when `parent_college` matches;
- `program` may override `department` only when its explicit `scope_targets` includes a target of
  that department and the parent college is compatible.

Equal-specificity edges, broader-to-narrower edges, and unproven hierarchy are rejected. This v1
does not add a general organization hierarchy or change `RuleScope`.

## Activation

A direct edge activates only when both endpoint decisions are `confirmed`:

- a confirmed rule with no active incoming edge is `active`;
- a confirmed rule with one active incoming edge is `overridden`;
- `needs_information` becomes `pending` and is never hidden;
- `not_applicable` remains `not_applicable` and is never hidden.

Two active direct edges targeting the same rule are ambiguous and fail closed. Chained direct edges
remain direct: `A -> B` and `B -> C` do not invent `A -> C`. Rules without an explicit edge remain
active even when one has a narrower scope.

## Input Reconciliation

The resolver fully revalidates all inputs and requires:

- unique rule IDs and exactly one decision for each rule;
- matching rule/decision logical modes;
- one shared document, KB SHA-256, and PDF SHA-256 identity;
- decision evidence references that match the rule's bound Fact IDs and pages;
- every policy endpoint to reference a supplied rule;
- every edge to pass subject, direction, and containment validation.

Failures expose only stable `RuleResolutionError` messages. Inputs and outputs have no new content
hashes: RSN-04 reuses the source identity and detached evidence established by RSN-03.

## Output Contract

`RuleResolution` v1 records the policy and shared source identity, plus exactly one entry for each
input rule. Each entry preserves rule ID, subject, original three-valued status, complete scope,
and detached official evidence. Overridden entries additionally name the direct overrider and
reviewed rationale.

Entries are ordered by disposition group, then frozen specificity, then rule ID. Canonical active,
overridden, pending, and not-applicable ID lists make downstream use explicit. The output contains
no profile, query, rule prose, retrieval score, final conclusion, or answer text.

## Real-Document Characterization

The reviewed 85-page ISCT KB currently has 2 `global`, 126 `department`, and 170 `unknown` Facts,
with no `college` or `program` Facts. `fact:00088` (global, page 10) and `fact:00063` (department,
page 7) verify the specificity/evidence shape, but they discuss different subjects. They therefore
do not justify a real override edge. The fixture records that negative review result instead of
inventing policy; positive override behavior is covered by compact synthetic reviewed scenarios.

## API

```python
from jgrad_admission_rag.reasoning import resolve_rule_precedence

resolution = resolve_rule_precedence(rules, decisions, policy)
```

Policy and resolution loaders accept strict versioned JSON from regular, non-symlinked files.
