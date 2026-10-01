from __future__ import annotations

import json
from pathlib import Path


STATIC_ROOT = Path(__file__).parents[1] / "src" / "jgrad_admission_rag" / "service" / "static"
FIXTURE_ROOT = Path(__file__).parent / "fixtures"


def test_rule04a_browser_acceptance_record_covers_scenarios_and_viewports() -> None:
    records = json.loads(
        (FIXTURE_ROOT / "rule04a_browser_acceptance_v1.json").read_text(encoding="utf-8")
    )
    scenarios = {
        "toeic-valid-boundary",
        "date-before-boundary",
        "toefl-ibt-valid",
        "toeic-missing-qr",
        "math-written-exam",
        "language-result-unknown",
    }
    assert len(records) == 12
    assert {(item["viewport"], item["scenario"]) for item in records} == {
        (viewport, scenario) for viewport in ("desktop", "mobile") for scenario in scenarios
    }
    assert all(item["horizontal_overflow"] is False for item in records)
    assert all(item["limitation"] for item in records)
    assert all(item["rules"] for item in records)
    assert all(
        evidence["source_pages"]
        for item in records
        for rule in item["rules"]
        for evidence in rule["evidence"]
    )

    toeic_records = [item for item in records if item["scenario"] == "toeic-valid-boundary"]
    for item in toeic_records:
        approved = next(
            rule for rule in item["rules"] if "approved-kind-toeic_lr" in rule["rule_id"]
        )
        assert approved["evidence"] == [{"fact_id": "fact:00110", "source_pages": [11]}]


def test_four_step_report_remains_and_legacy_low_frequency_form_is_removed() -> None:
    html = (STATIC_ROOT / "advanced.html").read_text(encoding="utf-8")
    for retained in (
        'id="reference-report"',
        'id="reference-copy"',
        'id="reference-report-body"',
        'id="reference-close"',
        'id="applicant-form"',
    ):
        assert retained in html
    for obsolete in (
        'id="report-form"',
        'id="report-view"',
        'id="graduate-school"',
        'id="visa-arrangements-needed"',
    ):
        assert obsolete not in html
    assert 'id="demo-completion-date"' in html
    assert 'id="demo-arrival-date"' in html
    assert 'id="demo-toeic-qr"' in html


def test_demo01_ui_has_cascading_target_requirements_and_evidence_drawer() -> None:
    html = (STATIC_ROOT / "advanced.html").read_text(encoding="utf-8")
    css = (STATIC_ROOT / "app.css").read_text(encoding="utf-8")
    javascript = (STATIC_ROOT / "app.js").read_text(encoding="utf-8")

    assert 'lang="zh-CN"' in html
    assert "申请检查向导" in html
    for field_id in (
        "school-select",
        "demo-degree-select",
        "intake-select",
        "college-select",
        "department-select",
        "route-select",
    ):
        assert f'<label for="{field_id}">' in html
        assert f'id="{field_id}"' in html
    assert '<dialog id="evidence-drawer"' in html
    assert 'aria-labelledby="drawer-title"' in html
    assert "技术详情" in javascript
    assert 'const TARGET_CATALOG_ENDPOINT = "/v1/reference-targets"' in javascript
    assert 'const BASE_REQUIREMENTS_ENDPOINT = "/v1/base-requirements"' in javascript
    assert "handleDemoTargetChange" in javascript
    assert "clearDemoResults" in javascript
    assert "evidenceDrawer.showModal()" in javascript
    assert "drawerTrigger?.isConnected" in javascript
    assert "drawerTrigger.focus({preventScroll: true})" in javascript
    assert "new AbortController()" in javascript
    assert "requirementsRequestId" in javascript
    assert "referenceCore.scopeKey(currentReferenceScope()) !== requestSnapshot" in javascript
    assert (
        'setMessage(targetStatus, "initial", "申请目标已改变，请完成选择后重新加载要求。")'
        in javascript
    )
    assert "请在文件中查看该页" in javascript
    assert "textContent" in javascript
    assert "innerHTML" not in javascript
    assert "localStorage" not in javascript
    assert "sessionStorage" not in javascript
    assert "東京科学大学" not in javascript
    assert "http://" not in javascript
    assert "https://" not in javascript
    assert ".demo-shell" in css
    assert ".evidence-drawer" in css
    assert "100dvh" in css
    assert "@media (max-width: 760px)" in css


