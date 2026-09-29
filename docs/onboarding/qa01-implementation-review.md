# QA-01 checkpoint 1: unpaid implementation evidence

Issue [#233](https://github.com/yasu-isct/J-Grad-Admission-RAG/issues/233). This is a Draft checkpoint,
not online acceptance. The service remained `reviewed-state-offline / offline_rules`; there were no
paid provider calls. The user-owned 8000/8001/8002 processes and worktrees were left intact.

## Reuse and necessary differences

| Existing result | Actual reuse | Necessary QA-01 difference |
| --- | --- | --- |
| M10 `generation/adaptive_qa.py`, DeepSeek provider, planning/final prompts | `_run_natural_qa` still calls one planner and at most one final model call; successful exact responses still use the existing cache | No prompt, provider, call-limit or cache-key change. Final call now receives verified Fact text instead of index embedding text. |
| `service/app.py` target-filtered BM25/BGE, selected document, 391 runtime | `_retrieve_natural_answer_evidence` and `_select_consolidated_evidence` are retained | `_plain_qa_references` resolves selected IDs/pages/section to the already registered KB Fact. Missing/mismatched Facts fail closed. Offline/final-failure references are a separate optional response field. |
| `generation-status`, `delivery.source` | Existing mode/configuration and live/cache/fallback/offline values drive the page | The page explains online configuration versus actual delivery before and after submission. |
| v1 `advanced.html`, `app.js`, `app.css` | Same four-step page, school selector, QA form and source links | Safe DOM text renders paragraphs, lists and emphasis; expandable Fact originals are separate from the answer. Duplicate identical originals collapse in the page. |
| Existing API/browser fixtures and M9 gates | Extended the same tests and kept reviewed endpoints intact | QA cases cover mode, unsafe model text, failed generation, source projection and 390px overflow. |

The optional `source_references` response field contains only a readable title, complete Fact text
and source page numbers. Existing clients may ignore it. It contains no Fact ID, scope, hash,
embedding text or search metadata. Each visible reference is bounded to 20,000 characters; a longer
Fact is withheld rather than cut after a condition. At most three references are projected. The
answer remains `reference_answer / reference_only / needs_review=true`; fallback and offline results
remain outside the successful-response cache.

## Same-mode comparison and real offline run

The pre-change baseline is the merged code's deterministic projection, not a newly started old
service. For the same ISCT 2027 April / 情報理工学院 / 情報工学系 / B schedule target and
`出願期間と書類必着日はいつですか。` in `offline_rules`, the old `_offline_simple_qa_answer`
concatenated `record.text`. `record.text` is the index projection created by
`retrieval/embedding_text.py`, beginning with `fact_type:`, `scope:`, `section_path:` and `title:`.
The new real HTTP response has `delivery.source=offline`, a 35-character state explanation, and
three source-bound Fact references (two were byte-identical and the page displays one). No internal
index fields appear in the answer or visible originals. This comparison uses the same selected
target/question/mode and the old code contract; it does not claim an old HTTP response was rerun.
The user's earlier 8002 screenshot is additional historical before evidence, but its complete target
identity was unavailable here, so it is not used as an exact-target comparison.

`托业是什么` on that same target and mode returned `delivery.source=offline`, an explicit statement
that AI organization is off, and zero verified Fact originals. This is an honest offline outcome,
not a new exam-definition template. The online one-call definition behavior has only synthetic
verification at this checkpoint.

The developer-owned real session started once on port 8017 from this worktree using
`python -m jgrad_admission_rag.demo_cli`, the existing
`D:\J-Grad-Admission-RAG\outputs\m10-09-deepseek-live` workspace,
`D:\J-Grad-Admission-RAG\outputs\model-cache`, BGE-M3 and explicit
`--generation-provider reviewed-state-offline`. `GET /v1/generation-status` returned
`configured=true`, `mode=offline_rules`, `provider=reviewed-state-offline`; readiness was true,
RSS 0.81 GiB. No `--allow-runtime-build` or `--rebuild` flag was used. The service was stopped
after validation.

Screenshots: [real short desktop](qa01-evidence/real-short-desktop.png),
[real short mobile](qa01-evidence/real-short-mobile.png),
[captured real date response replayed through final UI at 1440px](qa01-evidence/replay-date-desktop.png),
[the same at 390px](qa01-evidence/replay-date-mobile.png),
[synthetic long Japanese table and fallback at 1440px](qa01-evidence/synthetic-long-desktop.png),
and [at 390px](qa01-evidence/synthetic-long-mobile.png). Replay uses a synthetic base-requirements
fixture and the captured real QA JSON; its synthetic target label is not the real target. The long
table/fallback image is entirely synthetic. All three 390px scenes had document scroll width 390px.
The real date screenshot taken before the final duplicate-display fix remains in ignored local
`outputs/qa01-worktree/outputs/`; the committed replay screenshots show that final UI fix.

The first browser attempt sent one base-requirements POST and stopped before QA because the sandbox
blocked screenshot writing. The second attempt sent one base POST and two QA POSTs. Cumulative
developer ledger: **service starts 1/2, real QA HTTP 2/8, base POST 2/2, other real POST 0,
paid calls 0**. One start and four QA HTTP remain reserved for the later online checkpoint;
the unused two QA HTTP are not a new task authorization. Design allocation is untouched.

Read-only asset check: the source PDF SHA-256 remained
`57fdb935ffd2f6aa759f2c77f58b45826977225239fc1576d932b891ea50c735`;
all 12 files in the 391 runtime retained their pre-run hashes, including KB
`7fa46e49b7949aec289746dd5ec3c839969a822874f76c26f9ad2b64bc00f5ce`,
payloads `09a00401c89a580906cea56438eac91caab1e62111e7024468e69ad23d1c9397`,
and vectors `56508cad1dbf13c5e3258353676608cf4b6a174ac9c879983be9bdc8cd415df7`.
The separate 334 baseline was not opened by the service or changed.

## Tests and M9 integrity checkpoint

- Correct-worktree imports were confirmed by explicitly setting `PYTHONPATH` to this worktree's
  `src`. Focused adaptive/API/UI/browser/M9 endpoint suite: **43 passed, 1 skipped**. The skip is
  the existing real-PDF test. Browser coverage includes literal script/dangerous-link text,
  paragraphs, list emphasis, duplicate references and 390px overflow.
- Ruff check and format check passed over all 263 Python files; Node syntax, compileall and
  `git diff --check` passed. The frozen semantic retrieval gate passed unchanged.
- M9 grounded endpoint tests: **7 passed**. The grounded release gate recomputed the accepted
  report and all metric floors exactly; its sole failure is `implementation_sha256`. Old digest:
  `f2e73660b09c3a2374b1e674b15b31887c26686d9ba6bd604aeb4791048637c1`;
  observed natural-QA implementation digest:
  `32d1dce782288a05484d1cc53e1c5699a8a3ff1be8781a256c4209a4398cb27d`.
  The gate suite, observations, report, retrieval benchmark/report and thresholds were not changed.
  No M9 route, rule, citation, Applicant Profile or reviewed-result branch was edited.
- Automatic approval review rejected updating the M9 policy hash before design review, describing
  it as a persistent integrity-control change. The hash remains unchanged. Design must review the
  above natural-QA diff and M9 evidence before any authorized signature update; Quality CI is
  expected to fail only this gate until then. No workaround or baseline rerecording was performed.

Online behavior remains unverified on this head. Do not mark the Draft PR ready for final review or
merge until design approves the M9 fingerprint step, CI is green, and a separately authorized,
bounded real provider acceptance is complete.
