# ADR 0007: Typed consolidated answer obligations

## Status

Accepted for M10-08.

## Decision

The product natural-language route supplies the final generator with one ordered set of
server-owned propositions. Confirmed propositions carry opaque evidence IDs and must return a
`reviewed_rule` claim with the exact evidence set. Interpretations, missing coverage, unpublished
conversion relations, and missing-input states carry no evidence and must return a
`reviewed_disposition` claim bound to exactly one opaque finding ID.

Every proposition is an answer obligation. The provider output must contain exactly one atomic
claim for every finding, and `answer` must be the exact ordered projection of those claim texts.
This reconciles all generated prose to validated spans and makes omission fail closed.

The server validates claim meaning through predicate-specific subjects, relations, protected
numbers/dates/exam names, polarity and modality guards. It accepts materially different Chinese,
Japanese, or English phrasing only inside that semantic envelope. Affirmative facts retain complete
server-restored citations. Dispositions cannot carry citations or become official rejection,
acceptance, exemption, eligibility, completeness, or admission conclusions.

Necessary-slot matching is not sufficient on its own. After those checks, the validator must
consume the complete claim surface using only server-owned subjects, values, protected literals,
punctuation, and the predicate's bounded multilingual grammar. Any remaining semantic character
represents an untyped span and rejects the whole claim. Therefore a supported maximum-points or
listed-exam clause cannot lend its citation to an appended interview, submission, or other fact.

The browser presents the validated consolidated answer before citation controls. Verbatim official
text remains exclusively in the evidence drawer; user-facing prose is not required to copy it.

## Consequences

- A cache miss still uses at most one analysis and one generation call; an exact hit uses zero.
- JLPT/J.TEST and score-conversion gaps are generated as required, validated answer content rather
  than fixed UI prose.
- Unknown references, omitted obligations, changed protected literals, unsupported conjunctions,
  and cross-scope evidence continue to fail closed.
- Cache key versioning includes the updated pipeline and semantic-validator versions; existing
  cache privacy, TTL/LRU, single-flight, and invalidation guarantees remain unchanged.
- M9's grounded-RAG release boundary is unchanged; the new disposition kind is used by the M10
  consolidated route and does not turn missing coverage into evidence.
