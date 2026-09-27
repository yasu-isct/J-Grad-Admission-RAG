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

The developer monitored these paths across both controlled builds (SHA-256); the old Demo
corpus pointer below is not proof of the current product runtime identity:

| Tracked or runtime binding | Before and after |
| --- | --- |
| Reviewed ISCT identity file | `aa671c92b8f403f65e2f27c4cda9174c92d7937ec9d61f7955f8fc0276deeba4` |
| EVID-01 seed file | `a5b2bc4e294c52b14c94946886e43928b46fc7f3ff7724ee08a3aa1067aa0b85` |
| EVID-01 review pin file | `11d7d1cf3f1a5220662e7efb89ada76506c396642c49cf7f28b630bd1ea92e0b` |
| ISCT real-PDF fixture manifest | `8824169700383bfc0ac072dce90eabe1fb9c0befe52cda8ac7fae56f8032a42d` |
| Historical `outputs/demo/.../runtime-v1/corpus.json` | `0e5cef7cb8eeb78e823d6ae89af4464022bf39e6e4ae15fb57f79dbc630463fb` |

The developer's inventory mislabeled `outputs/semantic_baseline/isct-master` as the frozen
334 baseline. Its actual manifest is **298 vectors / schema 0.5**. The old
`outputs/demo/isct_2027_4_2026_9_master/runtime-v1` index also has a different vector digest
from the established product index. Its repeat reads returned access denied. These historical
measurements are retained below, but do not establish preservation of the protected 334/391 roles.

| Historical measured asset | File SHA-256 | Developer repeat read |
| --- | --- | --- |
| Old 298 KB | `8223fb91628a5c2d52536075057a4b954fee0f0abf0640db017c4acf8013f66d` | same |
| Old 298 index manifest | `99f275eb9f766fd703097317c646550bfe4e823319a1aca4ca43472282e89b19` | same |
| Old 298 payloads | `f1530da8b93f7ae0e816e43bbde0464c453b4d308743f28a2b03029ca0e4beb3` | same |
| Old 298 vectors | `2ea4241fc7a9242d8e4d26f01fb5b40c5c831b13802fc9756b27a6e1ad96e95e` | same |
| Old Demo KB | `7fa46e49b7949aec289746dd5ec3c839969a822874f76c26f9ad2b64bc00f5ce` | access denied |
| Old Demo index manifest | `59cf9540ac11f6d6391a62982e9829f682a1a75dc5409119965b41d61a72b3af` | access denied |
| Old Demo payloads | `09a00401c89a580906cea56438eac91caab1e62111e7024468e69ad23d1c9397` | access denied |
| Old Demo vectors | `910481542bc1d7304f1751a75dc760a0e4a2f276209a203997df35426d451b88` | access denied |

## Independent design review: correct asset bindings

On 2026-09-28 JST, design main independently passed **179 focused tests** and checked all
pre-existing function ASTs plus moved policy constants against main `c3e7288`: no behavior changes.
The retained before/after canonical KB bytes match each other and the established product KB
digest. No new real PDF extraction or KB/index build was performed by the reviewer.

The reviewer located and hashed the correct existing assets, reading manifest identities and
actual file bytes, not guessing asset roles from directory names:

| Verified asset | Relative local path | SHA-256 |
| --- | --- | --- |
| Frozen 334 manifest | `outputs/m9-01/index-bge-m3-5617a9f6/manifest.json` | `ff2dc4f94abafb85cc60f9af9da94c52daa3d305b25e3843a8010dedd7e6523b` |
| Frozen 334 payloads | same index, `payloads.jsonl` | `6d49c6d579216846749672a4fdd7520eb0ab1405cda9c976372ed413554214aa` |
| Frozen 334 vectors | same index, `embeddings.npy` | `3aca31a683e2145fa9e24566abd3af40540bba8473b0d6a895e0cf6297f67f58` |
| Product 391 manifest | `outputs/m10-09-deepseek-live/runtime-v1/indexes/isct_2027_4_2026_9_master/manifest.json` | `30225479016303ebc8bce2d6080a5c0f75224b5c5c920351aa4e1d247be8dae1` |
| Product 391 payloads | same index, `payloads.jsonl` | `09a00401c89a580906cea56438eac91caab1e62111e7024468e69ad23d1c9397` |
| Product 391 vectors | same index, `embeddings.npy` | `56508cad1dbf13c5e3258353676608cf4b6a174ac9c879983be9bdc8cd415df7` |
| Product KB | same runtime, `documents/isct_2027_4_2026_9_master/document_kb.json` | `7fa46e49b7949aec289746dd5ec3c839969a822874f76c26f9ad2b64bc00f5ce` |

The frozen manifest binds schema 0.6 and KB `b24f85ecc0400a7d6e6e0fac94e078b2515a0c378b5bc35383efcd05977dedf6`;
its standalone KB file was not separately rehashed in this review. The product corpus pointer
binds the verified 391 manifest/KB identity. These checks establish current state against prior
accepted identities; they do not retroactively supply developer pre/post measurements.
Evidence remains in ignored `outputs/build01/design-protected-verified.json` and
`design-manifest-inventory.json`. No ACL, model, runtime pointer or asset was changed.
Use identity, row count and content digest to distinguish these historical directories on future
handoffs; their names are not authoritative roles. Exact-head approval remains in the PR review.

Only `builder/kb_builder.py`, the new profile module, this evidence note and focused tests are
tracked changes. No extractor/chunker, production Schema, manifest, CLI/HTTP/API, rule, dependency,
EVID-01 seed/pin, MS02 contract, 334/391 asset, M13 state or runtime pointer changes are made.
Rollback reverts these additive/participant code and test/doc files; no data migration is needed.
GSFS import, reviewed excerpt lineage, rules, API/UI and further M15 work await separate design
approval after this PR's independent acceptance.
