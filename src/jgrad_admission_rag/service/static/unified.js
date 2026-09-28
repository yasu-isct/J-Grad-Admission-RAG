import {
  readyEntries, scopesFor, scopeKey, scopeLabel, hasSuppliedProfile,
  comparisonRequest, sliceReportRequest, mapLegacyBase, mapSliceEvidence,
  legacyReport, sliceReport, statusNames
} from "./unified-core.mjs";

const $ = (id) => document.getElementById(`uw-${id}`);
const selectors = ["school", "organization", "program", "degree", "edition", "intake", "route"];
const dimensions = selectors.slice(1);
const state = {
  entries: [], scopes: [], loaded: null, report: null, comparison: null,
  comparisonKey: null, generation: {target: 0, profile: 0, report: 0, comparison: 0, question: 0},
  controller: {target: null, report: null, comparison: null, question: null},
  generationStatus: null, evidenceTrigger: null, reportTrigger: null
};

function node(tag, content = "", className = "") {
  const result = document.createElement(tag);
  result.textContent = content;
  if (className) result.className = className;
  return result;
}
function appendText(parent, tag, content, className = "") {
  if (content) parent.append(node(tag, content, className));
}
function option(value, label) {
  const result = document.createElement("option");
  result.value = value;
  result.textContent = label;
  return result;
}
function unique(values) { return [...new Set(values.filter(Boolean))]; }
function safeSource(raw, page) {
  try {
    const url = new URL(raw);
    if (url.protocol !== "https:" || url.username || url.password) return null;
    if (Number.isSafeInteger(page) && page > 0) url.hash = `page=${page}`;
    return url.href;
  } catch { return null; }
}
function safeLocalPdf(raw, page) {
  return /^\/documents\/[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?\/source\.pdf$/.test(raw || "")
    && Number.isSafeInteger(page) && page > 0 ? `${raw}#page=${page}` : null;
}
function abortOperation(kind) {
  state.generation[kind] += 1;
  state.controller[kind]?.abort();
  state.controller[kind] = null;
}
function closeDialog(id) {
  const dialog = document.getElementById(id.startsWith("uw-") ? id : `uw-${id}`);
  if (dialog.open) dialog.close();
}
function clearReport(message = "当前目标或个人情况已变化，请按需重新生成。") {
  abortOperation("report");
  state.report = null;
  $("copy-fallback").value = "";
  $("copy-fallback").hidden = true;
  $("copy-fallback-label").hidden = true;
  $("copy-status").textContent = "";
  $("report-body").replaceChildren();
  $("report-status").textContent = message;
  closeDialog("report");
  $("generate").disabled = !state.loaded;
}
function clearComparison() {
  abortOperation("comparison");
  state.comparison = null;
  state.comparisonKey = null;
  $("comparison-panel").hidden = true;
  $("comparison-items").replaceChildren();
}
function invalidateProfile() {
  state.generation.profile += 1;
  abortOperation("question");
  $("qa-result").replaceChildren();
  $("qa-status").textContent = "个人情况已更新；如需参考问答，请重新提问。";
  clearComparison();
  clearReport("个人情况已更新，下一份报告将采用新信息。");
  updateQuestionAvailability();
}
function invalidateTarget() {
  abortOperation("target");
  abortOperation("question");
  state.loaded = null;
  clearComparison();
  clearReport("先查看募集要项，再按需生成。");
  $("coverage-tag").textContent = "尚未加载";
  $("target").textContent = "请点击“查看募集要项”，加载当前选择。";
  $("coverage").hidden = true;
  $("topics").className = "uw-empty";
  $("topics").replaceChildren(node("span", "选择上方学校和专攻，点击“查看募集要项”。无需先填写个人情况，也不会自动生成报告。"));
  $("qa-result").replaceChildren();
  $("qa-status").textContent = "";
  closeDialog("evidence");
  updateQuestionAvailability();
}

function selectedEntry() { return state.entries.find((item) => item.entry_id === $("school").value) || null; }
function currentScope() {
  return state.scopes.find((scope) => dimensions.every((field) => scope[field] === $(field).value)) || null;
}
function fillDimension(index) {
  const field = dimensions[index], select = $(field);
  const prefix = dimensions.slice(0, index);
  const eligible = state.scopes.filter((scope) => prefix.every((key) => scope[key] === $(key).value));
  const previous = select.value;
  select.replaceChildren();
  const choices = unique(eligible.map((scope) => scope[field]));
  for (const choice of choices) select.append(option(choice, choice));
  select.disabled = choices.length < 2;
  if (choices.includes(previous)) select.value = previous;
  else if (choices.length) select.value = choices[0];
  for (let next = index + 1; next < dimensions.length; next++) {
    const target = $(dimensions[next]);
    target.replaceChildren();
    target.disabled = true;
  }
  if (index + 1 < dimensions.length) fillDimension(index + 1);
}
function renderProfile() {
  const host = $("profile-fields");
  host.replaceChildren();
  const entry = selectedEntry();
  if (!entry) return;
  if (entry.kind === "reviewed_material_slice") {
    const fields = [
      ["employment-current", "目前是否受雇于单位"],
      ["employment-retain", "入学后是否继续在该单位任职"]
    ];
    for (const [id, label] of fields) {
      const wrapper = node("label", label);
      const select = document.createElement("select");
      select.id = `uw-${id}`;
      select.append(option("unknown", "未知／待确认"), option("yes", "是"), option("no", "否"));
      select.addEventListener("change", invalidateProfile);
      wrapper.append(select);
      host.append(wrapper);
    }
    $("compare").hidden = true;
    return;
  }
  const groups = [
    ["学历与毕业情况", [
      ["credential_basis", "最接近的学历路径", [["", "未填写"], ["ui_unknown", "不知道／待确认"],
        ["university_graduation", "日本大学毕业或预计毕业"], ["foreign_16_year_bachelor_equivalent", "外国 16 年教育／学士相当"],
        ["foreign_15_year_education", "外国 15 年教育"], ["university_three_year_enrollment", "大学在学满 3 年等"]]],
      ["completion_state", "毕业状态", [["", "未填写"], ["ui_unknown", "不知道／待确认"], ["ui_not_applicable", "自报目前不适用"],
        ["completed", "已毕业"], ["expected", "预计毕业"], ["not_completed", "尚未完成"]]]
    ]],
    ["英语考试与成绩单", [
      ["english_test_kind", "考试类型", [["", "未填写"], ["ui_unknown", "不知道／待确认"], ["ui_not_applicable", "自报未参加"],
        ["toeic_lr", "TOEIC L&R"], ["toefl_ibt", "TOEFL iBT"], ["toefl_ibt_home_edition", "TOEFL iBT Home Edition"], ["other", "其他"]]],
      ["english_score", "成绩", null, "number"], ["english_test_date", "考试日期", null, "date"],
      ["english_official_report_available", "官方成绩单", [["", "未填写"], ["ui_unknown", "不知道／待确认"], ["ui_not_applicable", "自报目前不适用"],
        ["true", "已取得"], ["false", "尚未取得"]]]
    ]],
    ["日语学习或证明", [
      ["japanese_background", "学习或证明情况", [["", "未填写"], ["ui_unknown", "不知道／待确认"], ["ui_not_applicable", "自报目前不适用"],
        ["studied", "学过日语"], ["certificate_available", "有日语能力证明"], ["not_studied", "未学过／尚无证明"]]]
    ]],
    ["材料准备状态", [
      ["address_label", "宛名标签"], ["application_form", "入学志愿票"], ["statement_of_purpose", "志望理由书"],
      ["bachelor_transcript", "学士课程成绩证明书"], ["graduation_or_expected_graduation_certificate", "毕业（预计）证明书"]
    ]]
  ];
  for (const [groupTitle, fields] of groups) {
    const details = document.createElement("details");
    details.open = groupTitle === "学历与毕业情况";
    details.append(node("summary", groupTitle));
    for (const [name, label, choices, type] of fields) {
      const wrapper = node("label", label);
      let control;
      if (choices || groupTitle === "材料准备状态") {
        control = document.createElement("select");
        for (const [value, caption] of choices || [
          ["", "未填写"], ["unknown", "不知道／待确认"], ["ui_not_applicable", "自报不适用（待核对）"],
          ["available", "我已准备"], ["not_yet", "尚未取得"]
        ]) control.append(option(value, caption));
      } else {
        control = document.createElement("input");
        control.type = type;
        if (type === "number") { control.min = "0"; control.max = "10000"; control.step = "0.01"; }
      }
      control.id = `uw-profile-${name}`;
      if (groupTitle === "材料准备状态") control.dataset.materialCode = name;
      control.addEventListener(type ? "input" : "change", invalidateProfile);
      wrapper.append(control);
      details.append(wrapper);
    }
    host.append(details);
  }
  $("compare").hidden = false;
}
function profileControls() {
  const value = (name) => $ (`profile-${name}`)?.value || "";
  const materials = [...document.querySelectorAll("#uw-profile-fields [data-material-code]")]
    .map((select) => ({code: select.dataset.materialCode, value: select.value}));
  return {
    credential_basis: value("credential_basis"), completion_state: value("completion_state"),
    english_test_kind: value("english_test_kind"), english_score: value("english_score"),
    english_test_date: value("english_test_date"),
    english_official_report_available: value("english_official_report_available"),
    japanese_background: value("japanese_background"), materials
  };
}
function profileDisclosure() {
  return [...$("profile-fields").querySelectorAll("label")].filter((label) => label.querySelector("select,input"))
    .map((label) => {
      const control = label.querySelector("select,input");
      const title = [...label.childNodes].filter((part) => part.nodeType === Node.TEXT_NODE)
        .map((part) => part.textContent.trim()).join(" ");
      const value = control.tagName === "SELECT"
        ? control.selectedOptions[0]?.textContent || "未填写" : control.value || "未填写";
      return {label: title, value};
    });
}
function employmentControls() {
  return {current: $("employment-current")?.value || "unknown", retain: $("employment-retain")?.value || "unknown"};
}
function updateQuestionAvailability() {
  const scope = currentScope();
  const allowed = Boolean(state.loaded && scope && scope.kind === "legacy_applicant");
  $("question").disabled = !allowed;
  $("ask").disabled = !allowed;
  if (scope?.kind === "reviewed_material_slice")
    $("qa-status").textContent = `当前${scope.school}材料切片暂不支持检索或自然语言问答。`;
  else if (!state.loaded) $("qa-status").textContent = "请先查看当前招生范围。";
}
function chooseSchool() {
  invalidateTarget();
  const entry = selectedEntry();
  state.scopes = entry ? scopesFor(entry) : [];
  if (entry) fillDimension(0);
  renderProfile();
  $("selection-note").textContent = entry?.kind === "reviewed_material_slice"
    ? "当前仅开放这一个固定审核范围；具体历史年份与覆盖范围见下方。"
    : "目录中的学院、专业与入学批次均按现有审核数据提供。";
  $("load").disabled = !currentScope();
  updateQuestionAvailability();
}
function chooseDimension(index) {
  invalidateTarget();
  if (index + 1 < dimensions.length) fillDimension(index + 1);
  renderProfile();
  $("load").disabled = !currentScope();
  updateQuestionAvailability();
}

function renderTopics(mapped) {
  const host = $("topics");
  host.className = "";
  host.replaceChildren();
  for (const [index, topic] of mapped.topics.entries()) {
    const article = node("article", "", "uw-topic");
    const heading = node("div", "", "uw-topic-top");
    heading.append(node("span", String(index + 1).padStart(2, "0"), "uw-number"), node("h3", topic.title));
    article.append(heading);
    appendText(article, "p", topic.summary);
    const details = [topic.status, topic.deadline && `截止：${topic.deadline}`,
      topic.dates.length && topic.dates.map((date) => date.display).join("；")].filter(Boolean).join(" · ");
    appendText(article, "p", details, "uw-meta");
    const actions = node("div", "", "uw-topic-actions");
    const button = node("button", "查看官方依据 ↗", "uw-link-button");
    button.type = "button";
    button.addEventListener("click", () => openEvidence(topic, button));
    actions.append(button, node("span", topic.status, "uw-badge"));
    article.append(actions);
    host.append(article);
  }
}
function sourceCard(source) {
  const box = node("div", "", "uw-source-box");
  box.append(node("h3", source.title));
  appendText(box, "p", `物理页 ${source.pages.join("、")}${source.printed ? ` · 印刷页 ${source.printed}` : ""}`);
  appendText(box, "p", source.context);
  box.append(node("blockquote", source.quote));
  const url = safeSource(source.source_url, source.pages[0]);
  if (url) {
    const link = node("a", "打开官方来源（页码定位依浏览器而定）");
    link.href = url; link.target = "_blank"; link.rel = "noopener noreferrer";
    box.append(link);
  }
  const local = safeLocalPdf(source.local_pdf_url, source.pages[0]);
  if (local) {
    const link = node("a", "在本地 PDF 查看对应页");
    link.href = local; link.target = "_blank"; link.rel = "noopener noreferrer";
    box.append(node("span", " · "), link);
  }
  return box;
}
function openEvidence(topic, trigger) {
  state.evidenceTrigger = trigger;
  const body = $("evidence-body");
  body.replaceChildren(node("span", "SOURCE EVIDENCE", "uw-eyebrow"), node("h2", topic.title));
  appendText(body, "p", scopeLabel(state.loaded.scope), "uw-muted");
  appendText(body, "p", topic.limitation, "uw-paper-note");
  for (const date of topic.dates) {
    appendText(body, "h3", date.label);
    appendText(body, "p", `${date.display} · 精度 ${date.precision}${date.uncertainty ? ` · ${date.uncertainty}` : ""}`);
    for (const source of date.sources) body.append(sourceCard(source));
  }
  for (const source of topic.sources) body.append(sourceCard(source));
  $("evidence").showModal();
  $("evidence").querySelector("[data-close]").focus();
}
function renderLoaded(mapped) {
  state.loaded = mapped;
  $("target").textContent = scopeLabel(mapped.scope);
  $("coverage-tag").textContent = mapped.scope.kind === "legacy_applicant"
    ? `${mapped.scope.school} · 部分审核` : `${mapped.scope.school} · 材料切片`;
  $("coverage").textContent = `${mapped.coverage}　${mapped.limitation}`;
  $("coverage").hidden = false;
  renderTopics(mapped);
  $("report-status").textContent = "报告将整理当前范围的全部已加载内容；个人情况可选填。";
  $("generate").disabled = false;
  updateQuestionAvailability();
}
async function requestJson(url, options = {}) {
  const response = await fetch(url, {cache: "no-store", credentials: "same-origin",
    headers: {Accept: "application/json", ...(options.body ? {"Content-Type": "application/json"} : {})},
    ...options});
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json();
}
async function loadRequirements() {
  const scope = currentScope();
  if (!scope || $("load").disabled) return;
  invalidateTarget();
  const generation = state.generation.target;
  const controller = new AbortController();
  state.controller.target = controller;
  $("load").disabled = true;
  $("coverage-tag").textContent = "正在加载";
  $("topics").className = "uw-empty";
  $("topics").textContent = "正在读取当前范围的已审核依据。";
  try {
    const raw = scope.kind === "legacy_applicant"
      ? await requestJson("/v1/base-requirements", {method: "POST", body: JSON.stringify(scope.request), signal: controller.signal})
      : await requestJson(`/v1/reference-slices/${encodeURIComponent(scope.entry_id)}/evidence`, {signal: controller.signal});
    if (generation !== state.generation.target || scopeKey(scope) !== scopeKey(currentScope())) return;
    renderLoaded(scope.kind === "legacy_applicant" ? mapLegacyBase(scope, raw) : mapSliceEvidence(scope, raw));
  } catch (error) {
    if (generation !== state.generation.target) return;
    $("coverage-tag").textContent = "加载失败";
    $("topics").textContent = "当前范围的官方要求暂时无法读取。请保留选择并点击“查看募集要项”重试。";
    $("report-status").textContent = "要求未加载，暂不能生成报告。";
  } finally {
    if (state.controller.target === controller) state.controller.target = null;
    if (generation === state.generation.target) $("load").disabled = false;
  }
}
function comparisonKey(scope, controls) { return JSON.stringify([scopeKey(scope), controls]); }
async function obtainComparison(scope, controls, reportGeneration) {
  const key = comparisonKey(scope, controls);
  if (state.comparison && state.comparisonKey === key) return state.comparison;
  abortOperation("comparison");
  const generation = state.generation.comparison;
  const controller = new AbortController();
  state.controller.comparison = controller;
  try {
    const payload = await requestJson("/v1/applicant-comparison", {
      method: "POST", body: JSON.stringify(comparisonRequest(scope, controls)), signal: controller.signal
    });
    if (generation !== state.generation.comparison || reportGeneration !== state.generation.report
      || key !== comparisonKey(currentScope(), profileControls())) throw new Error("对照输入已变化");
    state.comparison = payload;
    state.comparisonKey = key;
    renderComparison(payload);
    return payload;
  } finally { if (state.controller.comparison === controller) state.controller.comparison = null; }
}
function renderComparison(payload) {
  $("comparison-panel").hidden = false;
  $("comparison-summary").textContent = `${payload.comparison_statement}　共 ${payload.counts.total} 项；需补充 ${payload.counts.action_required}；需审核 ${payload.counts.review_required}；已记录 ${payload.counts.recorded}。`;
  const host = $("comparison-items");
  host.replaceChildren();
  for (const item of payload.items) {
    const article = document.createElement("article");
    article.append(node("h3", item.title), node("p", statusNames[item.comparison_status] || item.comparison_status),
      node("p", item.description), node("p", `下一步：${item.next_action}`));
    if (item.official_status) appendText(article, "p", `官方适用性：${item.official_status}；自报准备：${item.preparation_status || "未知"}`);
    if (item.evidence?.length) {
      const button = node("button", "查看官方依据", "uw-link-button");
      button.type = "button";
      button.addEventListener("click", () => openEvidence({
        title: item.title, dates: [], sources: item.evidence.map((source) => ({
          title: source.official_title, pages: source.pages, printed: null, quote: source.official_text,
          source_url: source.source_url, local_pdf_url: source.local_pdf_url, context: source.limitation
        })), limitation: item.limitation
      }, button));
      article.append(button);
    }
    if (item.action_group !== "recorded") {
      const label = node("label", "我已处理（仅本页记录）");
      const check = document.createElement("input");
      check.type = "checkbox";
      label.prepend(check);
      article.append(label);
    }
    host.append(article);
  }
  appendText(host, "p", payload.partial_checklist_statement, "uw-muted");
  appendText(host, "p", payload.limitation_statement, "uw-muted");
}
async function compareOnly() {
  if (!state.loaded || state.loaded.scope.kind !== "legacy_applicant") return;
  const scope = state.loaded.scope, controls = profileControls();
  if (!hasSuppliedProfile(controls)) { $("report-status").textContent = "尚未填写个人情况；可直接生成资料参考报告。"; return; }
  const generation = state.generation.report;
  $("compare").disabled = true;
  $("report-status").textContent = "正在对照个人情况。";
  try {
    await obtainComparison(scope, controls, generation);
    $("report-status").textContent = "个人对照已更新；可按需生成参考报告。";
  } catch {
    if (generation === state.generation.report) $("report-status").textContent = "个人对照失败；保留当前输入，请重试。";
  } finally { $("compare").disabled = false; }
}
function reportSection(body, title, paragraphs) {
  body.append(node("h3", title));
  for (const content of paragraphs.filter(Boolean)) appendText(body, "p", content);
}
function renderReport(report, mapped) {
  const body = $("report-body");
  body.replaceChildren(node("span", "ADMISSIONS REFERENCE", "uw-eyebrow"),
    node("h2", `${report.scope.school} · ${report.scope.program} · 募集要项参考报告`),
    node("p", scopeLabel(report.scope), "uw-muted"));
  body.append(node("div", report.kind === "legacy_applicant"
    ? `当前已审核结果的展示导出，不是新的权威报告。覆盖：${mapped.coverage}；限制：${mapped.limitation}`
    : `历史资料、部分材料范围。请结合完整原报告和官方依据核对条件。`, "uw-paper-note"));
  if (report.kind === "legacy_applicant") {
    for (const [index, topic] of report.topics.entries()) {
      reportSection(body, `${index + 1}. ${topic.title}`, [topic.status, topic.summary,
        topic.deadline && `截止：${topic.deadline}`, ...topic.dates.map((date) => `${date.label}：${date.display}`),
        topic.limitation, topic.sources.map((source) => `${source.title} · 物理页 ${source.pages.join("、")}`).join("；")]);
      const references = [...topic.sources, ...topic.dates.flatMap((date) => date.sources)];
      if (references.length) {
        const details = document.createElement("details");
        details.append(node("summary", `查看本项 ${references.length} 条官方依据`));
        for (const source of references) details.append(sourceCard(source));
        body.append(details);
      }
    }
    if (report.comparison) {
      reportSection(body, "个人情况与对照", [report.comparison.comparison_statement,
        ...report.profileDisclosure.map((field) => `${field.label}：${field.value}`),
        ...report.comparison.items.map((item) => `${item.title}：${statusNames[item.comparison_status] || item.comparison_status}。 ${item.description}`),
        report.comparison.partial_checklist_statement, report.comparison.limitation_statement]);
      for (const item of report.comparison.items) {
        if (!item.evidence?.length) continue;
        const details = document.createElement("details");
        details.append(node("summary", `${item.title} · 查看个人对照依据`));
        for (const evidence of item.evidence)
          details.append(sourceCard({
            title: evidence.official_title, pages: evidence.pages, printed: null,
            quote: evidence.official_text, source_url: evidence.source_url,
            local_pdf_url: evidence.local_pdf_url, context: evidence.limitation
          }));
        body.append(details);
      }
    } else reportSection(body, "资料整理范围", ["未加入个人情况，不作个人适用性判断。"]);
  } else {
    reportSection(body, "本次个人条件", [
      `目前受雇：${{unknown: "未知／待确认", yes: "是", no: "否"}[report.employment.current]}`,
      `入学后继续在职：${{unknown: "未知／待确认", yes: "是", no: "否"}[report.employment.retain]}`
    ]);
    for (const [index, topic] of report.topics.entries()) {
      reportSection(body, `${index + 1}. ${topic.title}`, [
        topic.status,
        `条件状态：${{matched: "匹配", not_matched: "本条条件不匹配", needs_information: "信息不足"}[topic.condition] || topic.condition}`,
        topic.explanation,
        topic.missing_fields.length ? `待明确：${topic.missing_fields.map((field) => field.includes("currently") ? "目前是否受雇" : "入学后是否继续在职").join("、")}` : "",
        ...topic.limitations,
        ...topic.citations.map((cite) => `${cite.source_title} · 物理页 ${cite.physical_pages.join("、")}${cite.printed_page_label ? `（印刷页 ${cite.printed_page_label}）` : ""}`)
      ]);
      const details = document.createElement("details");
      details.append(node("summary", `查看本项 ${topic.citations.length} 条官方引文`));
      for (const cite of topic.citations)
        details.append(sourceCard({
          title: cite.source_title, pages: cite.physical_pages, printed: cite.printed_page_label,
          quote: cite.quote_text, source_url: cite.official_source_url, local_pdf_url: null,
          context: [...(cite.official_heading_path || []), cite.stage === "enrollment_context_only" ? "入学手续关联" : ""].filter(Boolean).join(" › ")
        }));
      body.append(details);
    }
    reportSection(body, "覆盖范围与限制", report.raw.limitations_zh || []);
    const details = document.createElement("details");
    details.append(node("summary", "展开完整原始报告与引用"));
    details.append(node("pre", report.canonicalMarkdown));
    body.append(details);
  }
  reportSection(body, "待确认事项", ["未覆盖内容、未知条件与官方原文应单独核对；本报告不判断最终资格、受理或录取。"]);
  $("report").showModal();
  $("report").querySelector("[data-close]").focus();
}
async function generateReport() {
  if (!state.loaded || $("generate").disabled) return;
  state.reportTrigger = $("generate");
  clearReport("正在生成参考报告。");
  const mapped = state.loaded, scope = mapped.scope;
  const targetGeneration = state.generation.target;
  const profileGeneration = state.generation.profile;
  const reportGeneration = state.generation.report;
  const controller = new AbortController();
  state.controller.report = controller;
  $("generate").disabled = true;
  const current = () => reportGeneration === state.generation.report
    && targetGeneration === state.generation.target && profileGeneration === state.generation.profile
    && state.loaded === mapped && scopeKey(currentScope()) === scopeKey(scope);
  try {
    let report;
    if (scope.kind === "legacy_applicant") {
      const controls = profileControls();
      const comparison = hasSuppliedProfile(controls)
        ? await obtainComparison(scope, controls, reportGeneration) : null;
      if (!current()) return;
      report = legacyReport(mapped, comparison, comparison ? profileDisclosure() : []);
    } else {
      const employment = employmentControls();
      const payload = await requestJson(`/v1/reference-slices/${encodeURIComponent(scope.entry_id)}/reports`, {
        method: "POST", body: JSON.stringify(sliceReportRequest(scope, employment)), signal: controller.signal
      });
      if (!current() || JSON.stringify(employment) !== JSON.stringify(employmentControls())) return;
      report = sliceReport(scope, mapped, payload, employment);
    }
    if (!current()) return;
    state.report = report;
    renderReport(report, mapped);
    $("report-status").textContent = "参考报告已生成，可预览和复制。";
  } catch {
    if (current()) {
      state.report = null;
      $("report-status").textContent = "报告生成失败或引用不完整；已清除旧内容。请保留当前输入并重试。";
    }
  } finally {
    if (state.controller.report === controller) state.controller.report = null;
    if (current()) $("generate").disabled = false;
  }
}
async function copyReport() {
  if (!state.report || !state.loaded || scopeKey(state.report.scope) !== scopeKey(currentScope())) return;
  const text = state.report.text;
  try {
    await navigator.clipboard.writeText(text);
    $("copy-status").textContent = "已复制当前预览对应的完整报告与引用。";
  } catch {
    $("copy-fallback").value = text;
    $("copy-fallback").hidden = false;
    $("copy-fallback-label").hidden = false;
    $("copy-fallback").focus();
    $("copy-fallback").select();
    $("copy-status").textContent = "无法自动复制；请按 Ctrl+C 手动复制。";
  }
}
async function askQuestion(event) {
  event.preventDefault();
  const mapped = state.loaded, scope = mapped?.scope;
  if (!scope || scope.kind !== "legacy_applicant") return;
  const question = $("question").value.trim();
  if (!question || question.length > 1000) { $("qa-status").textContent = "请输入 1–1000 字的问题。"; return; }
  abortOperation("question");
  const generation = state.generation.question;
  const controller = new AbortController();
  state.controller.question = controller;
  $("ask").disabled = true;
  $("qa-status").textContent = "正在整理参考回答。";
  $("qa-result").replaceChildren();
  try {
    const body = await requestJson("/v1/natural-language-answers", {
      method: "POST", body: JSON.stringify({schema_version: "1.0", question,
        target: scope.request, applicant: comparisonRequest(scope, profileControls()).applicant}), signal: controller.signal
    });
    if (generation !== state.generation.question || mapped !== state.loaded) return;
    $("qa-status").textContent = "参考回答仅作补充，请以已审核规则和官方原文为准。";
    appendText($("qa-result"), "p", body.result?.answer?.answer || body.summary);
    for (const value of body.missing_context || []) appendText($("qa-result"), "p", `待确认：${value}`);
  } catch {
    if (generation === state.generation.question) $("qa-status").textContent = "问答暂时不可用；当前要求和已审核依据仍可查看。";
  } finally {
    if (state.controller.question === controller) state.controller.question = null;
    if (generation === state.generation.question) updateQuestionAvailability();
  }
}
async function start() {
  $("catalog-status").textContent = "";
  try {
    const catalog = await requestJson("/v1/reference-targets");
    state.entries = readyEntries(catalog);
    $("school").replaceChildren();
    for (const entry of state.entries) $("school").append(option(entry.entry_id, entry.institution_name));
    $("school").disabled = !state.entries.length;
    if (!state.entries.length) throw new Error("当前没有可用审核范围");
    chooseSchool();
  } catch {
    $("school").replaceChildren(option("", "能力目录暂时不可用"));
    $("catalog-status").textContent = "能力目录无法读取，请刷新本页重试。";
  }
}

$("school").addEventListener("change", chooseSchool);
dimensions.forEach((field, index) => $(field).addEventListener("change", () => chooseDimension(index)));
$("load").addEventListener("click", loadRequirements);
$("generate").addEventListener("click", generateReport);
$("compare").addEventListener("click", compareOnly);
$("copy").addEventListener("click", copyReport);
$("qa-form").addEventListener("submit", askQuestion);
for (const button of document.querySelectorAll("[data-close]"))
  button.addEventListener("click", () => closeDialog(button.dataset.close));
$("evidence").addEventListener("close", () => { state.evidenceTrigger?.focus(); state.evidenceTrigger = null; });
$("report").addEventListener("close", () => { state.reportTrigger?.focus(); state.reportTrigger = null; });
start();
