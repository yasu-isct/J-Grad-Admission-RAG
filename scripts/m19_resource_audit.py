"""Measure pure compilation RSS and retain frozen-input/reuse evidence; no new build."""

from hashlib import sha256
import ctypes
import json
from pathlib import Path
import subprocess
from time import monotonic

from scripts import m19_configs as compiler
from scripts.m19_budget import update
from scripts.m18_asset_audit import fingerprint
from jgrad_admission_rag.reviewed_fragment_import import publish_candidate, validate_candidate

ROOT = Path(__file__).resolve().parents[1]
ASSETS = Path("D:/J-Grad-Admission-RAG")
OUT = ROOT / "docs/onboarding/m19-evidence"


def peak_rss():
    if hasattr(ctypes, "windll"):

        class Counters(ctypes.Structure):
            _fields_ = [("cb", ctypes.c_ulong), ("PageFaultCount", ctypes.c_ulong)] + [
                (name, ctypes.c_size_t)
                for name in [
                    "PeakWorkingSetSize",
                    "WorkingSetSize",
                    "QuotaPeakPagedPoolUsage",
                    "QuotaPagedPoolUsage",
                    "QuotaPeakNonPagedPoolUsage",
                    "QuotaNonPagedPoolUsage",
                    "PagefileUsage",
                    "PeakPagefileUsage",
                ]
            ]

        counter = Counters()
        counter.cb = ctypes.sizeof(counter)
        kernel = ctypes.windll.kernel32
        kernel.GetCurrentProcess.restype = ctypes.c_void_p
        ctypes.windll.psapi.GetProcessMemoryInfo.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(Counters),
            ctypes.c_ulong,
        ]
        ok = ctypes.windll.psapi.GetProcessMemoryInfo(
            kernel.GetCurrentProcess(), ctypes.byref(counter), counter.cb
        )
        if not ok:
            raise OSError("RSS unavailable")
        return counter.PeakWorkingSetSize
    import resource

    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024


def save(name, value):
    (OUT / name).write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def main():
    pdfs = ASSETS / "outputs/source-documents/utokyo-gsfs/2027"
    started = monotonic()
    files, snapshot, inputs = compiler.compile_configs(pdf_dir=pdfs)
    seconds = monotonic() - started
    peak = peak_rss()
    assert peak < 1024**3
    update("pure compilation RSS measurement", seconds=seconds, peak_rss_bytes=peak)
    save(
        "resources.json",
        dict(
            seconds=seconds,
            peak_rss_bytes=peak,
            limit_bytes=1024**3,
            candidate_bytes=sum(map(len, snapshot.candidate_files.values())),
            config_bytes=sum(map(len, files.values())),
        ),
    )
    store = ASSETS / "outputs/reviewed-source-candidates"
    candidate_root = store / snapshot.plan.candidate_reference.build_id
    before = {
        str(p.relative_to(candidate_root)): fingerprint(p)
        for p in candidate_root.rglob("*")
        if p.is_file()
    }
    validate_candidate(candidate_root, *inputs)
    paths = {
        s.source_id: pdfs / f"{s.identity.source_pdf_sha256}.pdf" for s in snapshot.plan.sources
    }
    root, status, hashes = publish_candidate(store, *inputs, paths)
    after = {str(p.relative_to(root)): fingerprint(p) for p in root.rglob("*") if p.is_file()}
    assert status == "reused" and root == candidate_root and before == after
    update("read-only existing candidate reuse proof", identity=root.name)
    save(
        "candidate-reuse.json",
        dict(
            status=status,
            candidate_root=str(root),
            before=before,
            after=after,
            all_bytes_size_mtime_unchanged=True,
            mapper_recomputed_hashes=hashes,
            new_builds=0,
        ),
    )
    frozen = {}
    for name in [
        "m19-design-approval.json",
        "m19-questionnaire-authoring.json",
        "m19-questionnaire-evidence-seed-v3.json",
        "m19-source-review.json",
        "m19-source-review-pin-v3.json",
    ]:
        path = ROOT / "docs/onboarding" / name
        baseline = subprocess.check_output(
            ["git", "show", "ae93db63:" + path.relative_to(ROOT).as_posix()], cwd=ROOT
        )
        assert path.read_bytes().replace(b"\r\n", b"\n") == baseline.replace(b"\r\n", b"\n")
        frozen[name] = sha256(baseline).hexdigest()
    old = ASSETS / "outputs/m18-worktree/src/jgrad_admission_rag/service/static"
    protected = {
        str(old / name): fingerprint(old / name)
        for name in [
            "reviewed-material-presentation.mjs",
            "reviewed-material-presentation.manifest.json",
            "reviewed-material-presentation.sources.json",
        ]
    }
    for name, state in protected.items():
        assert (
            sha256(
                (ROOT / "src/jgrad_admission_rag/service/static" / Path(name).name).read_bytes()
            ).hexdigest()
            == state["sha256"]
        )
    save(
        "frozen-inputs.json",
        dict(
            base_main="ae93db63b37732ebb5ef4fe6edcbb81ee9bf33fa",
            all_frozen_inputs_unchanged=True,
            hashes=frozen,
            original_m18_static_files=protected,
        ),
    )
    print(
        json.dumps(
            dict(
                peak_rss_bytes=peak,
                seconds=seconds,
                candidate_status=status,
                frozen_inputs=len(frozen),
            )
        )
    )


if __name__ == "__main__":
    main()
