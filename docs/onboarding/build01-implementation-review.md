# BUILD-01 implementation and controlled comparison

Execution: [Issue #206](https://github.com/yasu-isct/J-Grad-Admission-RAG/issues/206),
[full Spec](build-profile-isolation-spec.md), [ADR 0011](../decisions/0011-explicit-build-profiles-and-reviewed-lineage.md).
Pre-change main: `c3e72884f96133b142eedc9439d64be867de0f4e` (design PR #207 merged).
Implementation commit: the head SHA of the implementation PR; recorded in its review body.
The profile, code revision and comparison live in this review record and PR, not in any production
KB or manifest schema.

## Checkpoint 1 — legacy baseline, policy and guard

Before code changes, the existing ISCT PDF passed the locked fixture SHA-256 check. Exactly one
pre-change `build_document_kb` call produced canonical bytes in ignored `outputs/build01/`.
The original ISCT entity catalog, context propagation and scope inference were then moved into
`builder/legacy_isct_v1.py` as a single implementation. The four moved function ASTs match main
exactly. `builder/kb_builder.py` re-exports historical helper names; shared Fact/RetrievalUnit
assembly and diagnostics still use those functions. `build_entities([])` intentionally still emits
25 legacy ISCT entities; this is a documented limit of the old route.

The new `build_document_kb_with_profile(pdf_path, identity, *, profile_id, ...)` requires an explicit
`legacy-isct-v1` selection. It revalidates the identity and checks exact structured institution,
document family, edition, document ID, degree level and intake terms before PDF I/O, source hashing
or extraction. Profile errors are `DocumentBuildProfileError`, a `DocumentBuildError` subclass, with
stable path-free codes `unknown_profile`, `invalid_identity` and `profile_identity_mismatch`.
Omitting `profile_id` raises Python `TypeError`; no implicit/default/fallback profile exists.
Display names, PDF filenames and source labels do not authorize a mismatched structured identity.
An accepted identity still passes the old exact PDF hash check before extraction.

The guard tests use the actual #202 GSFS common-source ID/hash/URL as a **rejection fixture** and a
second fictional school. Neither is a reviewed `DocumentIdentity` for GSFS production coverage,
nor does either cause GSFS PDF I/O or KB construction. Synthetic ISCT old/explicit entries produce
identical canonical bytes. The focused builder/embedding/profile set passed **83 tests**.

Compatibility boundary: the old `build_document_kb(...)` and existing CLI, Demo, HTTP and job
callers remain unchanged. The old function can still accept a non-ISCT synthetic identity and run
legacy rules; new-school onboarding must use the explicit entry. Extractor/chunker heuristics and
other ISCT application-materials rules are still coupled to the historical pipeline. Isolating
these three seams is not universal PDF parsing or multi-school onboarding.

## Checkpoint 2 — real parity, affected tests and handoff

Only one more controlled real build was run after implementation, this time through the explicit
entry. Each phase ran in one child process with a 15-minute timeout and no retry. There were two
real ISCT builds total (one before, one after); synthetic unit-test builds are separate. The
after-run compared the entire canonical byte string with the pre-change file, so this includes
text, IDs and ordering, scope, pages, entities, embedding text, diagnostics and manifest fields.

| Input or result | Pre-change legacy | Post-change explicit |
| --- | --- | --- |
| Main / profile | `c3e72884f96133b142eedc9439d64be867de0f4e` / implicit legacy | implementation PR head / `legacy-isct-v1` |
| PDF SHA-256 | `57fdb935ffd2f6aa759f2c77f58b45826977225239fc1576d932b891ea50c735` | same |
| PDF input | existing `outputs/real_pdf/isct_2027_4_2026_9_master.pdf` | same |
| Stable `source_pdf_label` | `isct_2027_4_2026_9_master.pdf` | same |
| Parameters | `max_chars=6000`, short Fact threshold `100`, reference ambiguity margin `0.1`, default quality thresholds | same |
| Canonical KB SHA-256 | `7fa46e49b7949aec289746dd5ec3c839969a822874f76c26f9ad2b64bc00f5ce` | exactly same |
| Canonical byte length | 3,361,076 | exactly same |
| Facts / RetrievalUnits / entities | 391 / 391 / 26 | exactly same |
| Input / emitted chunks / reference links | 467 / 391 / 10 | exactly same |
| Existing quality gate | passed | passed |
| Child build time / outer wall time | 8.500 s / 9.485 s | 8.469 s / 9.469 s |

The stable source label makes this controlled canonical digest equal to the existing 391-Fact
product KB digest. A different label/path would change manifest bytes; it would not justify
rewriting the existing baseline. No production KB/index/runtime file was written.

Affected direct tests: profile/builders, embedding text, CLI, Demo, service, build/job, EVID-01
and MS02 — **306 passed, 2 skipped**. New guards spy on PDF hashing, extraction and filesystem
opening to prove unsupported/mutated identities fail first. GitHub's normal Quality workflow is
the final CI check; no extra full model/browser/paid suite is requested. Logs and the exact before
and after canonical JSON are under the sole ignored `outputs/build01/` evidence directory.

Protected paths stayed byte-identical across both controlled builds (SHA-256):

| Tracked or runtime binding | Before and after |
| --- | --- |
| Reviewed ISCT identity file | `aa671c92b8f403f65e2f27c4cda9174c92d7937ec9d61f7955f8fc0276deeba4` |
| EVID-01 seed file | `a5b2bc4e294c52b14c94946886e43928b46fc7f3ff7724ee08a3aa1067aa0b85` |
| EVID-01 review pin file | `11d7d1cf3f1a5220662e7efb89ada76506c396642c49cf7f28b630bd1ea92e0b` |
| ISCT real-PDF fixture manifest | `8824169700383bfc0ac072dce90eabe1fb9c0befe52cda8ac7fae56f8032a42d` |
| Product runtime `corpus.json` | `0e5cef7cb8eeb78e823d6ae89af4464022bf39e6e4ae15fb57f79dbc630463fb` |

The frozen 334 and product 391 KB/index files were separately inventoried read-only after both
builds. The frozen 334 set was readable again after affected tests and all four hashes matched.
The local product runtime's four KB/index files then returned Windows access denied on repeat
reads, including an authorized read-only retry. No ACLs or assets were changed to bypass this.
Thus the final **391 runtime file rehash is unverified locally**; the initial exact digests and
this limitation are handed to design review. The controlled 391 canonical output still matches
the pre-change and existing product KB digest, and both builds' monitored runtime corpus pointer
hashes matched before/after. This inventory does not hash model weights or rebuild embeddings.

| Asset | SHA-256 at first inventory | Final rehash |
| --- | --- | --- |
| Frozen 334 KB file | `8223fb91628a5c2d52536075057a4b954fee0f0abf0640db017c4acf8013f66d` | same |
| Frozen 334 index manifest | `99f275eb9f766fd703097317c646550bfe4e823319a1aca4ca43472282e89b19` | same |
| Frozen 334 payloads | `f1530da8b93f7ae0e816e43bbde0464c453b4d308743f28a2b03029ca0e4beb3` | same |
| Frozen 334 vectors | `2ea4241fc7a9242d8e4d26f01fb5b40c5c831b13802fc9756b27a6e1ad96e95e` | same |
| Product 391 KB file | `7fa46e49b7949aec289746dd5ec3c839969a822874f76c26f9ad2b64bc00f5ce` | access denied |
| Product 391 index manifest | `59cf9540ac11f6d6391a62982e9829f682a1a75dc5409119965b41d61a72b3af` | access denied |
| Product 391 payloads | `09a00401c89a580906cea56438eac91caab1e62111e7024468e69ad23d1c9397` | access denied |
| Product 391 vectors | `910481542bc1d7304f1751a75dc760a0e4a2f276209a203997df35426d451b88` | access denied |

Only `builder/kb_builder.py`, the new profile module, this evidence note and focused tests are
tracked changes. No extractor/chunker, production Schema, manifest, CLI/HTTP/API, rule, dependency,
EVID-01 seed/pin, MS02 contract, 334/391 asset, M13 state or runtime pointer changes are made.
Rollback reverts these additive/participant code and test/doc files; no data migration is needed.
GSFS import, reviewed excerpt lineage, rules, API/UI and further M15 work await separate design
approval after this PR's independent acceptance.
