from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

import pytest

from jgrad_admission_rag.demo import load_demo_config
from tests.test_demo_cli import _free_port, _wait_json

pytestmark = pytest.mark.real_pdf


def test_real_pdf_starts_the_formal_demo_service(
    real_pdf_path: Path,
    tmp_path: Path,
) -> None:
    """Skip via the shared fixture when the private local PDF is unavailable."""

    workspace = (tmp_path / "real-demo").resolve()
    port = _free_port()
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "jgrad_admission_rag.demo_cli",
            "--pdf",
            str(real_pdf_path.resolve()),
            "--workspace",
            str(workspace),
            "--port",
            str(port),
        ],
        cwd=Path(__file__).resolve().parents[1],
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        base = f"http://127.0.0.1:{port}"
        assert _wait_json(f"{base}/v1/health/live", process)["ready"] is True
        assert _wait_json(f"{base}/v1/health/ready", process)["ready"] is True
        catalog = _wait_json(f"{base}/v1/target-catalog", process)
        identity = load_demo_config().identity
        assert catalog["schools"][0]["school_id"] == identity.institution_id
        assert catalog["schools"][0]["school_name"] == "東京科学大学"
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
