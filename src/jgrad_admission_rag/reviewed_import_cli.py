"""Local reviewed-source-v1 candidate generation, reuse and validation."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import sys

from pydantic import ValidationError

from .reviewed_fragment_import import (
    Candidate,
    ImportError,
    ImportTrust,
    load_inputs,
    map_candidate,
    publish_candidate,
    validate_candidate,
)
from .reviewed_source_evidence import EvidenceError, audit_sources, canonical_json_bytes, parse_json


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", required=True, choices=("reviewed-source-v1",))
    parser.add_argument("--mode", required=True, choices=("publish", "validate"))
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--target-contract", required=True, type=Path)
    parser.add_argument("--import-config", required=True, type=Path)
    parser.add_argument("--trust", required=True, type=Path)
    parser.add_argument("--candidate-root", required=True, type=Path)
    parser.add_argument("--source", required=True, action="append", metavar="ID=PATH")
    args = parser.parse_args(argv)
    started = datetime.now(timezone.utc).isoformat()
    try:
        paths = {}
        for item in args.source:
            source_id, separator, path = item.partition("=")
            if not separator or not source_id or not path or source_id in paths:
                raise ImportError("source paths require unique ID=PATH")
            paths[source_id] = Path(path)
        raw = args.bundle.read_bytes()
        manifest_raw = args.manifest.read_bytes()
        contract_raw = args.target_contract.read_bytes()
        config_raw = args.import_config.read_bytes()
        trust = ImportTrust.model_validate(parse_json(args.trust.read_bytes()))
        evidence, config = load_inputs(raw, manifest_raw, contract_raw, config_raw, trust)
        expected = map_candidate(evidence, config, manifest_raw, contract_raw, config_raw)
        candidate = Candidate.model_validate(parse_json(expected["candidate.json"]))
        if args.mode == "publish":
            root, status, hashes = publish_candidate(
                args.candidate_root, evidence, config, manifest_raw, contract_raw, config_raw, paths
            )
        else:
            if set(paths) != set(evidence.bundle.required_source_ids):
                raise ImportError("exactly the required source paths must be explicit")
            audit_sources(evidence, paths)
            root = args.candidate_root / candidate.build_id
            hashes = validate_candidate(
                root, evidence, config, manifest_raw, contract_raw, config_raw
            )
            status = "validated"
        report = {
            "status": status,
            "profile": args.profile,
            "build_id": candidate.build_id,
            "candidate_path": str(root),
            "started_utc": started,
            "ended_utc": datetime.now(timezone.utc).isoformat(),
            "input_sha256": {
                "bundle": sha256(raw).hexdigest(),
                "source_manifest": sha256(manifest_raw).hexdigest(),
                "target_contract": sha256(contract_raw).hexdigest(),
                "import_config": sha256(config_raw).hexdigest(),
            },
            "files_sha256": hashes,
        }
        sys.stdout.buffer.write(canonical_json_bytes(report))
        return 0
    except (OSError, ValueError, ValidationError, EvidenceError) as exc:
        # No excerpt or path leaks on failure; the caller records the failed budget slot.
        code = "input_unavailable" if isinstance(exc, OSError) else "validation_failed"
        sys.stderr.buffer.write(canonical_json_bytes({"status": code, "candidate": None}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
