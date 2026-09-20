from pathlib import Path


STATIC_ROOT = Path(__file__).parents[1] / "src" / "jgrad_admission_rag" / "service" / "static"


def test_progressive_flow_has_four_stateful_steps_and_safe_summaries() -> None:
    html = (STATIC_ROOT / "app.html").read_text(encoding="utf-8")
    javascript = (STATIC_ROOT / "app.js").read_text(encoding="utf-8")

    for number in range(1, 5):
        assert f'id="step-nav-{number}"' in html
        assert f'id="step-{number}-badge"' in html
    for number in range(1, 4):
        assert f'id="step-{number}-summary"' in html
    assert 'id="edit-target"' in html
    assert 'id="edit-requirements"' in html
    assert 'id="edit-applicant"' in html
    assert 'id="requirements-continue"' in html
    assert "updateFlowPresentation" in javascript
    assert "activateStep(4, true)" in javascript
    assert 'stale: "需要重新确认"' in javascript
    assert '已提供类别：${provided.length ? provided.join("、") : "无"}' in javascript
    assert (
        "demo-english-score"
        not in javascript.split("function updateApplicantStepSummary()", 1)[1]
        .split("function updateRequirementsSubmit()", 1)[0]
        .split("textContent", 1)[-1]
    )
    assert "localStorage" not in javascript
    assert "sessionStorage" not in javascript


def test_advanced_tools_are_native_collapsed_and_existing_functions_remain() -> None:
    html = (STATIC_ROOT / "app.html").read_text(encoding="utf-8")
    javascript = (STATIC_ROOT / "app.js").read_text(encoding="utf-8")

    assert '<details id="advanced-tools" class="advanced-tools">' in html
    assert "<strong>高级工具</strong>" in html
    assert '<form id="evidence-form"' in html
    assert '<form id="report-form"' in html
    assert 'const QUERY_ENDPOINT = "/v1/corpus/query"' in javascript
    assert 'const REPORT_ENDPOINT = "/v1/applicant-reports"' in javascript
    assert "innerHTML" not in javascript


def test_visual_system_uses_local_fonts_states_focus_and_reduced_motion() -> None:
    css = (STATIC_ROOT / "app.css").read_text(encoding="utf-8")

    assert "--color-primary:" in css
    assert "--color-success:" in css
    assert "--color-warning:" in css
    assert "--color-review:" in css
    assert 'font-family: -apple-system, BlinkMacSystemFont, "Segoe UI"' in css
    assert "summary:focus-visible" in css
    assert '.comparison-card[data-action-group="recorded"]' in css
    assert '.comparison-card[data-action-group="action_required"]' in css
    assert '.comparison-card[data-action-group="review_required"]' in css
    assert "@media (prefers-reduced-motion: reduce)" in css
    for forbidden in ("@import", "url(http:", "url(https:"):
        assert forbidden not in css


def test_frontend_does_not_add_rule_threshold_or_date_computation() -> None:
    javascript = (STATIC_ROOT / "app.js").read_text(encoding="utf-8")

    assert "requirement.deadline" in javascript
    assert "new Date(" not in javascript
    assert "Date.parse(" not in javascript
    assert "score >=" not in javascript
    assert "score <=" not in javascript
    assert "item.action_group" in javascript
    assert "card.dataset.actionGroup = item.action_group" in javascript
