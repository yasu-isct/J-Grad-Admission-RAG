"""Offline child process for one PARSE-01 candidate run."""

from __future__ import annotations

import argparse
import json
import socket
from pathlib import Path
from typing import Any


class NetworkDenied(RuntimeError):
    pass


def _deny_network() -> list[str]:
    attempts: list[str] = []

    def denied(*args: Any, **kwargs: Any) -> Any:
        target = repr(args[1] if len(args) > 1 else args[0] if args else kwargs)
        attempts.append(target)
        raise NetworkDenied(f"network disabled during candidate parse: {target}")

    socket.socket.connect = denied  # type: ignore[method-assign]
    socket.create_connection = denied  # type: ignore[assignment]
    return attempts


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-id", required=True)
    parser.add_argument("--pdf", type=Path, required=True)
    parser.add_argument("--tier", choices=("flash", "basic"), required=True)
    parser.add_argument("--raw", type=Path, required=True)
    parser.add_argument("--markdown", type=Path, required=True)
    parser.add_argument("--network-audit", type=Path, required=True)
    args = parser.parse_args()
    for target in (args.raw, args.markdown, args.network_audit):
        if target.exists():
            raise FileExistsError(f"refusing output conflict: {target}")
        target.parent.mkdir(parents=True, exist_ok=True)
    attempts = _deny_network()
    from mineru.parser import parse

    result = parse(args.pdf, tier=args.tier, ocr_mode="txt")
    args.raw.write_text(result.to_json() + "\n", encoding="utf-8")
    args.markdown.write_text(result.markdown(add_markers=True), encoding="utf-8")
    args.network_audit.write_text(
        json.dumps({"network_disabled": True, "attempts": attempts}, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
