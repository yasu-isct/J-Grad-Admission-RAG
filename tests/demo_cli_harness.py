"""Subprocess harness that supplies a synthetic reviewed config to jgrad-demo."""

from __future__ import annotations

import argparse
from pathlib import Path

from jgrad_admission_rag.demo_cli import main as demo_main


def main() -> None:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--config-dir", required=True)
    known, demo_arguments = parser.parse_known_args()
    demo_main(demo_arguments, config_dir=Path(known.config_dir))


if __name__ == "__main__":
    main()
