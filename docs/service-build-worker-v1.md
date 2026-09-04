# Durable Build Worker v1

APP-02B adds the bounded execution layer between APP-02A's durable job repository and the future
APP-02C HTTP routes. It claims repository records and invokes the existing knowledge builder; it
does not expose a public route or own a second job state machine.

```text
queued durable job -> atomic claim -> owned inputs -> builder thread
                   -> publish complete result | fail | cancel
```

## Lifecycle And Bounds

`BuildJobWorker` is inert until explicit asynchronous `start()`. Startup opens and recovers the
repository off the event loop, then starts a fixed number of claim loops. The default and local
runtime contract is one active build. A configured `max_active` from one through eight creates that many
long-lived slots; jobs never create additional orchestration tasks.

The worker drains durable queued work at startup. Once idle it waits on an event without polling;
later submission code calls `wake()` after a repository commit. Repeated starts and stops are
idempotent, including concurrent stops, and repository ownership is closed once.

The health snapshot exposes only `stopped`, `starting`, `healthy`, `stopping`, or `unhealthy`, the
active/bounded counts, and an allowlisted `repository_unavailable` or `worker_failure` diagnostic.
It contains no paths, exception details, identity, PDF, or extracted content.

## Blocking Work And Shared Assembly

Every repository operation and builder invocation runs through a worker thread, outside the async
event-loop thread. Both APP-01's synchronous HTTP build and this worker call the same
`build_response` boundary. That function applies the recorded `BuildOptions`, validates a detached
knowledge base, derives the quality summary, and replaces the physical path with a controlled
label: `uploaded.pdf` for APP-01 and `source.pdf` for durable jobs.

Passing quality publishes `succeeded`; failed quality publishes an inspectable `quality_failed`
result. Builder exceptions become `failed/build_failed` for only that job, and the next queued job
continues. Repository failures make the worker unhealthy and stop new claims.

## Cancellation And Shutdown

A queued job cancelled before claim is never built. For a running job, the existing builder is an
honestly non-interruptible thread phase. The worker checks cancellation immediately before build
and again before publication. If cancellation wins, the completed in-memory result is discarded
and the repository commits `cancelled`; if publication wins, its terminal result is immutable.

Shutdown stops new claims and wakes idle slots. It may wait for a short configured grace period,
but never waits indefinitely for an active builder. After the grace period orchestration is
cancelled and repository ownership closes; a detached builder cannot publish afterward. Its
durable `running` record is deliberately left for APP-02A recovery to mark
`failed/worker_interrupted` on the next open.

The boundary is local and single-service-instance. It adds no process pool, distributed queue,
forced thread termination, automatic retry, retention purge, or public job API.
