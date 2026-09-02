from __future__ import annotations

from pathlib import Path


def test_quality_workflow_is_offline_and_cannot_skip_the_semantic_gate() -> None:
    workflow = (Path(__file__).parents[1] / ".github/workflows/quality.yml").read_text("utf-8")

    assert 'HF_HUB_OFFLINE: "1"' in workflow
    assert 'TRANSFORMERS_OFFLINE: "1"' in workflow
    assert 'HF_HUB_DISABLE_TELEMETRY: "1"' in workflow
    assert 'python -m pip install -e ".[dev]"' in workflow
    assert 'python -m pytest -m "not model_integration"' in workflow
    assert "jgrad-check-retrieval-gate" in workflow
    assert "Confirm no Hugging Face cache was created" in workflow
    assert "continue-on-error" not in workflow
