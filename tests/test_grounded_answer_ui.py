from pathlib import Path


STATIC_ROOT = Path(__file__).parents[1] / "src" / "jgrad_admission_rag" / "service" / "static"


def test_grounded_answer_is_independent_and_reuses_current_target_and_profile() -> None:
    html = (STATIC_ROOT / "app.html").read_text(encoding="utf-8")
    javascript = (STATIC_ROOT / "app.js").read_text(encoding="utf-8")

    assert html.index('id="readiness-panel"') < html.index('id="grounded-answer-panel"')
    assert html.index('id="grounded-answer-panel"') < html.index('id="evidence-drawer"')
    assert 'id="grounded-question"' in html
    assert 'id="grounded-answer-status"' in html
    assert 'id="grounded-answer-output"' in html
    assert 'id="generation-mode-label"' in html
    assert "target: demoTargetRequest()" in javascript
    assert "applicant: demoApplicantInput()" in javascript
    assert 'const GROUNDED_ANSWER_ENDPOINT = "/v1/natural-language-answers"' in javascript
    assert 'const GENERATION_STATUS_ENDPOINT = "/v1/generation-status"' in javascript
    assert "在线生成服务未配置" in javascript
    assert "generationModeLabel.textContent = generationStatus.label" in javascript
    assert 'auditSummary.textContent = "技术详情 / 审计信息"' in javascript
    assert "label.textContent = claim.kind" not in javascript


def test_grounded_answer_ui_fails_closed_and_uses_safe_dom_only() -> None:
    javascript = (STATIC_ROOT / "app.js").read_text(encoding="utf-8")

    for forbidden in (
        "innerHTML",
        "outerHTML",
        "insertAdjacentHTML",
        "localStorage",
        "sessionStorage",
        "document.cookie",
    ):
        assert forbidden not in javascript
    assert "textContent = claim.text" in javascript
    assert "groundedController.abort" in javascript
    assert "snapshot !== JSON.stringify(groundedRequestPayload())" in javascript
    assert "generation_provider_timeout" in javascript
    assert "invalid_citation" in javascript
    assert "insufficient_evidence" in javascript
    assert "openDemoEvidence" in javascript
    assert "verifiedLocalPdfHref" in javascript
    assert "payload.subanswers" in javascript
    assert 'item.status === "answered"' in javascript


def test_grounded_answer_layout_has_mobile_overflow_guards() -> None:
    css = (STATIC_ROOT / "app.css").read_text(encoding="utf-8")

    assert ".grounded-answer-panel" in css
    assert "overflow: hidden" in css
    assert ".grounded-claim" in css
    assert "overflow-wrap: anywhere" in css
    assert "@media (max-width: 760px)" in css
    assert ".grounded-source-actions { display: grid; }" in css
