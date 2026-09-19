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
        "coursework-in-japan",
        "program-duration-years",
        "institution-recognition-status",
        "program-designation-status",
        "completion-timing-verification-status",
        "person-designation-status",
        "years-enrolled-at-eligibility-cutoff",
        "prescribed-credits-excellence-status",
        "institution-is-target-university",
        "gpt-after-two-years",
        "credits-after-two-years",
        "required-specialization-courses-status",
        "expected-specialist-credits",
        "liberal-arts-requirements-status",
        "prior-education-category",
        "sixteen-year-equivalence-status",
        "ministerial-course-standard-status",
        "ministerial-completion-deadline-status",
        "years-enrolled-before-withdrawal",
        "under-sixteen-year-country-status",
        "university-education-completion-status",
        "post-university-research-months-at-eligibility-cutoff",
        "graduate-equivalent-recognition-status",
        "age-at-enrollment",
        "professional-months",
        "research-months",
        "review-status",
        "review-requested",
        "review-completed",
        "age-at-eligibility-cutoff",
        "materials-arrival-date",
        "materials-dispatched-date",
        "online-steps-completed",
        "a-schedule-oral-participation",
        "current-residence-country",
        "special-accommodation-needed",
        "special-accommodation-contacted",
        "foreign-national-rule-applies",
        "residence-status-valid-until",
        "long-term-stay-allowed",
        "residence-status-contacted",
        "visa-arrangements-needed",
        "visa-advisor-consulted",
        "transcript-unavailable-reason",
        "transcript-contacted",
        "disaster-fee-consultation-needed",
        "disaster-fee-contacted",
        "scholarship-status",
        "scholarship-copy-emailed-date",
        "scholarship-method-received",
        "language-test-kind",
        "language-test-date",
        "language-test-score",
        "language-test-selected",
        "language-score-submission-method",
        "language-score-expected-arrival-date",
        "language-score-registered-mail",
        "language-score-replacement-after-deadline",
        "language-online-pdf",
        "toeic-qr-present",
        "toeic-digital-certificate",
        "toefl-score-report",
        "toefl-g179",
        "ets-paper-applicant",
        "ets-paper-institution",
    ):
        assert f'for="{field_id}"' in html
        assert f'id="{field_id}"' in html
    for submission_method in (
        "with_application",
        "department_later_by_mail",
        "written_exam_day_carry",
        "no_external_submission",
        "other",
    ):
        assert f'<option value="{submission_method}">' in html


