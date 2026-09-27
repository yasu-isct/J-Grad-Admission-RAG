"""Reproducible, isolated PARSE-01 acquisition lock and candidate runner.

Closed after a cumulative page-budget breach. Historical implementation is
retained for inspection; freeze and run refuse before any acquisition or parse.
"""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
# Import the isolated pilot module without executing the production parsing
# package initializer (which deliberately depends on the production PDF stack).
sys.path.insert(0, str(ROOT / "src" / "jgrad_admission_rag" / "parsing"))

from mineru_pilot import (  # noqa: E402
    RunLimits,
    adapt_raw_result,
    directory_size,
    pdf_page_count,
    sha256_file,
    sha256_json,
    supervise_worker,
    validate_execution_evidence,
)

PILOT = ROOT / "outputs" / "parser-pilot" / "mineru-4.0.7"
RUNS = PILOT / "runs-v3"
LEDGER = PILOT / "candidate-ledger-v3.json"
SOURCE_ROOT = ROOT / "outputs" / "source-documents" / "utokyo-gsfs" / "2027"
SOURCE_MANIFEST = ROOT / "docs" / "onboarding" / "utokyo-gsfs-complex-2027.sources.json"
RESOURCE_LOCK = ROOT / "docs" / "onboarding" / "mineru-4.0.7-pilot-lock.json"
GOLD = ROOT / "docs" / "onboarding" / "mineru-4.0.7-pilot-gold-v1.json"
CONFIG = PILOT / "config.yaml"
EXECUTION_LOCK = PILOT / "execution-lock-v3.json"


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _offline_environment() -> dict[str, str]:
    environment = dict(os.environ)
    for name in list(environment):
        upper = name.upper()
        if any(token in upper for token in ("API_KEY", "TOKEN", "PASSWORD", "SECRET")):
            environment.pop(name, None)
    environment.update(
        {
            "MINERU_HOME": str(PILOT / "home"),
            "MINERU_CONFIG": str(CONFIG),
            "MINERU_MODEL_SOURCE": "local",
            "MINERU_TABLE_DEVICE": "cpu",
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
            "MODELSCOPE_OFFLINE": "1",
            "OMP_NUM_THREADS": "8",
            "OPENBLAS_NUM_THREADS": "8",
            "MKL_NUM_THREADS": "8",
            "NUMEXPR_NUM_THREADS": "8",
            "PYTHONPATH": str(ROOT / "src"),
        }
    )
    return environment


def _resolved_artifacts(report_path: Path) -> list[dict[str, Any]]:
    artifacts = []
    for item in _json(report_path).get("install", []):
        metadata = item.get("metadata", {})
        archive = item.get("download_info", {}).get("archive_info", {})
        artifacts.append(
            {
                "name": metadata.get("name"),
                "version": metadata.get("version"),
                "url": item.get("download_info", {}).get("url"),
                "hashes": archive.get("hashes", {}),
            }
        )
    return sorted(artifacts, key=lambda item: (str(item["name"]).lower(), str(item["version"])))


def _model_readiness() -> dict[str, Any]:
    executable = Path(sys.executable).with_name(
        "mineru-kit.exe" if os.name == "nt" else "mineru-kit"
    )
    result = subprocess.run(
        [str(executable), "models", "verify", "--tier", "basic", "--small-backend", "onnx"],
        capture_output=True,
        text=True,
        check=False,
        env=_offline_environment(),
        cwd=ROOT,
    )
    readiness = {
        "command": "mineru-kit models verify --tier basic --small-backend onnx",
        "exit_code": result.returncode,
        "stdout": result.stdout.strip(),
        "stderr": result.stderr.strip(),
    }
    if result.returncode:
        raise RuntimeError(f"model readiness failed: {readiness}")
    return readiness


