from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

OUTPUT_ROOT = Path("outputs")
FINAL_JSON_DIR = OUTPUT_ROOT / "final_json"
FINAL_REPORTS_DIR = OUTPUT_ROOT / "final_reports"
INTERMEDIATE_DIR = OUTPUT_ROOT / "intermediate"
DIAGNOSTICS_DIR = OUTPUT_ROOT / "diagnostics"
SMOKE_TESTS_DIR = OUTPUT_ROOT / "smoke_tests"


def ensure_dir(path: str | Path) -> Path:
    target = Path(path)
    target.mkdir(parents=True, exist_ok=True)
    return target


def write_json(path: str | Path, payload: Any) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def read_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
