"use strict";

const CATALOG_ENDPOINT = "/v1/reviewed-documents";
const QUERY_ENDPOINT = "/v1/corpus/query";
const INTENT_ENDPOINT = "/v1/query-intents/parse";
const REPORT_ENDPOINT = "/v1/applicant-reports";
const TARGET_CATALOG_ENDPOINT = "/v1/target-catalog";
const BASE_REQUIREMENTS_ENDPOINT = "/v1/base-requirements";
const APPLICANT_COMPARISON_ENDPOINT = "/v1/applicant-comparison";
const GROUNDED_ANSWER_ENDPOINT = "/v1/grounded-answers";
const MAX_QUERY_LENGTH = 1000;
const TOP_K = 5;
const CANDIDATE_K = 20;

const byId = (id) => document.getElementById(id);
const form = byId("evidence-form");
const documentSelect = byId("document-select");
const documentDetail = byId("document-detail");
const queryInput = byId("query-input");
const queryCount = byId("query-count");
const submitButton = byId("submit-button");
const retryButton = byId("retry-button");
const statusMessage = byId("status-message");
const evidenceList = byId("evidence-list");
const resultCount = byId("result-count");
const reportForm = byId("report-form");
const reportQuery = byId("report-query");
const reportQueryCount = byId("report-query-count");
const reportSubmit = byId("report-submit");
const reportRetry = byId("report-retry");
const reportClear = byId("report-clear");
const reportStatus = byId("report-status");
const reportOutput = byId("report-output");
const evidenceTab = byId("evidence-tab");
const reportTab = byId("report-tab");
const evidenceView = byId("evidence-view");
const reportView = byId("report-view");
const targetForm = byId("target-form");
const schoolSelect = byId("school-select");
const demoDegreeSelect = byId("demo-degree-select");
const intakeSelect = byId("intake-select");
const collegeSelect = byId("college-select");
const departmentSelect = byId("department-select");
const routeField = byId("route-field");
const routeSelect = byId("route-select");
const requirementsSubmit = byId("requirements-submit");
const requirementsRetry = byId("requirements-retry");
const targetCompletionHint = byId("target-completion-hint");
const targetStatus = byId("target-status");
const targetSummary = byId("target-summary");
const requirementsOutput = byId("requirements-output");
const evidenceDrawer = byId("evidence-drawer");
const drawerClose = byId("drawer-close");
const drawerContent = byId("drawer-content");
const applicantForm = byId("applicant-form");
const comparisonSubmit = byId("comparison-submit");
const comparisonRetry = byId("comparison-retry");
const comparisonStatus = byId("comparison-status");
const comparisonOutput = byId("comparison-output");
const readinessPanel = byId("readiness-panel");
const readinessTarget = byId("readiness-target");
const partialChecklistStatement = byId("partial-checklist-statement");
const readinessFilters = byId("readiness-filters");
const filterEmpty = byId("filter-empty");
const requirementsContinue = byId("requirements-continue");
const editTarget = byId("edit-target");
const editRequirements = byId("edit-requirements");
const editApplicant = byId("edit-applicant");
const groundedForm = byId("grounded-answer-form");
const groundedQuestion = byId("grounded-question");
const groundedQuestionCount = byId("grounded-question-count");
const groundedSubmit = byId("grounded-answer-submit");
const groundedRetry = byId("grounded-answer-retry");
const groundedStatus = byId("grounded-answer-status");
const groundedOutput = byId("grounded-answer-output");
const groundedContext = byId("grounded-context");
const flowSteps = [1, 2, 3, 4].map((number) => ({
  number,
  panel: byId(number === 3 ? "applicant-panel" : number === 4 ? "readiness-panel" : `step-${number}-panel`),
  heading: byId(number === 1 ? "demo-heading" : number === 2 ? "requirements-heading" : number === 3 ? "applicant-heading" : "readiness-heading"),
  content: number < 4 ? byId(`step-${number}-content`) : null,
  summary: number < 4 ? byId(`step-${number}-summary`) : null,
  badge: byId(`step-${number}-badge`),
  nav: byId(`step-nav-${number}`)
}));

let catalogItems = [];
let lastAction = "catalog";
let reportPending = false;
let reportCanRetry = false;
let demoCatalog = [];
let requirementsPending = false;
let requirementsController = null;
let requirementsRequestId = 0;
let drawerTrigger = null;
let baseRequirementsLoaded = false;
let comparisonPending = false;
let comparisonController = null;
let comparisonRequestId = 0;
let activeStep = 1;
let requirementsEverLoaded = false;
let comparisonComplete = false;
let comparisonEverLoaded = false;
let groundedController = null;
let groundedRequestId = 0;
let groundedCanRetry = false;

const stepStateLabels = {
  locked: "未开始",
  current: "当前",
  complete: "已完成",
  stale: "需要重新确认"
};

function stepState(number) {
  if (number === activeStep) return "current";
  if (number === 1) return baseRequirementsLoaded ? "complete" : "locked";
  if (number === 2) {
    if (baseRequirementsLoaded) return activeStep === 2 ? "current" : "complete";
    return requirementsEverLoaded ? "stale" : "locked";
  }
  if (number === 3) {
    if (comparisonComplete) return activeStep === 3 ? "current" : "complete";
    if (comparisonEverLoaded) return "stale";
    return "locked";
  }
  if (comparisonComplete) return activeStep === 4 ? "current" : "complete";
  return comparisonEverLoaded ? "stale" : "locked";
}

function updateFlowPresentation() {
  for (const step of flowSteps) {
    const state = stepState(step.number);
    const isActive = step.number === activeStep;
    step.nav.dataset.state = state;
    step.nav.querySelector("small").textContent = stepStateLabels[state];
    if (isActive) step.nav.setAttribute("aria-current", "step");
    else step.nav.removeAttribute("aria-current");
    step.panel.dataset.stepState = state;
    step.badge.textContent = stepStateLabels[state];

    const available = step.number === 1
      || (step.number === 2 && baseRequirementsLoaded)
      || (step.number === 3 && baseRequirementsLoaded && (activeStep >= 3 || comparisonComplete))
      || (step.number === 4 && comparisonComplete && activeStep === 4);
    step.panel.hidden = !available;
    if (step.content) step.content.hidden = !isActive;
    if (step.summary) step.summary.hidden = isActive || state !== "complete";
  }
}

function focusStep(number) {
  const step = flowSteps[number - 1];
  step.panel.scrollIntoView({ block: "start", behavior: "auto" });
  step.heading.focus({ preventScroll: true });
}

function activateStep(number, focus = false) {
  activeStep = number;
  updateFlowPresentation();
  if (focus) requestAnimationFrame(() => focusStep(number));
}

function setMessage(element, state, message, focus = false) {
  element.dataset.state = state;
  element.textContent = message;
  element.hidden = false;
  if (focus) {
    element.focus();
  }
}

function setStatus(state, message, focus = false) {
  setMessage(statusMessage, state, message, focus);
}

function clearGroundedAnswer(message = "加载基础要求后即可提问。") {
  groundedRequestId += 1;
  if (groundedController) groundedController.abort();
  groundedController = null;
  groundedCanRetry = false;
  groundedRetry.hidden = true;
  groundedOutput.replaceChildren();
  groundedOutput.hidden = true;
  groundedQuestion.disabled = !baseRequirementsLoaded;
  groundedSubmit.disabled = !baseRequirementsLoaded;
  setMessage(groundedStatus, "initial", message);
}

function updateGroundedContext() {
  if (!baseRequirementsLoaded || !demoTargetComplete()) {
    groundedContext.textContent = "请先完成目标选择并加载基础要求。";
    return;
  }
  const target = currentDepartment();
  const intake = currentIntake();
  groundedContext.textContent = `当前复用：${currentSchool().school_name} · ${target ? target.department_name : departmentSelect.value} · ${intake.intake_name}；个人情况取自上方本页表单。`;
}

function groundedRequestPayload() {
  return {
    schema_version: "1.0",
    question: groundedQuestion.value.trim(),
    target: demoTargetRequest(),
    applicant: demoApplicantInput()
  };
}

function groundedFailureMessage(code, status) {
  if (code === "generation_provider_timeout" || status === 504) return "生成服务超时。当前选择和问题仍保留，可重试。";
  if (["generation_provider_unavailable", "grounded_service_unavailable", "provider_unavailable"].includes(code) || status === 503) return "生成或检索服务暂时不可用，请稍后重试。";
  if (code === "insufficient_evidence") return "当前检索证据不足，未生成回答。请缩小或改写问题。";
  if (["invalid_citation", "evidence_mismatch", "rule_state_mismatch", "unsupported_claim", "malformed_output", "incomplete_response"].includes(code)) return "回答未通过证据或引用校验，因此已安全隐藏。请重试或查看基础要求。";
  if (code === "unsupported_question" || status === 422) return "问题超出当前人工审核范围，或未包含可识别的资格、语言、日期、费用等主题。";
  return "暂时无法生成有依据的回答，请重试。";
}

function appendGroundedList(container, title, values) {
  if (!Array.isArray(values) || !values.length) return;
  const section = document.createElement("section");
  section.className = "grounded-boundary";
  section.append(heading(3, title));
  const list = document.createElement("ul");
  for (const value of values) {
    const item = document.createElement("li");
    item.textContent = String(value);
    list.append(item);
  }
  section.append(list);
  container.append(section);
}

function renderGroundedAnswer(payload) {
  groundedOutput.replaceChildren();
  const answer = payload.answer;
  const evidenceByFact = new Map((payload.evidence || []).map((item) => [item.fact_id, item]));
  const meta = document.createElement("p");
  meta.className = "grounded-answer-meta";
  for (const text of [
    `AI 生成 · ${answer.provider.provider}`,
    `模型 ${answer.provider.model}`,
    answer.provider.revision ? `revision ${answer.provider.revision}` : "revision 未提供",
    answer.needs_review ? "需要人工复核" : "审核状态完整"
  ]) {
    const badge = document.createElement("span");
    badge.textContent = text;
    meta.append(badge);
  }
  groundedOutput.append(meta);
  const scope = document.createElement("p");
  scope.className = "grounded-boundary";
  scope.textContent = `审核范围：${payload.reviewed_scope_statement}`;
  groundedOutput.append(scope);

  if (!Array.isArray(answer.claims) || !answer.claims.length) {
    const empty = document.createElement("p");
    empty.className = "grounded-boundary";
    empty.textContent = "证据已检索，但离线 provider 没有返回可安全展示的事实性主张。";
    groundedOutput.append(empty);
  }
  for (const claim of answer.claims || []) {
    const card = document.createElement("article");
    card.className = "grounded-claim";
    card.dataset.kind = claim.kind;
    const label = document.createElement("p");
    label.className = "comparison-category";
    label.textContent = claim.kind === "reviewed_rule" ? "人工审核规则" : claim.kind === "official_fact" ? "官方证据事实" : "申请人自报信息";
    const text = document.createElement("p");
    text.textContent = claim.text;
    card.append(label, text);
    const controls = document.createElement("div");
    controls.className = "grounded-citations";
    for (const citation of claim.citations || []) {
      const evidence = evidenceByFact.get(citation.fact_id);
      if (!evidence) continue;
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = `查看依据 · 第 ${citation.source_pages.join("、")} 页`;
      button.addEventListener("click", () => openDemoEvidence({ title: "生成回答的官方依据" }, evidence, button));
      controls.append(button);
    }
    if (controls.childElementCount) card.append(controls);
    groundedOutput.append(card);
  }
  appendGroundedList(groundedOutput, "仍缺少的信息", answer.missing_information);
  appendGroundedList(groundedOutput, "限制", answer.limitations);
  const sources = document.createElement("div");
  sources.className = "grounded-source-actions";
  if (payload.local_pdf_url) {
    const pdf = document.createElement("a");
    pdf.className = "source-link";
    pdf.href = payload.local_pdf_url;
    pdf.target = "_blank";
    pdf.rel = "noopener noreferrer";
    pdf.textContent = "打开本地已校验 PDF";
    sources.append(pdf);
  }
  const official = document.createElement("a");
  official.className = "source-link";
  official.href = payload.official_source_url;
  official.target = "_blank";
  official.rel = "noopener noreferrer";
  official.textContent = "打开官方招生网页";
  sources.append(official);
  groundedOutput.append(sources);
  groundedOutput.hidden = false;
}

