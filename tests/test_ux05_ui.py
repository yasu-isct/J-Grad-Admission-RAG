from pathlib import Path


STATIC = Path(__file__).parents[1] / "src" / "jgrad_admission_rag" / "service" / "static"


def test_step_four_separates_system_counts_from_personal_progress() -> None:
    html = (STATIC / "app.html").read_text(encoding="utf-8")
    js = (STATIC / "app.js").read_text(encoding="utf-8")

    assert 'id="action-summary-heading"' in html
    assert 'id="priority-actions"' in html
    assert 'aria-label="系统对照状态统计"' in html
    for field in ("total", "recorded", "action", "review"):
        assert f'id="count-{field}"' in html
    assert "payload.counts.action_required" in js
    assert "payload.counts.review_required" in js
    assert "payload.counts.recorded" in js
    assert 'item.action_group === "recorded"' in js
    assert "item.next_action" in js
    assert "item.description" in js
    assert "item.evidence" in js
    assert "item.limitation" in js
    assert "我的处理进度：已标记处理（仅个人记录）" in js
    assert (
        "学校已受理"
        not in js.split("function renderComparison(payload)", 1)[1].split(
            "function applyReadinessFilter()", 1
        )[0]
    )


def test_checkmarks_are_ephemeral_and_do_not_enter_api_payload() -> None:
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    comparison = js.split("function renderComparison(payload)", 1)[1].split(
        "function applyReadinessFilter()", 1
    )[0]
    request = js.split("function demoApplicantInput()", 1)[1].split(
        "function demoComparisonRequest()", 1
    )[0]

    assert 'checkbox.type = "checkbox"' in comparison
    assert 'checkbox.addEventListener("change"' in comparison
    assert 'card.dataset.handled = checkbox.checked ? "true" : "false"' in comparison
    assert "resetChecklistProgress(); activateStep(1, true)" in js
    assert "resetChecklistProgress(); activateStep(3, true)" in js
    assert "comparisonOutput.replaceChildren();" in js
    assert 'byId("priority-actions").replaceChildren();' in js
    assert "localStorage" not in js
    assert "sessionStorage" not in js
    assert "handled" not in request


def test_limitations_are_visible_without_conflating_recorded_with_satisfied() -> None:
    html = (STATIC / "app.html").read_text(encoding="utf-8")
    js = (STATIC / "app.js").read_text(encoding="utf-8")

    assert "材料实际到达、最终资格、申请完整性和录取均未由此验证" in html
    assert "刷新、修改目标、返回修改个人情况或重新对照都会清空勾选" in html
    assert "已记录仍不等于学校确认或完成出愿" in js
    assert 'progress.textContent = item.action_group === "recorded"' in js
    assert "official.textContent = `官方适用性：" in js
    assert "个人准备状态：" in js
    assert "已满足" not in html.split('id="readiness-panel"', 1)[1].split("</section>", 1)[0]
