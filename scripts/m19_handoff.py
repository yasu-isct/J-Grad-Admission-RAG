"""Maintain the one M19 handoff and shared audit; never starts a product service."""

import json
from datetime import datetime, timezone
from pathlib import Path
import subprocess

ROOT = Path("D:/J-Grad-Admission-RAG")
AUDIT = ROOT / "outputs/m19-audit"
REPO = "repos/yasu-isct/J-Grad-Admission-RAG"


def api(path, payload=None):
    command = ["gh", "api", path]
    if payload is not None:
        command += ["--method", "PATCH", "--input", "-"]
    return json.loads(
        subprocess.run(
            command,
            input=json.dumps(payload) if payload else None,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=True,
        ).stdout
    )


def main():
    AUDIT.mkdir(exist_ok=True)
    ledger = AUDIT / "budget.json"
    if not ledger.exists():
        data = dict(
            owner="M19 Main",
            worktree=str(ROOT / "outputs/m19-worktree"),
            branch="codex/m19-reviewed-config-delivery",
            base_main="ae93db63b37732ebb5ef4fe6edcbb81ee9bf33fa",
            dev=dict(candidate_publications=0, service_starts=0, posts=0),
            design=dict(candidate_publications=0, service_starts=0, posts=0),
            limits=dict(
                dev_candidate_publications=1,
                dev_service_starts=2,
                dev_posts=10,
                design_service_starts=1,
                design_posts=4,
            ),
            paid=0,
            downloads=0,
            full_parser_runs=0,
            vector_builds=0,
            candidate_seconds=0,
            events=[],
            initialization_evidence=[
                "GitHub #291 Ready with no comments or claim",
                "No M19 implementation PR, branch or worktree before this claim",
                "Only m19-design local records; source-review records all zero",
                "Only port 8000 active, PID 34116, user service; untouched",
                "Existing candidates only v1 f1721e7 and v2 7ea4903",
            ],
        )
        data["events"].append(
            dict(
                at=datetime.now(timezone.utc).isoformat(),
                action="ownership and budget audit; claim",
                human_seconds=None,
                machine_seconds=None,
                waiting_seconds=None,
                note="Prior time unknown",
            )
        )
        ledger.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    marker = "<!-- m19-ready-handoff -->"
    end = "<!-- /m19-ready-handoff -->"
    for number in [291, 191]:
        current = api(f"{REPO}/issues/{number}")
        old = current["body"]
        first, rest = old.split(end, 1)
        assert first.startswith(marker)
        first = first.replace("唯一 Ready，交新的 M19 Main", "In progress，M19 Main 已领取")
        first = first.replace(
            "下一责任方M19 Main领取实施。",
            "当前责任方 M19 Main 已核查 main/工作区/进程/累计账本并领取；"
            "独立工作区 `outputs/m19-worktree`，branch `codex/m19-reviewed-config-delivery`，"
            "base main `ae93db63b37732ebb5ef4fe6edcbb81ee9bf33fa`。"
            "沿 A→B→C→D 连续实施本包；共享账本 `outputs/m19-audit/budget.json`。"
            "用户 8000 在线服务保持。",
        )
        fresh = api(f"{REPO}/issues/{number}")
        assert fresh["body"] == old and fresh["updated_at"] == current["updated_at"]
        api(f"{REPO}/issues/{number}", dict(body=first + end + rest))
        (AUDIT / f"issue{number}-claimed.json").write_text(
            json.dumps(dict(number=number, updated_from=current["updated_at"]), indent=2),
            encoding="utf-8",
        )
    print("Claimed the existing handoff in #291 and #191; shared budget initialized.")


if __name__ == "__main__":
    main()
