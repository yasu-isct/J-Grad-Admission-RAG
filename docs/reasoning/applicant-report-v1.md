# Applicant Report v1

`ApplicantReport` is the in-memory APP-03C boundary that turns one reviewed partial rulebook, its
exact official evidence, one caller-supplied profile, and one covered query intent into a
deterministic cited report.

```text
ApplicantProfile + covered QueryIntent
  + ReviewedReportPlan + ReviewedReportEvidenceBundle
  -> applicability -> precedence -> interaction -> ReasoningTrace -> CitedAnswer
  -> ApplicantReport + fixed Japanese Markdown + literal official-evidence appendix
```

This is a report about the configured rules, not a comprehensive eligibility or admission
decision. The current real plan covers one reviewed age criterion only.

## Shared Applicability Core

Ranked retrieval and direct reviewed evidence enter applicability through separate typed adapters.
The existing `evaluate_applicability` keeps its `EvidencePack` query-consistency, primary/attached
binding, and missing-evidence behavior. APP-03C uses `DirectOfficialEvidence`, which contains only
the exact document/KB/PDF identity and `primary` official references already closed by APP-03B. It
has no query, rank, score, channel, row, or embedding metadata.

Both entry points delegate to the same private applicability core. Predicate truth tables, missing
profile fields, scope diagnostics, and three-valued status therefore have one implementation. The
report builder then calls the public `resolve_rule_precedence`, `analyze_rule_interactions`,
`build_reasoning_trace`, and `build_cited_answer` APIs in order; it does not manufacture their
entries, warnings, graph steps, findings, citations, or readiness status.

## Input And Self-Audit

Before applicant evaluation, the builder independently detaches and revalidates the profile,
intent, plan, and evidence bundle. It rejects empty intent, any unsupported or mixed category, and
every plan/evidence mismatch: plan and identity, document/PDF/KB bindings, Fact set, pages, exact
UTF-8 text hash, scope, and complete Fact-to-rule map must all agree. Evidence mismatch is a report
preparation error, never a negative applicant result.

Version 1 is immutable, forbids extra fields, and uses `schema_version="1.0"`. It retains the exact
source plan and APP-03B evidence bundle alongside the derived trace and cited answer. The visible
plan ID, complete document identity, KB binding, partial-coverage statements, report status, and
rule/finding/evidence/page counts must equal those sources.

Construction and strict byte loading independently rebuild precedence, interaction analysis,
trace, and cited answer from the embedded reviewed sources. Every decision and citation must close
against one exact evidence record, and each record must be cited under every rule that binds it.
Canonical serialization is finite, sorted JSON with one trailing LF. There is deliberately no file
loader or persistence policy because a report contains official text.

## Privacy And Output

The machine report contains predicate outcomes and missing field names, not the supplied
`ApplicantProfile`, applicant values, raw query or intent mentions, retrieval metadata, local
paths, model output, generated rationale, or hidden chain-of-thought. Public failures expose one
generic message plus an allowlisted stage code.

`render_applicant_report_markdown` reuses the accepted fixed Japanese `CitedAnswer` wording. It adds
a prominent partial-coverage notice, safely escaped reviewed coverage/limitation statements, and a
deduplicated appendix with stable `[fact:..., p.N]` or `[fact:..., pp.N,M]` markers, document ID,
and exact official Fact text. Official text is placed inside a dynamically sized backtick fence, so
headings, links, HTML, block quotes, and embedded backtick runs remain inert and cannot suppress
later sections.

`complete` means only that this partial report is ready. It never means that an applicant is
eligible, admitted, likely to succeed, or recommended to apply. A not-applicable atomic rule is
rendered only as that reviewed rule not applying to the supplied facts.

## Boundary

APP-03C performs no corpus access, retrieval, embedding/model call, logging, network activity,
clock/random operation, HTTP/CLI/UI work, or persistence. The next APP-03 slice may expose this
accepted in-memory builder through a strict local `/v1` route using server-owned plans and evidence;
callers must not be allowed to author rules or official evidence.
