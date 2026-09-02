# ApplicantProfile v1

`ApplicantProfile` v1 is the durable input contract for later applicant-aware reasoning. It records
only applicant- or operator-supplied assertions. It is not an extraction artifact, official
evidence, a retrieval request, an eligibility decision, or an answer.

## Boundary

The online flow remains deliberately separated:

```text
ApplicantProfile + query -> retrieval -> EvidencePack -> applicability reasoning -> cited answer
```

`EvidencePack` contains official, page-traceable guideline evidence. `ApplicantProfile` contains
caller facts such as citizenship, degree completion state, or a language-test result. A future
reasoner may compare the two, but v1 does not infer missing values, search documents, attach Fact
IDs/pages, store profiles, or reach a conclusion.

## Required Shape And Unknown Values

Every listed field is required in JSON. `null` means the caller does not know that fact; omission is
invalid. For `academic_credentials` and `language_test_results`, `null` means unknown and `[]` means
the caller explicitly supplied no entries. `false` and `0` remain known values and are never treated
as unknown.

The profile sections are `target_application`, `citizenship_and_residence`,
`academic_credentials`, `eligibility_facts`, and `language_test_results`. The controlled values are
stable enums: degree level, credential completion state, intake month, individual review state, and
language-result state. Countries use uppercase ISO 3166-1 alpha-2 codes. User-entered strings must
be non-empty, already trimmed, and cannot use placeholders such as `unknown`, `N/A`, or `未定`.

Citizenship is an unordered set: duplicate codes are rejected and valid codes are sorted in the
canonical representation. Academic credentials and language tests are ordered histories, so their
order is preserved. No names, emails, phone numbers, addresses, identity documents, tokens, uploads,
raw query text, Fact IDs, source pages, evidence, conclusions, or reasoning traces belong here.

## Safe Serialization

Use `canonical_applicant_profile_bytes(profile)` for deterministic UTF-8 JSON: keys are sorted and
the result ends in one LF. Use `load_applicant_profile_bytes` or `load_applicant_profile` for
untrusted input. The file loader accepts only a regular non-symlink file and its public errors avoid
echoing the profile payload or file path.

```python
from jgrad_admission_rag.reasoning import (
    ApplicantProfile,
    canonical_applicant_profile_bytes,
    load_applicant_profile_bytes,
)

profile = load_applicant_profile_bytes(raw_json)
canonical_json = canonical_applicant_profile_bytes(profile)
```

The schema version is currently `1.0`. Unsupported versions, unknown fields, non-finite numbers,
booleans supplied where integer quantities are required, invalid dates, duplicate countries, and
contradictory stated facts fail closed.
