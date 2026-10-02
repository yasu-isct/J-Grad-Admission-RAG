"""One AUTHOR-01 candidate identity; bounded publication or same-input reuse only.

No PDF extraction, model, embedding, vector build, download or old asset write.
Run from the isolated worktree with the project's existing Python environment.
"""

from __future__ import annotations

import ctypes
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import sys
from time import monotonic

from jgrad_admission_rag.reviewed_fragment_import import (
    ImportTrust,
    load_inputs,
    map_candidate,
    publish_candidate,
)
from jgrad_admission_rag.reviewed_source_evidence import parse_json


DOCS = Path(__file__).resolve().parent
ASSETS = Path("D:/J-Grad-Admission-RAG")
OUT = DOCS / "author01-evidence"


def peak_working_set() -> int:
    class Counters(ctypes.Structure):
        _fields_ = [("cb", ctypes.c_ulong), ("PageFaultCount", ctypes.c_ulong)] + [
            (name, ctypes.c_size_t)
            for name in (
                "PeakWorkingSetSize",
                "WorkingSetSize",
                "QuotaPeakPagedPoolUsage",
                "QuotaPagedPoolUsage",
                "QuotaPeakNonPagedPoolUsage",
                "QuotaNonPagedPoolUsage",
                "PagefileUsage",
                "PeakPagefileUsage",
            )
        ]

    counters = Counters()
    counters.cb = ctypes.sizeof(counters)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetCurrentProcess.restype = ctypes.c_void_p
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    psapi.GetProcessMemoryInfo.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong]
    if not psapi.GetProcessMemoryInfo(
        kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb
    ):
        raise ctypes.WinError(ctypes.get_last_error())
    return counters.PeakWorkingSetSize


def main() -> None:
    OUT.mkdir(exist_ok=True)
    journal_path = OUT / "candidate-operations.json"
    journal = json.loads(journal_path.read_text(encoding="utf-8")) if journal_path.exists() else []
    if len(journal) >= 2:
        raise RuntimeError("publication and same-identity reuse already recorded; use saved audit")
    started = datetime.now(timezone.utc).isoformat()
    clock = monotonic()
    raws = tuple(
        (DOCS / name).read_bytes()
        for name in (
            "author01-essay-evidence-seed-v2.json",
            "utokyo-gsfs-complex-2027.sources.json",
            "gsfs-source-set-contract-v0.1.examples.json",
            "author01-reviewed-fragment-import-v2.json",
        )
    )
    assert (
        sha256(raws[0]).hexdigest()
        == "96b5944a18e24cb2f65020dd3e7affb909522322ab8172ca5d9b375c56aea5ab"
    )
    trust = ImportTrust.model_validate(
        parse_json((DOCS / "author01-reviewed-fragment-import-trust-v2.json").read_bytes())
    )
    evidence, config = load_inputs(*raws, trust)
    expected = map_candidate(evidence, config, *raws[1:])
    build = parse_json(expected["candidate.json"])["build_id"]
    if journal and build != journal[0]["build_id"]:
        raise RuntimeError("a second candidate identity is not authorized")
    root = ASSETS / "outputs/reviewed-source-candidates" / build

    def state() -> dict:
        return (
            {
                name: {
                    "sha256": sha256((root / name).read_bytes()).hexdigest(),
                    "mtime_ns": (root / name).stat().st_mtime_ns,
                }
                for name in expected
            }
            if root.exists()
            else {}
        )

    before = state()
    sources = {
        source_id: ASSETS
        / "outputs/source-documents/utokyo-gsfs/2027"
        / f"{next(d.identity.source_pdf_sha256 for d in config.documents if d.source_id == source_id)}.pdf"
        for source_id in evidence.bundle.required_source_ids
    }
    row = {
        "started_utc": started,
        "build_id": build,
        "status": "attempting",
        "candidate_root": str(root),
        "input_sha256": [sha256(raw).hexdigest() for raw in raws],
    }
    journal.append(row)
    journal_path.write_text(json.dumps(journal, indent=2) + "\n", encoding="utf-8")
    actual_root, status, hashes = publish_candidate(
        root.parent, evidence, config, *raws[1:], sources
    )
    assert actual_root == root
    after = state()
    if before:
        assert before == after
    elapsed = monotonic() - clock
    peak = peak_working_set()
    assert elapsed < 60 and peak < 1024**3
    assert sum(map(len, expected.values())) < 8 * 1024**2
    row.update(
        status=status,
        ended_utc=datetime.now(timezone.utc).isoformat(),
        seconds=elapsed,
        peak_working_set_bytes=peak,
        candidate_bytes=sum(map(len, expected.values())),
        files_sha256=hashes,
        same_identity_reuse_unchanged=(before == after if before else None),
        file_state=after,
    )
    assert sum(item.get("seconds", 0) for item in journal) < 600
    journal_path.write_text(json.dumps(journal, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                key: row[key]
                for key in (
                    "status",
                    "build_id",
                    "seconds",
                    "peak_working_set_bytes",
                    "candidate_bytes",
                )
            }
        )
    )


if __name__ == "__main__":
    if sys.platform != "win32":
        raise SystemExit("this measured Windows operation is opt-in; do not run in CI")
    main()