def test_demo01_ui_has_cascading_target_requirements_and_evidence_drawer() -> None:
    html = (STATIC_ROOT / "app.html").read_text(encoding="utf-8")
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
    assert 'const TARGET_CATALOG_ENDPOINT = "/v1/target-catalog"' in javascript
    assert 'const BASE_REQUIREMENTS_ENDPOINT = "/v1/base-requirements"' in javascript
    assert "handleDemoTargetChange" in javascript
    assert "clearDemoResults" in javascript
    assert "evidenceDrawer.showModal()" in javascript
    assert "drawerTrigger.focus()" in javascript
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
    assert 'coursework_in_japan: nullableBoolean("coursework-in-japan")' in javascript
    assert 'program_duration_years: nullableInteger("program-duration-years")' in javascript
    assert (
        'institution_recognition_status: nullableText("institution-recognition-status")'
        in javascript
    )
    assert "completion_timing_verification_status: nullableText(" in javascript
    assert '"completion-timing-verification-status"' in javascript
    assert "years_enrolled_at_eligibility_cutoff: nullableInteger(" in javascript
    assert "prescribed_credits_excellence_status: nullableText(" in javascript
    assert (
        'institution_is_target_university: nullableBoolean("institution-is-target-university")'
        in javascript
    )
    assert 'gpt_after_two_years: nullableNumber("gpt-after-two-years")' in javascript
    assert 'credits_after_two_years: nullableInteger("credits-after-two-years")' in javascript
    assert "required_specialization_courses_expected_status: nullableText(" in javascript
    assert (
        'expected_specialist_credits: nullableInteger("expected-specialist-credits")' in javascript
    )
    assert "liberal_arts_requirements_expected_status: nullableText(" in javascript
    assert 'prior_education_category: nullableText("prior-education-category")' in javascript
    assert "sixteen_year_equivalence_status: nullableText(" in javascript
    assert "ministerial_completion_deadline_status: nullableText(" in javascript
    assert "post_university_research_months_at_eligibility_cutoff: nullableInteger(" in javascript
    assert '"post-university-research-months-at-eligibility-cutoff"' in javascript
    assert "graduate_equivalent_recognition_status: nullableText(" in javascript
    assert 'age_at_eligibility_cutoff: nullableInteger("age-at-eligibility-cutoff")' in javascript
    assert 'materials_arrival_date: nullableText("materials-arrival-date")' in javascript
    assert 'materials_dispatched_date: nullableText("materials-dispatched-date")' in javascript
    assert 'online_steps_completed: nullableBoolean("online-steps-completed")' in javascript
    assert "a_schedule_oral_exam_participation_planned: nullableBoolean(" in javascript
    assert '"a-schedule-oral-participation"' in javascript
    assert 'current_residence_country_code: nullableText("current-residence-country")' in javascript
    assert "preapplication_actions: {" in javascript
    assert (
        'special_accommodation_needed: nullableBoolean("special-accommodation-needed")'
        in javascript
    )
    assert (
        'foreign_national_rule_applies: nullableBoolean("foreign-national-rule-applies")'
        in javascript
    )
    assert (
        'residence_status_valid_until: nullableText("residence-status-valid-until")' in javascript
    )
    assert (
        'residence_status_allows_long_term_stay: nullableBoolean("long-term-stay-allowed")'
        in javascript
    )
    assert 'visa_timing_consulted_advisor: nullableBoolean("visa-advisor-consulted")' in javascript
    assert (
        'transcript_unavailable_reason: nullableText("transcript-unavailable-reason")' in javascript
    )
    assert (
        'disaster_fee_consulted_admissions: nullableBoolean("disaster-fee-contacted")' in javascript
    )
    assert (
        'scholarship_copy_emailed_date: nullableText("scholarship-copy-emailed-date")' in javascript
    )
    assert "language_test_results: languageTestResults()" in javascript
    assert 'test_kind: nullableText("language-test-kind")' in javascript
    assert 'selected_for_submission: nullableBoolean("language-test-selected")' in javascript
    assert (
        'score_sheet_submission_method: nullableText("language-score-submission-method")'
        in javascript
    )
    assert (
        "score_sheet_expected_arrival_date: nullableText("
        '"language-score-expected-arrival-date")' in javascript
    )
    assert (
        "score_sheet_registered_mail_planned: nullableBoolean("
        '"language-score-registered-mail")' in javascript
    )
    assert "score_sheet_replacement_after_deadline_planned: nullableBoolean(" in javascript
    assert '"language-score-replacement-after-deadline"' in javascript
    assert 'toefl_di_code_g179_set: nullableBoolean("toefl-g179")' in javascript
    assert 'return value === "" ? null : value === "true"' in javascript
    assert 'if (raw === "") return null' in javascript
    assert "reportRequest(item, profile, intentPayload)" in javascript
    assert "if (reportPending) return" in javascript
    assert (
        'finding.disposition === "active" && reviewedRule && reviewedRule.annotation_note'
        in javascript
    )
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


def test_report_ui_renders_exact_language_score_conversion() -> None:
    javascript = (STATIC_ROOT / "app.js").read_text(encoding="utf-8")

    assert "英語外部試験の換算" in javascript
    assert 'addMetadata(details, "入力試験", conversionResult.input_test_kind' in javascript
    assert 'addMetadata(details, "入力得点", conversionResult.input_score' in javascript
    assert 'addMetadata(details, "状態", conversionResult.status)' in javascript
    assert 'addMetadata(details, "結果形態", conversionResult.result_shape)' in javascript
    assert "conversionResult.evidence_binding.fact_id" in javascript
    assert "conversionResult.evidence_binding.source_pages.join" in javascript
    assert 'appendConversionCandidates(conversion, "PBT"' in javascript
    assert 'appendConversionCandidates(conversion, "TOEIC L&R"' in javascript
    assert "formatExactInterval(candidate)" in javascript
    assert "value.numerator}/${value.denominator}" in javascript
