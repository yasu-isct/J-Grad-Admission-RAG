"""Read-only check that the protected demo assets match the saved UX-01 manifest."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(r"D:\J-Grad-Admission-RAG")
MANIFEST = ROOT / "outputs/backups/demo-before-usability-20260930/manifest.json"
OUT = Path(__file__).resolve().parent / "ux02-evidence/asset-preflight.json"


def digest(path: Path) -> str:
    checksum = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            checksum.update(chunk)
    return checksum.hexdigest()


def main() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    mismatches = []
    for entry in manifest["assets"]:
        path = Path(entry["path"])
        if not path.is_file():
            mismatches.append({"path": str(path), "reason": "missing"})
            continue
        actual_size = path.stat().st_size
        actual_hash = digest(path)
        if actual_size != entry["size"] or actual_hash != entry["sha256"]:
            mismatches.append({"path": str(path), "reason": "size or sha256 mismatch"})
    result = {
        "manifest": str(MANIFEST),
        "manifest_sha256": digest(MANIFEST),
        "checked": len(manifest["assets"]),
        "mismatches": mismatches,
        "read_only_assets": True,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if mismatches:
        raise SystemExit(f"{len(mismatches)} protected assets failed identity check")


if __name__ == "__main__":
    main()
