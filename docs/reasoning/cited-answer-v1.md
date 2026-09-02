# Cited Answer v1

RSN-07 is the deterministic presentation boundary for M4. It consumes one fully validated
`ReasoningTrace` and projects its existing outcomes into a strict `CitedAnswer` plus fixed Japanese
Markdown. It does not evaluate a rule, resolve an override or interaction, summarize official text,
or decide admission eligibility.

```text
ReasoningTrace
    -> cited rule findings
    -> missing-information and review warnings
    -> canonical citation inventory
    -> fixed Japanese Markdown
```

## Report Readiness

`report_status` describes whether the rule findings report is ready, not whether an applicant is
eligible:

- `complete`: no pending rule, review warning, incomplete analysis, or missing evidence remains;
- `needs_information`: profile or scope information is missing, with no review blocker;
- `needs_review`: conflict, ambiguity, unreviewed interaction, incomplete interaction analysis,
  inconsistent scope, or missing official evidence remains.

The precedence is `needs_review` over `needs_information` over `complete`. Every rendered report
states that the status is not an eligibility, admission, probability, or recommendation result.

## Findings And Warnings

Each sufficiently evidenced resolution step becomes one rule finding. The finding preserves the
rule, subject, scope, applicability status, disposition, activated override, source applicability
and resolution step IDs, and citations. Japanese text comes from four fixed templates for `active`,
`overridden`, `pending`, and `not_applicable`; no upstream rationale or arbitrary prose is
interpolated.

An overridden finding cites both the replaced rule and the activated more-specific rule. A
conflict, ambiguity, or unreviewed interaction warning cites both endpoints and links to its source
interaction step. Compatible and inactive pairs produce no warning. If required evidence is absent,
the factual finding or warning is suppressed and replaced with a typed process notice.

## Citation Contract

A citation preserves document ID, Fact ID, exact pages, primary or attached role, source rule, and
source step IDs. The machine inventory sorts and deduplicates the complete tuple; different roles,
pages, rules, or provenance links remain distinct. Markdown exposes stable markers such as
`[fact:00063, p.7]` and `[fact:00063, pp.7,9,10]`. It never copies official passage text.

The answer also carries the canonical source rule IDs and trace step IDs, but not the complete
trace. Model validation closes every finding, warning, missing-information entry, citation, and
typed process notice against that ID inventory. Notice kinds enforce exact rule/step shapes, so a
ghost, omitted, or extra source step fails canonical serialization without adding a provenance hash.

## Rendering And Privacy

The renderer always uses these sections in order: report readiness, rule findings, optional missing
information, optional review items, citation inventory, and fixed limitations. Empty optional
sections are omitted. Machine identifiers are restricted to an injection-safe character set and
scope labels are Markdown/HTML escaped.

Hashes remain in canonical JSON provenance but never appear in Markdown. Neither output contains
the source trace snapshot, applicant values, raw query/profile, official text, annotation notes,
reviewed rationales, predicate expected values, retrieval scores, local paths, generated reasoning,
or model chain-of-thought.

## Real Characterization

The real scenario matrix reuses the accepted `fact:00063` page 7 rule. Confirmed, not-applicable,
and needs-information inputs render active, non-applicable, and pending rule findings respectively.
These are rule-level observations only; no overall age eligibility or admission conclusion is
created. Multi-rule interactions and override rendering remain synthetic because the reviewed real
corpus does not establish those combinations.

## API

```python
from jgrad_admission_rag.reasoning import (
    build_cited_answer,
    canonical_cited_answer_bytes,
    render_cited_answer_markdown,
)

answer = build_cited_answer("answer:application-review", reasoning_trace)
payload = canonical_cited_answer_bytes(answer)
markdown = render_cited_answer_markdown(answer)
```

RSN-07 deliberately adds no answer loader, persistence layer, API, UI, or model renderer.
