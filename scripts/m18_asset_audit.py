"""Explicit read-only asset fingerprints; never scan drives or modify asset paths."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
ASSETS = Path("D:/J-Grad-Admission-RAG")
OUT = ROOT / "docs/onboarding/m18-evidence"


def fingerprint(path):
    info = path.stat()
    return {
        "bytes": info.st_size,
        "mtime_ns": info.st_mtime_ns,
        "sha256": sha256(path.read_bytes()).hexdigest(),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("before", "after"))
    args = parser.parse_args()
    old = json.loads(
        (ROOT / "docs/onboarding/author01-evidence/protected-before.json").read_bytes()
    )
    paths = {Path(path) for path in old["files"]}
    frozen = ASSETS / "outputs/m9-01/index-bge-m3-5617a9f6"
    paths.update(frozen / name for name in ("manifest.json", "payloads.jsonl", "embeddings.npy"))
    paths.add(
        ASSETS
        / "outputs/m9-01/demo-bge/runtime-v1/documents/isct_2027_4_2026_9_master/document_kb.json"
    )
    # Pin all v2 metadata and candidate bytes in their original paths as well.
    audit = json.loads(
        (
            ROOT / "docs/onboarding/author01-design-evidence/independent-asset-audit.json"
        ).read_bytes()
    )
    candidate = Path(audit["candidate"])
    paths.update(candidate / name for name in audit["candidate_files"])
    historical = ASSETS / "outputs/author01-worktree/docs/onboarding"
    paths.update(
        historical / path.name for path in (ROOT / "docs/onboarding").glob("author01-*-v2.json")
    )
    paths.add(historical / "author01-essay-authoring-input.json")
    files = {str(path): fingerprint(path) for path in sorted(paths)}
    for path, expected in old["files"].items():
        assert files[path] == expected, f"historical protected asset changed: {path}"
    for relative, expected in audit["candidate_files"].items():
        assert files[str(candidate / relative)]["sha256"] == expected
    # Git compares protected tracked bytes including M9 pins and both v1/v2 inputs.
    protected = [
        path
        for path in (ROOT / "docs/onboarding").glob("author01-*.json")
        if not path.name.startswith("m18")
    ]
    protected += [
        ROOT / "src/jgrad_admission_rag/service/app.py",
        ROOT / "config/grounded_rag_release_gate_v1.json",
        ROOT / "config/semantic_retrieval_gate_manifest_v1.json",
    ]
    tracked = {}
    for path in protected:
        relative = path.relative_to(ROOT).as_posix()
        baseline = subprocess.check_output(["git", "show", f"8aa4e812:{relative}"], cwd=ROOT)
        # Checkout uses CRLF on Windows, while Git stores LF; compare canonical lines.
        assert path.read_bytes().replace(b"\r\n", b"\n") == baseline.replace(b"\r\n", b"\n"), (
            relative
        )
        tracked[relative] = sha256(baseline).hexdigest()
    result = {
        "checked_utc": datetime.now(timezone.utc).isoformat(),
        "files": files,
        "tracked_bytes_match_main": tracked,
        "candidate_bytes": sum(
            files[str(candidate / name)]["bytes"] for name in audit["candidate_files"]
        ),
    }
    if args.phase == "after":
        before = json.loads((OUT / "protected-before.json").read_bytes())
        assert before["files"] == files
        assert before["tracked_bytes_match_main"] == tracked
        result["all_before_after_unchanged"] = True
    OUT.mkdir(exist_ok=True)
    (OUT / f"protected-{args.phase}.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "protected_files": len(files),
                "tracked_inputs": len(tracked),
                "candidate_bytes": result["candidate_bytes"],
                "phase": args.phase,
            }
        )
    )


if __name__ == "__main__":
    main()
