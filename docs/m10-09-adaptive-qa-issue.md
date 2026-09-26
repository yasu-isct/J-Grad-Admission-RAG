# M10-09: Adaptive DeepSeek planning over bounded local retrieval

## Decision

Use one model planning call to distinguish general explanations from questions that require local
admission-document confirmation. For the latter, execute bounded target-scoped local retrieval and
make one final model call. Do not add per-wording Python intent branches or restore M9 citation
closure in the reference assistant.

## Acceptance boundary

- general questions use one provider call and no retrieval when the planner says lookup is not
  required;
- admission-specific questions use no more than one planning and one final call;
- model queries are structurally bounded, then run only against the selected local document and
  target scope;
- zero hits still reach final generation with an explicit unconfirmed-local-rule status;
- exact successful repeats add zero calls;
- neither provider request contains Applicant Profile values or internal provenance;
- planning and final failures produce explicit, uncached local/reference fallbacks;
- the public result remains `reference_answer` / `reference_only` / `needs_review=true`;
- M9 structured and grounded features remain unchanged.

## Systemic debugging rule

Failures must be assigned to planning, retrieval, corpus coverage, final generation,
orchestration/cache/provider, or UI. A fix must address its owning layer and generalize to at least
two sibling questions. No wording-specific branch is added in this issue.