async function submitGroundedAnswer() {
  const question = groundedQuestion.value.trim();
  if (!baseRequirementsLoaded || !demoTargetComplete() || !question || question.length > MAX_QUERY_LENGTH) {
    setMessage(groundedStatus, "error", "请输入 1–1000 个字符的问题，并先加载基础要求。", true);
    return;
  }
  if (groundedController) groundedController.abort();
  const payload = groundedRequestPayload();
  const snapshot = JSON.stringify(payload);
  const requestId = ++groundedRequestId;
  groundedController = new AbortController();
  const timeout = globalThis.setTimeout(() => groundedController && groundedController.abort("timeout"), 15000);
  groundedSubmit.disabled = true;
  groundedRetry.hidden = true;
  groundedOutput.hidden = true;
  groundedCanRetry = false;
  setMessage(groundedStatus, "loading", "正在检索审核证据并校验生成引用。");
  try {
    const response = await fetch(GROUNDED_ANSWER_ENDPOINT, { method: "POST", headers: { Accept: "application/json", "Content-Type": "application/json" }, body: snapshot, cache: "no-store", credentials: "same-origin", signal: groundedController.signal });
    const body = await response.json().catch(() => ({}));
    if (requestId !== groundedRequestId || snapshot !== JSON.stringify(groundedRequestPayload())) return;
    if (!response.ok) {
      const failure = new Error("grounded request failed");
      failure.code = body.code;
      failure.status = response.status;
      throw failure;
    }
    if (!body.answer || !Array.isArray(body.answer.claims) || !Array.isArray(body.evidence)) throw new Error("invalid response");
    renderGroundedAnswer(body);
    setMessage(groundedStatus, "success", "回答已通过审核状态与引用闭合校验。", true);
  } catch (error) {
    if (requestId !== groundedRequestId) return;
    const timedOut = groundedController && groundedController.signal.reason === "timeout";
    groundedCanRetry = true;
    groundedRetry.hidden = false;
    groundedOutput.replaceChildren();
    groundedOutput.hidden = true;
    setMessage(groundedStatus, "error", timedOut ? "生成服务超时。当前选择和问题仍保留，可重试。" : groundedFailureMessage(error && error.code, error && error.status), true);
  } finally {
    globalThis.clearTimeout(timeout);
    if (requestId === groundedRequestId) {
      groundedController = null;
      groundedSubmit.disabled = !baseRequirementsLoaded;
    }
  }
}

function clearResults() {
  evidenceList.replaceChildren();
  resultCount.textContent = "";
  resultCount.hidden = true;
}

function clearReportResult() {
  reportOutput.replaceChildren();
  reportCanRetry = false;
  reportRetry.hidden = true;
}

function setBusy(busy) {
  documentSelect.disabled = busy || catalogItems.length === 0;
  queryInput.disabled = busy || catalogItems.length === 0;
  submitButton.disabled = busy || catalogItems.length === 0;
  reportSubmit.disabled = busy || reportPending || catalogItems.length === 0;
}

function selectedCatalogItem() {
  return catalogItems.find((item) => item.identity.document_id === documentSelect.value);
}

function documentLabel(item) {
  const identity = item.identity;
  const terms = identity.intake_terms.map((term) => `${term.year}年${term.month}月`).join(" / ");
  const edition = item.version_classification === "active" ? "現行" : "過去版";
  return `${identity.institution_name} | ${identity.official_title} | ${terms} | ${edition}`;
}

function updateDocumentDetail() {
  const item = selectedCatalogItem();
  if (!item) {
    documentDetail.textContent = "";
    byId("report-coverage").textContent = "";
    byId("report-limitation").textContent = "";
    return;
  }
  const categoryLabels = {
    eligibility: "出願資格", documents: "提出書類", application_dates: "出願日程",
    fees: "費用", language_tests: "語学試験", selection_exams: "選抜試験",
    results: "結果発表", enrollment: "入学手続", contacts_forms: "連絡先・様式",
    department_requirements: "系・コース要件"
  };
  const categories = item.covered_categories.map((value) => categoryLabels[value] || value).join("、");
  documentDetail.textContent = `部分的な審査済み規則 | 対象: ${categories} | ${item.limitation_statement}`;
  byId("report-coverage").textContent = `確認済み範囲: ${item.reviewed_coverage_statement}`;
  byId("report-limitation").textContent = `制限事項: ${item.limitation_statement}`;
}

function populateCatalog(items) {
  catalogItems = items;
  documentSelect.replaceChildren();
  if (items.length === 0) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = "利用可能な募集要項がありません";
    documentSelect.append(option);
    setBusy(false);
    setStatus("empty", "現在、検索できる審査済み募集要項はありません。", true);
    return;
  }
  for (const item of items) {
    const option = document.createElement("option");
    option.value = item.identity.document_id;
    option.textContent = documentLabel(item);
    documentSelect.append(option);
  }
  setBusy(false);
  updateDocumentDetail();
  setStatus("success", "募集要項を選び、確認したい内容を入力してください。");
}

function publicErrorMessage(status, code, context = "search") {
  if (status === 422 || code === "invalid_request") {
    return context === "report" ? "質問または入力条件を確認してください。" : "入力内容を確認して、もう一度検索してください。";
  }
  if (status === 404) return "選択した募集要項が見つかりません。募集要項を選び直してください。";
  if (status === 409) return "募集要項の状態が更新されました。再読み込みして、明示的に再試行してください。";
  if (status === 503) return context === "report" ? "レポート機能を利用できません。設定を確認して再試行してください。" : "検索サービスを利用できません。しばらく待って再試行してください。";
  return context === "report" ? "レポートを作成できませんでした。再試行してください。" : "検索を完了できませんでした。再試行してください。";
}

async function safeErrorCode(response) {
  try {
    const payload = await response.json();
    return typeof payload.code === "string" ? payload.code : "";
  } catch (_error) {
    return "";
  }
}

async function loadCatalog() {
  lastAction = "catalog";
  retryButton.hidden = true;
  clearResults();
  setBusy(true);
  setStatus("loading", "審査済み募集要項を読み込んでいます。");
  try {
    const response = await fetch(CATALOG_ENDPOINT, { method: "GET", headers: { Accept: "application/json" }, cache: "no-store", credentials: "same-origin" });
    if (!response.ok) throw { publicMessage: publicErrorMessage(response.status, await safeErrorCode(response)) };
    const payload = await response.json();
    if (!payload || !Array.isArray(payload.items)) throw { publicMessage: "募集要項一覧を確認できませんでした。再試行してください。" };
    populateCatalog(payload.items);
  } catch (error) {
    catalogItems = [];
    documentSelect.replaceChildren();
    setBusy(false);
    retryButton.hidden = false;
    setStatus("error", error && typeof error.publicMessage === "string" ? error.publicMessage : "募集要項一覧を読み込めませんでした。再試行してください。", true);
  }
}

function selectionRequest(item) {
  return {
    schema_version: "1.0", document_ids: [item.identity.document_id], institution_ids: [],
    document_family_ids: [], degree_levels: [], intake_terms: [],
    version_mode: item.version_classification === "historical" ? "historical_only" : "active_only",
    allow_multiple_documents: false
  };
}

function searchRequest(item, query) {
  return {
    schema_version: "1.0", selection: selectionRequest(item),
    search: {
      query, top_k: TOP_K, candidate_k: CANDIDATE_K,
      metadata_filter: { fact_types: [], scope_types: [], scope_targets: [], parent_colleges: [] },
      scope_preference: { preferred_scope_targets: [], preferred_parent_colleges: [] }
    }
  };
}

function pageCitation(value) {
  const pages = value.source_pages;
  const pageLabel = pages.length === 1 ? `p.${pages[0]}` : `pp.${pages.join(", ")}`;
  const factId = value.key ? value.key.fact_id : value.fact_id;
  return `[${factId}, ${pageLabel}]`;
}

function score(value) {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric.toFixed(4) : "-";
}

function channelText(hit) {
  const details = [];
  if (hit.matched_channels.includes("vector")) details.push(`vector #${hit.vector_rank} (${score(hit.vector_score)})`);
  if (hit.matched_channels.includes("lexical")) details.push(`lexical #${hit.lexical_rank} (${score(hit.lexical_score)})`);
  details.push(`fusion ${score(hit.fused_score)}`);
  return details.join(" | ");
}

function addMetadata(list, label, value) {
  const term = document.createElement("dt");
  term.textContent = label;
  const detail = document.createElement("dd");
  detail.textContent = value;
  list.append(term, detail);
}

function renderHit(hit) {
  const item = document.createElement("li");
  item.className = "evidence-item";
  const heading = document.createElement("div");
  heading.className = "evidence-heading";
  const rank = document.createElement("span");
  rank.className = "evidence-rank";
  rank.textContent = `#${hit.rank}`;
  const title = document.createElement("h3");
  title.textContent = `${hit.identity.official_title} (${hit.key.document_id})`;
  heading.append(rank, title);
  const citation = document.createElement("p");
  citation.className = "citation";
  citation.textContent = pageCitation(hit);
  const quote = document.createElement("blockquote");
  quote.className = "evidence-text";
  quote.textContent = hit.text;
  const metadata = document.createElement("dl");
  metadata.className = "evidence-meta";
  addMetadata(metadata, "セクション", hit.section_path.join(" / "));
  const targets = hit.scope_targets.length > 0 ? hit.scope_targets.join(" / ") : "指定なし";
  addMetadata(metadata, "適用範囲", `${hit.scope_type} | ${targets}${hit.parent_college ? ` | ${hit.parent_college}` : ""}`);
  addMetadata(metadata, "種別", hit.fact_type);
  addMetadata(metadata, "検索診断", channelText(hit));
  item.append(heading, citation, quote, metadata);
  return item;
}

function renderResults(payload) {
  clearResults();
  const hits = Array.isArray(payload.hits) ? payload.hits : [];
  if (hits.length === 0) {
    setStatus("empty", "該当する根拠候補は見つかりませんでした。質問を変えて再試行してください。", true);
    retryButton.hidden = false;
    return;
  }
  for (const hit of hits) evidenceList.append(renderHit(hit));
  resultCount.textContent = `${hits.length}件`;
  resultCount.hidden = false;
  setStatus("success", `${hits.length}件の根拠候補が見つかりました。`, true);
}

async function submitSearch() {
  const item = selectedCatalogItem();
  const query = queryInput.value.trim();
  if (!item) { setStatus("error", "募集要項を選択してください。", true); documentSelect.focus(); return; }
  if (!query || query.length > MAX_QUERY_LENGTH) { setStatus("error", `質問は1文字以上${MAX_QUERY_LENGTH}文字以内で入力してください。`, true); queryInput.focus(); return; }
  lastAction = "search";
  retryButton.hidden = true;
  clearResults();
  setBusy(true);
  setStatus("loading", "公式文書から根拠候補を検索しています。");
  try {
    const response = await fetch(QUERY_ENDPOINT, { method: "POST", headers: { Accept: "application/json", "Content-Type": "application/json" }, body: JSON.stringify(searchRequest(item, query)), cache: "no-store", credentials: "same-origin" });
    if (!response.ok) throw { publicMessage: publicErrorMessage(response.status, await safeErrorCode(response)) };
    renderResults(await response.json());
  } catch (error) {
    retryButton.hidden = false;
    setStatus("error", error && typeof error.publicMessage === "string" ? error.publicMessage : "検索サービスに接続できません。再試行してください。", true);
  } finally {
    setBusy(false);
  }
}

function nullableText(id) {
  const value = byId(id).value.trim();
  return value === "" ? null : value;
}

function nullableInteger(id) {
  const raw = byId(id).value;
  if (raw === "") return null;
  const value = Number(raw);
  if (!Number.isSafeInteger(value)) throw new Error("integer");
  return value;
}

function nullableBoolean(id) {
  const value = byId(id).value;
  return value === "" ? null : value === "true";
}

