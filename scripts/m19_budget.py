"""One persistent M19 ledger; reservations precede real actions, failures count."""

from datetime import datetime, timezone
import json
from pathlib import Path

LEDGER = Path("D:/J-Grad-Admission-RAG/outputs/m19-audit/budget.json")


def update(action, *, resource=None, identity=None, seconds=None, **details):
    data = json.loads(LEDGER.read_bytes())
    if resource:
        used = data["dev"][resource]
        limit = data["limits"]["dev_" + resource]
        if resource == "candidate_publications" and data.get("candidate_build_id") == identity:
            resource = None
        else:
            if used >= limit:
                raise ValueError(f"M19 developer {resource} exhausted")
            data["dev"][resource] += 1
            if identity:
                data["candidate_build_id"] = identity
    if seconds is not None:
        data["candidate_seconds"] += seconds
        if seconds >= 60 or data["candidate_seconds"] >= 600:
            raise ValueError("M19 pure generation time budget exhausted")
    data["events"].append(
        dict(
            at=datetime.now(timezone.utc).isoformat(),
            action=action,
            resource=resource,
            identity=identity,
            machine_seconds=seconds,
            **details,
        )
    )
    LEDGER.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return data
