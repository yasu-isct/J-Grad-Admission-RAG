# Rule Interaction v1

RSN-05 analyzes interactions among rules that remain relevant after RSN-04. It consumes a fully
validated `RuleResolution` and a small human-reviewed `RuleInteractionPolicy`, then emits a
deterministic evidence-preserving report.

```text
RuleResolution + RuleInteractionPolicy
    -> live same-subject pairs
    -> compatible coverage or conflict/ambiguity/unreviewed warning
```

The layers remain separate: RSN-03 evaluates one rule, RSN-04 applies reviewed direct overrides,
and RSN-05 checks whether the remaining rules have a reviewed relationship. RSN-05 never changes
applicability or precedence and never decides final eligibility.

## Reviewed Policy

`RuleInteractionPolicy` v1 is immutable, closed, and canonically serialized. A policy may contain
zero or more unordered rule pairs. Pair endpoints are normalized to lexical order and each pair has
one exact `subject_key`, one reviewed relationship, and a short rationale:

- `compatible`: both reviewed rules may coexist for this subject;
- `conflict`: if both apply, their requirements cannot simultaneously govern this subject;
- `ambiguous`: reviewed evidence does not support one deterministic interpretation or choice.

Self-pairs, duplicate or reversed-duplicate pairs, multiple relationships for one pair, ghost rule
IDs, and cross-subject pairs fail closed. A zero-interaction policy is valid: missing review is
reported explicitly instead of being treated as compatibility.

The policy contains no applicant values, queries, official text, executable predicates, regular
expressions, model output, retrieval scores, or eligibility conclusions. Scope, shared evidence,
Fact order, and similarity never create a relationship.

## Live Pair Universe

Only `active` and `pending` resolution entries are live. For each subject, RSN-05 constructs every
unordered pair of live rules. `overridden` and `not_applicable` entries remain in the embedded source
resolution but do not produce current-applicant warnings.

Every live same-subject pair appears exactly once:

- reviewed compatible pairs enter `reviewed_compatible_pair_ids` and emit no warning;
- reviewed conflict or ambiguous pairs emit one warning;
- uncovered pairs emit one `unreviewed_interaction` warning.

Policy pairs whose endpoints are not both live enter `inactive_policy_pair_ids`. Different subjects
never form a pair.

## Warning Semantics

Warnings use one certainty:

- `confirmed`: both endpoint dispositions are `active`;
- `potential`: at least one endpoint is `pending`.

Here `confirmed` describes the current pair state only. It is not a legal judgment or a claim that
the applicant is ineligible. An unreviewed warning means policy coverage is incomplete; it does not
assert conflict or ambiguity.

Each warning preserves both rule IDs, original applicability statuses, current dispositions,
scopes, and detached official evidence grouped by source rule. Reviewed conflict/ambiguity warnings
carry the reviewed rationale; unreviewed warnings carry only the stable
`missing_reviewed_relationship` diagnostic.

## Durable Report

`RuleInteractionReport` v1 embeds the validated source `RuleResolution` and the canonical reviewed
interaction snapshot. This deliberate duplication lets an independent loader reconstruct all live
pairs and verify warnings, certainty, compatible and inactive coverage, evidence, counts, source
identity, and `analysis_complete` without trusting producer-supplied summaries.

`analysis_complete` is true only when every live same-subject pair has a reviewed relationship.
The report reuses RSN-04 document/KB/PDF identity and adds no hashes. Canonical pair IDs are compact
JSON arrays of `[subject_key, first_rule_id, second_rule_id]`, avoiding ambiguous delimiter parsing.

The report contains no raw profile/query, official prose, retrieval score, hidden chain-of-thought,
final eligibility, or answer text.

## Real-Document Characterization

The current 85-page ISCT KB supplies `fact:00088` and `fact:00089`, both global application-document
Facts on page 10, as a plausible same-subject review candidate. Existing annotations do not prove
that they conflict, are semantically ambiguous, or are safe independently executable compatible
rules. The fixture therefore records the pair as `unreviewed`. Positive conflict and ambiguity
behavior is proven only with compact synthetic reviewed cases.

## API

```python
from jgrad_admission_rag.reasoning import analyze_rule_interactions

report = analyze_rule_interactions(resolution, interaction_policy)
```

Policy and report loaders accept versioned UTF-8 JSON only from regular, non-symlinked files.
