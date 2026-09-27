# Public Demo Deployment Architecture v1

Status: proposed for M13, pending the operator's provider and monthly-cost approval.

As-of date: 2026-09-27.

This decision covers the existing one-school Science Tokyo Demo. It does not authorize creating a
cloud resource, adding a payment method or domain, uploading a private asset, rebuilding an index,
or making a paid model call.

## Verified Baseline

GitHub `main` includes ART-01 PR #184 at merge commit `bcd6db2`. Its Quality check passed and issue
#183 is closed. No open M13 or DEPLOY issue or pull request existed before DEPLOY-01 #185 was
created.

The local production candidate was started once with Hugging Face and Transformers offline flags,
the BGE-M3 cache-only provider, the reviewed-state offline generation provider, and no build or
rebuild flag. `/v1/health/ready` became ready without a DeepSeek call.

| Measurement | Observed value | Planning consequence |
| --- | ---: | --- |
| Runtime lifecycle | `reused-read-only` | Startup must never fall through to a build |
| Product index | 391 payloads / 391 vectors | Preserve this exact product runtime |
| Product KB SHA-256 prefix | `7fa46e49b794` | Audit before activation |
| PDF SHA-256 | `57fdb935ffd2f6aa759f2c77f58b45826977225239fc1576d932b891ea50c735` | Audit before activation |
| Embedding identity | `BAAI/bge-m3` at `5617a9f61b028005a4858fdac845db406aefb181`, 1024 dimensions | Load cache-only |
| Product runtime size | 6.36 MiB / 12 files | Mount with the PDF and reviewed runtime assets |
| Official PDF size | 4.85 MiB | Private deployment asset, read-only |
| BGE-M3 cache size | 4.251 GiB / 23 files | Dominates persistent storage |
| Process start to readiness | 9.94 seconds | A 30-second startup allowance is sufficient locally |
| Ready working set | 790.4 MiB | 2 GiB may work but needs a Linux hard-limit test |
| Ready private committed memory | 4,443.1 MiB | Do not claim a 2 GiB production fit from RSS alone |
| Startup CPU | 9.03 CPU-seconds on a 32-logical-CPU workstation | One CPU is viable for a limited Demo, with slower startup |

The formal frozen semantic release baseline remains the separate 334-vector `b24f85ec...` index.
It is not a deployment input and must not be replaced by, or substituted for, the 391-vector
product runtime.

The current service serializes embedding calls with `provider_lock` and generation calls with
`generation_provider_lock`. M13 should therefore run one application process and explicitly cap
local retrieval at one active embedding call and online generation at one active request. A small
queue can serve ordinary portfolio traffic; horizontal worker replication would duplicate the
model in memory and is neither required nor safe until measured.

## Asset Placement

The initial deployment should use one versioned, operator-provisioned asset bundle. Provisioning
copies bytes; service startup only audits and opens them. The bundle should have a recorded manifest
of relative path, byte length, and SHA-256, and should be activated only after the existing runtime
compatibility audit succeeds.

| Asset | In Git | Placement | Runtime mode |
| --- | --- | --- | --- |
| Application code and public static files | Yes | Reproducible non-root container image | Read-only |
| Official PDF | No | Private persistent asset bundle | Read-only |
| Document KB and reviewed runtime configs | No | Private persistent asset bundle | Read-only |
| 391-vector product index | No | Private persistent asset bundle | Read-only |
| BGE-M3 cache | No | Private persistent asset bundle | Read-only, cache-only model load |
| Packaged reviewed configs already tracked in `src/` | Yes | Container image; identity checked against runtime | Read-only |
| `DEEPSEEK_API_KEY` | No | Provider secret/environment setting | Process environment only |
| Exact-answer cache | No | Bounded process memory initially | Writable, cleared on restart |
| Logs | No | Provider log stream | Writable, redacted and retention-bounded |

The disk may be writable to an operator during provisioning, but the service container should see
the activated asset directory read-only. No boot command may run PDF parsing, KB construction,
embedding construction, model download, or asset copy. A missing or incompatible bundle is a hard
readiness failure.

## Option A: Render Web Service With Persistent Disk

Architecture:

```text
browser -> Render managed HTTPS -> one non-root FastAPI container
                                      |-- /var/lib/jgrad/assets (read-only in the app)
                                      |     PDF + runtime-v1 + BGE-M3 cache
                                      |-- process-local bounded answer cache
                                      `-- DEEPSEEK_API_KEY from Render secret env
```

Use the Singapore region, a single `1c-2g` web service, and an 8 GB persistent disk for the first
staging attempt. Render supplies a stable `onrender.com` HTTPS address and managed TLS. The Hobby
workspace itself is $0; current web compute is $25/month for 1 CPU and 2 GB RAM, and persistent
disk is $0.25/GB-month, so the starting fixed estimate is **$27/month**. Five GB/month of outbound
bandwidth is included and excess is currently $0.15/GB.

The 2 GB selection is conditional. Before staging is accepted, the container must start and answer
bounded retrieval requests under an actual 2 GB Linux memory limit with no swap-dependent success.
If that test fails, stop rather than silently scale: Render's 4 GB plan is currently $85/month, so
the corresponding fixed estimate becomes **$87/month**. That cost change requires a new user
approval.

Benefits:

- managed HTTPS, platform hostname, deploy health checks, container builds, secrets, and rollbacks;
- encrypted persistent disk with automatic daily snapshots retained for at least seven days;
- secure operator file transfer to the attached disk by SSH/SCP;
- least operational work for a portfolio Demo.

Constraints:

- a disk-backed service cannot scale to multiple instances;
- only the disk mount persists, disk size can grow but not shrink, and recovery restores a whole
  snapshot;
- Singapore is the closest documented Render region, not Tokyo;
- the memory-fit uncertainty creates a large $27-to-$87 step.

Official sources:

- Render pricing and bandwidth: https://render.com/pricing
- Compute plan identities: https://render.com/docs/compute-plans
- Persistent disk, encryption, snapshots, limits, and SCP: https://render.com/docs/disks
- Managed platform HTTPS: https://render.com/docs/tls
- Public web-service hostname and port contract: https://render.com/docs/web-services
- Disk-backed single-instance limit: https://render.com/docs/scaling

## Option B: Amazon Lightsail VM Plus Distribution

Architecture:

```text
browser -> Lightsail distribution HTTPS -> Tokyo Lightsail VM
                                             `-- reverse proxy -> one FastAPI container
                                                   |-- host asset directory, bind-mounted read-only
                                                   `-- secret environment file owned by root