function nullableNumber(id) {
  const raw = byId(id).value;
  if (raw === "") return null;
  const value = Number(raw);
  if (!Number.isFinite(value)) throw new Error("number");
  return value;
}

function academicCredentials() {
  const credential = {
    institution_country_code: nullableText("credential-country"),
    degree_level: nullableText("credential-degree-level"),
    credential_basis: nullableText("credential-basis"),
    completion_state: nullableText("completion-state"),
    completion_date: nullableText("completion-date"),
    expected_completion_date: nullableText("expected-completion-date"),
    years_of_education: nullableInteger("years-of-education"),
    coursework_in_japan: nullableBoolean("coursework-in-japan"),
    program_duration_years: nullableInteger("program-duration-years"),
    institution_recognition_status: nullableText("institution-recognition-status"),
    program_designation_status: nullableText("program-designation-status"),
    completion_timing_verification_status: nullableText(
      "completion-timing-verification-status"
    ),
    person_designation_status: nullableText("person-designation-status"),
    years_enrolled_at_eligibility_cutoff: nullableInteger(
      "years-enrolled-at-eligibility-cutoff"
    ),
    prescribed_credits_excellence_status: nullableText(
      "prescribed-credits-excellence-status"
    ),
    institution_is_target_university: nullableBoolean("institution-is-target-university"),
    gpt_after_two_years: nullableNumber("gpt-after-two-years"),
    credits_after_two_years: nullableInteger("credits-after-two-years"),
    required_specialization_courses_expected_status: nullableText(
      "required-specialization-courses-status"
    ),
    expected_specialist_credits: nullableInteger("expected-specialist-credits"),
    liberal_arts_requirements_expected_status: nullableText(
      "liberal-arts-requirements-status"
    ),
    prior_education_category: nullableText("prior-education-category"),
    sixteen_year_equivalence_status: nullableText("sixteen-year-equivalence-status"),
    ministerial_course_standard_status: nullableText("ministerial-course-standard-status"),
    ministerial_completion_deadline_status: nullableText("ministerial-completion-deadline-status"),
    years_enrolled_before_withdrawal: nullableInteger("years-enrolled-before-withdrawal"),
    under_sixteen_year_bachelor_country_status: nullableText("under-sixteen-year-country-status"),
    university_education_completion_status: nullableText("university-education-completion-status"),
    post_university_research_months_at_eligibility_cutoff: nullableInteger(
      "post-university-research-months-at-eligibility-cutoff",
    ),
    graduate_equivalent_recognition_status: nullableText("graduate-equivalent-recognition-status")
  };
  return Object.values(credential).every((value) => value === null) ? null : [credential];
}

function languageTestResults() {
  const result = {
    test_kind: nullableText("language-test-kind"),
    test_date: nullableText("language-test-date"),
    score: nullableNumber("language-test-score"),
    validity_status: null,
    official_report_available: null,
    selected_for_submission: nullableBoolean("language-test-selected"),
    score_sheet_submission_method: nullableText("language-score-submission-method"),
    score_sheet_expected_arrival_date: nullableText("language-score-expected-arrival-date"),
    score_sheet_registered_mail_planned: nullableBoolean("language-score-registered-mail"),
    score_sheet_replacement_after_deadline_planned: nullableBoolean(
      "language-score-replacement-after-deadline"
    ),
    downloaded_online_pdf: nullableBoolean("language-online-pdf"),
    toeic_verification_qr_present: nullableBoolean("toeic-qr-present"),
    toeic_digital_official_score_certificate: nullableBoolean("toeic-digital-certificate"),
    toefl_test_taker_score_report_pdf: nullableBoolean("toefl-score-report"),
    toefl_di_code_g179_set: nullableBoolean("toefl-g179"),
    ets_paper_sent_to_applicant: nullableBoolean("ets-paper-applicant"),
    ets_paper_sent_to_institution: nullableBoolean("ets-paper-institution")
  };
  return Object.values(result).every((value) => value === null) ? null : [result];
}

function applicantProfile() {
  return {
    schema_version: "1.0",
    target_application: {
      graduate_school_or_college: nullableText("graduate-school"),
      department_or_program: nullableText("department-program"),
      requested_degree_level: nullableText("degree-level"),
      intake_year: nullableInteger("intake-year"),
      intake_month: nullableInteger("intake-month"),
      application_route: nullableText("application-route")
    },
    citizenship_and_residence: {
      citizenship_country_codes: null,
      current_residence_country_code: nullableText("current-residence-country"),
      residence_status_category: null
    },
    academic_credentials: academicCredentials(),
    eligibility_facts: {
      age_at_enrollment: nullableInteger("age-at-enrollment"),
      professional_experience_months: nullableInteger("professional-months"),
      research_experience_months: nullableInteger("research-months"),
      individual_review_status: nullableText("review-status"),
      individual_review_requested: nullableBoolean("review-requested"),
      individual_review_completed: nullableBoolean("review-completed"),
      age_at_eligibility_cutoff: nullableInteger("age-at-eligibility-cutoff")
    },
    application_submission: {
      materials_arrival_date: nullableText("materials-arrival-date"),
      materials_dispatched_date: nullableText("materials-dispatched-date"),
      online_steps_completed: nullableBoolean("online-steps-completed"),
      a_schedule_oral_exam_participation_planned: nullableBoolean(
        "a-schedule-oral-participation"
      )
    },
    preapplication_actions: {
      special_accommodation_needed: nullableBoolean("special-accommodation-needed"),
      special_accommodation_contacted_admissions: nullableBoolean("special-accommodation-contacted"),
      foreign_national_rule_applies: nullableBoolean("foreign-national-rule-applies"),
      residence_status_valid_until: nullableText("residence-status-valid-until"),
      residence_status_allows_long_term_stay: nullableBoolean("long-term-stay-allowed"),
      residence_status_contacted_admissions: nullableBoolean("residence-status-contacted"),
      visa_arrangements_needed: nullableBoolean("visa-arrangements-needed"),
      visa_timing_consulted_advisor: nullableBoolean("visa-advisor-consulted"),
      transcript_unavailable_reason: nullableText("transcript-unavailable-reason"),
      transcript_unavailability_consulted_admissions: nullableBoolean("transcript-contacted"),
      disaster_fee_consultation_needed: nullableBoolean("disaster-fee-consultation-needed"),
      disaster_fee_consulted_admissions: nullableBoolean("disaster-fee-contacted"),
      scholarship_status: nullableText("scholarship-status"),
      scholarship_copy_emailed_date: nullableText("scholarship-copy-emailed-date"),
      scholarship_application_method_received: nullableBoolean("scholarship-method-received")
    },
    language_test_results: languageTestResults()
  };
}

function validateProfile(profile) {
  if (!reportForm.checkValidity()) return "入力値の範囲と形式を確認してください。";
  const facts = profile.eligibility_facts;
  const credential = profile.academic_credentials ? profile.academic_credentials[0] : null;
  if (credential && credential.completion_state === "completed" && credential.expected_completion_date !== null) return "修了済みの学歴に見込日を入力することはできません。";
  if (credential && credential.completion_state === "expected" && credential.completion_date !== null) return "修了見込みの学歴に修了済みの日付を入力することはできません。";
  if (credential && credential.completion_state === "not_completed" && (credential.completion_date !== null || credential.expected_completion_date !== null)) return "未修了・見込み日なしの学歴に修了日を入力することはできません。";
  const status = facts.individual_review_status;
  if (status === "not_requested" && (facts.individual_review_requested === true || facts.individual_review_completed === true)) return "個別資格審査の状態と申請・完了の回答が矛盾しています。";
  if (status === "requested" && (facts.individual_review_requested === false || facts.individual_review_completed === true)) return "個別資格審査の状態と申請・完了の回答が矛盾しています。";
  if (status === "completed" && (facts.individual_review_requested === false || facts.individual_review_completed === false)) return "個別資格審査の状態と申請・完了の回答が矛盾しています。";
  if (facts.individual_review_completed === true && facts.individual_review_requested === false) return "完了済みの個別資格審査を未申請にはできません。";
  return "";
}

function reportRequest(item, profile, intent) {
  return { schema_version: "1.0", report_id: "local-ui-report", profile, intent, selection: selectionRequest(item) };
}

function statusLabel(code) {
  const labels = { complete: "準備完了", needs_information: "情報が必要", needs_review: "要確認", confirmed: "確認済み", not_applicable: "該当せず", active: "有効", overridden: "上書き", pending: "保留" };
  return labels[code] || code;
}

function heading(level, text) {
  const element = document.createElement(`h${level}`);
  element.textContent = text;
  return element;
}

function citationList(citations) {
  const list = document.createElement("ul");
  list.className = "compact-list";
  for (const citation of citations || []) {
    const item = document.createElement("li");
    item.textContent = `${pageCitation(citation)} | document: ${citation.document_id} | rule: ${citation.source_rule_id} | role: ${citation.role} | steps: ${citation.source_step_ids.join(", ")}`;
    list.append(item);
  }
  return list;
}

