from pathlib import Path


STATIC_ROOT = Path(__file__).parents[1] / "src" / "jgrad_admission_rag" / "service" / "static"


def test_step_three_uses_four_native_keyboard_groups_with_text_states() -> None:
    html = (STATIC_ROOT / "app.html").read_text(encoding="utf-8")
    javascript = (STATIC_ROOT / "app.js").read_text(encoding="utf-8")
    css = (STATIC_ROOT / "app.css").read_text(encoding="utf-8")

    assert html.count('data-profile-group="') == 4
    for key in ("education", "english", "japanese", "materials"):
        assert '<details class="profile-group' in html
        assert f'data-profile-group="{key}"' in html
    assert html.count('class="profile-group-state" data-state="empty"') == 4
    assert "initializeProfileGroups()" in javascript
    assert 'window.matchMedia("(min-width: 761px)")' in javascript
    assert ".profile-group > summary" in css
    assert '.profile-group-state[data-state="complete"]' in css
    assert "summary:focus-visible" in css


def test_unknown_and_not_applicable_are_ui_only_and_submission_contract_is_unchanged() -> None:
    html = (STATIC_ROOT / "app.html").read_text(encoding="utf-8")
    javascript = (STATIC_ROOT / "app.js").read_text(encoding="utf-8")

    for state in ("未填写", "不知道", "不适用", "尚未取得"):
        assert state in html
    assert 'value && !value.startsWith("ui_") ? value : null' in javascript
    assert (
        'preparation: ["available", "not_yet"].includes(select.value) ? select.value : "unknown"'
        in javascript
    )
    assert 'value === "true" ? true : value === "false" ? false : null' in javascript
    assert "resetApplicantInputs();" in javascript
    assert '"english_test_kind"' not in html
    assert "localStorage" not in javascript
    assert "sessionStorage" not in javascript


def test_linked_english_help_and_evidence_limits_are_not_rule_judgments() -> None:
    html = (STATIC_ROOT / "app.html").read_text(encoding="utf-8")
    javascript = (STATIC_ROOT / "app.js").read_text(encoding="utf-8")

    assert 'id="english-link-hint"' in html
    assert 'aria-live="polite"' in html
    assert "服务端还需要考试类型" in javascript
    assert "成绩和考试日期可暂时留空" in javascript
    assert "日语信息目前只记录" in html
    assert "不会给出“已满足日语要求”的结论" in html
    assert "不代表内容有效、学校已收到或受理" in html
    assert "官方适用性在结果中单独显示" in html
    assert "score >=" not in javascript
    assert "score <=" not in javascript