```

Use an 8 GB Linux instance in `ap-northeast-1` (Tokyo), its included 160 GB SSD and attached static
IP, plus the smallest Lightsail distribution. The current fixed estimate is **$46.50/month**:
$44 for the VM and $2.50 for the 50 GB distribution. The distribution's default CloudFront domain
is HTTPS-enabled, so a purchased domain is not required for staging. Instance snapshots are an
optional $0.05/GB-month; their cost depends on changed blocks and retention.

A 4 GB VM plus distribution would be $26.50/month, but it sits below the observed 4.34 GiB private
commit and is not the safe baseline. It may be evaluated later under a hard limit, not assumed.

Benefits:

- 8 GB RAM removes the immediate model-memory uncertainty at less cost than Render's 4 GB tier;
- Tokyo region, ample included disk, static IP, firewall, SSH, and predictable transfer bundle;
- full control over read-only bind mounts, systemd/container restart policy, and host hardening.

Constraints:

- the operator owns OS patching, Docker, reverse proxy, firewall, log rotation, monitoring,
  certificate/origin behavior, rollback, and incident recovery;
- a public VM origin must be hardened even when the distribution is the advertised entry point;
- a default CloudFront hostname is stable and HTTPS-enabled but less portfolio-friendly than a
  named PaaS URL; a custom domain remains a separate user decision;
- snapshots and a second retained instance can add charges.

Official sources:

- Lightsail bundle, distribution, block storage, and snapshot pricing:
  https://aws.amazon.com/lightsail/pricing/
- Tokyo availability: https://docs.aws.amazon.com/lightsail/latest/userguide/understanding-regions-and-availability-zones-in-amazon-lightsail.html
- Default distribution HTTPS domain: https://docs.aws.amazon.com/lightsail/latest/userguide/understanding-tls-ssl-certificates-in-lightsail-https.html
- Static IP behavior: https://docs.aws.amazon.com/lightsail/latest/userguide/lightsail-create-static-ip.html
- Firewall behavior: https://docs.aws.amazon.com/lightsail/latest/userguide/understanding-firewall-and-port-mappings-in-amazon-lightsail.html

## Variable DeepSeek Cost

Infrastructure estimates exclude model usage. DeepSeek currently bills `deepseek-flash` per token;
at peak time its published rates are $0.006 per million cache-hit input tokens, $0.30 per million
cache-miss input tokens, and $1.20 per million output tokens. Rates can change. The application must
still enforce per-request limits, a global call budget, and a kill switch; provider-side caching is
not a substitute for the application's exact-answer zero-call cache.

Source: https://api-docs.deepseek.com/quick_start/pricing/

DEPLOY-03 must select explicit daily/monthly call and spend-equivalent limits before online
generation is enabled. Until then, staging should start with natural-language generation disabled.

## Public Attack Surface To Close

The current `create_app` registers local product routes and administrative/general service routes
together. A public deployment must expose only the UI assets, verified source PDF, health routes,
generation status, reviewed catalogs, base requirements, applicant comparison, bounded natural
language answer, and any product route proven necessary by the browser.

It must not register or route these current endpoints publicly:

- `POST /v1/knowledge-bases/build`;
- all `/v1/build-jobs` create/read/result/cancel/retry/delete routes;
- `POST /v1/corpus/query`;
- general intent, grounded-answer, or applicant-report routes unless the browser's public flow has
  a documented need for them.

DEPLOY-03 must also add a same-origin policy, explicit trusted hosts/proxy boundary, body and
question limits, local and generation concurrency limits, source-aware rate limiting, a global
generation budget/circuit breaker, redacted logs, generic errors, and a health path that performs
no provider call or asset load. Applicant Profile stays request-local and must not be logged.

## Recovery And Rollback

Application rollback selects a previously verified immutable image. Asset rollback stops the
service, restores or re-provisions a previously checksummed asset bundle, makes it read-only, runs
the compatibility audit, and only then restarts. Neither path rebuilds a runtime. The source PDF,
runtime, and model cache remain recoverable from the operator-controlled canonical local copies;
provider snapshots are convenience recovery, not the sole source of truth.

## Recommendation And Decision Gate

Recommend **Option A, Render at an expected $27/month**, because it provides the required stable
HTTPS entry point, secrets, disk snapshots, health checks, and rollback with the least operational
surface for a limited portfolio Demo. This recommendation is conditional on a pre-deployment 2 GB
Linux hard-limit test. Do not upgrade to the $87/month 4 GB tier automatically.

Choose **Option B, Lightsail 8 GB plus distribution at $46.50/month**, if predictable memory
headroom and Tokyo placement are more important than managed operations.

Before DEPLOY-02 begins, the operator must approve one provider and fixed monthly ceiling. That
approval still does not authorize asset upload; the exact third-party location and access controls
must be shown again before provisioning.