function renderReport(payload) {
  clearReportResult();
  const report = payload.report;
  const answer = report.cited_answer;
  const rulesById = new Map(report.source_plan.rules.map((rule) => [rule.rule_id, rule]));
  const coverage = document.createElement("section");
  coverage.className = "report-section coverage-result";
  coverage.append(heading(3, "部分的な審査済み範囲"));
  const coverageText = document.createElement("p");
  coverageText.textContent = report.reviewed_coverage_statement;
  const limitationText = document.createElement("p");
  limitationText.textContent = report.limitation_statement;
  coverage.append(coverageText, limitationText);

  const readiness = document.createElement("section");
  readiness.className = "report-section";
  readiness.append(heading(3, "レポート準備状態"));
  const readinessValue = document.createElement("p");
  readinessValue.className = "readiness-value";
  readinessValue.textContent = `${statusLabel(report.report_status)} (${report.report_status})`;
  readiness.append(readinessValue);

  const findings = document.createElement("section");
  findings.className = "report-section";
  findings.append(heading(3, "規則ごとの確認結果"));
  const findingList = document.createElement("ol");
  findingList.className = "finding-list";
  for (const finding of answer.rule_findings) {
    const item = document.createElement("li");
    const title = document.createElement("h4");
    title.textContent = finding.rule_id;
    const details = document.createElement("dl");
    details.className = "evidence-meta";
    addMetadata(details, "Finding ID", finding.finding_id);
    addMetadata(details, "状態", `${statusLabel(finding.original_status)} (${finding.original_status})`);
    addMetadata(details, "配置", `${statusLabel(finding.disposition)} (${finding.disposition})`);
    addMetadata(details, "対象", finding.subject_key);
    addMetadata(details, "適用判定ステップ", finding.source_applicability_step_id);
    addMetadata(details, "解決ステップ", finding.source_resolution_step_id);
    const scope = finding.scope;
    addMetadata(details, "適用範囲", `${scope.scope_type} | ${(scope.scope_targets || []).join(" / ") || "指定なし"}${scope.parent_college ? ` | ${scope.parent_college}` : ""}`);
    if (finding.activated_override) {
      const override = finding.activated_override;
      addMetadata(details, "上書き", `${override.overrider_rule_id} | ${override.subject_key} | ${override.rationale}`);
    }
    const reviewedRule = rulesById.get(finding.rule_id);
    if (finding.disposition === "active" && reviewedRule && reviewedRule.annotation_note) {
      addMetadata(details, "審査済み説明", reviewedRule.annotation_note);
    }
    item.append(title, details, citationList(finding.citations));
    findingList.append(item);
  }
  findings.append(findingList);

  const diagnostics = document.createElement("section");
  diagnostics.className = "report-section";
  diagnostics.append(heading(3, "不足情報・確認事項"));
  const diagnosticList = document.createElement("ul");
  diagnosticList.className = "diagnostic-list";
  for (const missing of answer.missing_information) {
    const item = document.createElement("li");
    item.textContent = `missing | rule: ${missing.rule_id} | field: ${missing.field_path} | applicability: ${missing.source_applicability_step_id} | resolution: ${missing.source_resolution_step_id}`;
    diagnosticList.append(item);
  }
  for (const warning of answer.interaction_warnings) {
    const item = document.createElement("li");
    item.textContent = `${warning.kind} | ${warning.certainty} | rules: ${warning.rule_ids.join(", ")} | id: ${warning.warning_id} | pair: ${warning.pair_id} | step: ${warning.source_interaction_step_id}`;
    item.append(citationList(warning.citations));
    diagnosticList.append(item);
  }
  for (const notice of answer.process_notices) {
    const item = document.createElement("li");
    item.textContent = `${notice.kind} | rules: ${notice.rule_ids.join(", ")} | steps: ${notice.source_step_ids.join(", ")}`;
    diagnosticList.append(item);
  }
  if (!diagnosticList.hasChildNodes()) {
    const item = document.createElement("li");
    item.textContent = "不足情報・確認事項なし";
    diagnosticList.append(item);
  }
  diagnostics.append(diagnosticList);

  const conversion = document.createElement("section");
  conversion.className = "report-section";
  conversion.append(heading(3, "英語外部試験の換算"));
  const conversionResult = report.language_score_conversion;
  if (conversionResult) {
    const details = document.createElement("dl");
    details.className = "evidence-meta";
    addMetadata(details, "入力試験", conversionResult.input_test_kind || "未指定");
    addMetadata(details, "入力得点", conversionResult.input_score || "未指定");
    addMetadata(details, "状態", conversionResult.status);
    addMetadata(details, "結果形態", conversionResult.result_shape);
    addMetadata(details, "根拠", `${conversionResult.evidence_binding.fact_id} | p.${conversionResult.evidence_binding.source_pages.join(",")}`);
    conversion.append(details);
    if (conversionResult.conversion_chain.length) {
      const chain = document.createElement("ol");
      chain.className = "diagnostic-list";
      for (const step of conversionResult.conversion_chain) {
        const item = document.createElement("li");
        item.textContent = `${step.operation}: ${step.expression}`;
        chain.append(item);
      }
      conversion.append(chain);
    }
    appendConversionCandidates(conversion, "PBT", conversionResult.pbt_candidates);
    appendConversionCandidates(conversion, "TOEIC L&R", conversionResult.toeic_candidates);
    for (const field of conversionResult.missing_fields) {
      const item = document.createElement("p");
      item.textContent = `不足情報: ${field}`;
      conversion.append(item);
    }
    for (const limitation of conversionResult.limitations) {
      const item = document.createElement("p");
      item.textContent = `制限: ${limitation}`;
      conversion.append(item);
    }
  } else {
    const unavailable = document.createElement("p");
    unavailable.textContent = "この審査済み計画には換算基準がありません。";
    conversion.append(unavailable);
  }

  const allocation = document.createElement("section");
  allocation.className = "report-section";
  allocation.append(heading(3, "志望系の英語公式配点"));
  const allocationResult = report.language_score_allocation;
  const allocationDetails = document.createElement("dl");
  allocationDetails.className = "evidence-meta";
  if (allocationResult) {
    addMetadata(allocationDetails, "対象", allocationResult.target || "未指定");
    addMetadata(allocationDetails, "状態", allocationResult.status);
    const points = allocationResult.maximum_points === null
      ? "審査済み数値配点の対象外または未確認"
      : `${allocationResult.maximum_points} points（公式配点・満点）`;
    addMetadata(allocationDetails, "配点", points);
    if (allocationResult.evidence) {
      addMetadata(allocationDetails, "根拠", `${allocationResult.evidence.fact_id} | p.${allocationResult.evidence.source_pages.join(",")}`);
    }
    addMetadata(allocationDetails, "制限", allocationResult.limitation_statement);
  } else {
    addMetadata(allocationDetails, "状態", "この審査済み計画には系別配点データがありません。");
  }
  allocation.append(allocationDetails);

  const evaluation = document.createElement("section");
  evaluation.className = "report-section";
  evaluation.append(heading(3, "志望系の英語評価方式"));
  const evaluationResult = report.language_evaluation;
  const evaluationDetails = document.createElement("dl");
  evaluationDetails.className = "evidence-meta";
  if (evaluationResult) {
    addMetadata(evaluationDetails, "対象", evaluationResult.target || "未指定");
    addMetadata(evaluationDetails, "状態", evaluationResult.status);
    if (evaluationResult.evidence) {
      if (evaluationResult.assessment_source === "written_exam") {
        addMetadata(evaluationDetails, "評価方式", "校内英語筆答試験 / 合格・不合格");
        addMetadata(evaluationDetails, "受験対象", "全員");
        addMetadata(evaluationDetails, "外部試験による免除", "なし");
        addMetadata(evaluationDetails, "選抜上の位置づけ", "本選抜合格の必要条件");
      } else {
        addMetadata(evaluationDetails, "出願日程", evaluationResult.application_route);
        addMetadata(evaluationDetails, "評価方式", "指定英語外部試験のスコア");
        addMetadata(evaluationDetails, "校内英語筆答試験", "実施なし");
        addMetadata(
          evaluationDetails,
          "評価用途",
          "口頭試問対象者の選定 / 最終総合評価"
        );
      }
      addMetadata(evaluationDetails, "根拠", `${evaluationResult.evidence.fact_id} | p.${evaluationResult.evidence.source_pages.join(",")}`);
    } else {
      addMetadata(evaluationDetails, "評価方式", "審査済み非数値評価の対象外または未確認");
    }
    addMetadata(evaluationDetails, "制限", evaluationResult.limitation_statement);
  } else {
    addMetadata(evaluationDetails, "状態", "この審査済み計画には非数値評価データがありません。");
  }
  evaluation.append(evaluationDetails);

  const programLanguage = document.createElement("section");
  programLanguage.className = "report-section";
  programLanguage.append(heading(3, "プロジェクト固有の言語選考条件"));
  const programLanguageResult = report.program_language_condition;
  const programLanguageDetails = document.createElement("dl");
  programLanguageDetails.className = "evidence-meta";
  if (programLanguageResult) {
    addMetadata(programLanguageDetails, "出願経路", programLanguageResult.application_route || "未指定");
    addMetadata(programLanguageDetails, "状態", programLanguageResult.status);
    if (programLanguageResult.evidence) {
      addMetadata(programLanguageDetails, "プログラム", programLanguageResult.program);
      addMetadata(programLanguageDetails, "言語", "中国語");
      addMetadata(programLanguageDetails, "入学選考での扱い", "選考対象外");
      addMetadata(programLanguageDetails, "根拠", `${programLanguageResult.evidence.fact_id} | p.${programLanguageResult.evidence.source_pages.join(",")}`);
    } else {
      addMetadata(programLanguageDetails, "選考条件", "審査範囲外または情報不足");
    }
    addMetadata(programLanguageDetails, "制限", programLanguageResult.limitation_statement);
  } else {
    addMetadata(programLanguageDetails, "状態", "この審査済み計画にはプロジェクト固有の言語条件がありません。");
  }
  programLanguage.append(programLanguageDetails);

  const materials = document.createElement("section");
  materials.className = "report-section";
  materials.append(heading(3, "一般志願者の共通出願書類"));
  const materialsResult = report.application_materials;
  const materialsDetails = document.createElement("dl");
  materialsDetails.className = "evidence-meta";
  if (materialsResult) {
    const labels = {
      required: "この共通一覧で提出が必要",
      eligibility_review_path: "出願資格審査の提出書類として取り扱う（この共通一覧では不要）",
      needs_information: "出願資格経路の確認が必要",
      not_covered: "この募集要項の対象外",
    };
    for (const entry of materialsResult.entries) {
      addMetadata(materialsDetails, `${entry.number}. ${entry.official_name}`, labels[entry.applicability]);
    }
    addMetadata(materialsDetails, "根拠", `${materialsResult.evidence.fact_id} | p.${materialsResult.evidence.source_pages.join(",")}`);
    addMetadata(materialsDetails, "制限", materialsResult.limitation_statement);
  } else {
    addMetadata(materialsDetails, "状態", "この審査済み計画には共通提出材料データがありません。");
  }
  materials.append(materialsDetails);

  const evidence = document.createElement("section");
  evidence.className = "report-section";
  evidence.append(heading(3, "公式根拠（原文）"));
  for (const record of report.evidence_bundle.evidence_records) {
    const item = document.createElement("article");
    item.className = "report-evidence";
    item.append(heading(4, pageCitation(record)));
    const identity = document.createElement("p");
    identity.textContent = `文書: ${record.document_id} | Fact: ${record.fact_id}`;
    const quote = document.createElement("blockquote");
    quote.className = "evidence-text";
    quote.textContent = record.text;
    item.append(identity, quote);
    evidence.append(item);
  }

  const finalNotice = document.createElement("p");
  finalNotice.className = "final-notice";
  finalNotice.textContent = "この結果は、総合的な出願資格、合否、合格可能性、または推奨を示すものではありません。";
  reportOutput.append(coverage, readiness, findings, diagnostics, conversion, allocation, evaluation, programLanguage, materials, evidence, finalNotice);
  setMessage(reportStatus, report.report_status, `レポート準備状態: ${statusLabel(report.report_status)} (${report.report_status})`, true);
}

function appendConversionCandidates(container, label, candidates) {
  if (!candidates.length) return;
  const list = document.createElement("ol");
  list.className = "diagnostic-list";
  for (const candidate of candidates) {
    const item = document.createElement("li");
    item.textContent = `${label}: ${formatExactInterval(candidate)}`;
    list.append(item);
  }
  container.append(list);
}

function formatExactInterval(candidate) {
  const lower = formatExactScore(candidate.lower);
  const upper = formatExactScore(candidate.upper);
  return lower === upper ? lower : `${lower} .. ${upper}`;
}

function formatExactScore(value) {
  return value.decimal === null ? `${value.numerator}/${value.denominator}` : value.decimal;
}

async function submitReport() {
  if (reportPending) return;
  const item = selectedCatalogItem();
  const query = reportQuery.value.trim();
  if (!item) { setMessage(reportStatus, "error", "募集要項を選択してください。", true); documentSelect.focus(); return; }
  if (!query || query.length > MAX_QUERY_LENGTH) { setMessage(reportStatus, "error", `質問は1文字以上${MAX_QUERY_LENGTH}文字以内で入力してください。`, true); reportQuery.focus(); return; }
  let profile;
  try { profile = applicantProfile(); } catch (_error) { setMessage(reportStatus, "error", "数値は整数で入力してください。", true); return; }
  const validation = validateProfile(profile);
  if (validation) { setMessage(reportStatus, "error", validation, true); return; }

  clearReportResult();
  reportPending = true;
  setBusy(true);
  setMessage(reportStatus, "loading", "質問の意図を確認しています。");
  try {
    const intentResponse = await fetch(INTENT_ENDPOINT, { method: "POST", headers: { Accept: "application/json", "Content-Type": "application/json" }, body: JSON.stringify({ schema_version: "1.0", query }), cache: "no-store", credentials: "same-origin" });
    if (!intentResponse.ok) throw { publicMessage: publicErrorMessage(intentResponse.status, await safeErrorCode(intentResponse), "report") };
    const intentPayload = await intentResponse.json();
    if (!intentPayload || intentPayload.schema_version !== "1.0") throw { publicMessage: "質問の意図を確認できませんでした。" };
    setMessage(reportStatus, "loading", "審査済み規則からレポートを作成しています。");
    const response = await fetch(REPORT_ENDPOINT, { method: "POST", headers: { Accept: "application/json", "Content-Type": "application/json" }, body: JSON.stringify(reportRequest(item, profile, intentPayload)), cache: "no-store", credentials: "same-origin" });
    if (!response.ok) throw { publicMessage: publicErrorMessage(response.status, await safeErrorCode(response), "report") };
    renderReport(await response.json());
  } catch (error) {
    reportCanRetry = true;
    reportRetry.hidden = false;
    setMessage(reportStatus, "error", error && typeof error.publicMessage === "string" ? error.publicMessage : "レポートサービスに接続できません。再試行してください。", true);
  } finally {
    reportPending = false;
    setBusy(false);
  }
}