def test_demo02_ui_collects_minimal_profile_and_invalidates_stale_comparisons() -> None:
    html = (STATIC_ROOT / "advanced.html").read_text(encoding="utf-8")
    javascript = (STATIC_ROOT / "app.js").read_text(encoding="utf-8")

    for field_id in (
        "demo-credential-basis",
        "demo-completion-state",
        "demo-english-kind",
        "demo-english-score",
        "demo-english-date",
        "demo-english-report",
        "demo-japanese-background",
    ):
        assert f'for="{field_id}"' in html
        assert f'id="{field_id}"' in html
    assert html.count("data-material-code=") == 5
    assert 'const APPLICANT_COMPARISON_ENDPOINT = "/v1/applicant-comparison"' in javascript
    assert "demoApplicantInput" in javascript
    assert "comparisonRequestId" in javascript
    assert "comparisonController = new AbortController()" in javascript
    assert "requestSnapshot !== JSON.stringify(demoComparisonRequest())" in javascript
    assert 'applicantForm.addEventListener("input",' in javascript
    assert "baseRequirementsLoaded = false" in javascript
    assert 'id="readiness-panel"' in html
    assert html.count('name="readiness-filter"') == 4
    assert "item.action_group" in javascript
    assert "item.next_action" in javascript
    assert "applyReadinessFilter" in javascript
    assert "payload.counts.total !== payload.items.length" in javascript
    assert 'clearComparison("正在由服务端对照个人情况与审核规则。")' in javascript
    assert 'clearComparison("个人情况暂时无法对照，请检查输入后重试。")' in javascript
    assert 'role="status" aria-live="polite" hidden>当前筛选下没有项目。' in html
    assert "localStorage" not in javascript
    assert "sessionStorage" not in javascript


def test_current_report_uses_loaded_evidence_and_validated_comparison() -> None:
    javascript = (STATIC_ROOT / "app.js").read_text(encoding="utf-8")
    core = (STATIC_ROOT / "unified-core.mjs").read_text(encoding="utf-8")
    assert "referenceCore.legacyReport(loadedReference" in javascript
    assert "referenceCore.sliceReport(scope, loadedReference" in javascript
    assert "validateEnglishPreparationResult(mapped.scope, comparison)" in core
    assert "validateApplicationPreparationResult(mapped.scope, comparison)" in core
    assert 'const APPLICANT_COMPARISON_ENDPOINT = "/v1/applicant-comparison"' in javascript
    assert 'const REPORT_ENDPOINT = "/v1/applicant-reports"' not in javascript
    assert "parse_query_intent" not in javascript


def test_current_report_uses_safe_structured_rendering() -> None:
    javascript = (STATIC_ROOT / "app.js").read_text(encoding="utf-8")
    assert "referenceReader.text" in javascript
    assert "content.append" in javascript
    assert "payload.markdown" not in javascript
    for forbidden in (
        "innerHTML",
        "outerHTML",
        "insertAdjacentHTML",
        "document.write",
        "eval(",
        "localStorage",
        "sessionStorage",
    ):
        assert forbidden not in javascript


def test_current_report_has_responsive_layout_and_visible_focus() -> None:
    css = (STATIC_ROOT / "app.css").read_text(encoding="utf-8")
    assert ".reference-report" in css
    assert "input:focus-visible" in css
    assert "@media (max-width: 760px)" in css


def test_current_report_keeps_english_preparation_projection() -> None:
    javascript = (STATIC_ROOT / "app.js").read_text(encoding="utf-8")
    assert "view.english" in javascript
    assert 'addSection("英语成绩与证明"' in javascript
