"""Archive 126 planning calls, then replay the unchanged product evidence path.

Capture is opt-in and append-only. Replay never constructs an online provider.
No final generation, model downloads, index builds, or benchmark edits.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import statistics
import sys
import time
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
FIXTURES = ROOT / "tests/fixtures"
OUT = FIXTURES / "adaptive_retrieval_recall_v1"
BENCHMARK = FIXTURES / "grounded_rag_retrieval_queries_v1.json"
ARCHIVED = FIXTURES / "grounded_rag_retrieval_report_v1.json"
MAIN_SHA = "a7835b55bf05839f695d8fde31d5bcf6af7e9f1a"
DOCUMENT = "isct_2027_4_2026_9_master"
REVISION = "5617a9f61b028005a4858fdac845db406aefb181"
EXPECTED_RUNTIME = {
    f"documents/{DOCUMENT}/document_kb.json":
        "7fa46e49b7949aec289746dd5ec3c839969a822874f76c26f9ad2b64bc00f5ce",
    f"indexes/{DOCUMENT}/payloads.jsonl":
        "09a00401c89a580906cea56438eac91caab1e62111e7024468e69ad23d1c9397",
    f"indexes/{DOCUMENT}/embeddings.npy":
        "56508cad1dbf13c5e3258353676608cf4b6a174ac9c879983be9bdc8cd415df7",
}


def now():
    return datetime.now(timezone.utc).isoformat()


def digest(value):
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")).hexdigest()


def file_hash(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".pending")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def protected(runtime):
    values = {"runtime/" + p.relative_to(runtime).as_posix(): file_hash(p)
              for p in sorted(runtime.rglob("*")) if p.is_file()}
    for p in (BENCHMARK, ARCHIVED, ROOT / "config/grounded_rag_release_gate_v1.json"):
        values[p.relative_to(ROOT).as_posix()] = file_hash(p)
    # Do not copy or parse the PDF; verify the archived official identity only.
    pdf = runtime.parents[1] / "real_pdf" / (DOCUMENT + ".pdf")
    values["official_pdf"] = file_hash(pdf)
    return values


def checked_inputs(runtime):
    benchmark = read(BENCHMARK)
    for relative, expected in EXPECTED_RUNTIME.items():
        if file_hash(runtime / relative) != expected:
            raise ValueError(f"runtime identity mismatch: {relative}")
    kb = read(runtime / f"documents/{DOCUMENT}/document_kb.json")
    assert len(kb["facts"]) == 391
    assert len(benchmark["queries"]) == 42
    assert Counter(q["query_language"] for q in benchmark["queries"]) == {"ja": 38, "zh": 4}
    assert protected(runtime)["official_pdf"] == benchmark["source_pdf_sha256"]
    return benchmark, kb


def prepare(runtime):
    from jgrad_admission_rag.generation.adaptive_qa import (
        ADAPTIVE_QA_PLANNING_PROMPT_VERSION, ADAPTIVE_QA_PLANNING_SYSTEM_PROMPT,
        ADAPTIVE_QA_SCHEMA_VERSION, AdaptiveQaPlanDraft,
    )
    from jgrad_admission_rag.generation.deepseek_responses import (
        DeepSeekResponsesConfig, _projection_for,
    )
    from jgrad_admission_rag.reasoning.reviewed_report_plan import load_reviewed_report_plan
    from jgrad_admission_rag.service.demo_requirements import (
        DemoTargetRequest, build_demo_target_catalog, build_demo_target_summary,
    )

    if (OUT / "run-settings.json").exists():
        raise RuntimeError("Pre-registration exists; do not overwrite it")
    benchmark, _ = checked_inputs(runtime)
    plan = load_reviewed_report_plan(runtime / "config/reviewed_report_plan.json")
    catalog = build_demo_target_catalog((plan,))
    departments = {d.department_id: c.college_id
                   for c in catalog.schools[0].degrees[0].intakes[0].colleges
                   for d in c.departments}
    targets = []
    for question in benchmark["queries"]:
        explicit = [name for name in departments if name in question["query"]]
        assert len(explicit) <= 1
        department = explicit[0] if explicit else "情報工学系"
        september = question["query_id"] == "rq:0008"
        target = DemoTargetRequest(
            school_id="isct", document_id=DOCUMENT, degree_id="master",
            intake={"year": 2026 if september else 2027, "month": 9 if september else 4},
            college_id=departments[department], department_id=department,
            application_route="b_schedule" if department == "情報工学系" else None,
        )
        summary = build_demo_target_summary((plan,), target)
        label = " / ".join((summary.school_name, summary.degree_name, summary.intake_name,
                            summary.college_name, summary.department_name))
        targets.append({"query_id": question["query_id"], "question": question["query"],
                        "target": target.model_dump(mode="json"), "target_label": label,
                        "reason": "explicit department" if explicit else "fixed demo default"})
    settings = {
        "created_at": now(), "source_main_sha": MAIN_SHA, "rounds": 3,
        "questions_per_round": 42, "authorized_planning_invocations": 126,
        "provider": "deepseek-responses", "provider_config": asdict(DeepSeekResponsesConfig(
            model="deepseek-flash")), "temperature": "omitted", "top_p": "omitted",
        "seed": "omitted", "reasoning_effort": "none", "store": False,
        "planning_prompt_version": ADAPTIVE_QA_PLANNING_PROMPT_VERSION,
        "schema_version": ADAPTIVE_QA_SCHEMA_VERSION,
        "system_prompt": ADAPTIVE_QA_PLANNING_SYSTEM_PROMPT,
        "system_prompt_sha256": digest(ADAPTIVE_QA_PLANNING_SYSTEM_PROMPT),
        "pydantic_schema": AdaptiveQaPlanDraft.model_json_schema(),
        "wire_schema": _projection_for(AdaptiveQaPlanDraft).schema,
        "benchmark_sha256": file_hash(BENCHMARK), "targets_sha256": digest(targets),
        "protocol_sha256": file_hash(ROOT / "docs/evaluation/adaptive-retrieval-recall-v1.md"),
        "packages": {n: importlib.metadata.version(n) for n in (
            "openai", "pydantic", "sentence-transformers", "numpy", "torch", "transformers")},
        "source_hashes": {p.relative_to(ROOT).as_posix(): file_hash(p)
                          for p in sorted((ROOT / "src").rglob("*.py"))},
        "protected_before": protected(runtime),
    }
    settings["wire_schema_sha256"] = digest(settings["wire_schema"])
    settings["pydantic_schema_sha256"] = digest(settings["pydantic_schema"])
    save(OUT / "targets.json", targets)
    save(OUT / "run-settings.json", settings)
    print("Prepared 42 fixed targets, protocol and immutable input identities", flush=True)


def verify_settings(runtime):
    checked_inputs(runtime)
    settings = read(OUT / "run-settings.json")
    if protected(runtime) != settings["protected_before"]:
        raise ValueError("Protected inputs changed")
    assert digest(read(OUT / "targets.json")) == settings["targets_sha256"]
    for relative, expected in settings["source_hashes"].items():
        assert file_hash(ROOT / relative) == expected, relative
    return settings


class PlanningArchiveClient:
    """Observe the default SDK without changing its retry or transport configuration."""

    def __init__(self, **kwargs):
        from openai import OpenAI

        self.client = OpenAI(**kwargs)
        self.current = None
        self.path = None
        self.responses = self
        self.client._client.event_hooks["request"].append(self.on_request)
        self.client._client.event_hooks["response"].append(self.on_response)

    def on_request(self, request):
        self.current["http_attempts"].append({"started_at": now()})
        save(self.path, self.current)

    def on_response(self, response):
        self.current["http_attempts"][-1].update({
            "status_code": response.status_code, "received_at": now()})
        save(self.path, self.current)

    def create(self, **kwargs):
        if kwargs["text"]["format"]["name"] != "adaptive_qa_plan":
            raise RuntimeError("Only the planning endpoint is authorized")
        if "wire_request" in self.current:
            raise RuntimeError("Outer retries are forbidden")
        self.current["wire_request"] = kwargs
        self.current["wire_request_sha256"] = digest(kwargs)
        save(self.path, self.current)
        response = self.client.responses.create(**kwargs)
        self.current["raw_response"] = response.model_dump(mode="json")
        self.current["raw_response_sha256"] = digest(self.current["raw_response"])
        save(self.path, self.current)
        return response


def capture(runtime, authorization):
    from jgrad_admission_rag.generation.adaptive_qa import (
        AdaptiveQaPlanningRequest, plan_adaptive_checked,
    )
    from jgrad_admission_rag.generation.deepseek_responses import (
        DeepSeekResponsesConfig, DeepSeekResponsesGenerationProvider,
    )
    from jgrad_admission_rag.generation.provider import GenerationError

    if authorization != 126:
        raise ValueError("Capture requires --authorized-planning-calls 126")
    settings = verify_settings(runtime)
    if not os.environ.get("DEEPSEEK_API_KEY"):
        raise RuntimeError("Existing DEEPSEEK_API_KEY is required; never archive credentials")
    clients = []

    def factory(**kwargs):
        client = PlanningArchiveClient(**kwargs)
        clients.append(client)
        return client

    provider = DeepSeekResponsesGenerationProvider(
        DeepSeekResponsesConfig(**settings["provider_config"]), _client_factory=factory)
    client = clients[0]
    for round_number in range(1, 4):
        for target in read(OUT / "targets.json"):
            query_id = target["query_id"]
            path = OUT / "plans" / f"round-{round_number}" / (query_id.replace(":", "-") + ".json")
            if path.exists():
                old = read(path)
                if old["status"] not in {"ok", "fallback"}:
                    raise RuntimeError(f"Interrupted invocation {path}; never resubmit")
                continue
            if len(list((OUT / "plans").glob("round-*/*.json"))) >= authorization:
                raise RuntimeError("Authorized invocation count exhausted")
            request = AdaptiveQaPlanningRequest(question=target["question"],
                                                target_label=target["target_label"])
            row = {"round": round_number, "query_id": query_id, "started_at": now(),
                   "status": "started", "http_attempts": [],
                   "planning_prompt_version": settings["planning_prompt_version"],
                   "schema_version": settings["schema_version"],
                   "model": settings["provider_config"]["model"],
                   "request": request.model_dump(mode="json"),
                   "settings_sha256": digest(settings)}
            save(path, row)
            client.current, client.path = row, path
            started = time.perf_counter()
            try:
                result = plan_adaptive_checked(provider, request)
                row["plan"] = result.model_dump(mode="json")
                row["plan_sha256"] = digest(row["plan"])
                row["status"] = "ok"
            except GenerationError as error:
                row["status"] = "fallback"
                row["error_code"] = str(error.code.value)
            row["finished_at"] = now()
            row["elapsed_seconds"] = time.perf_counter() - started
            save(path, row)
            print(f"round={round_number} {query_id} {row['status']} "
                  f"lookup={row.get('plan', {}).get('needs_local_lookup')} "
                  f"seconds={row['elapsed_seconds']:.1f}", flush=True)
    client.client.close()


def score(gold_ids, selected_ids):
    gold = set(gold_ids)
    if not gold:
        raise ValueError("Empty gold denominator is not allowed")
    return len(gold.intersection(selected_ids)) / len(gold)


def select_for_plan(archive, request, settings, state):
    from jgrad_admission_rag.generation.question_analysis import DeterministicQuestionUnderstandingProvider
    from jgrad_admission_rag.service.app import (
        _retrieve_deterministic_fallback, _retrieve_natural_answer_evidence,
        _select_consolidated_evidence,
    )

    if archive["status"] == "fallback":
        analysis = DeterministicQuestionUnderstandingProvider().analyze(request.question)
        return _retrieve_deterministic_fallback(request, analysis, settings, state)
    if archive["status"] != "ok":
        raise ValueError("Incomplete planning archive")
    assert digest(archive["plan"]) == archive["plan_sha256"]
    if not archive["plan"]["needs_local_lookup"]:
        return ()
    packs = _retrieve_natural_answer_evidence(
        tuple(archive["plan"]["search_queries"]), request, settings, state)
    return _select_consolidated_evidence(packs, None, request.target)


def replay(runtime, cache):
    from jgrad_admission_rag.retrieval.sentence_transformer import (
        SentenceTransformerConfig, SentenceTransformerEmbeddingProvider,
    )
    from jgrad_admission_rag.service.app import (
        _retrieved_evidence_matches_target, _retrieve_natural_answer_evidence,
        _select_consolidated_evidence,
    )
    from jgrad_admission_rag.service.grounded_answers import GroundedAnswerRequest
    from jgrad_admission_rag.service.runtime import ServiceSettings, ServiceState

    prereg = verify_settings(runtime)
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    provider = SentenceTransformerEmbeddingProvider(SentenceTransformerConfig(
        model_name="BAAI/bge-m3", revision=REVISION, expected_dimension=1024,
        cache_folder=cache))
    settings = ServiceSettings(corpus_root=runtime, manifest_path=runtime / "corpus.json",
                               policy_path=runtime / "policy.json")
    state = ServiceState(provider=provider)
    benchmark, kb = checked_inputs(runtime)
    targets = {t["query_id"]: t for t in read(OUT / "targets.json")}
    facts = {f["fact_id"]: f for f in kb["facts"]}
    for name in ("single-query", "round-1", "round-2", "round-3"):
        rows = []
        for question in benchmark["queries"]:
            query_id = question["query_id"]
            request = GroundedAnswerRequest(question=question["query"],
                                           target=targets[query_id]["target"], applicant={})
            archive_path = OUT / "plans" / name / (query_id.replace(":", "-") + ".json")
            started = time.perf_counter()
            if name == "single-query":
                packs = _retrieve_natural_answer_evidence((request.question,), request, settings, state)
                selected = _select_consolidated_evidence(packs, None, request.target)
                queries, status, archive_hash = [request.question], "single-query", None
            else:
                archive = read(archive_path)
                assert archive["settings_sha256"] == digest(prereg)
                assert archive["query_id"] == query_id
                assert archive["request"]["question"] == question["query"]
                selected = select_for_plan(archive, request, settings, state)
                queries = archive.get("plan", {}).get("search_queries", [])
                status = archive["status"]
                if status == "ok" and not archive["plan"]["needs_local_lookup"]:
                    status = "no_lookup"
                archive_hash = file_hash(archive_path)
            evidence = [{"fact_id": e.fact_id, "document_id": e.document_id,
                         "source_pages": list(e.source_pages), "scope_type": e.scope_type,
                         "scope_targets": list(e.scope_targets), "parent_college": e.parent_college,
                         "text_sha256": digest(e.text), "text_characters": len(e.text),
                         "section_path": list(e.section_path)} for e in selected]
            gold = question["relevant_fact_ids"]
            eligible = [fid for fid in gold if _retrieved_evidence_matches_target(
                SimpleNamespace(**facts[fid]), request.target)]
            selected_ids = [e.fact_id for e in selected]
            rows.append({"query_id": query_id, "query_language": question["query_language"],
                         "question": question["query"], "status": status,
                         "search_queries": queries, "plan_archive_sha256": archive_hash,
                         "gold_fact_ids": gold, "selected": evidence,
                         "hit_fact_ids": sorted(set(gold).intersection(selected_ids)),
                         "missed_fact_ids": sorted(set(gold).difference(selected_ids)),
                         "recall": score(gold, selected_ids), "scope_eligible_gold_ids": eligible,
                         "scope_ceiling": len(eligible) / len(set(gold)),
                         "scope_excluded_gold": [{"fact_id": fid, "scope_type": facts[fid]["scope_type"],
                                                  "scope_targets": facts[fid]["scope_targets"],
                                                  "parent_college": facts[fid]["parent_college"]}
                                                 for fid in gold if fid not in eligible],
                         "retrieval_seconds": time.perf_counter() - started})
            save(OUT / "results" / (name + ".json"), rows)
            print(f"{name} {query_id} recall={rows[-1]['recall']:.4f} selected={len(selected)}",
                  flush=True)
    after = protected(runtime)
    assert after == prereg["protected_before"]
    save(OUT / "protected-after.json", {"checked_at": now(), "unchanged": True, "hashes": after})


def summarize():
    values = {}
    for name in ("single-query", "round-1", "round-2", "round-3"):
        rows = read(OUT / "results" / (name + ".json"))
        assert len(rows) == 42 and len({r["query_id"] for r in rows}) == 42
        values[name] = {
            "groups": {group: {"n": len(subset), "recall": statistics.mean(r["recall"] for r in subset),
                                "scope_ceiling": statistics.mean(r["scope_ceiling"] for r in subset)}
                       for group in ("all", "ja", "zh")
                       if (subset := [r for r in rows if group == "all" or r["query_language"] == group])},
            "no_lookup_ids": [r["query_id"] for r in rows if r["status"] == "no_lookup"],
            "fallback_ids": [r["query_id"] for r in rows if r["status"] == "fallback"],
        }
    aggregate = {}
    for group in ("all", "ja", "zh"):
        recalls = [values[f"round-{n}"]["groups"][group]["recall"] for n in (1, 2, 3)]
        aggregate[group] = {"mean": statistics.mean(recalls), "min": min(recalls), "max": max(recalls)}
    archives = [read(p) for p in sorted((OUT / "plans").glob("round-*/*.json"))]
    assert len(archives) == 126
    save(OUT / "summary.json", {
        "metric": "macro_final_evidence_set_recall", "component_archived": read(ARCHIVED)["aggregates"],
        "paths": values, "adaptive_three_rounds": aggregate,
        "planning_invocations": len(archives),
        "http_attempts": sum(len(a["http_attempts"]) for a in archives),
        "planning_failures": sum(a["status"] == "fallback" for a in archives),
        "final_generation_invocations": 0,
    })
    print(json.dumps(aggregate, ensure_ascii=False), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("prepare", "capture", "replay", "summarize"))
    parser.add_argument("--runtime", type=Path)
    parser.add_argument("--model-cache", type=Path)
    parser.add_argument("--authorized-planning-calls", type=int, default=0)
    args = parser.parse_args()
    if args.stage != "summarize" and args.runtime is None:
        parser.error("--runtime is required")
    if args.stage == "prepare":
        prepare(args.runtime.resolve())
    elif args.stage == "capture":
        capture(args.runtime.resolve(), args.authorized_planning_calls)
    elif args.stage == "replay":
        if args.model_cache is None:
            parser.error("--model-cache is required")
        replay(args.runtime.resolve(), args.model_cache.resolve())
    else:
        summarize()


if __name__ == "__main__":
    main()
