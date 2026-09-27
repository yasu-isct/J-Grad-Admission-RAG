"""Reproducible, isolated PARSE-01 acquisition lock and candidate runner.

Not collected by pytest.  Run only with the dedicated MinerU 4.0.7 interpreter.
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

from jgrad_admission_rag.parsing.mineru_pilot import (
    RunLimits,
    adapt_raw_result,
    sha256_file,
    supervise_worker,
)

ROOT = Path(__file__).resolve().parents[1]
PILOT = ROOT / "outputs" / "parser-pilot" / "mineru-4.0.7"
SOURCE_ROOT = ROOT / "outputs" / "source-documents" / "utokyo-gsfs" / "2027"
SOURCE_MANIFEST = ROOT / "docs" / "onboarding" / "utokyo-gsfs-complex-2027.sources.json"
RESOURCE_LOCK = ROOT / "docs" / "onboarding" / "mineru-4.0.7-pilot-lock.json"
GOLD = ROOT / "docs" / "onboarding" / "mineru-4.0.7-pilot-gold-v1.json"
EXECUTION_LOCK = PILOT / "execution-lock.json"


def _json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _freeze() -> None:
    if EXECUTION_LOCK.exists():
        raise FileExistsError(f"refusing to replace frozen lock: {EXECUTION_LOCK}")
    resource = _json(RESOURCE_LOCK)
    sources = _json(SOURCE_MANIFEST)["sources"]
    model_root = PILOT / "models" / "MinerU-4_models_onnx"
    model_files = []
    for expected in resource["model"]["files"]:
        path = model_root / expected["path"]
        actual = {"path": expected["path"], "bytes": path.stat().st_size, "sha256": sha256_file(path)}
        if actual != expected:
            raise ValueError(f"model lock mismatch: {actual!r} != {expected!r}")
        model_files.append(actual)
    source_files = []
    for expected in sources:
        path = SOURCE_ROOT / f"{expected['sha256']}.pdf"
        actual = {
            "source_id": expected["source_id"],
            "path": path.relative_to(ROOT).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
            "physical_page_count": expected["physical_page_count"],
        }
        if actual["sha256"] != expected["sha256"] or actual["bytes"] != expected["bytes"]:
            raise ValueError(f"source lock mismatch: {expected['source_id']}")
        source_files.append(actual)
    distributions = sorted(
        ({"name": item.metadata["Name"], "version": item.version} for item in importlib.metadata.distributions()),
        key=lambda item: item["name"].lower(),
    )
    acquisition_files = []
    for name in ("pip-report.json", "psutil-pip-report.json"):
        path = PILOT / "acquisition" / name
        acquisition_files.append(
            {"path": path.relative_to(ROOT).as_posix(), "bytes": path.stat().st_size, "sha256": sha256_file(path)}
        )
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
            {"path": path.relative_to(ROOT).as_posix(), "bytes": path.stat().st_size, "sha256": sha256_file(path)}
        )
    lock = {
        "artifact_kind": "parse-01-execution-lock",
        "production_enabled": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "python": {"executable": str(Path(sys.executable).resolve()), "version": platform.python_version()},
        "platform": platform.platform(),
        "resource_lock": {"path": RESOURCE_LOCK.relative_to(ROOT).as_posix(), "sha256": sha256_file(RESOURCE_LOCK)},
        "gold": {"path": GOLD.relative_to(ROOT).as_posix(), "sha256": sha256_file(GOLD)},
        "config": {"path": "outputs/parser-pilot/mineru-4.0.7/config.yaml", "sha256": sha256_file(PILOT / "config.yaml")},
        "model": {
            "repo": resource["model"]["repo"],
            "revision": resource["model"]["revision"],
            "verified_files": model_files,
        },
        "sources": source_files,
        "baseline_reports": baseline_files,
        "acquisition_reports": acquisition_files,
        "distributions": distributions,
        "pip_check": pip_check.stdout.strip(),
        "candidate_network_policy": "socket connect/create_connection denied; HF/transformers/modelscope offline",
        "limits": resource["limits"],
    }
    EXECUTION_LOCK.write_text(json.dumps(lock, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"execution_lock": str(EXECUTION_LOCK), "sha256": sha256_file(EXECUTION_LOCK)}))


def _offline_environment() -> dict[str, str]:
    environment = dict(os.environ)
    for name in list(environment):
        upper = name.upper()
        if any(token in upper for token in ("API_KEY", "TOKEN", "PASSWORD", "SECRET")):
            environment.pop(name, None)
    environment.update(
        {
            "MINERU_HOME": str(PILOT / "home"),
            "MINERU_CONFIG": str(PILOT / "config.yaml"),
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


def _run(source_id: str, tier: str, repetition: int) -> None:
    if not EXECUTION_LOCK.exists():
        raise FileNotFoundError("freeze execution-lock.json before any parse")
    source = next(item for item in _json(SOURCE_MANIFEST)["sources"] if item["source_id"] == source_id)
    pdf = SOURCE_ROOT / f"{source['sha256']}.pdf"
    run_dir = PILOT / "runs" / tier / source_id / f"run-{repetition}"
    if run_dir.exists():
        raise FileExistsError(f"refusing existing run directory: {run_dir}")
    run_dir.mkdir(parents=True)
    raw = run_dir / "raw.json"
    markdown = run_dir / "document.md"
    network = run_dir / "network-audit.json"
    command = [
        sys.executable,
        "-m",
        "jgrad_admission_rag.parsing.mineru_worker",
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
    ]
    resource_limits = _json(RESOURCE_LOCK)["limits"]
    timeout = resource_limits[f"{tier}_seconds_per_pdf"]
    supervise_worker(
        command,
        environment=_offline_environment(),
        report_path=run_dir / "supervision.json",
        limits=RunLimits(
            timeout_seconds=timeout,
            process_tree_rss_bytes=resource_limits["process_tree_rss_bytes"],
            minimum_free_ram_bytes=resource_limits["minimum_free_ram_bytes"],
        ),
    )
    raw_value = _json(raw)
    view = adapt_raw_result(
        raw_value,
        source_id=source_id,
        source_pdf=pdf,
        expected_source_sha256=source["sha256"],
        tier=tier,  # type: ignore[arg-type]
    )
    comparison = run_dir / "comparison-view.json"
    comparison.write_text(view.model_dump_json(indent=2) + "\n", encoding="utf-8")
    manifest = {
        "source_id": source_id,
        "source_pdf_sha256": sha256_file(pdf),
        "tier": tier,
        "repetition": repetition,
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
