"""Replay EXAM-02A design states on main's actual four-step HTML and CSS.

No product server or POST: only /app and /assets/app.css are served in memory.
All non-examination data is labelled as a structural placeholder.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
STATIC = ROOT / "src/jgrad_admission_rag/service/static"
OUT = HERE / "exam02a-evidence"
EDGE = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
ORIGIN = "http://exam02a-candidate.test"
BASE = "8f12010fbac6dd6b9781259d92448e18ada63a35"

SAMPLES = {
    "simple": {
        "college": "工学院", "department": "システム制御系", "page": "31",
        "lead": "学校公布的 B 日程：2026 年 8 月 18 日 9:30–11:30（日本时间）",
        "subjects": "数学：微积分、线性代数、傅里叶／拉普拉斯变换、微分方程、概率统计。",
        "selection": "本册没有写选答数量；暂不推断是否全部作答。",
        "points": "专业笔试 150 分，外部英语成绩 50 分。",
        "oral": "学校公布的 A 日程为 7 月 11 日线上口述；B 日程口述为 8 月 24 日，资格者参加。查看某一日程不表示本人获准参加。",
        "report": "考试安排（学校公布的日程；本人适用路径待学校确认）：A 日程为 2026 年 7 月 11 日线上口述。B 日程专业笔试为 2026 年 8 月 18 日 9:30–11:30，科目为数学，范围包括微积分、线性代数、傅里叶／拉普拉斯变换、微分方程、概率统计；本册未载选答数量。专业笔试 150 分，外部英语成绩 50 分。B 日程口述为 8 月 24 日，仅资格者参加。",
    },
    "complex": {
        "college": "環境・社会理工学院", "department": "建築学系", "page": "60–61",
        "lead": "学校公布的 B 日程：2026 年 8 月 18 日，共通 10:00–11:30",
        "subjects": "共通六领域：建筑规划、城市与城镇建设、建筑结构与结构力学、建筑环境与设备工程、建筑材料与施工、建筑历史与设计。",
        "selection": "六领域各出 2 小题，共 12 题全部作答；另按申请时所有志愿导师的共同指定，选专门 A 即日设计（13:30–17:30）或专门 B 建筑学科目（13:30–15:30，六领域选一，历史与设计为小论文）。",
        "points": "专业笔试 500 分；本系表未载英语配分。",
        "oral": "学校公布的 A 日程为 7 月 11 日口述；B 日程口述为 8 月 25 日。专门科目 A/B 与招生 A/B 日程不同；尚未确认导师指定时不替申请人选科目。",
        "report": "考试安排（学校公布的日程；本人适用路径待学校确认）：A 日程为 2026 年 7 月 11 日口述。B 日程在 2026 年 8 月 18 日有共通笔试 10:00–11:30，建筑规划、城市与城镇建设、建筑结构与结构力学、建筑环境与设备工程、建筑材料与施工、建筑历史与设计六领域各出 2 小题，共 12 题全答；专业笔试 500 分。专门 A 即日设计为 13:30–17:30，或专门 B 建筑学科目为 13:30–15:30，须按申请时所有志愿导师的共同指定选择；当前未替申请人选定。B 日程口述为 8 月 25 日。",
    },
}


def run_case(browser, sample_name: str, state: str, width: int, height: int) -> dict:
    html = (STATIC / "advanced.html").read_text(encoding="utf-8")
    html = html.replace('<script src="/assets/overview.js" defer></script>', "")
    html = html.replace('<script src="/assets/app.js" defer></script>', "")
    page = browser.new_page(viewport={"width": width, "height": height})
    errors: list[str] = []
    calls: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))

    def route_request(route) -> None:
        path = urlparse(route.request.url).path
        calls.append(f"{route.request.method} {path}")
        if path == "/app":
            route.fulfill(body=html, content_type="text/html; charset=utf-8")
        elif path == "/assets/app.css":
            route.fulfill(body=(STATIC / "app.css").read_bytes(), content_type="text/css")
        else:
            route.abort()
            raise AssertionError(f"unexpected request: {path}")

    page.route("**/*", route_request)
    assert page.goto(f"{ORIGIN}/app").status == 200
    page.add_style_tag(content=".candidate-jump{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:20px}.candidate-jump button{width:auto}.requirements-output>.result-section{margin-top:20px}.requirements-output>*{min-width:0}")
    page.evaluate("({sample,state})=>{window.candidateSample=sample;window.candidateState=state}", {"sample": SAMPLES[sample_name], "state": state})
    page.add_script_tag(path=str(HERE / "exam02a-candidate-state.js"))
    assert page.evaluate("window.candidateReady")
    assert page.locator(".application-flow > .flow-step").count() == 4
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    if state == "exam":
        for target in ("dates", "materials", "exam"):
            page.locator(f".candidate-jump [data-target={target}]").click()
            assert page.locator(f"#candidate-{target}").evaluate("e => e === document.activeElement")
        page.locator("#candidate-exam details summary").click()
        assert page.locator("#candidate-exam details").get_attribute("open") is not None
        page.locator("#candidate-exam button").click()
        assert page.locator("#evidence-drawer").is_visible()
        page.locator("#drawer-close").click()
        assert not page.locator("#evidence-drawer").is_visible()
        page.locator("#step-2-panel .reference-generate").click()
        assert not page.locator("#candidate-exam-topic").is_checked()
        page.locator("#reference-copy").click()
        default_copy = page.evaluate("window.copiedText")
        assert "考试安排（学校公布" not in default_copy
        page.locator("#candidate-exam-topic").check()
        page.locator("#reference-copy").click()
        copied = page.evaluate("window.copiedText")
        assert SAMPLES[sample_name]["subjects"].split("：")[-1].split("、")[0] in copied
        assert "如上" not in copied
        if width > 600:
            (OUT / f"{sample_name}-report-default.txt").write_text(default_copy + "\n", encoding="utf-8")
            (OUT / f"{sample_name}-report-exam.txt").write_text(copied + "\n", encoding="utf-8")
        page.locator("#reference-close").click()
    else:
        assert page.locator("#readiness-panel").is_visible()
        assert page.locator("#step-3-summary .edit-step").is_visible()
        assert page.locator("#comparison-output .requirement-card").is_visible()
    assert not errors, errors
    assert all(x in ("GET /app", "GET /assets/app.css") for x in calls), calls
    page.evaluate("window.scrollTo(0, 0)")
    label = "desktop" if width > 600 else "mobile"
    path = OUT / f"{sample_name}-{state}-{label}.png"
    page.screenshot(path=str(path), full_page=True)
    result = {"sample": sample_name, "state": state, "viewport": [width, height], "screenshot": path.name, "requests": calls, "page_errors": errors}
    page.close()
    return result


def main() -> None:
    for name in ("advanced.html", "app.css"):
        baseline = subprocess.run(
            ["git", "show", f"{BASE}:src/jgrad_admission_rag/service/static/{name}"],
            cwd=ROOT, capture_output=True, check=True,
        ).stdout
        assert (STATIC / name).read_bytes() == baseline, f"{name} differs from reviewed main"
    OUT.mkdir(exist_ok=True)
    results = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=str(EDGE))
        for sample in SAMPLES:
            for state in ("exam", "readiness"):
                for width, height in ((1440, 900), (390, 844)):
                    results.append(run_case(browser, sample, state, width, height))
        browser.close()
    (OUT / "current-page-replay.json").write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{len(results)} current-page static states, no product POST/service")


if __name__ == "__main__":
    main()