function clearReport() {
  form.reset();
  reportForm.reset();
  queryCount.textContent = `0 / ${MAX_QUERY_LENGTH}`;
  reportQueryCount.textContent = `0 / ${MAX_QUERY_LENGTH}`;
  clearResults();
  clearReportResult();
  setStatus("initial", "募集要項を選び、確認したい内容を入力してください。");
  setMessage(reportStatus, "initial", "質問と分かる範囲の条件を入力してください。", true);
}

function activateTab(tab) {
  const showReport = tab === reportTab;
  evidenceTab.setAttribute("aria-selected", String(!showReport));
  reportTab.setAttribute("aria-selected", String(showReport));
  evidenceTab.tabIndex = showReport ? -1 : 0;
  reportTab.tabIndex = showReport ? 0 : -1;
  evidenceView.hidden = showReport;
  reportView.hidden = !showReport;
  tab.focus();
}

function handleTabKey(event) {
  if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
  event.preventDefault();
  activateTab(event.currentTarget === evidenceTab ? reportTab : evidenceTab);
}

function option(value, label) {
  const item = document.createElement("option");
  item.value = value;
  item.textContent = label;
  return item;
}

function resetDemoSelect(select, message) {
  select.replaceChildren(option("", message));
  select.disabled = true;
}

function clearDemoResults(message = "完成左侧选择后，再明确加载要求。") {
  requirementsOutput.replaceChildren();
  targetSummary.hidden = false;
  targetSummary.textContent = message;
}

function currentSchool() {
  return demoCatalog.find((item) => item.school_id === schoolSelect.value);
}

function currentDegree() {
  const school = currentSchool();
  return school ? school.degrees.find((item) => item.degree_id === demoDegreeSelect.value) : null;
}

function currentIntake() {
  const degree = currentDegree();
  return degree ? degree.intakes.find((item) => `${item.document_id}:${item.year}:${item.month}` === intakeSelect.value) : null;
}

function currentCollege() {
  const intake = currentIntake();
  return intake ? intake.colleges.find((item) => item.college_id === collegeSelect.value) : null;
}

function currentDepartment() {
  const college = currentCollege();
  return college ? college.departments.find((item) => item.department_id === departmentSelect.value) : null;
}

function demoTargetComplete() {
  const department = currentDepartment();
  return Boolean(
    currentSchool() && currentDegree() && currentIntake() && currentCollege() && department
    && (department.application_routes.length === 0 || routeSelect.value)
  );
}

function targetLabel(target) {
  return [
    target.school_name,
    target.degree_name,
    target.intake_name,
    target.college_name,
    target.department_name,
    target.application_route_name
  ].filter(Boolean).join(" · ");
}

function updateTargetStepSummary(target) {
  byId("step-1-summary-text").textContent = targetLabel(target);
}

function updateRequirementsStepSummary(payload) {
  const labels = [
    ["dates", "关键日期"],
    ["materials", "核心材料"],
    ["eligibility", "学历资格"],
    ["language", "语言要求"]
  ];
  const counts = labels.map(([category, label]) => {
    const count = payload.requirements.filter((item) => item.category === category).length;
    return `${label} ${count} 项`;
  });
  const hasDates = payload.requirements.some((item) => item.category === "dates");
  byId("step-2-summary-text").textContent = `${counts.join(" · ")}${hasDates ? "；请优先核对关键日期与截止说明。" : ""}`;
}

function updateApplicantStepSummary() {
  const categories = [
    ["学历", profileGroupHasProvidedValue("education")],
    ["英语", profileGroupHasProvidedValue("english")],
    ["日语", profileGroupHasProvidedValue("japanese")],
    ["材料", profileGroupHasProvidedValue("materials")]
  ];
  const provided = categories.filter(([, value]) => value).map(([label]) => label);
  const missing = categories.filter(([, value]) => !value).map(([label]) => label);
  const parts = [
    `已提供类别：${provided.length ? provided.join("、") : "无"}`,
    `未提供类别：${missing.length ? missing.join("、") : "无"}`
  ];
  byId("step-3-summary-text").textContent = parts.join("；");
}

function updateRequirementsSubmit() {
  const department = currentDepartment();
  const missing = [
    [currentSchool(), "学校"],
    [currentDegree(), "学位"],
    [currentIntake(), "入学时间"],
    [currentCollege(), "学院"],
    [department, "系／专业"],
    [department && (department.application_routes.length === 0 || routeSelect.value), "出愿日程／方式"]
  ].filter(([complete]) => !complete).map(([, label]) => label);
  requirementsSubmit.disabled = requirementsPending || missing.length > 0;
  targetCompletionHint.dataset.state = missing.length ? "incomplete" : "ready";
  targetCompletionHint.textContent = requirementsPending
    ? "正在读取官方要求，请稍候。"
    : missing.length
      ? `还需选择：${missing.join("、")}。`
      : "申请目标已完整，可以查看基础出愿要求。";
}

function profileValueState(control) {
  if (!control.value) return "empty";
  if (["unknown", "ui_unknown", "ui_not_applicable"].includes(control.value)) return "unknown";
  return "provided";
}

function profileGroupControls(group) {
  return Array.from(group.querySelectorAll("select, input"));
}

function profileGroupHasProvidedValue(key) {
  const group = applicantForm.querySelector(`[data-profile-group="${key}"]`);
  return profileGroupControls(group).some((control) => profileValueState(control) === "provided");
}

function updateProfileGroupStates() {
  for (const group of applicantForm.querySelectorAll(".profile-group")) {
    const values = profileGroupControls(group).map(profileValueState);
    const state = values.every((value) => value === "provided")
      ? "complete"
      : values.some((value) => value === "provided")
        ? "partial"
        : values.some((value) => value === "unknown") ? "unknown" : "empty";
    const labels = { complete: "已填写", partial: "已填写部分", unknown: "仍需确认", empty: "待填写" };
    const badge = group.querySelector(".profile-group-state");
    badge.dataset.state = state;
    badge.textContent = labels[state];
  }
}

function updateEnglishInputHint() {
  const kind = byId("demo-english-kind").value;
  const score = byId("demo-english-score").value;
  const date = byId("demo-english-date").value;
  const report = byId("demo-english-report").value;
  const concreteKind = kind && !kind.startsWith("ui_");
  const hint = byId("english-link-hint");
  if ((score || date) && !concreteKind) {
    hint.dataset.state = "attention";
    hint.textContent = "已填写成绩或考试日期：服务端还需要考试类型。可先继续填写，但提交前请选类型，或清空成绩与日期。";
  } else if (kind === "ui_not_applicable" && report === "true") {
    hint.dataset.state = "attention";
    hint.textContent = "你选择了未参加考试，同时标记已取得官方成绩单；请核对这两项输入。这里不判断成绩是否有效。";
  } else if (concreteKind) {
    hint.dataset.state = "info";
    hint.textContent = "考试类型已记录。成绩、日期和官方成绩单可暂时留空；已填写也不代表成绩有效或学校已受理。";
  } else {
    hint.dataset.state = "info";
    hint.textContent = "成绩和考试日期可暂时留空；如果填写其中之一，请先选择考试类型。";
  }
}

function initializeProfileGroups() {
  const desktop = window.matchMedia("(min-width: 761px)").matches;
  for (const group of applicantForm.querySelectorAll(".profile-group")) {
    group.open = desktop || group.dataset.profileGroup === "education";
  }
  updateProfileGroupStates();
  updateEnglishInputHint();
}

function resetApplicantInputs() {
  applicantForm.reset();
  updateProfileGroupStates();
  updateEnglishInputHint();
}

function populateDegreeSelect() {
  resetDemoSelect(demoDegreeSelect, "请选择学位");
  resetDemoSelect(intakeSelect, "请先选择学位");
  resetDemoSelect(collegeSelect, "请先选择入学时间");
  resetDemoSelect(departmentSelect, "请先选择学院");
  resetDemoSelect(routeSelect, "请选择日程或方式");
  routeField.hidden = true;
  const school = currentSchool();
  if (!school) { updateRequirementsSubmit(); return; }
  demoDegreeSelect.replaceChildren(option("", "请选择学位"));
  for (const degree of school.degrees) demoDegreeSelect.append(option(degree.degree_id, degree.degree_name));
  demoDegreeSelect.disabled = false;
  if (school.degrees.length === 1) demoDegreeSelect.value = school.degrees[0].degree_id;
  populateIntakeSelect();
}

function populateIntakeSelect() {
  resetDemoSelect(intakeSelect, "请选择入学时间");
  resetDemoSelect(collegeSelect, "请先选择入学时间");
  resetDemoSelect(departmentSelect, "请先选择学院");
  resetDemoSelect(routeSelect, "请选择日程或方式");
  routeField.hidden = true;
  const degree = currentDegree();
  if (!degree) { updateRequirementsSubmit(); return; }
  intakeSelect.replaceChildren(option("", "请选择入学时间"));
  for (const intake of degree.intakes) intakeSelect.append(option(`${intake.document_id}:${intake.year}:${intake.month}`, intake.intake_name));
  intakeSelect.disabled = false;
  updateRequirementsSubmit();
}

function populateCollegeSelect() {
  resetDemoSelect(collegeSelect, "请选择学院");
  resetDemoSelect(departmentSelect, "请先选择学院");
  resetDemoSelect(routeSelect, "请选择日程或方式");
  routeField.hidden = true;
  const intake = currentIntake();
  if (!intake) { updateRequirementsSubmit(); return; }
  collegeSelect.replaceChildren(option("", "请选择学院"));
  for (const college of intake.colleges) collegeSelect.append(option(college.college_id, college.college_name));
  collegeSelect.disabled = false;
  updateRequirementsSubmit();
}

function populateDepartmentSelect() {
  resetDemoSelect(departmentSelect, "请选择系／专业");
  resetDemoSelect(routeSelect, "请选择日程或方式");
  routeField.hidden = true;
  const college = currentCollege();
  if (!college) { updateRequirementsSubmit(); return; }
  departmentSelect.replaceChildren(option("", "请选择系／专业"));
  for (const department of college.departments) departmentSelect.append(option(department.department_id, department.department_name));
  departmentSelect.disabled = false;
  updateRequirementsSubmit();
}

function populateRouteSelect() {
  resetDemoSelect(routeSelect, "请选择日程或方式");
  const department = currentDepartment();
  if (!department || department.application_routes.length === 0) {
    routeField.hidden = true;
    updateRequirementsSubmit();
    return;
  }
  routeSelect.replaceChildren(option("", "请选择日程或方式"));
  for (const route of department.application_routes) routeSelect.append(option(route.route_id, route.route_name));
  routeSelect.disabled = false;
  routeField.hidden = false;
  updateRequirementsSubmit();
}

function populateDemoCatalog(schools) {
  demoCatalog = schools;
  schoolSelect.replaceChildren(option("", "请选择学校"));
  for (const school of schools) schoolSelect.append(option(school.school_id, school.school_name));
  schoolSelect.disabled = schools.length === 0;
  if (schools.length === 1) schoolSelect.value = schools[0].school_id;
  populateDegreeSelect();
  requirementsRetry.hidden = true;
  setMessage(targetStatus, schools.length ? "success" : "empty", schools.length ? "审核目录已就绪，请完成申请目标。" : "当前没有可用的审核目标。", schools.length === 0);
}

async function loadDemoCatalog() {
  cancelPendingRequirements();
  baseRequirementsLoaded = false;
  invalidateComparison("请先加载基础要求。");
  activateStep(1);
  demoCatalog = [];
  requirementsRetry.hidden = true;
  clearDemoResults();
  resetDemoSelect(schoolSelect, "正在读取审核目录");
  resetDemoSelect(demoDegreeSelect, "请先选择学校");
  resetDemoSelect(intakeSelect, "请先选择学位");
  resetDemoSelect(collegeSelect, "请先选择入学时间");
  resetDemoSelect(departmentSelect, "请先选择学院");
  setMessage(targetStatus, "loading", "正在读取服务端审核目标目录。");
  try {
    const response = await fetch(TARGET_CATALOG_ENDPOINT, { method: "GET", headers: { Accept: "application/json" }, cache: "no-store", credentials: "same-origin" });
    if (!response.ok) throw new Error();
    const payload = await response.json();
    if (!payload || !Array.isArray(payload.schools)) throw new Error();
    populateDemoCatalog(payload.schools);
  } catch (_error) {
    requirementsRetry.hidden = false;
    setMessage(targetStatus, "error", "审核目录暂时无法读取，请重试。", true);
  }
}

