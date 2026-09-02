# Reasoning Trace v1

RSN-06 joins the validated outputs of RSN-03, RSN-04, and RSN-05 into one deterministic audit
graph. It records how reviewed rules moved through applicability, precedence, and interaction
analysis without making a final eligibility decision.

```text
reviewed rules + applicability decisions + RuleInteractionReport
    -> applicability steps
    -> resolution steps
    -> interaction steps
    -> terminal step IDs and coverage
```

## Graph Contract

Every reviewed rule has one applicability step and one resolution step. Applicability steps have
no dependencies. Each resolution step depends on its matching applicability step. Every live
same-subject pair and every inactive reviewed policy pair has one interaction step depending on
both endpoint resolution steps. Steps are ordered by kind and then rule or canonical pair ID, so
all edges point backward.

Terminal IDs contain every interaction step plus each resolution step that is not an interaction
endpoint. Missing profile fields, pending dispositions, unreviewed interactions, warning certainty,
and incomplete interaction coverage remain visible rather than being promoted to a conclusion.

## Evidence And Source Snapshots

Each step preserves detached official evidence by rule: document ID, Fact ID, source pages, and
primary or attached role. The trace reuses the existing document, KB, and PDF identity and creates
no trace hash.

The artifact embeds canonical source snapshots sufficient to rebuild itself. Reviewed rule
snapshots retain predicates, expected policy values, scope, evidence bindings, and authoritative
Fact hashes, but deliberately omit human annotation prose. Applicability decisions and the complete
RuleInteractionReport are embedded unchanged. Loading canonical JSON revalidates those snapshots,
rebuilds every step, edge, terminal ID, evidence group, count, and completeness flag, then rejects
any mismatch.

## Privacy And Presentation Boundary

This is a user-auditable event graph, not hidden chain-of-thought. It contains typed policy inputs,
upstream outcomes, short reviewed interaction rationales, diagnostics, and official provenance.
It never contains actual applicant values, a profile or raw query, official text, annotation notes,
retrieval scores, generated reasoning, final eligibility, probability, recommendation, or answer
prose. RSN-07 may render answers from a validated trace but cannot fill in information absent here.

## Real Characterization

The real fixture reuses the accepted `fact:00063` page 7 individual-review age rule. Separate
confirmed, not-applicable, and needs-information traces preserve their exact statuses and evidence.
They contain no interaction step because the reviewed corpus does not establish a real rule pair
for that scenario. Multi-rule topology is covered by compact synthetic fixtures.

## API

```python
from jgrad_admission_rag.reasoning import build_reasoning_trace

trace = build_reasoning_trace(
    "trace:application-review",
    reviewed_rules,
    applicability_decisions,
    interaction_report,
)
```

Canonical loaders accept versioned UTF-8 JSON only from regular, non-symlinked files.
