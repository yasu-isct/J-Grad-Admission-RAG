// Design-only state on the checked-in advanced.html skeleton; no product API calls.
(() => {
  const sample = window.candidateSample;
  const state = window.candidateState;
  const id = (value) => document.getElementById(value);
  const make = (tag, className, value) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (value !== undefined) node.textContent = value;
    return node;
  };
  const scope = `东京科学大学／${sample.college}／${sample.department}／修士／2027 年 4 月入学`;
  id("current-target-bar").hidden = false;
  id("current-target-name").textContent = scope;
  document.querySelector(".intro").append(make("p", "field-detail", "设计审核静态样例：考试资料来自本册系表；非考试内容保留当前四步页的结构占位，不代表该系真实响应或个人结论。"));

  for (const [number, phase] of [[1, "complete"], [2, state === "exam" ? "current" : "complete"], [3, state === "exam" ? "locked" : "complete"], [4, state === "exam" ? "locked" : "current"]]) {
    const nav = id(`step-nav-${number}`);
    nav.dataset.state = phase;
    nav.querySelector("small").textContent = phase === "complete" ? "已完成" : phase === "current" ? "当前" : "未开始";
    if (phase === "current") nav.setAttribute("aria-current", "step"); else nav.removeAttribute("aria-current");
  }
  id("step-1-panel").dataset.stepState = "complete";
  id("step-1-content").hidden = true;
  id("step-1-summary").hidden = false;
  id("step-1-summary-text").textContent = scope;
  id("edit-target").addEventListener("click", () => id("step-1-panel").scrollIntoView());
  id("step-2-panel").hidden = false;
  id("step-2-panel").dataset.stepState = state === "exam" ? "current" : "complete";
  id("step-2-badge").textContent = state === "exam" ? "当前" : "已完成";
  id("step-2-content").hidden = state !== "exam";
  id("step-2-summary").hidden = state === "exam";
  id("step-2-summary-text").textContent = "关键时间 · 材料 · 考试安排";
  id("target-summary").textContent = scope;
  id("edit-requirements").addEventListener("click", () => id("step-2-panel").scrollIntoView());

  const output = id("requirements-output");
  output.replaceChildren();
  const nav = make("nav", "candidate-jump");
  nav.setAttribute("aria-label", "第二步内容定位");
  for (const [key, label] of [["dates", "关键时间"], ["materials", "出愿材料"], ["exam", "考试安排"]]) {
    const button = make("button", "secondary", label);
    button.type = "button";
    button.dataset.target = key;
    button.addEventListener("click", () => {
      const target = id(`candidate-${key}`);
      target.scrollIntoView({block: "start"});
      target.focus({preventScroll: true});
    });
    nav.append(button);
  }
  output.append(nav);
  function section(key, title, help) {
    const node = make("section", "result-section");
    node.id = `candidate-${key}`;
    node.tabIndex = -1;
    node.append(make("h3", "", title), make("p", "field-detail", help));
    output.append(node);
    return node;
  }
  const dates = section("dates", "关键时间", "这里沿用当前目标的已审日期规则卡；本静态样例不代填截止日。");
  const dateCard = make("article", "requirement-card");
  dateCard.append(make("h4", "", "出愿与材料送达"), make("p", "", "正式页面从现有基础要求响应显示日期；寄出不等于送达。"));
  dates.append(dateCard);
  const materials = section("materials", "出愿材料", "这里沿用当前目标的材料要求与中文准备指南。");
  const materialCard = make("article", "requirement-card");
  materialCard.append(make("h4", "", "申请表与证明材料"), make("p", "", "正式材料清单仍由当前目标的既有响应生成。"));
  const guide = make("details", "preparation-guide-details");
  guide.append(make("summary", "", "展开材料准备说明"), make("p", "", "继续使用原四步页已有的中文材料指南和原文入口。"));
  materialCard.append(guide);
  materials.append(materialCard);

  const exam = section("exam", "考试安排 · 学校公布的 A/B 日程", "查阅某一日程不表示申请人获准参加；由学校确认实际路径。");
  exam.classList.add("exam-arrangement");
  exam.append(make("p", "exam-lead", sample.lead), make("h4", "", "考什么"), make("p", "", sample.subjects), make("h4", "", "怎么选答"), make("p", "", sample.selection), make("p", "", sample.points));
  const oral = make("details", "");
  oral.append(make("summary", "", "口述、路径与适用条件"), make("p", "", sample.oral));
  exam.append(oral);
  const source = make("button", "secondary", "查看官方原文");
  source.type = "button";
  source.addEventListener("click", () => {
    id("drawer-title").textContent = "官方依据 · 考试安排";
    id("drawer-content").textContent = `固定资料物理／印刷 p.${sample.page}；正式产品沿用已审核原文窗口。`;
    id("evidence-drawer").showModal();
    id("drawer-close").onclick = () => { id("evidence-drawer").close(); source.focus(); };
  });
  exam.append(source);

  id("applicant-panel").hidden = state === "exam";
  id("applicant-panel").dataset.stepState = "complete";
  id("step-3-badge").textContent = "已完成";
  id("step-3-content").hidden = true;
  id("step-3-summary").hidden = false;
  id("step-3-summary-text").textContent = "未填写个人情况；可返回修改";
  id("edit-applicant").addEventListener("click", () => {
    id("step-3-content").hidden = false;
    id("step-3-summary").hidden = true;
    id("applicant-panel").dataset.stepState = "current";
  });
  id("readiness-panel").hidden = state === "exam";
  id("readiness-panel").dataset.stepState = "current";
  id("step-4-badge").textContent = "当前";
  id("readiness-target").textContent = scope;
  id("partial-checklist-statement").textContent = "静态样例未对照个人情况；以下仅保留现有待办区域结构。";
  id("priority-actions").replaceChildren(make("p", "", "当前没有个人对照结果；材料待办由原第四步在核对后生成。"));
  const todo = make("article", "requirement-card");
  todo.append(make("h3", "", "材料准备待办"), make("p", "", "未填写、条件不明与明确缺项仍由既有规则分别标记；本样例不生成个人结论。"));
  const todoDetails = make("details", "preparation-guide-details");
  todoDetails.append(make("summary", "", "按需查看材料指南"), make("p", "", "真实响应保持已有中文指南与原文入口。"));
  todo.append(todoDetails);
  id("comparison-output").replaceChildren(todo);
  id("generation-mode-label").textContent = "示意 · 未调用问答";
  id("grounded-context").textContent = scope;

  const report = id("reference-report");
  const reportBody = id("reference-report-body");
  let copiedText = "";
  function reportText(includeExam) {
    const base = `参考报告（静态样例）\n目标：${scope}\n关键时间与材料：由当前目标的真实基础要求响应填写。`;
    return includeExam ? `${base}\n${sample.report}` : base;
  }
  function openReport() {
    reportBody.replaceChildren();
    const choices = make("fieldset", "reader-report-options");
    choices.append(make("legend", "", "选择报告内容"));
    const label = make("label", "");
    const checkbox = make("input", "");
    checkbox.type = "checkbox";
    checkbox.id = "candidate-exam-topic";
    label.append(checkbox, document.createTextNode("考试安排（可选）"));
    choices.append(label);
    const paper = make("div", "reader-report-paper");
    const title = make("div", "reader-report-title");
    title.append(make("h3", "", "出愿准备参考"));
    const content = make("section", "reader-report-section");
    function refresh() { content.textContent = reportText(checkbox.checked); copiedText = content.textContent; }
    checkbox.addEventListener("change", refresh);
    refresh();
    paper.append(title, content);
    reportBody.append(choices, paper);
    report.showModal();
  }
  for (const button of document.querySelectorAll(".reference-generate")) {
    button.disabled = false;
    button.addEventListener("click", openReport);
  }
  id("reference-close").addEventListener("click", () => report.close());
  id("reference-copy").addEventListener("click", () => { window.copiedText = copiedText; id("reference-report-status").textContent = "已复制样例文字"; });
  window.candidateReady = true;
})();
