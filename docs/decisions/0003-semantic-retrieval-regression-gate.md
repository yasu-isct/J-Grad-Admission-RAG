# ADR 0003: Semantic Retrieval Regression Gate

## Status

Accepted.

## Context

RET-08 captured a reviewed, cache-only BGE-M3 characterization of the frozen Japanese admission
retrieval benchmark. The project needs a repeatable CI decision without committing its PDF, model
snapshot, vector index, or raw benchmark questions.

## Decision

`jgrad-check-retrieval-gate` is a pure offline verifier. It reads a compact RET-08 report fixture,
the strict policy at `config/semantic_retrieval_gate_v1.json`, and an implementation manifest. It
does not construct an embedding provider, load a KB or index, or fetch a model.

The policy pins the report, source KB/PDF, benchmark, fact projections, semantic payloads/vectors,
and BGE-M3 identity. It requires the approved global floors, count caps, weak slices, and the
`rq:0012` primary/reference recovery rule. A valid quality regression returns exit code `1`; unsafe,
malformed, stale, or non-canonical configuration returns `2`.

The manifest signs the exact retrieval-affecting files resolved from a fixed, non-overlapping glob
set. A new matching file, missing file, duplicate glob match, symlink, or hash mismatch fails
closed. The hash input is each sorted relative POSIX path, a NUL byte, its raw bytes, and a NUL byte.

GitHub Actions runs normal offline tests, Ruff, compilation, whitespace checks, then the gate. It
installs only `.[dev]`, sets Hugging Face and Transformers offline variables, and confirms that its
temporary Hugging Face directory remains empty.

## Consequences

The gate catches changes to declared retrieval semantics before merge, without reproducing a
four-gigabyte model evaluation in CI. It does not claim that the baseline is universally good, nor
does it replace future semantic evaluation when the KB, benchmark, model, or intended behavior
changes. Such a change requires a reviewed new baseline and a new policy/manifest version.