function demoTargetRequest() {
  const intake = currentIntake();
  return {
    schema_version: "1.0",
    school_id: schoolSelect.value,
    document_id: intake.document_id,
    degree_id: demoDegreeSelect.value,
    intake: { year: intake.year, month: intake.month },
    college_id: collegeSelect.value,
    department_id: departmentSelect.value,
    application_route: routeSelect.value || null
  };
}

function requirementStatusLabel(status) {
  const labels = {
    required: "官方状态：必需",
    conditional: "官方状态：有条件适用",
    needs_information: "官方状态：待补充信息",
    needs_review: "官方状态：需要人工确认",
    not_applicable: "官方状态：不适用",
    not_covered: "官方状态：当前未覆盖"
  };
  return labels[status] || `官方状态：${status}`;
}

function profileGroupsFromSchema() {
  return Array.from(document.querySelectorAll("[data-profile-group]"), (group) => ({
    key: group.dataset.profileGroup,
    label: group.dataset.profileLabel,
    requirementCategories: (group.dataset.requirementCategories || "")
      .split(",")
      .filter(Boolean)
  }));
}

function applicationOverview(payload) {
  return globalThis.JGradOverview.buildApplicationOverview(payload, profileGroupsFromSchema());
}

function profileCta(className = "") {
  const button = document.createElement("button");
  button.type = "button";
  button.className = className;
  button.textContent = "填写个人情况，检查我还缺什么";
  button.addEventListener("click", () => {
    if (baseRequirementsLoaded) activateStep(3, true);
  });
  return button;
}

function renderDateEvent(event) {
  const card = document.createElement("article");
  card.className = "date-event";
  card.dataset.eventType = event.event_type;
  const header = document.createElement("div");
  header.className = "date-event-header";
  header.append(heading(5, event.label));
  const nature = document.createElement("span");
  nature.className = "date-nature";
  nature.dataset.nature = event.nature;
  const natureLabels = {
    opens: "开放时间",
    period: "出愿期间",
    must_arrive: "必着截止",
    recommended_arrival: "建议到达"
  };
  nature.textContent = natureLabels[event.nature] || event.nature;
  header.append(nature);
  const conclusion = document.createElement("p");
  conclusion.className = "date-conclusion";
  conclusion.textContent = event.display_text;
  card.append(header, conclusion);
  if (event.uncertainty_note) {
    const note = document.createElement("p");
    note.className = "date-uncertainty";
    note.textContent = event.uncertainty_note;
    card.append(note);
  }
  if (Array.isArray(event.evidence) && event.evidence.length) {
    const actions = document.createElement("div");
    actions.className = "actions";
    for (const evidence of event.evidence) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "secondary";
      button.textContent = event.evidence.length === 1
        ? "核对直接依据"
        : `核对直接依据 · 第 ${evidence.pages.join("、")} 页`;
      button.addEventListener("click", () => openDemoEvidence(event, evidence, button));
      actions.append(button);
    }
    card.append(actions);
  }
  return card;
}

function appendRequirementEvidence(card, requirement) {
  if (!Array.isArray(requirement.evidence) || !requirement.evidence.length) return;
  const actions = document.createElement("div");
  actions.className = "actions requirement-evidence-actions";
  for (const evidence of requirement.evidence) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "secondary";
    button.textContent = requirement.evidence.length === 1
      ? "查看官方依据"
      : `查看官方依据 · 第 ${evidence.pages.join("、")} 页`;
    button.addEventListener("click", () => openDemoEvidence(requirement, evidence, button));
    actions.append(button);
  }
  card.append(actions);
}

function renderRequirementCard(requirement, options = {}) {
  const card = document.createElement("article");
  card.className = `requirement-card${options.compact ? " requirement-card-compact" : ""}`;
  card.dataset.category = requirement.category;
  card.append(heading(4, requirement.title));
  const status = document.createElement("span");
  status.className = "requirement-status";
  status.dataset.status = requirement.official_status;
  status.textContent = requirementStatusLabel(requirement.official_status);
  const description = document.createElement("p");
  description.className = "requirement-description";
  description.textContent = requirement.description;
  card.append(status, description);
  if (requirement.deadline) {
    const deadline = document.createElement("p");
    deadline.className = "deadline-callout";
    deadline.textContent = `官方日期／截止：${requirement.deadline}`;
    card.append(deadline);
  }
  if (!options.compact && requirement.reviewed_summary) {
    const detail = document.createElement("details");
    detail.className = "technical-disclosure";
    const summary = document.createElement("summary");
    summary.textContent = "查看审核日期摘要（日文）";
    const excerpt = document.createElement("blockquote");
    excerpt.className = "reviewed-summary";
    excerpt.textContent = requirement.reviewed_summary;
    detail.append(summary, excerpt);
    card.append(detail);
  }
  appendRequirementEvidence(card, requirement);
  return card;
}

function renderApplicationOverview(payload, overview) {
  const section = document.createElement("section");
  section.className = "application-overview";
  section.setAttribute("aria-labelledby", "application-overview-heading");
  const copy = document.createElement("div");
  copy.className = "application-overview-copy";
  const eyebrow = document.createElement("p");
  eyebrow.className = "section-label";
  eyebrow.textContent = "申请概览";
  const title = heading(3, "先确认截止，再开始准备");
  title.id = "application-overview-heading";
  const target = document.createElement("p");
  target.className = "overview-target";
  target.textContent = targetLabel(payload.target);
  copy.append(eyebrow, title, target);

  const metrics = document.createElement("dl");
  metrics.className = "overview-metrics";
  const metricValues = [
    ["最重要的必着截止", overview.deadlineText, "deadline"],
    ["核心材料", overview.materialCount === null ? "暂无已审核数据" : `${overview.materialCount} 项`, "materials"],
    ["基础要求待确认", overview.needsInformationCount === null ? "暂无已审核数据" : `${overview.needsInformationCount} 项`, "pending"]
  ];
  for (const [label, value, kind] of metricValues) {
    const item = document.createElement("div");
    item.dataset.metric = kind;
    const dt = document.createElement("dt");
    dt.textContent = label;
    const dd = document.createElement("dd");
    dd.textContent = value;
    item.append(dt, dd);
    metrics.append(item);
  }
  if (overview.needsInformationCount !== null) {
    const pendingMetric = metrics.querySelector('[data-metric="pending"]');
    const note = document.createElement("p");
    note.className = "overview-metric-note";
    note.textContent = `其中 ${overview.profileComparableCount} 项可进入个人对照，${overview.otherConfirmationCount} 项需另行确认`;
    pendingMetric.append(note);
  }
  copy.append(metrics);

  const action = document.createElement("aside");
  action.className = "overview-action";
  const actionLabel = document.createElement("p");
  actionLabel.textContent = "下一步";
  const actionHint = document.createElement("p");
  actionHint.className = "field-detail";
  actionHint.textContent = "填写后会使用现有规则保守对照，不会保存个人资料。";
  action.append(actionLabel, profileCta("overview-cta"), actionHint);
  section.append(copy, action);
  return section;
}

function renderKeyDates(requirements) {
  const section = document.createElement("section");
  section.className = "result-section key-dates-section";
  section.append(heading(3, "关键时间"));
  const intro = document.createElement("p");
  intro.className = "section-intro";
  intro.textContent = "“必着”表示材料必须在该时点前送达；“建议到达”只是降低延误风险的建议，不是另一个强制截止。";
  section.append(intro);
  const dateList = document.createElement("div");
  dateList.className = "date-event-list";
  for (const requirement of requirements) {
    for (const event of Array.isArray(requirement.date_events) ? requirement.date_events : []) {
      dateList.append(renderDateEvent(event));
    }
  }
  if (!dateList.childElementCount) {
    const empty = document.createElement("p");
    empty.className = "empty-reviewed-data";
    empty.textContent = "暂无已审核数据";
    dateList.append(empty);
  }
  section.append(dateList);
  return section;
}

function renderRequirementSection(title, entries, className) {
  const section = document.createElement("section");
  section.className = `result-section ${className}`;
  section.append(heading(3, title));
  const list = document.createElement("div");
  list.className = "requirement-list";
  if (entries.length) {
    for (const requirement of entries) list.append(renderRequirementCard(requirement));
  } else {
    const empty = document.createElement("p");
    empty.className = "empty-reviewed-data";
    empty.textContent = "暂无已审核数据";
    list.append(empty);
  }
  section.append(list);
  return section;
}

function renderPendingRequirements(entries, overview) {
  const section = document.createElement("section");
  section.className = "result-section pending-section";
  const count = overview.needsInformationCount;
  section.append(heading(3, count === null
    ? "仍需进一步确认的基础要求"
    : `仍需进一步确认的基础要求：${count} 项`));
  const explanation = document.createElement("p");
  explanation.className = "section-intro";
  explanation.textContent = count === null
    ? "当前暂无已审核数据，不会推断要求是否满足。"
    : `其中 ${overview.profileComparableCount} 项可进入现有个人对照；${overview.otherConfirmationCount} 项需另行确认。待确认不等于不符合，填写个人情况也不保证所有项目都能得出结论。`;
  section.append(explanation);
  if (overview.otherConfirmationRequirements.length) {
    const otherNotice = document.createElement("p");
    otherNotice.className = "pending-other-notice";
    otherNotice.textContent = `当前个人情况步骤不处理：${overview.otherConfirmationRequirements.map((item) => item.title).join("、")}。请核对实际情况及官方要求。`;
    section.append(otherNotice);
  }
  const inputHeading = heading(4, "下一步可填写的个人情况");
  inputHeading.className = "profile-input-heading";
  section.append(inputHeading);
  const categories = document.createElement("ul");
  categories.className = "profile-needs-list";
  for (const group of overview.profileInputGroups) {
    const item = document.createElement("li");
    item.textContent = group.label;
    categories.append(item);
  }
  if (!categories.childElementCount) {
    const item = document.createElement("li");
    item.textContent = "暂无已审核数据";
    categories.append(item);
  }
  section.append(categories);
  if (entries.length) {
    const details = document.createElement("details");
    details.className = "pending-details";
    const summary = document.createElement("summary");
    summary.textContent = `查看待确认的 ${entries.length} 项要求`;
    const list = document.createElement("div");
    list.className = "requirement-list";
    for (const requirement of entries) list.append(renderRequirementCard(requirement, { compact: true }));
    details.append(summary, list);
    section.append(details);
  }
  return section;
}

function renderRequirements(payload) {
  requirementsOutput.replaceChildren();
  const target = payload.target;
  targetSummary.hidden = true;
  targetSummary.textContent = targetLabel(target);
  updateTargetStepSummary(target);
  updateRequirementsStepSummary(payload);
  const overview = applicationOverview(payload);
  const requirements = payload.requirements;
  const dateRequirements = requirements.filter((item) => item.category === "dates");
  const requiredMaterials = requirements.filter((item) => (
    item.category === "materials" && item.official_status === "required"
  ));
  const pending = requirements.filter((item) => item.official_status === "needs_information");
  const secondary = requirements.filter((item) => (
    item.category !== "dates"
    && !(item.category === "materials" && item.official_status === "required")
    && item.official_status !== "needs_information"
  ));

  requirementsOutput.append(
    renderApplicationOverview(payload, overview),
    renderKeyDates(dateRequirements),
    renderRequirementSection("必须准备的材料", requiredMaterials, "materials-section"),
    renderPendingRequirements(pending, overview)
  );

  const next = document.createElement("section");
  next.className = "result-section next-step-section";
  const nextCopy = document.createElement("div");
  nextCopy.append(heading(3, "下一步：对照你的个人情况"));
  const nextText = document.createElement("p");
  nextText.textContent = "继续到现有个人情况步骤，填写后查看还缺哪些材料或信息。";
  nextCopy.append(nextText);
  next.append(nextCopy, profileCta("next-step-cta"));
  requirementsOutput.append(next);

  const other = document.createElement("details");
  other.className = "result-section other-requirements";
  const otherSummary = document.createElement("summary");
  otherSummary.textContent = `其他说明与已审核要求${secondary.length ? `（${secondary.length} 项）` : ""}`;
  const otherList = document.createElement("div");
  otherList.className = "requirement-list";
  for (const requirement of secondary) otherList.append(renderRequirementCard(requirement));
  if (!secondary.length) {
    const empty = document.createElement("p");
    empty.className = "empty-reviewed-data";
    empty.textContent = "暂无其他已审核要求";
    otherList.append(empty);
  }
  other.append(otherSummary, otherList);
  requirementsOutput.append(other);

  const boundary = document.createElement("p");
  boundary.className = "final-notice";
  boundary.textContent = `审核覆盖：${payload.coverage_statement} 限制：${payload.limitation_statement}`;
  requirementsOutput.append(boundary);
}

