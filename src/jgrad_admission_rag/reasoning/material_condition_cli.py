"""Local, condition-only JSONL preview for explicit synthetic requests."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

from .material_conditions import (
    MaterialConditionError,
    evaluate,
    load_policy_files,
    load_request,
)
from ..reviewed_source_evidence import canonical_json_bytes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", required=True, type=Path)
    parser.add_argument("--trust", required=True, type=Path)
    parser.add_argument("--request", required=True, type=Path, action="append")
    args = parser.parse_args(argv)
    try:
        policy, digest = load_policy_files(args.policy, args.trust)
        encoded = []
        for path in args.request:
            if path.is_symlink() or not path.is_file():
                raise MaterialConditionError("request file unavailable or unsafe")
            preview = evaluate(policy, load_request(path.read_bytes()), digest)
            raw = canonical_json_bytes(preview.model_dump(mode="json"))
            if len(raw) > 256 * 1024:
                raise MaterialConditionError("preview exceeds 256 KiB")
            encoded.append(raw)
    except (OSError, MaterialConditionError, ValueError, TypeError):
        sys.stderr.buffer.write(
            canonical_json_bytes({"status": "invalid_request", "previews": None})
        )
        return 2
    for raw in encoded:
        sys.stdout.buffer.write(raw)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