def _collect_execution_evidence() -> dict[str, Any]:
    resource = _json(RESOURCE_LOCK)
    sources = _json(SOURCE_MANIFEST)["sources"]
    model_root = PILOT / "models" / "MinerU-4_models_onnx"
    model_files = []
    for expected in resource["model"]["files"]:
        path = model_root / expected["path"]
        actual = {
            "path": expected["path"],
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        if actual != expected:
            raise ValueError(f"model lock mismatch: {actual!r} != {expected!r}")
        model_files.append(actual)

    dictionary_expected = resource["model"]["ocr_dictionary"]
    dictionary_path = (
        Path(sys.executable).resolve().parents[1]
        / "Lib"
        / "site-packages"
        / dictionary_expected["package_path"]
    )
    dictionary_actual = {
        "package_path": dictionary_expected["package_path"],
        "characters": len(dictionary_path.read_text(encoding="utf-8").splitlines()),
        "sha256": sha256_file(dictionary_path),
    }
    if dictionary_actual != dictionary_expected:
        raise ValueError("OCR dictionary does not match the resource lock")

    source_files = []
    for expected in sources:
        path = SOURCE_ROOT / f"{expected['sha256']}.pdf"
        actual = {
            "source_id": expected["source_id"],
            "path": path.relative_to(ROOT).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
            "physical_page_count": pdf_page_count(path),
        }
        locked = {
            "source_id": expected["source_id"],
            "path": path.relative_to(ROOT).as_posix(),
            "bytes": expected["bytes"],
            "sha256": expected["sha256"],
            "physical_page_count": expected["physical_page_count"],
        }
        if actual != locked:
            raise ValueError(f"source lock mismatch: {expected['source_id']}")
        source_files.append(actual)

    distributions = sorted(
        (
            {"name": item.metadata["Name"], "version": item.version}
            for item in importlib.metadata.distributions()
        ),
        key=lambda item: item["name"].lower(),
    )
    acquisition_reports = []
    resolved_artifacts = []
    for name in ("pip-report.json", "psutil-pip-report.json"):
        path = PILOT / "acquisition" / name
        acquisition_reports.append(
            {
                "path": path.relative_to(ROOT).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
        resolved_artifacts.extend(_resolved_artifacts(path))

    check_environment = dict(os.environ)
    check_environment.pop("PYTHONPATH", None)
    pip_check = subprocess.run(
        [sys.executable, "-m", "pip", "check"],
        capture_output=True,
        text=True,
        check=False,
        cwd=PILOT,
        env=check_environment,
    )
    if pip_check.returncode:
        raise RuntimeError(pip_check.stdout + pip_check.stderr)

    baseline_files = []
    for path in sorted((ROOT / "outputs" / "parser-pilot" / "ms02").glob("*.json")):
        baseline_files.append(
            {
                "path": path.relative_to(ROOT).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    pilot_code = []
    for path in (
        ROOT / "src" / "jgrad_admission_rag" / "parsing" / "mineru_pilot.py",
        ROOT / "src" / "jgrad_admission_rag" / "parsing" / "mineru_worker.py",
        Path(__file__).resolve(),
    ):
        pilot_code.append({"path": path.relative_to(ROOT).as_posix(), "sha256": sha256_file(path)})

    return {
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "resource_lock": {
            "path": RESOURCE_LOCK.relative_to(ROOT).as_posix(),
            "sha256": sha256_file(RESOURCE_LOCK),
        },
        "gold": {"path": GOLD.relative_to(ROOT).as_posix(), "sha256": sha256_file(GOLD)},
        "config": {"path": CONFIG.relative_to(ROOT).as_posix(), "sha256": sha256_file(CONFIG)},
        "model": {
            "repo": resource["model"]["repo"],
            "revision": resource["model"]["revision"],
            "verified_files": model_files,
            "ocr_dictionary": dictionary_actual,
            "readiness": _model_readiness(),
        },
        "sources": source_files,
        "baseline_reports": baseline_files,
        "acquisition_reports": acquisition_reports,
        "resolved_artifacts": sorted(
            resolved_artifacts, key=lambda item: (str(item["name"]).lower(), str(item["version"]))
        ),
        "distributions": distributions,
        "pip_check": pip_check.stdout.strip(),
        "pilot_code": pilot_code,
        "candidate_network_policy": "socket connect/create_connection denied; HF/transformers/modelscope offline",
        "limits": resource["limits"],
    }


def _require_open_pilot() -> None:
    raise RuntimeError("PARSE-01 closed: 388 attempted page-passes exceed the 168-page budget")


def _freeze() -> None:
    _require_open_pilot()
    if EXECUTION_LOCK.exists():
        raise FileExistsError(f"refusing to replace frozen lock: {EXECUTION_LOCK}")
    evidence = _collect_execution_evidence()
    lock = {
        "artifact_kind": "parse-01-execution-lock-v3",
        "production_enabled": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "evidence_sha256": sha256_json(evidence),
        "evidence": evidence,
    }
    EXECUTION_LOCK.write_text(
        json.dumps(lock, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps({"execution_lock": str(EXECUTION_LOCK), "sha256": sha256_file(EXECUTION_LOCK)})
    )


def _load_ledger() -> dict[str, Any]:
    if not LEDGER.exists():
        return {"artifact_kind": "parse-01-candidate-ledger-v3", "runs": [], "wall_seconds": 0.0}
    return _json(LEDGER)


def _write_ledger(ledger: dict[str, Any]) -> None:
    temporary = LEDGER.with_suffix(".tmp")
    temporary.write_text(json.dumps(ledger, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(LEDGER)


def _preflight_limits(limits: dict[str, Any], ledger: dict[str, Any]) -> float:
    pilot_bytes = directory_size(PILOT)
    report_bytes = directory_size(RUNS) if RUNS.exists() else 0
    if pilot_bytes > limits["pilot_disk_bytes"]:
        raise RuntimeError("pilot_disk_limit")
    if report_bytes > limits["report_bytes"]:
        raise RuntimeError("report_disk_limit")
    remaining = limits["candidate_parse_wall_seconds"] - float(ledger["wall_seconds"])
    if remaining <= 0:
        raise RuntimeError("candidate_wall_limit")
    return remaining


def _run(source_id: str, tier: str, repetition: int) -> None:
    _require_open_pilot()
    if not EXECUTION_LOCK.exists():
        raise FileNotFoundError("freeze execution-lock-v3.json before any parse")
    lock = _json(EXECUTION_LOCK)
    current_evidence = _collect_execution_evidence()
    evidence_sha256 = validate_execution_evidence(lock, current_evidence)
    source = next(item for item in current_evidence["sources"] if item["source_id"] == source_id)
    pdf = ROOT / source["path"]
    resource_limits = current_evidence["limits"]
    ledger = _load_ledger()
    remaining = _preflight_limits(resource_limits, ledger)

    run_dir = RUNS / tier / source_id / f"run-{repetition}"
    if run_dir.exists():
        raise FileExistsError(f"refusing existing run directory: {run_dir}")
    run_dir.mkdir(parents=True)
    raw = run_dir / "raw.json"
    markdown = run_dir / "document.md"
    network = run_dir / "network-audit.json"
    runtime = run_dir / "runtime-audit.json"
    command = [
        sys.executable,
        str(ROOT / "src" / "jgrad_admission_rag" / "parsing" / "mineru_worker.py"),
        "--source-id",
        source_id,
        "--pdf",
        str(pdf),
        "--tier",
        tier,
        "--raw",
        str(raw),
        "--markdown",
        str(markdown),
        "--network-audit",
        str(network),
        "--runtime-audit",
        str(runtime),
    ]
    per_pdf_timeout = resource_limits[f"{tier}_seconds_per_pdf"]
    timeout = min(float(per_pdf_timeout), remaining)
    timeout_reason = "timeout" if timeout == per_pdf_timeout else "candidate_wall_limit"
    supervision = run_dir / "supervision.json"
    try:
        supervise_worker(
            command,
            environment=_offline_environment(),
            report_path=supervision,
            limits=RunLimits(
                timeout_seconds=timeout,
                timeout_reason=timeout_reason,
                process_tree_rss_bytes=resource_limits["process_tree_rss_bytes"],
                minimum_free_ram_bytes=resource_limits["minimum_free_ram_bytes"],
                pilot_root=PILOT,
                pilot_disk_bytes=resource_limits["pilot_disk_bytes"],
                report_root=RUNS,
                report_bytes=resource_limits["report_bytes"],
                disk_poll_seconds=30.0,
            ),
        )
    finally:
        if supervision.exists():
            report = _json(supervision)
            ledger["runs"].append(
                {
                    "source_id": source_id,
                    "tier": tier,
                    "repetition": repetition,
                    "physical_pages_attempted": source["physical_page_count"],
                    "elapsed_seconds": report["elapsed_seconds"],
                    "stop_reason": report["stop_reason"],
                }
            )
            ledger["wall_seconds"] = round(
                sum(float(item["elapsed_seconds"]) for item in ledger["runs"]), 3
            )
            _write_ledger(ledger)

    raw_value = _json(raw)
    runtime_value = _json(runtime)
    view = adapt_raw_result(
        raw_value,
        source_id=source_id,
        source_pdf=pdf,
        expected_source_sha256=source["sha256"],
        raw_result_sha256=sha256_file(raw),
        runtime_audit=runtime_value,
        runtime_audit_sha256=sha256_file(runtime),
        execution_lock_sha256=sha256_file(EXECUTION_LOCK),
        environment_evidence_sha256=evidence_sha256,
        config_sha256=current_evidence["config"]["sha256"],
        model_revision=current_evidence["model"]["revision"],
        run_repetition=repetition,
        tier=tier,  # type: ignore[arg-type]
    )
    comparison = run_dir / "comparison-view.json"
    comparison.write_text(view.model_dump_json(indent=2) + "\n", encoding="utf-8")
    manifest = {
        "source_id": source_id,
        "source_pdf_sha256": sha256_file(pdf),
        "tier": tier,
        "repetition": repetition,
        "run_id": view.run_id,
        "execution_lock_sha256": sha256_file(EXECUTION_LOCK),
        "files": {
            item.name: {"bytes": item.stat().st_size, "sha256": sha256_file(item)}
            for item in sorted(run_dir.iterdir())
            if item.name != "run-manifest.json"
        },
    }
    (run_dir / "run-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(manifest))


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("freeze")
    run = subparsers.add_parser("run")
    run.add_argument("source_id")
    run.add_argument("tier", choices=("flash", "basic"))
    run.add_argument("repetition", type=int)
    args = parser.parse_args()
    if args.command == "freeze":
        _freeze()
    else:
        _run(args.source_id, args.tier, args.repetition)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