function appendDefinition(list, term, value) {
  const dt = document.createElement("dt");
  dt.textContent = term;
  const dd = document.createElement("dd");
  dd.textContent = value;
  list.append(dt, dd);
}

function appendHighlightedOfficialText(container, officialText, highlights) {
  let offset = 0;
  for (const highlight of highlights) {
    const valid = Number.isSafeInteger(highlight.start)
      && Number.isSafeInteger(highlight.end)
      && highlight.start >= offset
      && highlight.end > highlight.start
      && highlight.end <= officialText.length
      && officialText.slice(highlight.start, highlight.end) === highlight.exact_text;
    if (!valid) {
      container.textContent = officialText;
      return false;
    }
    container.append(document.createTextNode(officialText.slice(offset, highlight.start)));
    const mark = document.createElement("mark");
    mark.textContent = highlight.exact_text;
    container.append(mark);
    offset = highlight.end;
  }
  container.append(document.createTextNode(officialText.slice(offset)));
  return true;
}

function verifiedLocalPdfHref(baseUrl, page) {
  if (typeof baseUrl !== "string"
      || !/^\/documents\/[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?\/source\.pdf$/.test(baseUrl)
      || !Number.isSafeInteger(page)
      || page < 1) return null;
  return `${baseUrl}#page=${page}`;
}

function openDemoEvidence(requirement, evidence, trigger) {
  drawerTrigger = trigger;
  drawerContent.replaceChildren();
  drawerContent.append(heading(3, requirement.title || requirement.label || "官方依据"));
  const meta = document.createElement("dl");
  meta.className = "evidence-meta";
  appendDefinition(meta, "官方文档", evidence.official_title);
  appendDefinition(meta, "学校／入学时间", `${evidence.school_name} · ${evidence.intake_name}`);
  appendDefinition(meta, "官方页码", `第 ${evidence.pages.join("、")} 页（来源链接不保证自动定位，请在文件中查看该页）`);
  const highlights = Array.isArray(evidence.highlights) ? evidence.highlights : [];
  const evidenceBody = document.createDocumentFragment();
  if (highlights.length) {
    const directHeading = document.createElement("p");
    directHeading.className = "direct-evidence-heading";
    directHeading.textContent = "与这条结论直接对应的官方原文";
    evidenceBody.append(directHeading);
    for (const highlight of highlights) {
      const direct = document.createElement("blockquote");
      direct.className = "direct-evidence";
      const label = document.createElement("span");
      label.className = "direct-evidence-label";
      label.textContent = "直接依据";
      const mark = document.createElement("mark");
      mark.textContent = highlight.exact_text;
      direct.append(label, mark);
      evidenceBody.append(direct);
    }
    const context = document.createElement("details");
    context.className = "official-context";
    const contextSummary = document.createElement("summary");
    contextSummary.textContent = "展开完整官方原文";
    const quote = document.createElement("blockquote");
    quote.className = "evidence-text";
    appendHighlightedOfficialText(quote, evidence.official_text, highlights);
    context.append(contextSummary, quote);
    evidenceBody.append(context);
  } else {
    const quote = document.createElement("blockquote");
    quote.className = "evidence-text";
    quote.textContent = evidence.official_text;
    evidenceBody.append(quote);
  }
  const limitation = document.createElement("p");
  limitation.className = "final-notice";
  limitation.textContent = `安全限制：${evidence.limitation}`;
  const details = document.createElement("details");
  const summary = document.createElement("summary");
  summary.textContent = "技术详情";
  const technical = document.createElement("dl");
  technical.className = "evidence-meta";
  appendDefinition(technical, "Fact ID", evidence.fact_id);
  appendDefinition(technical, "Document ID", evidence.document_id);
  appendDefinition(technical, "Scope", `${evidence.scope_type}${evidence.parent_college ? ` · ${evidence.parent_college}` : ""}${evidence.scope_targets.length ? ` · ${evidence.scope_targets.join("、")}` : ""}`);
  details.append(summary, technical);
  const sourceActions = document.createElement("div");
  sourceActions.className = "source-actions";
  if (evidence.local_pdf_url) {
    for (const page of evidence.pages) {
      const href = verifiedLocalPdfHref(evidence.local_pdf_url, page);
      if (!href) continue;
      const pdfLink = document.createElement("a");
      pdfLink.className = "source-link pdf-source-link";
      pdfLink.href = href;
      pdfLink.target = "_blank";
      pdfLink.rel = "noopener noreferrer";
      pdfLink.textContent = `在 PDF 中查看第 ${page} 页`;
      sourceActions.append(pdfLink);
    }
  }
  const source = document.createElement("a");
  source.className = "source-link official-web-link";
  source.href = evidence.source_url;
  source.target = "_blank";
  source.rel = "noopener noreferrer";
  source.textContent = "打开官方招生网页";
  sourceActions.append(source);
  drawerContent.append(meta, evidenceBody, limitation, details, sourceActions);
  evidenceDrawer.showModal();
  drawerClose.focus();
}

function nullableDemoValue(id) {
  const value = byId(id).value;
  return value && !value.startsWith("ui_") ? value : null;
}

function nullableDemoNumber(id) {
  const value = byId(id).value;
  return value === "" ? null : Number(value);
}

function nullableDemoBoolean(id) {
  const value = byId(id).value;
  return value === "true" ? true : value === "false" ? false : null;
}

function demoApplicantInput() {
  return {
    credential_basis: nullableDemoValue("demo-credential-basis"),
    completion_state: nullableDemoValue("demo-completion-state"),
    english_test_kind: nullableDemoValue("demo-english-kind"),
    english_score: nullableDemoNumber("demo-english-score"),
    english_test_date: nullableDemoValue("demo-english-date"),
    english_official_report_available: nullableDemoBoolean("demo-english-report"),
    japanese_background: nullableDemoValue("demo-japanese-background"),
    materials: Array.from(document.querySelectorAll("[data-material-code]"), (select) => ({
      code: select.dataset.materialCode,
      preparation: ["available", "not_yet"].includes(select.value) ? select.value : "unknown"
    }))
  };
}

function demoComparisonRequest() {
  return { schema_version: "1.0", target: demoTargetRequest(), applicant: demoApplicantInput() };
}

function cancelPendingComparison() {
  comparisonRequestId += 1;
  if (comparisonController) comparisonController.abort();
  comparisonController = null;
  comparisonPending = false;
  comparisonSubmit.disabled = !baseRequirementsLoaded;
}

function clearComparison(message = "填写个人情况后，可由服务端进行保守对照。") {
  comparisonComplete = false;
  comparisonOutput.replaceChildren();
  byId("priority-actions").replaceChildren();
  readinessPanel.hidden = true;
  readinessTarget.textContent = "";
  partialChecklistStatement.textContent = "";
  byId("count-total").textContent = "0";
  byId("count-recorded").textContent = "0";
  byId("count-action").textContent = "0";
  byId("count-review").textContent = "0";
  readinessFilters.querySelector('[value="all"]').checked = true;
  filterEmpty.hidden = true;
  comparisonRetry.hidden = true;
  setMessage(comparisonStatus, "initial", message);
}

function comparisonStatusLabel(status) {
  const labels = {
    recorded: "已记录",
    possible_match: "可能匹配，仍需核对",
    needs_information: "需要更多信息",
    needs_review: "需要学校／人工审核",
    not_applicable: "不适用",
    not_covered: "当前未覆盖"
  };
  return labels[status] || status;
}

function resetChecklistProgress() {
  for (const checkbox of comparisonOutput.querySelectorAll(".personal-check input")) {
    checkbox.checked = false;
    checkbox.dispatchEvent(new Event("change"));
  }
}

function renderPriorityActions(entries) {
  const container = byId("priority-actions");
  container.replaceChildren();
  const pending = entries.filter(({ item }) => item.action_group !== "recorded");
  const title = heading(4, "优先处理");
  container.append(title);
  if (!pending.length) {
    const empty = document.createElement("p");
    empty.textContent = "当前没有被系统归入补充或人工确认的项目；已记录仍不等于学校确认或完成出愿。";
    container.append(empty);
    return;
  }
  const list = document.createElement("ol");
  for (const { item, cardId } of pending.slice(0, 3)) {
    const row = document.createElement("li");
    const link = document.createElement("a");
    link.href = `#${cardId}`;
    link.textContent = item.title;
    link.addEventListener("click", (event) => {
      event.preventDefault();
      readinessFilters.querySelector('[value="all"]').checked = true;
      applyReadinessFilter();
      const target = byId(cardId);
      if (!target) return;
      window.history.replaceState(null, "", `#${cardId}`);
      target.scrollIntoView({ block: "start", behavior: "auto" });
      target.focus({ preventScroll: true });
    });
    const action = document.createElement("span");
    action.textContent = `${item.action_group === "action_required" ? "需要补充" : "需学校／人工确认"} · ${item.next_action}`;
    row.append(link, action);
    list.append(row);
  }
  container.append(list);
  if (pending.length > 3) {
    const remainder = document.createElement("p");
    remainder.className = "field-detail";
    remainder.textContent = `下方还有 ${pending.length - 3} 项需要逐项核对。`;
    container.append(remainder);
  }
}

function renderComparison(payload) {
  comparisonOutput.replaceChildren();
  readinessTarget.textContent = targetLabel(payload.target);
  partialChecklistStatement.textContent = payload.partial_checklist_statement;
  byId("count-total").textContent = String(payload.counts.total);
  byId("count-recorded").textContent = String(payload.counts.recorded);
  byId("count-action").textContent = String(payload.counts.action_required);
  byId("count-review").textContent = String(payload.counts.review_required);
  readinessFilters.querySelector('[value="all"]').checked = true;
  const groups = [["action_required", "需要补充"], ["review_required", "需学校／人工确认"], ["recorded", "已记录／可能匹配"]];
  const entriesWithIds = groups.flatMap(([actionGroup]) => payload.items
    .filter((item) => item.action_group === actionGroup)
    .map((item, index) => ({ item, cardId: `comparison-${actionGroup}-${index}` })));
  renderPriorityActions(entriesWithIds);
  const categoryLabels = { education: "学历", english: "英语", japanese: "日语", materials: "材料" };
  for (const [actionGroup, label] of groups) {
    const entries = entriesWithIds.filter(({ item }) => item.action_group === actionGroup);
    if (!entries.length) continue;
    const section = document.createElement("section");
    section.className = "requirement-group comparison-group";
    section.dataset.actionGroup = actionGroup;
    section.append(heading(3, label));
    const list = document.createElement("div");
    list.className = "requirement-list";
    for (const { item, cardId } of entries) {
      const card = document.createElement("article");
      card.className = "requirement-card comparison-card";
      card.id = cardId;
      card.tabIndex = -1;
      card.dataset.actionGroup = item.action_group;
      const category = document.createElement("p");
      category.className = "comparison-category";
      category.textContent = categoryLabels[item.category] || item.category;
      card.append(category);
      card.append(heading(4, item.title));
      const statusLabel = document.createElement("p");
      statusLabel.className = "comparison-state-label";
      statusLabel.textContent = "系统对照状态";
      const status = document.createElement("span");
      status.className = "requirement-status";
      status.dataset.status = item.comparison_status;
      status.textContent = comparisonStatusLabel(item.comparison_status);
      const description = document.createElement("p");
      description.className = "comparison-reason";
      description.textContent = `原因：${item.description}`;
      card.append(statusLabel, status, description);
      const nextAction = document.createElement("p");
      nextAction.className = "next-action";
      nextAction.textContent = `下一步：${item.next_action}`;
      card.append(nextAction);
      if (item.official_status) {
        const officialLabels = { required: "适用", eligibility_review_path: "由个别资格审查路径承接", needs_information: "需要学历路径信息", not_covered: "当前未覆盖" };
        const preparationLabels = { available: "已有", not_yet: "尚未准备", unknown: "未提供／不确定" };
        const official = document.createElement("p");
        official.className = "field-detail";
        official.textContent = `官方适用性：${officialLabels[item.official_status] || item.official_status}；个人准备状态：${preparationLabels[item.preparation_status] || item.preparation_status}`;
        card.append(official);
      }
      const progress = document.createElement("p");
      progress.className = "personal-progress";
      progress.textContent = item.action_group === "recorded" ? "我的处理进度：此项没有待勾选行动" : "我的处理进度：待处理";
      card.append(progress);
      if (item.action_group !== "recorded") {
        const label = document.createElement("label");
        label.className = "personal-check";
        const checkbox = document.createElement("input");
        checkbox.type = "checkbox";
        checkbox.addEventListener("change", () => {
          progress.textContent = checkbox.checked ? "我的处理进度：已标记处理（仅个人记录）" : "我的处理进度：待处理";
          card.dataset.handled = checkbox.checked ? "true" : "false";
        });
        const labelText = document.createElement("span");
        labelText.textContent = "我已处理（仅记录个人进度）";
        label.append(checkbox, labelText);
        card.append(label);
      }
      if (item.evidence.length) {
        const actions = document.createElement("div");
        actions.className = "actions";
        for (const evidence of item.evidence) {
          const button = document.createElement("button");
          button.type = "button";
          button.className = "secondary";
          button.textContent = "查看官方依据";
          button.addEventListener("click", () => openDemoEvidence(item, evidence, button));
          actions.append(button);
        }
        card.append(actions);
      }
      if (item.limitation) {
        const limit = document.createElement("details");
        limit.className = "comparison-limit";
        const summary = document.createElement("summary");
        summary.textContent = "判断边界";
        const text = document.createElement("p");
        text.textContent = item.limitation;
        limit.append(summary, text);
        card.append(limit);
      }
      list.append(card);
    }
    section.append(list);
    comparisonOutput.append(section);
  }
  const boundary = document.createElement("p");
  boundary.className = "final-notice";
  boundary.textContent = `${payload.comparison_statement} 限制：${payload.limitation_statement}`;
  comparisonOutput.append(boundary);
  filterEmpty.hidden = true;
  comparisonComplete = true;
  comparisonEverLoaded = true;
  updateApplicantStepSummary();
}

function applyReadinessFilter() {
  const selected = readinessFilters.querySelector('input[name="readiness-filter"]:checked').value;
  let visible = 0;
  for (const card of comparisonOutput.querySelectorAll(".comparison-card")) {
    card.hidden = selected !== "all" && card.dataset.actionGroup !== selected;
    if (!card.hidden) visible += 1;
  }
  for (const group of comparisonOutput.querySelectorAll(".comparison-group")) {
    group.hidden = !Array.from(group.querySelectorAll(".comparison-card")).some((card) => !card.hidden);
  }
  filterEmpty.hidden = visible !== 0;
}

async function submitApplicantComparison() {
  if (comparisonPending || !baseRequirementsLoaded || !demoTargetComplete()) return;
  const requestSnapshot = JSON.stringify(demoComparisonRequest());
  const requestId = ++comparisonRequestId;
  comparisonController = new AbortController();
  clearComparison("正在由服务端对照个人情况与审核规则。");
  comparisonPending = true;
  comparisonSubmit.disabled = true;
  comparisonRetry.hidden = true;
  setMessage(comparisonStatus, "loading", "正在由服务端对照个人情况与审核规则。");
  try {
    const response = await fetch(APPLICANT_COMPARISON_ENDPOINT, { method: "POST", headers: { Accept: "application/json", "Content-Type": "application/json" }, body: requestSnapshot, cache: "no-store", credentials: "same-origin", signal: comparisonController.signal });
    if (!response.ok) throw new Error();
    const payload = await response.json();
    if (!payload || !Array.isArray(payload.items)) throw new Error();
    if (requestId !== comparisonRequestId || requestSnapshot !== JSON.stringify(demoComparisonRequest())) return;
    renderComparison(payload);
    setMessage(comparisonStatus, "success", "个人情况已完成保守对照。");
    activateStep(4, true);
  } catch (error) {
    if (error && error.name === "AbortError") return;
    if (requestId !== comparisonRequestId) return;
    clearComparison("个人情况暂时无法对照，请检查输入后重试。");
    comparisonRetry.hidden = false;
    setMessage(comparisonStatus, "error", "个人情况暂时无法对照，请检查输入后重试。", true);
  } finally {
    if (requestId === comparisonRequestId) {
      comparisonPending = false;
      comparisonController = null;
      comparisonSubmit.disabled = !baseRequirementsLoaded;
    }
  }
}

function invalidateComparison(message) {
  cancelPendingComparison();
  clearComparison(message);
}

async function submitBaseRequirements() {
  if (requirementsPending || !demoTargetComplete()) return;
  activateStep(1);
  const requestPayload = demoTargetRequest();
  const requestSnapshot = JSON.stringify(requestPayload);
  const requestId = ++requirementsRequestId;
  requirementsController = new AbortController();
  baseRequirementsLoaded = false;
  clearGroundedAnswer("基础要求正在更新，请稍候。");
  updateGroundedContext();
  invalidateComparison("基础要求正在更新，请稍候。");
  clearDemoResults("正在从服务端加载基础要求。");
  requirementsPending = true;
  updateRequirementsSubmit();
  requirementsRetry.hidden = true;
  setMessage(targetStatus, "loading", "正在核对审核规则与官方依据。");
  try {
    const response = await fetch(BASE_REQUIREMENTS_ENDPOINT, { method: "POST", headers: { Accept: "application/json", "Content-Type": "application/json" }, body: requestSnapshot, cache: "no-store", credentials: "same-origin", signal: requirementsController.signal });
    if (!response.ok) throw new Error();
    const payload = await response.json();
    if (!payload || !Array.isArray(payload.requirements)) throw new Error();
    if (requestId !== requirementsRequestId || !demoTargetComplete() || requestSnapshot !== JSON.stringify(demoTargetRequest())) return;
    renderRequirements(payload);
    baseRequirementsLoaded = true;
    requirementsEverLoaded = true;
    comparisonSubmit.disabled = false;
    clearComparison();
    clearGroundedAnswer("可针对当前目标和本页个人情况提问。");
    updateGroundedContext();
    setMessage(targetStatus, "success", "基础要求已加载。请逐项查看官方依据。");
    activateStep(2, true);
  } catch (error) {
    if (error && error.name === "AbortError") return;
    if (requestId !== requirementsRequestId) return;
    clearDemoResults("基础要求暂时无法加载。");
    requirementsRetry.hidden = false;
    setMessage(targetStatus, "error", "无法加载基础要求，请检查选择后重试。", true);
  } finally {
    if (requestId === requirementsRequestId) {
      requirementsPending = false;
      requirementsController = null;
      updateRequirementsSubmit();
    }
  }
}

function cancelPendingRequirements() {
  requirementsRequestId += 1;
  if (requirementsController) requirementsController.abort();
  requirementsController = null;
  requirementsPending = false;
  updateRequirementsSubmit();
}

function handleDemoTargetChange(next) {
  cancelPendingRequirements();
  baseRequirementsLoaded = false;
  invalidateComparison("申请目标已改变，请重新加载基础要求。");
  clearDemoResults("申请目标已改变，请完成选择后重新加载要求。");
  resetApplicantInputs();
  clearGroundedAnswer("申请目标已改变，请重新加载基础要求后提问。");
  updateGroundedContext();
  requirementsRetry.hidden = true;
  setMessage(targetStatus, "initial", "申请目标已改变，请完成选择后重新加载要求。");
  activateStep(1);
  next();
}

queryInput.addEventListener("input", () => { queryCount.textContent = `${queryInput.value.length} / ${MAX_QUERY_LENGTH}`; });
reportQuery.addEventListener("input", () => { reportQueryCount.textContent = `${reportQuery.value.length} / ${MAX_QUERY_LENGTH}`; });
groundedQuestion.addEventListener("input", () => { groundedQuestionCount.textContent = `${groundedQuestion.value.length} / ${MAX_QUERY_LENGTH}`; });
documentSelect.addEventListener("change", () => { updateDocumentDetail(); clearReportResult(); setMessage(reportStatus, "initial", "募集要項が変わりました。条件を確認して明示的に再送信してください。"); });
form.addEventListener("submit", (event) => { event.preventDefault(); submitSearch(); });
reportForm.addEventListener("submit", (event) => { event.preventDefault(); submitReport(); });
retryButton.addEventListener("click", () => { if (lastAction === "catalog") loadCatalog(); else submitSearch(); });
reportRetry.addEventListener("click", () => { if (reportCanRetry) submitReport(); });
reportClear.addEventListener("click", clearReport);
evidenceTab.addEventListener("click", () => activateTab(evidenceTab));
reportTab.addEventListener("click", () => activateTab(reportTab));
evidenceTab.addEventListener("keydown", handleTabKey);
reportTab.addEventListener("keydown", handleTabKey);
targetForm.addEventListener("submit", (event) => { event.preventDefault(); submitBaseRequirements(); });
applicantForm.addEventListener("submit", (event) => { event.preventDefault(); submitApplicantComparison(); });
applicantForm.addEventListener("input", () => {
  updateProfileGroupStates();
  updateEnglishInputHint();
  invalidateComparison("个人输入已改变，请重新对照。");
  clearGroundedAnswer("个人情况已改变；下次提交将使用最新的本页输入。");
  updateGroundedContext();
  if (baseRequirementsLoaded) activateStep(3);
});
applicantForm.addEventListener("change", () => {
  updateProfileGroupStates();
  updateEnglishInputHint();
});
comparisonRetry.addEventListener("click", submitApplicantComparison);
readinessFilters.addEventListener("change", applyReadinessFilter);
requirementsContinue.addEventListener("click", () => {
  if (baseRequirementsLoaded) activateStep(3, true);
});
editTarget.addEventListener("click", () => { resetChecklistProgress(); activateStep(1, true); });
editRequirements.addEventListener("click", () => activateStep(2, true));
editApplicant.addEventListener("click", () => { resetChecklistProgress(); activateStep(3, true); });
schoolSelect.addEventListener("change", () => handleDemoTargetChange(populateDegreeSelect));
demoDegreeSelect.addEventListener("change", () => handleDemoTargetChange(populateIntakeSelect));
intakeSelect.addEventListener("change", () => handleDemoTargetChange(populateCollegeSelect));
collegeSelect.addEventListener("change", () => handleDemoTargetChange(populateDepartmentSelect));
departmentSelect.addEventListener("change", () => handleDemoTargetChange(populateRouteSelect));
routeSelect.addEventListener("change", () => handleDemoTargetChange(updateRequirementsSubmit));
requirementsRetry.addEventListener("click", () => { if (demoCatalog.length) submitBaseRequirements(); else loadDemoCatalog(); });
groundedForm.addEventListener("submit", (event) => { event.preventDefault(); submitGroundedAnswer(); });
groundedRetry.addEventListener("click", () => { if (groundedCanRetry) submitGroundedAnswer(); });
drawerClose.addEventListener("click", () => evidenceDrawer.close());
evidenceDrawer.addEventListener("close", () => { if (drawerTrigger) drawerTrigger.focus(); drawerTrigger = null; });

updateFlowPresentation();
initializeProfileGroups();
clearGroundedAnswer();
updateGroundedContext();
loadCatalog();
loadDemoCatalog();
