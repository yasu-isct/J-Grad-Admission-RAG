# QA-01 local mode check

First confirm that the current checkout contains the QA-01 code in PR #236 (or the corresponding
updated `main` after merge). Run these commands from that checkout's repository root. Do not
switch branches in an old shared source directory used by a running preview or launch this guide
from that old checkout. Use an isolated checkout and a free port without replacing the user's
8000/8001/8002 services.

Use the existing reviewed 391-vector runtime. Do not
pass `--allow-runtime-build` or `--rebuild`. The workspace argument is the parent of `runtime-v1`.
Choose an unused port; the examples use 8017. Stop only the process you started with Ctrl+C.

```powershell
$env:PYTHONPATH = (Join-Path (Get-Location) 'src')
$python = 'D:\J-Grad-Admission-RAG\.venv\Scripts\python.exe'
& $python -m jgrad_admission_rag.demo_cli `
  --pdf D:\J-Grad-Admission-RAG\outputs\real_pdf\isct_2027_4_2026_9_master.pdf `
  --workspace D:\J-Grad-Admission-RAG\outputs\m10-09-deepseek-live `
  --reference-workspace-config D:\J-Grad-Admission-RAG\outputs\display-01\real-config.json `
  --embedding-provider bge-m3 `
  --embedding-cache D:\J-Grad-Admission-RAG\outputs\model-cache `
  --generation-provider reviewed-state-offline `
  --port 8017
```

Open `http://127.0.0.1:8017/app`. Before asking, check
`http://127.0.0.1:8017/v1/reference-targets` includes the existing Science Tokyo and
University of Tokyo entrances. The reference workspace config is an existing read-only asset;
omit it only for a deliberately Science Tokyo-only diagnostic session.
Then check
`http://127.0.0.1:8017/v1/generation-status`: `provider=reviewed-state-offline` and
`mode=offline_rules` mean local retrieval only. The page says this before a question is submitted.
Offline results show status plus expandable official source text where a matched Fact can be
verified; they are not an AI-written answer.

For a separately authorized online session, use the same command and paths but replace the last
provider line with `--generation-provider deepseek-responses --generation-model deepseek-flash`.
Set `DEEPSEEK_API_KEY` privately in that process environment; never put the key in a command log,
screenshot, or committed file. Use `--generation-max-retries 0` for bounded acceptance. A configured
online status reports `provider=deepseek-responses`, `mode=online_model`, `configured=true` and the
chosen model. That confirms local configuration only. A successful answer reports `delivery.source=live`;
an exact successful repeat may report `cache_hit`; a failed online generation reports `fallback`.
Do not treat `online_model` alone as proof that the remote provider succeeded.

The fixed cache-only BGE-M3 revision is `5617a9f61b028005a4858fdac845db406aefb181`.
The separate 334-vector frozen regression index under `outputs/m9-01/index-bge-m3-5617a9f6`
must not be substituted for the 391-vector runtime. This guide does not authorize paid calls or
change the M9 authority boundary.
