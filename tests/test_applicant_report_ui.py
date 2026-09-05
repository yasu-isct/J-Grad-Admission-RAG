from __future__ import annotations

from pathlib import Path


STATIC_ROOT = Path(__file__).parents[1] / "src" / "jgrad_admission_rag" / "service" / "static"


def test_report_ui_has_separate_accessible_workflow_and_explicit_unknowns() -> None:
    html = (STATIC_ROOT / "app.html").read_text(encoding="utf-8")
    assert 'role="tablist"' in html
    assert 'role="tab"' in html
    assert 'role="tabpanel"' in html
    assert "申請条件レポート" in html
    assert "部分的な規則範囲" in html
    assert "不要な個人情報" in html
    assert "入力と結果を消去" in html
    assert html.count('<option value="">不明</option>') >= 5
    for field_id in (
        "graduate-school",
        "department-program",
        "degree-level",
        "intake-year",
        "intake-month",
        "application-route",
        "credential-country",
        "credential-degree-level",
        "credential-basis",
        "completion-state",
        "completion-date",
        "expected-completion-date",
        "years-of-education",
        "age-at-enrollment",
        "professional-months",
        "research-months",
        "review-status",
        "review-requested",
        "review-completed",
    ):
        assert f'for="{field_id}"' in html
        assert f'id="{field_id}"' in html


def test_report_ui_builds_exact_profile_and_server_owned_intent_flow() -> None:
    javascript = (STATIC_ROOT / "app.js").read_text(encoding="utf-8")
    assert 'const INTENT_ENDPOINT = "/v1/query-intents/parse"' in javascript
    assert 'const REPORT_ENDPOINT = "/v1/applicant-reports"' in javascript
    assert 'report_id: "local-ui-report"' in javascript
    assert "citizenship_country_codes: null" in javascript
    assert "current_residence_country_code: null" in javascript
    assert "residence_status_category: null" in javascript
    assert "academic_credentials: academicCredentials()" in javascript
    assert 'credential_basis: nullableText("credential-basis")' in javascript
    assert 'completion_date: nullableText("completion-date")' in javascript
    assert 'expected_completion_date: nullableText("expected-completion-date")' in javascript
    assert 'years_of_education: nullableInteger("years-of-education")' in javascript
    assert "language_test_results: null" in javascript
    assert 'return value === "" ? null : value === "true"' in javascript
    assert 'if (raw === "") return null' in javascript
    assert "reportRequest(item, profile, intentPayload)" in javascript
    assert "if (reportPending) return" in javascript
    assert "parse_query_intent" not in javascript


def test_report_ui_renders_only_safe_structured_report_fields() -> None:
    javascript = (STATIC_ROOT / "app.js").read_text(encoding="utf-8")
    for field in (
        "reviewed_coverage_statement",
        "limitation_statement",
        "report_status",
        "rule_findings",
        "missing_information",
        "interaction_warnings",
        "process_notices",
        "evidence_records",
        "source_plan",
        "annotation_note",
        "source_pages",
    ):
        assert field in javascript
    assert "payload.markdown" not in javascript
    assert "source_kb_sha256" not in javascript
    assert "source_pdf_sha256" not in javascript
    for forbidden in (
        "innerHTML",
        "outerHTML",
        "insertAdjacentHTML",
        "document.write",
        "eval(",
        "local" + "Storage",
        "session" + "Storage",
        "indexedDB",
        "document.cookie",
        "service" + "Worker",
        "console.",
        "window.location",
        "URLSearchParams",
    ):
        assert forbidden not in javascript


def test_report_ui_has_responsive_report_layout_and_visible_focus() -> None:
    css = (STATIC_ROOT / "app.css").read_text(encoding="utf-8")
    assert ".report-grid" in css
    assert ".form-grid" in css
    assert '.tab-button[aria-selected="true"]' in css
    assert "input:focus-visible" in css
    assert "@media (max-width: 760px)" in css
