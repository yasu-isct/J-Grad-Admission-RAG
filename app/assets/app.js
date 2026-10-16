"use strict";

const TARGET_CATALOG_ENDPOINT = "/v1/reference-targets";
const BASE_REQUIREMENTS_ENDPOINT = "/v1/base-requirements";
const APPLICANT_COMPARISON_ENDPOINT = "/v1/applicant-comparison";
const GROUNDED_ANSWER_ENDPOINT = "/v1/natural-language-answers";
const GENERATION_STATUS_ENDPOINT = "/v1/generation-status";
const MAX_QUERY_LENGTH = 1000;
const byId = (id) => document.getElementById(id);
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
const materialInputs = Array.from(applicantForm.querySelectorAll("[data-material-code]"));
const materialInputOriginalNames = new Map(materialInputs.map((select) =>
  [select, select.parentElement.firstChild.textContent.trim()]));
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
const changeSchool = byId("change-school");
const currentTargetBar = byId("current-target-bar");
const currentTargetName = byId("current-target-name");
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
const generationModeLabel = byId("generation-mode-label");
const flowSteps = [1, 2, 3, 4].map((number) => ({
  number,
  panel: byId(number === 3 ? "applicant-panel" : number === 4 ? "readiness-panel" : `step-${number}-panel`),
  heading: byId(number === 1 ? "demo-heading" : number === 2 ? "requirements-heading" : number === 3 ? "applicant-heading" : "readiness-heading"),
  content: number < 4 ? byId(`step-${number}-content`) : null,
  summary: number < 4 ? byId(`step-${number}-summary`) : null,
  badge: byId(`step-${number}-badge`),
  nav: byId(`step-nav-${number}`)
}));

let demoCatalog = [];
let requirementsPending = false;
let requirementsController = null;
let requirementsRequestId = 0;
let drawerTrigger = null;
let drawerScopeKey = null;
let drawerGraph = null;

function discardEvidenceDrawer() {
  drawerTrigger = null;
  drawerGraph = null;
  drawerScopeKey = null;
  if (evidenceDrawer.open) evidenceDrawer.close();
}
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
let generationStatus = null;
let referenceCore = null;
let referenceEntries = [];
let loadedReference = null;
let referenceReport = null;
let referenceReader = null;
let referenceReportController = null;
let referenceReportRequestId = 0;
let baseResponse = null;
let comparisonResponse = null;
let referenceTrigger = null;
const referenceButtons = Array.from(document.querySelectorAll(".reference-generate"));
const referenceDialog = byId("reference-report");
const referenceBody = byId("reference-report-body");
const referenceActionStatuses = [byId("reference-inline-status"), byId("reference-step4-status")];

function setReferenceActionState(state, message, enabled = baseRequirementsLoaded) {
  for (const status of referenceActionStatuses) setMessage(status, state, message);
  for (const button of referenceButtons) {
    button.disabled = !enabled;
    button.textContent = state === "loading" ? "作成中…"
      : state === "error" && enabled ? "レポートの作成を再試行" : "準備レポートを作成";
  }
}

function clearReferenceReport(message = "志望先または本人情報が変更されました。必要に応じて再作成してください。") {
  referenceReportRequestId += 1;
  if (referenceReportController) referenceReportController.abort();
  referenceReportController = null;
  referenceReport = null;
  referenceReader = null;
  referenceBody.replaceChildren();
  byId("reference-copy").disabled = true;
  byId("reference-copy-fallback").value = "";
  byId("reference-copy-fallback").hidden = true;
  byId("reference-copy-fallback-label").hidden = true;
  byId("reference-report-status").textContent = "";
  setReferenceActionState("initial", message);
  if (referenceDialog.open) referenceDialog.close();
}

function cancelPendingReferenceComparison() {
  if (!referenceReportController || referenceReport?.kind !== "legacy_applicant") return;
  const controller = referenceReportController;
  referenceReportRequestId += 1;
  referenceReportController = null;
  controller.abort();
}

function updateProfileCapability() {
  const slice = currentReferenceEntry()?.kind === "reviewed_material_slice";
  byId("legacy-profile-grid").hidden = slice;
  byId("slice-profile").hidden = !slice;
  byId("slice-material-preparation").replaceChildren();
  byId("slice-material-preparation").hidden = true;
  comparisonSubmit.textContent = slice ? "対象書類の条件を確認" : "本人の状況と照合";
  byId("readiness-filters").hidden = slice;
  byId("grounded-answer-panel").hidden = slice;
  clearGroundedAnswer(slice ? "この資料の質問機能は未対応です。" : "基本要件を読み込むと質問できます。");
  updateGroundedContext();
}

const stepStateLabels = {
  locked: "未実施",
  current: "現在",
  complete: "完了",
  stale: "再確認が必要"
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
  const showTarget = activeStep >= 2 && baseRequirementsLoaded && loadedReference;
  currentTargetBar.hidden = !showTarget;
  currentTargetBar.dataset.compact = activeStep === 4 ? "true" : "false";
  if (showTarget) currentTargetName.textContent = [loadedReference.scope.school,
    loadedReference.scope.program].filter(Boolean).join(" · ");
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

function heading(level, text) {
  const element = document.createElement(`h${level}`);
  element.textContent = text;
  return element;
}

function clearGroundedAnswer(message = "基本要件を読み込むと質問できます。") {
  groundedRequestId += 1;
  if (groundedController) groundedController.abort();
  groundedController = null;
  groundedCanRetry = false;
  groundedRetry.hidden = true;
  groundedOutput.replaceChildren();
  groundedOutput.hidden = true;
  const configured = Boolean(generationStatus && generationStatus.configured);
  const supported = currentReferenceEntry()?.kind !== "reviewed_material_slice";
  groundedQuestion.disabled = !baseRequirementsLoaded || !configured || !supported;
  groundedSubmit.disabled = !baseRequirementsLoaded || !configured || !supported;
  setMessage(groundedStatus, "initial", !supported ? "この資料の検索・質問機能は未対応です。"
    : generationStatus && !configured
      ? `${generationAvailabilityLabel(generationStatus)}。確認済みの基本要件は引き続き参照できます。` : message);
}

function generationAvailabilityLabel(status) {
  if (!status?.configured) return status?.mode === "offline_rules"
    ? "オフライン資料を利用できません" : "オンライン回答を利用できません";
  if (status.mode === "online_model") return "オンライン回答が利用できます";
  if (status.mode === "offline_rules") return "オフライン資料のみ";
  return "質問機能が利用できます";
}

function updateGroundedContext() {
  if (currentReferenceEntry()?.kind === "reviewed_material_slice") {
    groundedContext.textContent = "この資料の検索・質問機能は未対応です。確認済みの項目と公式原文をご覧ください。";
    return;
  }
  if (!baseRequirementsLoaded || !demoTargetComplete()) {
    groundedContext.textContent = "志望先を選択し、出願の基本要件を読み込んでください。";
    return;
  }
  const target = currentDepartment();
  const intake = currentIntake();
  groundedContext.textContent = `選択中：${currentSchool().school_name} · ${target ? target.department_name : departmentSelect.value} · ${intake.intake_name}。本人情報は上のフォームを使用します。`;
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
  if (code === "online_generation_not_configured") return "オンライン回答は現在利用できません。確認済みの要件と公式資料は引き続き閲覧できます。";
  if (code === "generation_provider_timeout" || status === 504) return "回答処理がタイムアウトしました。選択内容と質問を保持しています。再試行してください。";
  if (["generation_provider_unavailable", "grounded_service_unavailable", "provider_unavailable"].includes(code) || status === 503) return "回答・検索サービスを利用できません。しばらくしてから再試行してください。";
  if (code === "insufficient_evidence") return "回答に必要な根拠が不足しています。質問の範囲を絞るか、表現を変えてください。";
  if (["invalid_citation", "evidence_mismatch", "rule_state_mismatch", "unsupported_claim", "malformed_output", "incomplete_response"].includes(code)) return "回答の根拠・引用を確認できなかったため、表示していません。再試行するか、基本要件をご覧ください。";
  if (code === "unsupported_question" || status === 422) return "対象資料にない内容、または出願事項を特定できない質問です。表現を変えてください。";
  return "根拠に基づく回答を生成できませんでした。再試行してください。";
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

function appendAnswerInline(container, value) {
  for (const part of String(value).split(/(\*\*[^*]+\*\*)/g)) {
    if (part.startsWith("**") && part.endsWith("**")) {
      const strong = document.createElement("strong");
      strong.textContent = part.slice(2, -2);
      container.append(strong);
    } else container.append(document.createTextNode(part));
  }
}

function appendReadableAnswer(container, value) {
  const lines = String(value || "").replace(/\r\n?/g, "\n").split("\n");
  let paragraph = [];
  let list = null;
  const flush = () => {
    if (!paragraph.length) return;
    const text = document.createElement("p");
    appendAnswerInline(text, paragraph.join(" "));
    container.append(text);
    paragraph = [];
  };
  for (const line of lines) {
    const value = line.trim();
    if (!value) { flush(); list = null; continue; }
    const bullet = value.match(/^(?:[-*•]|\d+[.)])\s+(.+)$/);
    if (bullet) {
      flush();
      const ordered = /^\d/.test(value);
      if (!list || list.tagName !== (ordered ? "OL" : "UL")) {
        list = document.createElement(ordered ? "ol" : "ul");
        container.append(list);
      }
      const item = document.createElement("li");
      appendAnswerInline(item, bullet[1]);
      list.append(item);
      continue;
    }
    const headingMatch = value.match(/^#{1,4}\s+(.+)$/);
    if (headingMatch) {
      flush(); list = null;
      const title = document.createElement("h4");
      appendAnswerInline(title, headingMatch[1]);
      container.append(title);
      continue;
    }
    list = null;
    paragraph.push(value);
  }
  flush();
}

function appendGroundedResult(container, payload, offline) {
  const answer = payload.answer;
  const referenceOnly = answer.kind === "reference_answer";
  const response = document.createElement("section");
  response.className = "grounded-response";
  response.append(heading(3, offline ? "オフラインの参考資料"
    : referenceOnly ? "参考回答" : "回答のまとめ"));
  const responseText = document.createElement("div");
  responseText.className = "grounded-response-text";
  appendReadableAnswer(responseText, answer.answer);
  response.append(responseText);
  container.append(response);
  if (!referenceOnly && (!Array.isArray(answer.claims) || !answer.claims.length)) {
    const empty = document.createElement("p");
    empty.className = "grounded-boundary";
    empty.textContent = "検索は完了しましたが、根拠を確認できる結論はありませんでした。";
    container.append(empty);
  }
  appendGroundedList(container, "追加確認が必要", answer.missing_information);
  appendGroundedList(container, "回答の対象範囲", (answer.limitations || []).filter((item) =>
    !String(item).includes("確認が必要な参考回答")));
}

function renderGroundedAnswer(payload) {
  groundedOutput.replaceChildren();
  const offline = ["offline", "fallback"].includes(payload.delivery?.source)
    || payload.mode?.mode === "offline_rules";
  const meta = document.createElement("p");
  meta.className = "grounded-answer-meta";
  const deliveryLabels = {cache_hit: "前回の結果を表示", live: "オンライン回答",
    fallback: "オンラインサービス停止中 · オフライン参考資料", offline: "オフライン参考資料"};
  for (const text of [deliveryLabels[payload.delivery?.source] || "今回の参考内容"]) {
    const badge = document.createElement("span");
    badge.textContent = text;
    meta.append(badge);
  }
  groundedOutput.append(meta);
  if (payload.result) appendGroundedResult(groundedOutput, payload.result, offline);
  if (!payload.result && payload.summary) appendGroundedList(groundedOutput, "今回の結果", [payload.summary]);
  if (!payload.result) appendGroundedList(groundedOutput, "回答に関する注意", ["引用を確認できる回答がありません。公式資料をご確認ください。"]);
  const missing = [...new Set((payload.missing_context || []).filter((value) =>
    !(payload.result?.answer?.missing_information || []).includes(value)))];
  appendGroundedList(groundedOutput, "追加で必要な情報", missing);
  appendGroundedList(groundedOutput, "現在の対象範囲外", payload.unsupported_parts);
  appendGroundedList(groundedOutput, "未回答の内容", (payload.subanswers || [])
    .filter((part) => part.status !== "answered").map((part) => part.message));
  groundedOutput.hidden = false;
}

async function loadGenerationStatus() {
  try {
    const response = await fetch(GENERATION_STATUS_ENDPOINT, { headers: { Accept: "application/json" }, cache: "no-store", credentials: "same-origin" });
    const body = await response.json();
    if (!response.ok || typeof body.configured !== "boolean" || !Number.isInteger(body.request_timeout_seconds) || body.request_timeout_seconds < 1 || body.request_timeout_seconds > 3600) throw new Error("invalid generation status");
    generationStatus = body;
  } catch (_) {
    generationStatus = { configured: false, label: "回答モードを確認できません" };
  }
  generationModeLabel.textContent = generationAvailabilityLabel(generationStatus);
  clearGroundedAnswer(baseRequirementsLoaded ? "選択した志望先と本人情報について質問できます。" : "基本要件を読み込むと質問できます。");
}

async function submitGroundedAnswer() {
  const question = groundedQuestion.value.trim();
  if (!baseRequirementsLoaded || !demoTargetComplete() || !question || question.length > MAX_QUERY_LENGTH) {
    setMessage(groundedStatus, "error", "基本要件を読み込み、1〜1000文字で質問してください。", true);
    return;
  }
  if (groundedController) groundedController.abort();
  const payload = groundedRequestPayload();
  const snapshot = JSON.stringify(payload);
  const requestId = ++groundedRequestId;
  groundedController = new AbortController();
  const timeout = globalThis.setTimeout(() => groundedController && groundedController.abort("timeout"), generationStatus.request_timeout_seconds * 1000);
  groundedSubmit.disabled = true;
  groundedRetry.hidden = true;
  groundedOutput.hidden = true;
  groundedCanRetry = false;
  setMessage(groundedStatus, "loading", "質問を確認しています。必要に応じて募集要項を検索します。");
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
    if (!body.mode || !body.analysis || !Array.isArray(body.subanswers)) throw new Error("invalid response");
    renderGroundedAnswer(body);
    const offline = ["offline", "fallback"].includes(body.delivery?.source)
      || body.mode?.mode === "offline_rules";
    setMessage(groundedStatus, body.result ? "success" : "initial", body.result
      ? offline ? "オフライン参考資料を表示しました。今回はオンライン回答を取得できていません。" : "回答を表示しました。"
      : "表示できる回答がありません。下の説明をご確認ください。", true);
  } catch (error) {
    if (requestId !== groundedRequestId) return;
    const timedOut = groundedController && groundedController.signal.reason === "timeout";
    groundedCanRetry = true;
    groundedRetry.hidden = false;
    groundedOutput.replaceChildren();
    groundedOutput.hidden = true;
    setMessage(groundedStatus, "error", timedOut ? "回答処理がタイムアウトしました。選択内容と質問を保持しています。再試行してください。" : groundedFailureMessage(error && error.code, error && error.status), true);
  } finally {
    globalThis.clearTimeout(timeout);
    if (requestId === groundedRequestId) {
      groundedController = null;
      groundedSubmit.disabled = !baseRequirementsLoaded || !generationStatus || !generationStatus.configured;
    }
  }
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

function clearDemoResults(message = "志望先を選択して、出願要件を読み込んでください。") {
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
  if (target?.kind) return referenceCore.scopeLabel(target);
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
    ["dates", "重要な日程"],
    ["materials", "主な提出書類"],
    ["eligibility", "学歴・出願資格"],
    ["language", "語学の要件"]
  ];
  const counts = labels.map(([category, label]) => {
    const count = payload.requirements.filter((item) => item.category === category).length;
    return `${label} ${count}項目`;
  });
  const hasDates = payload.requirements.some((item) => item.category === "dates");
  byId("step-2-summary-text").textContent = `${counts.join(" · ")}${hasDates ? " · 日程はステップ2へ" : ""}`;
}

function updateApplicantStepSummary() {
  if (currentReferenceEntry()?.kind === "reviewed_material_slice") {
    const current = byId("slice-current-employed").selectedOptions[0].textContent;
    const retain = byId("slice-retain-employed").selectedOptions[0].textContent;
    const preparations = Array.from(byId("slice-material-preparation").querySelectorAll("select"),
      (control) => `${control.dataset.materialName}：${control.selectedOptions[0].textContent}`);
    byId("step-3-summary-text").textContent = [`現在在職：${current}／入学後も在職：${retain}`,
      ...preparations].join("；");
    return;
  }
  const categories = [
    ["学歴", profileGroupHasProvidedValue("education")],
    ["オンライン手続き・郵送", profileGroupHasProvidedValue("submission")],
    ["英語", profileGroupHasProvidedValue("english")],
    ["日本語", profileGroupHasProvidedValue("japanese")],
    ["書類", profileGroupHasProvidedValue("materials")]
  ];
  const provided = categories.filter(([, value]) => value).map(([label]) => label);
  const missing = categories.filter(([, value]) => !value).map(([label]) => label);
  const parts = [
    `入力済み：${provided.length ? provided.join("、") : "なし"}`,
    `未入力：${missing.length ? missing.join("、") : "なし"}`
  ];
  byId("step-3-summary-text").textContent = parts.join("；");
}

function updateRequirementsSubmit() {
  const department = currentDepartment();
  const missing = [
    [currentSchool(), "学校"],
    [currentDegree(), "学位"],
    [currentIntake(), "入学時期"],
    [currentCollege(), "学院・研究科"],
    [department, "系・専攻"],
    [department && (department.application_routes.length === 0 || routeSelect.value), "入試日程・選抜区分"]
  ].filter(([complete]) => !complete).map(([, label]) => label);
  requirementsSubmit.disabled = requirementsPending || missing.length > 0;
  targetCompletionHint.dataset.state = missing.length ? "incomplete" : "ready";
  targetCompletionHint.textContent = requirementsPending
    ? "募集要項を読み込んでいます。"
    : missing.length
      ? `次の項目を選択してください：${missing.join("、")}。`
      : "志望先を選択しました。出願の基本要件を確認できます。";
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
    const labels = { complete: "入力済み", partial: "一部入力済み", unknown: "追加確認が必要", empty: "入力待ち" };
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
    hint.textContent = "スコア・受験日を入力した場合は試験の種類も必要です。照合する前に種類を選ぶか、スコアと日付を空欄にしてください。";
  } else if (kind === "ui_not_applicable" && report === "true") {
    hint.dataset.state = "attention";
    hint.textContent = "「未受験」と「公式スコア証明取得済み」が選択されています。入力内容をご確認ください。スコアの有効性を判定するものではありません。";
  } else if (concreteKind) {
    hint.dataset.state = "info";
    hint.textContent = "試験の種類を記録しました。スコア・受験日・証明書は空欄にできます。入力だけで有効性や大学の受理を認定することはありません。";
  } else {
    hint.dataset.state = "info";
    hint.textContent = "スコア・受験日は空欄にできます。入力する場合は試験の種類も選択してください。";
  }
}

const englishProofControls = ["demo-english-online-pdf", "demo-toeic-qr",
  "demo-toeic-certificate", "demo-toefl-report-pdf", "demo-toefl-g179"];

function updateEnglishProofVisibility() {
  const kind = byId("demo-english-kind").value;
  const toeic = kind === "toeic_lr";
  const toefl = kind === "toefl_ibt" || kind === "toefl_ibt_home_edition";
  byId("demo-english-proof-fields").hidden = !(toeic || toefl);
  byId("demo-toeic-proof-fields").hidden = !toeic;
  byId("demo-toefl-proof-fields").hidden = !toefl;
}

function updateApplicationPreparationVisibility() {
  const state = byId("demo-completion-state").value;
  byId("demo-completion-date-field").hidden = state !== "completed";
  byId("demo-expected-completion-date-field").hidden = state !== "expected";
  const basis = byId("demo-credential-basis").value;
  byId("demo-review-status-field").hidden = !["foreign_15_year_education",
    "university_three_year_enrollment"].includes(basis);
}

function applicationPreparationInput() {
  return {
    completion_date: nullableDemoValue("demo-completion-date"),
    expected_completion_date: nullableDemoValue("demo-expected-completion-date"),
    individual_review_status: nullableDemoValue("demo-review-status"),
    materials_dispatched_date: nullableDemoValue("demo-dispatched-date"),
    materials_arrival_date: nullableDemoValue("demo-arrival-date"),
    online_steps_completed: nullableDemoBoolean("demo-online-steps")
  };
}

function applicationDatesReconcile() {
  const dispatched = byId("demo-dispatched-date").value;
  const arrival = byId("demo-arrival-date").value;
  const hint = byId("demo-submission-hint");
  if (dispatched && arrival && arrival < dispatched) {
    hint.dataset.state = "attention";
    hint.textContent = "到着日が発送日より前になっています。日付をご確認ください。";
    return false;
  }
  hint.dataset.state = "info";
  hint.textContent = "到着日が不明な場合は空欄にしてください。発送日を到着日として扱いません。";
  return true;
}

function englishPreparationInput() {
  return {
    downloaded_online_pdf: nullableDemoBoolean("demo-english-online-pdf"),
    toeic_verification_qr_present: nullableDemoBoolean("demo-toeic-qr"),
    toeic_digital_official_score_certificate: nullableDemoBoolean("demo-toeic-certificate"),
    toefl_test_taker_score_report_pdf: nullableDemoBoolean("demo-toefl-report-pdf"),
    toefl_di_code_g179_set: nullableDemoBoolean("demo-toefl-g179")
  };
}

function initializeProfileGroups() {
  const desktop = window.matchMedia("(min-width: 761px)").matches;
  for (const group of applicantForm.querySelectorAll(".profile-group")) {
    group.open = desktop || group.dataset.profileGroup === "education";
  }
  updateProfileGroupStates();
  updateEnglishInputHint();
  updateEnglishProofVisibility();
  updateApplicationPreparationVisibility();
}

function resetApplicantInputs() {
  applicantForm.reset();
  updateProfileGroupStates();
  updateEnglishInputHint();
  updateEnglishProofVisibility();
  updateApplicationPreparationVisibility();
  applicationDatesReconcile();
}

function populateDegreeSelect() {
  resetDemoSelect(demoDegreeSelect, "学位を選択してください");
  resetDemoSelect(intakeSelect, "学位を選択してください");
  resetDemoSelect(collegeSelect, "入学時期を選択してください");
  resetDemoSelect(departmentSelect, "学院・研究科を選択してください");
  resetDemoSelect(routeSelect, "日程・選抜区分を選択してください");
  routeField.hidden = true;
  const school = currentSchool();
  if (!school) { updateRequirementsSubmit(); return; }
  demoDegreeSelect.replaceChildren(option("", "学位を選択してください"));
  for (const degree of school.degrees) demoDegreeSelect.append(option(degree.degree_id, degree.degree_name));
  demoDegreeSelect.disabled = false;
  if (school.degrees.length === 1) demoDegreeSelect.value = school.degrees[0].degree_id;
  populateIntakeSelect();
}

function populateIntakeSelect() {
  resetDemoSelect(intakeSelect, "入学時期を選択してください");
  resetDemoSelect(collegeSelect, "入学時期を選択してください");
  resetDemoSelect(departmentSelect, "学院・研究科を選択してください");
  resetDemoSelect(routeSelect, "日程・選抜区分を選択してください");
  routeField.hidden = true;
  const degree = currentDegree();
  if (!degree) { updateRequirementsSubmit(); return; }
  intakeSelect.replaceChildren(option("", "入学時期を選択してください"));
  for (const intake of degree.intakes) intakeSelect.append(option(`${intake.document_id}:${intake.year}:${intake.month}`, intake.intake_name));
  intakeSelect.disabled = false;
  updateRequirementsSubmit();
}

function populateCollegeSelect() {
  resetDemoSelect(collegeSelect, "学院・研究科を選択してください");
  resetDemoSelect(departmentSelect, "学院・研究科を選択してください");
  resetDemoSelect(routeSelect, "日程・選抜区分を選択してください");
  routeField.hidden = true;
  const intake = currentIntake();
  if (!intake) { updateRequirementsSubmit(); return; }
  collegeSelect.replaceChildren(option("", "学院・研究科を選択してください"));
  for (const college of intake.colleges) collegeSelect.append(option(college.college_id, college.college_name));
  collegeSelect.disabled = false;
  updateRequirementsSubmit();
}

function populateDepartmentSelect() {
  resetDemoSelect(departmentSelect, "系・専攻を選択してください");
  resetDemoSelect(routeSelect, "日程・選抜区分を選択してください");
  routeField.hidden = true;
  const college = currentCollege();
  if (!college) { updateRequirementsSubmit(); return; }
  departmentSelect.replaceChildren(option("", "系・専攻を選択してください"));
  for (const department of college.departments) departmentSelect.append(option(department.department_id, department.department_name));
  departmentSelect.disabled = false;
  updateRequirementsSubmit();
}

function populateRouteSelect() {
  resetDemoSelect(routeSelect, "日程・選抜区分を選択してください");
  const department = currentDepartment();
  if (!department || department.application_routes.length === 0) {
    routeField.hidden = true;
    updateRequirementsSubmit();
    return;
  }
  routeSelect.replaceChildren(option("", "日程・選抜区分を選択してください"));
  for (const route of department.application_routes) routeSelect.append(option(route.route_id, route.route_name));
  routeSelect.disabled = false;
  routeField.hidden = false;
  updateRequirementsSubmit();
}

function populateDemoCatalog(schools) {
  demoCatalog = schools;
  schoolSelect.replaceChildren(option("", "学校を選択してください"));
  for (const school of schools) schoolSelect.append(option(school.school_id, school.school_name));
  schoolSelect.disabled = schools.length === 0;
  if (schools.length === 1) schoolSelect.value = schools[0].school_id;
  populateDegreeSelect();
  requirementsRetry.hidden = true;
  setMessage(targetStatus, schools.length ? "success" : "empty", schools.length ? "対象一覧を読み込みました。志望先を選択してください。" : "現在、利用できる対象がありません。", schools.length === 0);
}

function catalogForReferenceEntry(item) {
  if (item.kind === "legacy_applicant") return item.legacy_catalog;
  const scope = referenceCore.scopesFor(item)[0];
  const target = item.target;
  // Selection-only projection. The request retains the slice target and never
  // sends this UI shape or a fabricated legacy document ID to an API.
  return {
    school_id: item.entry_id, school_name: scope.school,
    degrees: [{
      degree_id: target.degree_level, degree_name: scope.degree,
      intakes: [{
        document_id: null, year: target.intake.year, month: target.intake.month,
        intake_name: `${scope.intake} · ${scope.edition}`,
        colleges: [{
          college_id: target.organization_id || scope.organization, college_name: scope.organization,
          departments: [{
            department_id: target.program_id || scope.program, department_name: scope.program,
            application_routes: [{route_id: target.examination_schedule_id || scope.route, route_name: scope.route}]
          }]
        }]
      }]
    }]
  };
}

function currentReferenceEntry() {
  return referenceEntries.find((item) => (item.kind === "legacy_applicant"
    ? item.legacy_catalog.school_id : item.entry_id) === schoolSelect.value) || null;
}

function currentReferenceScope() {
  if (!demoTargetComplete() || !referenceCore) return null;
  const entry = currentReferenceEntry();
  if (!entry) return null;
  const scopes = referenceCore.scopesFor(entry);
  if (entry.kind === "reviewed_material_slice") return scopes[0];
  const request = demoTargetRequest();
  return scopes.find((scope) => JSON.stringify(scope.request) === JSON.stringify(request)) || null;
}

function refreshMaterialInputLabels(scope) {
  for (const select of materialInputs) {
    const display = referenceCore.materialDisplay(scope, select.dataset.materialCode,
      materialInputOriginalNames.get(select));
    const label = display.verified
      ? `${display.name} · ${display.official}` : `${display.name} · ${display.description}`;
    select.parentElement.replaceChildren(document.createTextNode(`${label} `), select);
  }
}

async function loadDemoCatalog() {
  discardEvidenceDrawer();
  cancelPendingRequirements();
  baseRequirementsLoaded = false;
  loadedReference = null;
  baseResponse = null;
  comparisonResponse = null;
  clearReferenceReport();
  invalidateComparison("先に出願の基本要件を読み込んでください。");
  activateStep(1);
  demoCatalog = [];
  requirementsRetry.hidden = true;
  clearDemoResults();
  resetDemoSelect(schoolSelect, "対象一覧を読み込み中");
  resetDemoSelect(demoDegreeSelect, "学校を選択してください");
  resetDemoSelect(intakeSelect, "学位を選択してください");
  resetDemoSelect(collegeSelect, "入学時期を選択してください");
  resetDemoSelect(departmentSelect, "学院・研究科を選択してください");
  setMessage(targetStatus, "loading", "公開デモの対象一覧を読み込んでいます。");
  try {
    const response = await fetch(TARGET_CATALOG_ENDPOINT, { method: "GET", headers: { Accept: "application/json" }, cache: "no-store", credentials: "same-origin" });
    if (!response.ok) throw new Error();
    const payload = await response.json();
    referenceEntries = referenceCore.readyEntries(payload);
    populateDemoCatalog(referenceEntries.map(catalogForReferenceEntry));
    updateProfileCapability();
  } catch (_error) {
    requirementsRetry.hidden = false;
    setMessage(targetStatus, "error", "対象一覧を読み込めませんでした。再試行してください。", true);
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
    required: "要件：必須",
    conditional: "要件：条件付きで対象",
    needs_information: "要件：追加情報が必要",
    needs_review: "要件：確認が必要",
    not_applicable: "要件：対象外",
    not_covered: "要件：現在の対象範囲外",
    submission_required: "条件に該当：準備が必要",
    submission_not_required: "条件に該当：この書類自体の提出は不要",
    rule_not_applicable: "この条件の対象外です。提出全般が免除される意味ではありません。"
  };
  return labels[status] || `公式要件：${status}`;
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
  button.textContent = currentReferenceEntry()?.kind === "reviewed_material_slice"
    ? "本人情報から対象書類を確認" : "本人情報から準備が必要なものを確認";
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
    opens: "受付開始",
    period: "出願期間",
    must_arrive: "必着期限",
    recommended_arrival: "推奨到着日"
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
  appendEvidenceChoices(card, event);
  return card;
}

function appendEvidenceChoices(card, requirement) {
  const evidenceRows = Array.isArray(requirement.evidence) ? requirement.evidence : [];
  if (!evidenceRows.length) return;
  const choices = document.createElement("details");
  choices.className = "evidence-choice-list";
  const summary = document.createElement("summary");
  summary.textContent = `根拠を見る（${evidenceRows.length}件）`;
  choices.append(summary);
  const actions = document.createElement("div");
  actions.className = "actions requirement-evidence-actions";
  evidenceRows.forEach((evidence, index) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "secondary";
    const quote = evidence.highlights?.[0]?.exact_text || evidence.official_text || "原文を見る";
    const excerpt = String(quote).replace(/\s+/g, " ").slice(0, 42);
    button.textContent = `${index + 1}件目 · ${evidence.official_title || "公式資料"} · PDF ${ (evidence.pages || []).join("、")}ページ · ${excerpt}`;
    button.addEventListener("click", () => openDemoEvidence(requirement, evidence, button));
    actions.append(button);
  });
  choices.append(actions);
  card.append(choices);
}

function appendRequirementEvidence(card, requirement) {
  if (requirement.graphTopic) {
    const actions = document.createElement("div");
    actions.className = "actions requirement-evidence-actions";
    const button = document.createElement("button");
    button.type = "button";
    button.className = "secondary";
    button.textContent = `根拠を見る（${requirement.graphTopic.sources.length}件）`;
    button.addEventListener("click", () => openEvidenceGraph(requirement, button));
    actions.append(button);
    card.append(actions);
    return;
  }
  appendEvidenceChoices(card, requirement);
}

function appendPreparationGuide(card, guide, officialName = null) {
  if (!guide) return;
  const collapse = card.classList.contains("requirement-card");
  const container = collapse ? document.createElement("details") : card;
  if (collapse) {
    container.className = "preparation-guide-details";
    const summary = document.createElement("summary");
    summary.textContent = "準備のしかた";
    container.append(summary);
  }
  if (officialName) container.append(officialName);
  const steps = document.createElement("ol");
  steps.className = "preparation-steps";
  for (const line of guide.steps) {
    const item = document.createElement("li");
    item.textContent = line;
    steps.append(item);
  }
  container.append(steps);
  for (const line of guide.warnings) {
    const note = document.createElement("p");
    note.className = "preparation-warning";
    note.textContent = `注意事項：${line}`;
    container.append(note);
  }
  if (guide.conditions.length) {
    const details = document.createElement("details");
    details.className = "preparation-conditions";
    const summary = document.createElement("summary");
    summary.textContent = "例外・特別な場合を確認";
    details.append(summary);
    for (const condition of guide.conditions) {
      const note = document.createElement("p");
      note.textContent = `${condition.title}：${condition.text}`;
      details.append(note);
    }
    container.append(details);
  }
  if (collapse) card.append(container);
}

function renderRequirementCard(requirement, options = {}) {
  const card = document.createElement("article");
  card.className = `requirement-card${options.compact ? " requirement-card-compact" : ""}`;
  card.dataset.category = requirement.category;
  const material = requirement.category === "materials"
    ? referenceCore.materialDisplay(options.scope,
      requirement.material_code || requirement.requirement_id, requirement.title) : null;
  const guide = material ? referenceCore.materialGuide(options.scope, {
    id: requirement.material_code || requirement.requirement_id,
    sources: requirement.graphTopic?.sources || requirement.evidence
  }) : null;
  const pendingSliceGuide = guide && requirement.graphTopic && !requirement.conditionResultLoaded;
  card.append(heading(4, material ? material.name : requirement.title));
  const official = material?.official ? document.createElement("p") : null;
  if (official) {
    official.className = "material-official-name";
    official.textContent = material.official;
    if (!guide) card.append(official);
  }
  const status = document.createElement("span");
  status.className = "requirement-status";
  status.dataset.status = requirement.official_status;
  status.textContent = pendingSliceGuide ? "書類の適用条件は未確認" : material
    ? ({required: "提出が必要", needs_information: "適用条件を確認してください",
      submission_not_required: "この書類の提出は不要", rule_not_applicable: "この条件の対象外",
      submission_required: "現在の条件では提出が必要", not_covered: "対象資料の範囲外"})[requirement.official_status]
      || "適用条件を確認してください"
    : requirementStatusLabel(requirement.official_status);
  const description = document.createElement("p");
  description.className = "requirement-description";
  description.textContent = material ? guide?.purpose || material.description
    : String(requirement.requirement_id?.includes("english-submission-computer-science")
      ? requirement.reviewed_summary || requirement.description : requirement.description || "")
      .replace(/\bRULE-\d+[A-Z]?\b\s*/g, "").trim();
  card.append(status, description);
  if (guide && !pendingSliceGuide
    && !["required", "submission_required"].includes(requirement.official_status)) {
    const conditional = document.createElement("p");
    conditional.className = "preparation-warning";
    conditional.textContent = "適用条件の確認が必要です。以下は提出が必要な場合の準備方法です。";
    card.append(conditional);
  }
  if (guide) appendPreparationGuide(card, guide, official);
  if (requirement.requirement_id === "language:preparation-guide") {
    description.remove();
    const list = document.createElement("ul");
    list.className = "english-guide-list";
    for (const line of String(requirement.reviewed_summary || "").split("\n").filter(Boolean)) {
      const item = document.createElement("li");
      item.textContent = line;
      list.append(item);
    }
    card.append(list);
  }
  if (requirement.deadline) {
    const deadline = document.createElement("p");
    deadline.className = "deadline-callout";
    deadline.textContent = `公式の日程・締切：${requirement.deadline}`;
    card.append(deadline);
  }
  if (!options.compact && requirement.reviewed_summary
    && requirement.requirement_id !== "language:preparation-guide") {
    const detail = document.createElement("details");
    detail.className = "technical-disclosure";
    const summary = document.createElement("summary");
    summary.textContent = "確認済みの日程の要約を見る";
    const excerpt = document.createElement("blockquote");
    excerpt.className = "reviewed-summary";
    excerpt.textContent = String(requirement.reviewed_summary).replace(/\bRULE-\d+[A-Z]?\b\s*/g, "").trim();
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
  eyebrow.textContent = "出願の概要";
  const title = heading(3, "期限を確認してから準備を始める");
  title.id = "application-overview-heading";
  const target = document.createElement("p");
  target.className = "overview-target";
  target.textContent = targetLabel(payload.target);
  copy.append(eyebrow, title, target);

  const metrics = document.createElement("dl");
  metrics.className = "overview-metrics";
  const metricValues = [
    ["書類の必着期限", overview.deadlineText, "deadline"],
    ["主な提出書類", overview.materialCount === null ? "確認済みのデータはありません" : `${overview.materialCount}項目`, "materials"],
    ["確認が必要な基本要件", overview.needsInformationCount === null ? "確認済みのデータはありません" : `${overview.needsInformationCount}項目`, "pending"]
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
    note.textContent = `うち${overview.profileComparableCount}項目は本人情報と照合でき、${overview.otherConfirmationCount}項目は別途確認が必要です`;
    pendingMetric.append(note);
  }
  copy.append(metrics);

  const action = document.createElement("aside");
  action.className = "overview-action";
  const actionLabel = document.createElement("p");
  actionLabel.textContent = "次のステップ";
  const actionHint = document.createElement("p");
  actionHint.className = "field-detail";
  actionHint.textContent = "入力内容を確認済みの条件と照合します。個人情報は保存しません。";
  action.append(actionLabel, profileCta("overview-cta"), actionHint);
  section.append(copy, action);
  return section;
}

function renderKeyDates(requirements, emptyMessage = "確認済みのデータはありません") {
  const section = document.createElement("section");
  section.className = "result-section key-dates-section";
  section.append(heading(3, "重要な日程"));
  const intro = document.createElement("p");
  intro.className = "section-intro";
  intro.textContent = requirements.length
    ? "「必着」はその期限までに書類が到着する必要があるという意味です。「推奨到着日」は遅延を避けるための目安であり、必須の期限ではありません。"
    : "このサンプルでは日程を整理していません。公式募集要項でご確認ください。";
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
    empty.textContent = emptyMessage;
    dateList.append(empty);
  }
  section.append(dateList);
  return section;
}

function renderRequirementSection(title, entries, className, scope) {
  const section = document.createElement("section");
  section.className = `result-section ${className}`;
  section.append(heading(3, title));
  const list = document.createElement("div");
  list.className = "requirement-list";
  if (entries.length) {
    for (const requirement of entries) list.append(renderRequirementCard(requirement, {scope}));
  } else {
    const empty = document.createElement("p");
    empty.className = "empty-reviewed-data";
    empty.textContent = "確認済みのデータはありません";
    list.append(empty);
  }
  section.append(list);
  return section;
}

function renderPendingRequirements(entries, overview, scope) {
  const section = document.createElement("section");
  section.className = "result-section pending-section";
  const count = overview.needsInformationCount === null ? null : entries.length;
  section.append(heading(3, count === null
    ? "追加確認が必要な基本要件"
    : `追加確認が必要な基本要件：${count}項目`));
  const explanation = document.createElement("p");
  explanation.className = "section-intro";
  explanation.textContent = count === null
    ? "確認済みデータがないため、要件を満たすかどうかは判定しません。"
    : "確認が必要な資格・語学の要件です。書類の適用条件と準備状況は書類リストで確認できます。";
  section.append(explanation);
  if (overview.otherConfirmationRequirements.length) {
    const otherNotice = document.createElement("p");
    otherNotice.className = "pending-other-notice";
    otherNotice.textContent = `この本人情報の照合では扱わない項目：${overview.otherConfirmationRequirements.map((item) => item.title).join("、")}。状況と公式要件を確認してください。`;
    section.append(otherNotice);
  }
  const inputHeading = heading(4, "次のステップで確認する本人情報");
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
    item.textContent = "確認済みのデータはありません";
    categories.append(item);
  }
  section.append(categories);
  if (entries.length) {
    const details = document.createElement("details");
    details.className = "pending-details";
    const summary = document.createElement("summary");
    summary.textContent = `要確認の${entries.length}項目を見る`;
    const list = document.createElement("div");
    list.className = "requirement-list";
    for (const requirement of entries) list.append(renderRequirementCard(requirement, { compact: true, scope }));
    details.append(summary, list);
    section.append(details);
  }
  return section;
}

function renderExamCard(exam) {
  if (exam?.schema_version === "2.0" && exam.status === "available") return renderExamCardV2(exam);
  const section = document.createElement("section");
  section.className = "result-section exam-arrangement";
  section.append(heading(3, exam?.status === "available" ? "試験日程 · B日程" : "試験日程"));
  if (exam?.status !== "available") {
    const note = document.createElement("p");
    note.textContent = exam?.message || "試験情報を表示できません。公式募集要項をご確認ください。";
    section.append(note);
    return section;
  }
  const rows = referenceCore.examReportRows(exam);
  const lead = document.createElement("p");
  lead.className = "exam-lead";
  lead.textContent = rows[0];
  section.append(lead, heading(4, "試験科目"));
  const subjects = document.createElement("ul");
  for (const row of rows.slice(1, 4)) {
    const item = document.createElement("li");
    item.textContent = row;
    subjects.append(item);
  }
  section.append(subjects);
  for (const row of rows.slice(4, 6)) {
    const text = document.createElement("p");
    text.textContent = row;
    section.append(text);
  }
  const after = document.createElement("details");
  const summary = document.createElement("summary");
  summary.textContent = "筆記試験後の口述試験：対象者と日程";
  const oral = document.createElement("p");
  oral.textContent = rows[6];
  after.append(summary, oral);
  const oralSource = document.createElement("button");
  oralSource.type = "button";
  oralSource.className = "quiet";
  oralSource.textContent = "口述試験対象者の発表について原文を見る";
  oralSource.addEventListener("click", () => openDemoEvidence({title: "口述試験対象者の発表"},
    exam.evidence[1], oralSource, {examYearNote: "17時頃から発表されるのは口述試験の対象者です。最終合格発表ではありません。"}));
  after.append(oralSource);
  section.append(after);
  const actions = document.createElement("div");
  actions.className = "source-actions";
  const source = document.createElement("button");
  source.type = "button";
  source.className = "secondary";
  source.textContent = "公式原文を見る";
  source.addEventListener("click", () => openDemoEvidence({title: "B日程の試験日程"}, exam.evidence[0], source,
    {examYearNote: "試験の実施年は、冊子の表紙・出願フロー・情報工学系の試験ページを照合して確認しています。", examYearPages: [1, 2]}));
  const english = document.createElement("button");
  english.type = "button";
  english.className = "secondary";
  english.textContent = "英語スコア証明の要件を見る";
  english.addEventListener("click", () => {
    const target = requirementsOutput.querySelector(".english-section");
    if (!target) return;
    target.scrollIntoView({behavior: "smooth", block: "start"});
    target.setAttribute("tabindex", "-1");
    target.focus({preventScroll: true});
  });
  actions.append(source, english);
  section.append(actions);
  return section;
}

function examSourcesForField(exam, fieldPath) {
  const field = exam.field_bindings.find((item) => item.field_path === fieldPath);
  if (!field) return [];
  const groups = new Map();
  for (const source of field.sources) {
    const fact = exam.evidence.find((item) => item.fact_id === source.source_id);
    const evidence = fact || (source.source_id.startsWith("pdf_page:") ? {
      official_title: exam.official_title, school_name: currentReferenceScope()?.school || "選択中の学校",
      intake_name: currentReferenceScope()?.intake || "この冊子の対象", pages: source.physical_pages,
      official_text: source.exact_text, source_url: exam.official_source_url,
      local_pdf_url: exam.local_pdf_url,
      limitation: "確認済みPDFページの該当箇所です。ページ全体と大学の通知も併せてご確認ください。"
    } : null);
    if (!evidence) continue;
    const key = `${source.source_id}:${source.physical_pages.join(",")}`;
    if (!groups.has(key)) groups.set(key, {evidence, anchors: []});
    const group = groups.get(key);
    if (!group.anchors.includes(source.exact_text)) group.anchors.push(source.exact_text);
  }
  return [...groups.values()];
}

function openExamFieldEvidence(label, sources, trigger) {
  drawerTrigger = trigger;
  drawerScopeKey = currentReferenceScope() ? referenceCore.scopeKey(currentReferenceScope()) : null;
  drawerGraph = null;
  evidenceDrawer.classList.remove("relationship-window");
  byId("drawer-title").textContent = "公式資料の根拠";
  drawerContent.replaceChildren(heading(3, label));
  const note = document.createElement("p");
  note.className = "evidence-chinese-summary";
  note.textContent = "この試験情報の根拠をページ・該当箇所ごとに表示しています。本人に適用される選抜区分・資格は大学の案内をご確認ください。";
  drawerContent.append(note);
  const cards = document.createElement("div");
  cards.className = "relation-nodes";
  for (const {evidence, anchors} of sources) {
    const card = document.createElement("article");
    card.className = "relation-node";
    card.append(heading(4, `PDF ${evidence.pages.join("、")}ページ`));
    for (const anchor of anchors) {
      const quote = document.createElement("blockquote");
      quote.className = "direct-evidence";
      const mark = document.createElement("mark");
      mark.textContent = anchor;
      quote.append(mark);
      card.append(quote);
    }
    const context = document.createElement("details");
    context.className = "official-context";
    const summary = document.createElement("summary");
    summary.textContent = "このページの前後の文脈を表示";
    const full = document.createElement("blockquote");
    full.className = "evidence-text";
    full.textContent = evidence.official_text;
    context.append(summary, full);
    card.append(context);
    for (const page of evidence.pages) {
      const href = verifiedLocalPdfHref(evidence.local_pdf_url, page);
      if (!href) continue;
      const link = document.createElement("a");
      link.className = "source-link pdf-source-link";
      link.href = href;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.textContent = `PDFの${page}ページを開く`;
      card.append(link);
    }
    cards.append(card);
  }
  drawerContent.append(cards);
  if (!evidenceDrawer.open) evidenceDrawer.showModal();
  evidenceDrawer.scrollTop = 0;
  drawerClose.focus({preventScroll: true});
}

function renderExamCardV2(exam) {
  const view = referenceCore.examV2View(exam);
  const section = document.createElement("section");
  section.className = "result-section exam-arrangement";
  section.append(heading(3, "試験日程 · 大学が公表したA/B日程"));
  const lead = document.createElement("p");
  lead.className = "exam-lead";
  lead.textContent = view.lead;
  section.append(lead);
  if (view.course) {
    const course = document.createElement("p");
    course.className = "exam-course-notice";
    course.textContent = view.course;
    section.append(course);
  }
  if (view.subjects.length) {
    section.append(heading(4, "試験科目"));
    const list = document.createElement("ul");
    for (const text of view.subjects) {
      const item = document.createElement("li");
      item.textContent = text;
      list.append(item);
    }
    section.append(list);
  }
  for (const text of [view.selection, view.points]) if (text) {
    const row = document.createElement("p");
    row.textContent = text;
    section.append(row);
  }
  const more = document.createElement("details");
  const summary = document.createElement("summary");
  summary.textContent = "口述試験・英語・使用言語";
  more.append(summary);
  for (const text of [view.aOral, view.bOral, view.specialist, view.english, view.language]) if (text) {
    const row = document.createElement("p");
    row.textContent = text;
    more.append(row);
  }
  section.append(more);
  const actions = document.createElement("div");
  actions.className = "source-actions";
  for (const [path, label] of [["b.subjects", "筆記試験の原文を見る"], ["a.oral", "A日程の原文を見る"],
    ["b.oral", "B日程の口述試験の原文を見る"], ["english.submission", "英語の原文を見る"]]) {
    const sources = examSourcesForField(exam, path);
    if (!sources.length) continue;
    const button = document.createElement("button");
    button.type = "button";
    button.className = "secondary";
    button.textContent = label;
    button.addEventListener("click", () => openExamFieldEvidence(label, sources, button));
    actions.append(button);
  }
  section.append(actions);
  return section;
}

function requirementsJumpNav() {
  const nav = document.createElement("nav");
  nav.className = "requirements-jump";
  nav.setAttribute("aria-label", "このページの要件");
  for (const [selector, label] of [[".key-dates-section", "重要な日程"],
    [".materials-section", "出願書類"], [".exam-arrangement", "試験日程"]]) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "secondary";
    button.textContent = label;
    button.addEventListener("click", () => {
      const section = requirementsOutput.querySelector(selector);
      if (!section) return;
      section.scrollIntoView({behavior: "smooth", block: "start"});
      section.tabIndex = -1;
      section.focus({preventScroll: true});
    });
    nav.append(button);
  }
  return nav;
}

function renderRequirements(payload, scope, exam) {
  requirementsOutput.replaceChildren();
  const target = payload.target;
  targetSummary.hidden = true;
  targetSummary.textContent = targetLabel(target);
  updateTargetStepSummary(target);
  updateRequirementsStepSummary(payload);
  const overview = applicationOverview(payload);
  const requirements = payload.requirements;
  const dateRequirements = requirements.filter((item) => item.category === "dates");
  const englishRequirements = requirements.filter((item) => item.category === "language");
  const materialRequirements = requirements.filter((item) => item.category === "materials");
  const pending = requirements.filter((item) => item.category !== "materials"
    && item.official_status === "needs_information");
  const secondary = requirements.filter((item) => (
    item.category !== "dates"
    && item.category !== "materials"
    && item.category !== "language"
    && item.official_status !== "needs_information"
  ));

  requirementsOutput.append(
    ...(scope.request.school_id === "isct" ? [requirementsJumpNav()] : []),
    renderApplicationOverview(payload, overview),
    renderKeyDates(dateRequirements),
    renderRequirementSection("英語試験・スコア証明", englishRequirements, "english-section", scope),
    renderRequirementSection("確認済みの書類", materialRequirements, "materials-section", scope),
    renderExamCard(exam),
    renderPendingRequirements(pending, overview, scope)
  );

  const next = document.createElement("section");
  next.className = "result-section next-step-section";
  const nextCopy = document.createElement("div");
  nextCopy.append(heading(3, "次のステップ：本人の状況と照合"));
  const nextText = document.createElement("p");
  nextText.textContent = "次のステップで本人の状況を選び、準備が必要な書類や情報を確認できます。";
  nextCopy.append(nextText);
  next.append(nextCopy, profileCta("next-step-cta"));
  requirementsOutput.append(next);

  const other = document.createElement("details");
  other.className = "result-section other-requirements";
  const otherSummary = document.createElement("summary");
  otherSummary.textContent = `その他の説明・確認済み要件${secondary.length ? `（${secondary.length} 项）` : ""}`;
  const otherList = document.createElement("div");
  otherList.className = "requirement-list";
  for (const requirement of secondary) otherList.append(renderRequirementCard(requirement, {scope}));
  if (!secondary.length) {
    const empty = document.createElement("p");
    empty.className = "empty-reviewed-data";
    empty.textContent = "その他の確認済み要件はありません";
    otherList.append(empty);
  }
  other.append(otherSummary, otherList);
  requirementsOutput.append(other);

  const boundary = document.createElement("p");
  boundary.className = "final-notice";
  boundary.textContent = "確認済みの一部要件を整理しています。他の出願条件・提出方法・受理の扱いは、募集要項全体をご確認ください。";
  requirementsOutput.append(boundary);
}

function sourceAsEvidence(source, scope) {
  return {
    official_title: source.title, school_name: scope.school, intake_name: scope.intake,
    pages: source.pages, printed: source.printed, official_text: source.quote, source_url: source.source_url,
    local_pdf_url: source.local_pdf_url, limitation: source.context,
    highlights: source.highlights || []
  };
}

function renderSliceRequirements(mapped) {
  const scope = mapped.scope;
  requirementsOutput.replaceChildren();
  targetSummary.hidden = true;
  targetSummary.textContent = referenceCore.scopeLabel(scope);
  updateTargetStepSummary(scope);
  byId("step-2-summary-text").textContent = `過去資料・確認済みの書類${mapped.topics.length}項目。日程は未収録です。`;
  const overview = document.createElement("section");
  overview.className = "application-overview";
  const copy = document.createElement("div");
  copy.className = "application-overview-copy";
  copy.append(heading(3, "確認済み書類の対象範囲"));
  const label = document.createElement("p");
  label.className = "overview-target";
  label.textContent = referenceCore.scopeLabel(scope);
  const limit = document.createElement("p");
  limit.className = "final-notice";
  limit.textContent = `過去資料の書類${mapped.topics.length}項目のみが対象です。日程や全書類の一覧は含みません。最新の公式募集要項を確認してください。`;
  copy.append(label, limit);
  const action = document.createElement("aside");
  action.className = "overview-action";
  action.append(profileCta("overview-cta"));
  overview.append(copy, action);
  const requirements = mapped.topics.map((topic) => ({
    category: "materials", title: topic.title, material_code: topic.id, description: topic.summary,
    official_status: "needs_information", deadline: "",
    evidence: topic.sources.map((source) => sourceAsEvidence(source, scope)),
    graphTopic: topic, graphScope: scope
  }));
  requirementsOutput.append(
    overview,
    renderKeyDates([], "この資料の日程は未整理です"),
    renderRequirementSection(`収録している書類 ${requirements.length}項目`, requirements, "materials-section", scope)
  );
  const next = document.createElement("section");
  next.className = "result-section next-step-section";
  next.append(heading(3, "次のステップ：本人の状況を確認"), profileCta("next-step-cta"));
  requirementsOutput.append(next);
  renderSlicePreparation(mapped);
}

function slicePreparationValues() {
  return Object.fromEntries(Array.from(byId("slice-material-preparation").querySelectorAll("select"),
    (control) => [control.dataset.sliceMaterialCode, control.value]));
}

function renderSlicePreparation(mapped) {
  byId("slice-profile-coverage").textContent = `収録している書類${mapped.topics.length}項目のみを照合します。在職条件の未入力は「いいえ」とせず、全書類の不足件数も算出しません。`;
  const container = byId("slice-material-preparation");
  container.replaceChildren();
  const controls = referenceCore.slicePreparationControls(mapped);
  container.hidden = controls.length === 0;
  if (!controls.length) return;
  const legend = document.createElement("legend");
  legend.textContent = "書類の準備（自己申告）";
  const note = document.createElement("p");
  note.className = "field-help";
  note.id = "slice-material-help";
  note.textContent = "準備状況はこの画面でのみ記録します。公式の提出要件は変わりません。「準備済み」は有効性・提出済み・受理を意味しません。";
  const inputs = document.createElement("div");
  inputs.className = "material-inputs";
  for (const control of controls) {
    const label = document.createElement("label");
    label.textContent = control.name;
    const select = document.createElement("select");
    select.dataset.sliceMaterialCode = control.id;
    select.dataset.materialName = control.name;
    select.setAttribute("aria-describedby", note.id);
    for (const [value, text] of [["unknown", "不明・未入力"], ["available", "準備済み"], ["not_yet", "未準備"]]) {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = text;
      select.append(option);
    }
    label.append(select);
    inputs.append(label);
  }
  container.append(legend, note, inputs);
}

function refreshSlicePreparation() {
  updateApplicantStepSummary();
  if (!referenceReport || referenceReport.kind !== "reviewed_material_slice" || !loadedReference
    || referenceCore.scopeKey(referenceReport.scope) !== referenceCore.scopeKey(currentReferenceScope())) return;
  referenceReport = referenceCore.withSlicePreparation(referenceReport, slicePreparationValues());
  referenceReader = null;
  renderSliceReadiness(referenceReport, loadedReference);
  setReferenceActionState("success", "準備状況を更新しました。公式の条件は変わりません。レポートを表示・コピーできます。", true);
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
  // Public sample copy: PDFs are not hosted. Verified excerpts remain visible.
  return null;
}

const relationMeanings = {
  cross_reference: "送付方法を参照",
  department_specific_detail: "詳細は専攻の要件を確認",
  consulting_is_distinct_from_submitting: "確認用の一覧と提出する用紙は別",
  corroborates_condition_with_submission_method: "補足条件とアップロード方法を併せて確認",
  supplements: "補足説明",
  shares_employment_context_but_separate_enrollment_stage: "入学手続きに関する背景情報（今回の出願時の提出義務ではありません）"
};

function graphDocumentLabel(title) {
  if (title.includes("追加提出物一覧")) return "専攻独自の追加提出物一覧";
  if (title.includes("入試案内")) return "入試案内";
  if (title.includes("募集要項")) return "募集要項";
  return title.length > 22 ? `…${title.slice(-22)}` : title;
}

function graphNodeLabel(source) {
  const role = source.stage === "enrollment_context_only" ? "入学手続きの背景情報"
    : source.role === "basis" ? "出願要件の直接の根拠" : "出願に関連する説明";
  return `${role} · ${graphDocumentLabel(source.title)} · PDF ${source.pages.join("、")}ページ${source.printed ? `／印刷页 ${source.printed}` : ""}`;
}

function graphSourceCard(source, requirement, cardPosition) {
  const node = document.createElement("article");
  node.className = "relation-node";
  node.dataset.recordId = source.record_id;
  node.append(heading(4, graphNodeLabel(source)));
  const context = document.createElement("p");
  context.textContent = (source.context?.split(" · ")[0] || "確認済みの範囲に含まれる資料")
    .replace(/\b[A-Z]\d{2,}\b/g, "関連条項");
  const button = document.createElement("button");
  button.type = "button";
  button.className = "secondary";
  button.dataset.recordId = source.record_id;
  button.dataset.graphCard = String(cardPosition);
  button.textContent = "原文を見る";
  button.addEventListener("click", () => openDemoEvidence(requirement,
    sourceAsEvidence(source, requirement.graphScope), button,
    {fromGraph: true, scrollTop: evidenceDrawer.scrollTop}));
  node.append(context, button);
  return node;
}

function graphPaths(relations) {
  const pending = [...relations];
  const paths = [];
  while (pending.length) {
    const targets = new Set(pending.map((edge) => edge.to));
    const first = pending.find((edge) => !targets.has(edge.from)) || pending[0];
    const path = [];
    let current = first.from;
    const visited = new Set();
    while (!visited.has(current)) {
      visited.add(current);
      const index = pending.findIndex((edge) => edge.from === current);
      if (index < 0) break;
      const [edge] = pending.splice(index, 1);
      path.push(edge);
      current = edge.to;
    }
    paths.push(path);
  }
  return paths;
}

function openEvidenceGraph(requirement, trigger, focusCard = null, scrollTop = 0) {
  if (focusCard === null) {
    drawerTrigger = trigger;
    drawerScopeKey = currentReferenceScope() ? referenceCore.scopeKey(currentReferenceScope()) : null;
    drawerGraph = {requirement, trigger};
  }
  const topic = requirement.graphTopic;
  evidenceDrawer.classList.add("relationship-window");
  byId("drawer-title").textContent = "書類の根拠となる資料の関係";
  drawerContent.replaceChildren();
  drawerContent.append(heading(3, requirement.title));
  const explanation = document.createElement("p");
  explanation.className = "relation-intro";
  explanation.textContent = `${requirement.description} 矢印は確認済みの資料間の関係を示します。各資料がすべて出願時の提出書類であるという意味ではありません。`;
  drawerContent.append(explanation);
  const sources = new Map(topic.sources.map((source) => [source.record_id, source]));
  const known = topic.relations.filter((row) => Object.hasOwn(relationMeanings, row.kind)
    && sources.has(row.from) && sources.has(row.to));
  const paths = graphPaths(known);
  const connected = new Set(known.flatMap((edge) => [edge.from, edge.to]));
  const graph = document.createElement("div");
  graph.className = "relation-graph";
  let cardPosition = 0;
  const renderCard = (source) => graphSourceCard(source, requirement, cardPosition++);
  for (const path of paths) {
    const flow = document.createElement("section");
    flow.className = "relation-path";
    if (path.length > 2) flow.classList.add("relation-path-long");
    flow.append(renderCard(sources.get(path[0].from)));
    for (const row of path) {
      const edge = document.createElement("div");
      edge.className = row.kind === "shares_employment_context_but_separate_enrollment_stage"
        ? "relation-edge relation-edge-stage" : "relation-edge";
      edge.setAttribute("aria-label", `${graphNodeLabel(sources.get(row.from))} → ${graphNodeLabel(sources.get(row.to))}：${relationMeanings[row.kind]}`);
      const meaning = document.createElement("span");
      meaning.textContent = relationMeanings[row.kind];
      edge.append(meaning);
      flow.append(edge, renderCard(sources.get(row.to)));
    }
    graph.append(flow);
  }
  const independent = topic.sources.filter((source) => !connected.has(source.record_id));
  if (independent.length) {
    const nodes = document.createElement("section");
    nodes.className = "relation-nodes";
    if (paths.length) nodes.append(heading(4, "その他の参考資料"));
    for (const source of independent) nodes.append(renderCard(source));
    graph.append(nodes);
  }
  drawerContent.append(graph);
  if (!topic.relations.length || topic.relations.some((row) => !Object.hasOwn(relationMeanings, row.kind))) {
    const note = document.createElement("p");
    note.className = "relation-unknown";
    note.textContent = topic.relations.length ? "一部の関係は図に未表示です。各資料は上から個別に確認できます。"
      : "図示できる確認済みの関係がないため、資料を個別に表示しています。";
    drawerContent.append(note);
  }
  if (!evidenceDrawer.open) evidenceDrawer.showModal();
  evidenceDrawer.scrollTop = scrollTop;
  const focus = focusCard !== null
    ? Array.from(graph.querySelectorAll("button")).find((button) => button.dataset.graphCard === focusCard)
    : null;
  (focus || drawerClose).focus({preventScroll: true});
}

function openDemoEvidence(requirement, evidence, trigger, options = {}) {
  if (!options.fromGraph) {
    drawerTrigger = trigger;
    drawerScopeKey = currentReferenceScope() ? referenceCore.scopeKey(currentReferenceScope()) : null;
    drawerGraph = null;
    evidenceDrawer.classList.remove("relationship-window");
  }
  byId("drawer-title").textContent = options.fromGraph ? "公式原文" : "公式資料の根拠";
  drawerContent.replaceChildren();
  if (options.fromGraph && drawerGraph) {
    const back = document.createElement("button");
    back.type = "button";
    back.className = "secondary relation-back";
    back.textContent = "資料の関係に戻る";
    back.addEventListener("click", () => openEvidenceGraph(drawerGraph.requirement,
      drawerGraph.trigger, trigger.dataset.graphCard, options.scrollTop));
    drawerContent.append(back);
  }
  drawerContent.append(heading(3, requirement.title || requirement.label || "公式資料の根拠"));
  if (options.examYearNote) {
    const yearNote = document.createElement("p");
    yearNote.className = "evidence-chinese-summary";
    yearNote.textContent = options.examYearNote;
    drawerContent.append(yearNote);
  }
  const guidance = referenceCore?.materialGuide(currentReferenceScope(), {
    id: requirement.requirement_id || requirement.item_id || requirement.material_code,
    sources: requirement.graphTopic?.sources || requirement.evidence
  });
  if (guidance) {
    const summary = document.createElement("section");
    summary.className = "evidence-chinese-summary";
    summary.append(heading(4, "この書類の準備ポイント"));
    const purpose = document.createElement("p");
    purpose.textContent = guidance.purpose;
    summary.append(purpose);
    appendPreparationGuide(summary, guidance);
    const context = document.createElement("p");
    context.className = "field-detail";
    context.textContent = guidance.sourceNote
      || "下の原文は10ページの共通書類一覧で、他の書類も含まれます。準備ポイントは現在の書類のみを整理しています。";
    summary.append(context);
    drawerContent.append(summary);
  }
  const meta = document.createElement("dl");
  meta.className = "evidence-meta";
  appendDefinition(meta, "公式資料", evidence.official_title);
  appendDefinition(meta, "学校・入学時期", `${evidence.school_name} · ${evidence.intake_name}`);
  appendDefinition(meta, "ページ", `PDFページ ${evidence.pages.join("、")}${evidence.printed ? `／印刷页 ${evidence.printed}` : ""}（リンクで自動移動しない場合は、ファイル内で該当ページを開いてください）`);
  const highlights = Array.isArray(evidence.highlights) ? evidence.highlights : [];
  const evidenceBody = document.createDocumentFragment();
  if (highlights.length) {
    const directHeading = document.createElement("p");
    directHeading.className = "direct-evidence-heading";
    directHeading.textContent = "この説明の直接の根拠となる公式原文";
    evidenceBody.append(directHeading);
    for (const highlight of highlights) {
      const direct = document.createElement("blockquote");
      direct.className = "direct-evidence";
      const label = document.createElement("span");
      label.className = "direct-evidence-label";
      label.textContent = "直接の根拠";
      const mark = document.createElement("mark");
      mark.textContent = highlight.exact_text;
      direct.append(label, mark);
      evidenceBody.append(direct);
    }
    const context = document.createElement("details");
    context.className = "official-context";
    const contextSummary = document.createElement("summary");
    contextSummary.textContent = "公式原文を全文表示";
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
  limitation.textContent = `留意事項：${evidence.limitation}`;
  const details = document.createElement("details");
  const summary = document.createElement("summary");
  summary.textContent = "技術情報";
  const technical = document.createElement("dl");
  technical.className = "evidence-meta";
  if (evidence.document_id) {
    appendDefinition(technical, "Fact ID", evidence.fact_id);
    appendDefinition(technical, "Document ID", evidence.document_id);
    appendDefinition(technical, "Scope", `${evidence.scope_type}${evidence.parent_college ? ` · ${evidence.parent_college}` : ""}${evidence.scope_targets?.length ? ` · ${evidence.scope_targets.join("、")}` : ""}`);
  }
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
      pdfLink.textContent = `PDFの${page}ページを開く`;
      sourceActions.append(pdfLink);
    }
    for (const page of options.examYearPages || []) {
      const href = verifiedLocalPdfHref(evidence.local_pdf_url, page);
      if (!href) continue;
      const pdfLink = document.createElement("a");
      pdfLink.className = "source-link pdf-source-link";
      pdfLink.href = href;
      pdfLink.target = "_blank";
      pdfLink.rel = "noopener noreferrer";
      pdfLink.textContent = page === 1 ? "表紙の年度を見る" : "出願・試験の流れを見る";
      sourceActions.append(pdfLink);
    }
  }
  const source = document.createElement("a");
  source.className = "source-link official-web-link";
  source.href = evidence.source_url;
  source.target = "_blank";
  source.rel = "noopener noreferrer";
  source.textContent = "大学の入試案内を開く";
  sourceActions.append(source);
  drawerContent.append(meta, evidenceBody, limitation);
  if (evidence.document_id) drawerContent.append(details);
  drawerContent.append(sourceActions);
  if (!evidenceDrawer.open) evidenceDrawer.showModal();
  evidenceDrawer.scrollTop = 0;
  (options.fromGraph ? drawerContent.querySelector(".relation-back") : drawerClose).focus();
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
  return { schema_version: "1.0", target: demoTargetRequest(), applicant: demoApplicantInput(),
    english_preparation: englishPreparationInput(),
    application_preparation: applicationPreparationInput() };
}

function cancelPendingComparison() {
  comparisonRequestId += 1;
  if (comparisonController) comparisonController.abort();
  comparisonController = null;
  comparisonPending = false;
  comparisonSubmit.disabled = !baseRequirementsLoaded;
}

function clearComparison(message = "サンプルケースを選ぶと、保存済みの照合結果を確認できます。") {
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
    recorded: "記録済み",
    possible_match: "該当する可能性あり・要確認",
    needs_information: "追加情報が必要",
    needs_review: "大学・担当者の確認が必要",
    not_applicable: "対象外",
    not_covered: "現在の対象範囲外"
  };
  return labels[status] || status;
}

function resetChecklistProgress() {
  for (const checkbox of comparisonOutput.querySelectorAll(".personal-check input")) {
    checkbox.checked = false;
    checkbox.dispatchEvent(new Event("change"));
  }
}

function materialPreparationState(item) {
  if (item.preparation_status === "available") return "準備済み（自己申告）";
  if (item.preparation_status === "not_yet") return item.official_status === "required"
    ? "準備が必要" : "自己申告：未準備";
  return "準備状況が未入力";
}

function materialOfficialState(item) {
  const labels = {
    required: "提出が必要",
    not_applicable: "現在の条件では提出不要",
    eligibility_review_path: "適用条件：資格審査区分の確認が必要",
    needs_information: "適用条件：要確認",
    not_covered: "適用条件は対象資料の範囲外"
  };
  return labels[item.official_status] || "適用条件：要確認";
}

function materialNextAction(item) {
  if (item.official_status === "not_applicable") return "現在の条件では、この書類の提出は不要です。";
  if (item.official_status === "not_covered") return "募集要項全体をご覧いただくか、大学へご確認ください。";
  if (item.official_status !== "required") return "まず自分の出願条件に該当するか確認してください。";
  if (item.preparation_status === "not_yet") return "公式案内に従って準備し、提出要件を確認してください。";
  if (item.preparation_status === "available") return "書類の内容が公式要件を満たしているか確認してください。";
  return "準備状況を入力し、公式案内と照合してください。";
}

function englishActionGroup(check) {
  if (check.status === "action_needed") return "action_required";
  if (check.status === "needs_information" || check.status === "not_covered") return "review_required";
  return "recorded";
}

function renderPriorityActions(entries, scope, englishEntries = [], applicationEntries = []) {
  const container = byId("priority-actions");
  container.hidden = false;
  container.replaceChildren();
  const pending = entries.filter(({ item }) => item.action_group !== "recorded");
  const englishPending = englishEntries.filter(({ actionGroup }) => actionGroup !== "recorded");
  const applicationPending = applicationEntries.filter(({ actionGroup }) => actionGroup !== "recorded");
  const prioritized = [
    ...applicationPending.filter(({ actionGroup }) => actionGroup === "action_required"),
    ...englishPending.filter(({ actionGroup }) => actionGroup === "action_required"),
    ...applicationPending.filter(({ actionGroup }) => actionGroup === "review_required"),
    ...englishPending.filter(({ actionGroup }) => actionGroup === "review_required"),
    ...pending
  ];
  const title = heading(4, "優先する準備");
  container.append(title);
  if (!prioritized.length) {
    const empty = document.createElement("p");
    empty.textContent = "追加準備・確認が必要な項目は現在ありません。ただし、記録済みでも大学の確認済み・出願完了を意味しません。";
    container.append(empty);
    return;
  }
  const list = document.createElement("ol");
  for (const entry of prioritized.slice(0, 3)) {
    const { item, check, cardId } = entry;
    const row = document.createElement("li");
    const link = document.createElement("a");
    link.href = `#${cardId}`;
    const material = item?.category === "materials"
      ? referenceCore.materialDisplay(scope, item.item_id, item.title) : null;
    link.textContent = check ? `${entry.kind === "application" ? "卒業・提出" : "英語"} · ${check.title}`
      : material ? material.name : item.title;
    link.addEventListener("click", (event) => {
      event.preventDefault();
      readinessFilters.querySelector('[value="all"]').checked = true;
      applyReadinessFilter();
      const target = byId(cardId);
      if (!target) return;
      for (let parent = target.parentElement; parent; parent = parent.parentElement)
        if (parent.tagName === "DETAILS") parent.open = true;
      window.history.replaceState(null, "", `#${cardId}`);
      target.scrollIntoView({ block: "start", behavior: "auto" });
      target.focus({ preventScroll: true });
    });
    row.append(link);
    list.append(row);
  }
  container.append(list);
  if (prioritized.length > 3) {
    const remainder = document.createElement("p");
    remainder.className = "field-detail";
    remainder.textContent = `下にあと${prioritized.length - 3}項目の確認事項があります。`;
    container.append(remainder);
  }
}

function renderEnglishPreparation(result, entries) {
  const section = document.createElement("section");
  section.className = "requirement-group english-preparation-group comparison-topic-group";
  section.append(heading(3, "英語スコア証明"));
  const pending = entries.filter(({actionGroup}) => actionGroup !== "recorded");
  const reference = entries.filter(({actionGroup}) => actionGroup === "recorded");
  const overview = document.createElement("p");
  overview.className = "english-topic-overview";
  overview.textContent = pending.length
    ? `${pending.length}項目が対応・確認待ちです。下に一覧を表示します。`
    : "英語について明確な未対応項目はありません。公式の証明要件はご確認ください。";
  section.append(overview);
  const scope = document.createElement("p");
  scope.className = "field-detail";
  scope.textContent = result.scope_statement;
  section.append(scope);
  const list = document.createElement("div");
  list.className = "english-check-list";
  const statusLabels = {reported_match: "申告上は準備済み", action_needed: "対応が必要",
    needs_information: "確認待ち", not_applicable: "この項目は対象外", not_covered: "未対応"};
  const renderRow = ({ check, cardId, actionGroup }) => {
    const card = document.createElement("article");
    card.className = "english-check-row comparison-card";
    card.id = cardId;
    card.tabIndex = -1;
    card.dataset.actionGroup = actionGroup;
    card.dataset.category = "english";
    card.append(heading(4, check.title));
    const status = document.createElement("span");
    status.className = "requirement-status";
    status.dataset.status = check.status;
    status.textContent = statusLabels[check.status];
    const explanation = document.createElement("p");
    explanation.textContent = check.explanation;
    const action = document.createElement("p");
    action.className = "next-action";
    action.textContent = `次にすること：${check.next_action}`;
    card.append(status, explanation, action);
    appendRequirementEvidence(card, {title: check.title, evidence: check.evidence});
    return card;
  };
  for (const entry of pending) list.append(renderRow(entry));
  section.append(list);
  if (reference.length) {
    const details = document.createElement("details");
    details.className = "english-reference-details";
    const summary = document.createElement("summary");
    summary.textContent = `記録済み・対象外の確認項目を見る（${reference.length}）`;
    details.append(summary);
    const rows = document.createElement("div");
    rows.className = "english-check-list";
    for (const entry of reference) rows.append(renderRow(entry));
    details.append(rows);
    section.append(details);
  }
  return section;
}

function renderApplicationPreparation(result, entries) {
  const section = document.createElement("section");
  section.className = "requirement-group application-preparation-group comparison-topic-group";
  section.append(heading(3, "資格・手続き · 卒業・提出"));
  const scope = document.createElement("p");
  scope.className = "field-detail";
  scope.textContent = result.scope_statement;
  section.append(scope);
  const list = document.createElement("div");
  list.className = "requirement-list";
  const labels = {reported_match: "申告内容を記録済み", action_needed: "対応が必要",
    needs_information: "確認待ち", not_applicable: "この項目は対象外", not_covered: "未対応"};
  for (const { check, cardId, actionGroup } of entries) {
    const card = document.createElement("article");
    card.className = "requirement-card comparison-card";
    card.id = cardId;
    card.tabIndex = -1;
    card.dataset.actionGroup = actionGroup;
    card.dataset.category = "application";
    card.append(heading(4, check.title));
    const status = document.createElement("span");
    status.className = "requirement-status";
    status.dataset.status = check.status;
    status.textContent = labels[check.status];
    const explanation = document.createElement("p");
    explanation.textContent = check.explanation;
    const action = document.createElement("p");
    action.className = "next-action";
    action.textContent = `次にすること：${check.next_action}`;
    card.append(status, explanation, action);
    appendRequirementEvidence(card, {title: check.title, evidence: check.evidence});
    list.append(card);
  }
  section.append(list);
  return section;
}

function renderComparison(payload, scope) {
  byId("readiness-panel").classList.remove("slice-readiness");
  byId("readiness-filters").hidden = false;
  byId("readiness-panel").querySelector(".readiness-counts").hidden = false;
  byId("readiness-panel").querySelector(".action-summary-total").hidden = false;
  comparisonOutput.replaceChildren();
  readinessTarget.textContent = targetLabel(payload.target);
  partialChecklistStatement.textContent = "確認済みの範囲のみを整理しています。他の要件は募集要項全体をご確認ください。";
  readinessFilters.querySelector('[value="all"]').checked = true;
  const groups = [["action_required", "準備が必要"], ["review_required", "確認・審査が必要"], ["recorded", "申告済み・要件と一致する可能性"]];
  const entriesWithIds = groups.flatMap(([actionGroup]) => payload.items
    .filter((item) => item.action_group === actionGroup)
    .map((item, index) => ({ item, cardId: `comparison-${actionGroup}-${index}` })));
  const detailed = payload.english_preparation_result;
  const visibleEntries = detailed
    ? entriesWithIds.filter(({ item }) => item.category !== "english") : entriesWithIds;
  const englishEntries = (detailed?.checks || []).map((check, index) => ({
    check, cardId: `comparison-english-${index}`, actionGroup: englishActionGroup(check)
  }));
  const application = payload.application_preparation_result;
  const applicationEntries = (application?.checks || []).map((check, index) => ({
    check, cardId: `comparison-application-${index}`, actionGroup: englishActionGroup(check),
    kind: "application"
  }));
  const visibleGroups = [
    ...visibleEntries.map(({ item }) => item.action_group),
    ...englishEntries.map(({ actionGroup }) => actionGroup),
    ...applicationEntries.map(({ actionGroup }) => actionGroup)
  ];
  byId("count-total").textContent = String(visibleGroups.length);
  byId("count-recorded").textContent = String(visibleGroups.filter((group) => group === "recorded").length);
  byId("count-action").textContent = String(visibleGroups.filter((group) => group === "action_required").length);
  byId("count-review").textContent = String(visibleGroups.filter((group) => group === "review_required").length);
  renderPriorityActions(visibleEntries, scope, englishEntries, applicationEntries);
  const categoryLabels = { education: "学歴", english: "英語", japanese: "日本語", materials: "書類" };
  const materialEntries = visibleEntries.filter(({ item }) => item.category === "materials");
  const educationEntries = visibleEntries.filter(({ item }) => item.category === "education");
  const otherEntries = visibleEntries.filter(({ item }) => !["materials", "education"].includes(item.category));
  const sections = [
    ["materials", `出願書類の準備（${materialEntries.length}項目）`, materialEntries],
    ["education", "資格・手続き · 学歴", educationEntries],
    ["other", "その他の確認済み要件", otherEntries]
  ];
  if (!materialEntries.length) {
    if (detailed) comparisonOutput.append(renderEnglishPreparation(detailed, englishEntries));
    if (application) comparisonOutput.append(renderApplicationPreparation(application, applicationEntries));
  }
  for (const [actionGroup, label, entries] of sections) {
    if (!entries.length) continue;
    const section = document.createElement("section");
    section.className = "requirement-group comparison-group comparison-topic-group";
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
      card.dataset.category = item.category;
      const material = item.category === "materials"
        ? referenceCore.materialDisplay(scope, item.item_id, item.title) : null;
      const guide = material ? referenceCore.materialGuide(scope, {
        id: item.item_id, evidence: item.evidence
      }) : null;
      const category = document.createElement("p");
      category.className = "comparison-category";
      category.textContent = categoryLabels[item.category] || item.category;
      card.append(category);
      card.append(heading(4, material ? material.name : item.title));
      if (material) {
        const officialName = document.createElement("p");
        officialName.className = "material-official-name";
        officialName.textContent = material.official || "正式名称は要確認";
        const what = document.createElement("p");
        what.className = "material-explanation";
        what.textContent = guide?.purpose || material.description;
        const applicability = document.createElement("p");
        applicability.className = "material-applicability";
        applicability.textContent = materialOfficialState(item);
        card.append(what, applicability);
        if (guide && item.official_status !== "required") {
          const conditional = document.createElement("p");
          conditional.className = "preparation-warning";
          conditional.textContent = "この区分での提出要否は確認待ちです。以下は提出が必要な場合の準備方法です。";
          card.append(conditional);
        }
        if (guide) appendPreparationGuide(card, guide, officialName);
        else card.append(officialName);
      }
      const statusLabel = document.createElement("p");
      statusLabel.className = "comparison-state-label";
      statusLabel.textContent = material ? "準備状況" : "確認結果";
      const status = document.createElement("span");
      status.className = "requirement-status";
      status.dataset.status = item.comparison_status;
      status.textContent = material ? materialPreparationState(item)
        : comparisonStatusLabel(item.comparison_status);
      const description = document.createElement("p");
      description.className = "comparison-reason";
      description.textContent = `説明：${item.description}`;
      card.append(statusLabel, status);
      if (!material) card.append(description);
      const nextAction = document.createElement("p");
      nextAction.className = "next-action";
      nextAction.textContent = `次にすること：${material ? materialNextAction(item) : item.next_action}`;
      card.append(nextAction);
      if (item.official_status && !material) {
        const officialLabels = { required: "対象", eligibility_review_path: "個別資格審査で確認", needs_information: "学歴区分の情報が必要", not_covered: "現在の対象範囲外" };
        const preparationLabels = { available: "準備済み", not_yet: "未準備", unknown: "未入力・不明" };
        const official = document.createElement("p");
        official.className = "field-detail";
        official.textContent = `公式要件の適用：${officialLabels[item.official_status] || item.official_status}／準備状況：${preparationLabels[item.preparation_status] || item.preparation_status}`;
        card.append(official);
      }
      const progress = document.createElement("p");
      progress.className = "personal-progress";
      progress.textContent = item.action_group === "recorded" ? "進捗：記録するアクションはありません" : "進捗：未対応";
      if (!material) card.append(progress);
      if (item.action_group !== "recorded") {
        const label = document.createElement("label");
        label.className = "personal-check";
        const checkbox = document.createElement("input");
        checkbox.type = "checkbox";
        checkbox.addEventListener("change", () => {
          if (!material) progress.textContent = checkbox.checked
            ? "進捗：対応済み（本人の記録のみ）" : "進捗：未対応";
          card.dataset.handled = checkbox.checked ? "true" : "false";
        });
        const labelText = document.createElement("span");
        labelText.textContent = material ? "対応済み（この画面のみ）" : "対応済みとして記録";
        label.append(checkbox, labelText);
        card.append(label);
      }
      appendRequirementEvidence(card, item);
      if (item.limitation && !material && item.comparison_status !== "recorded") {
        const limit = document.createElement("details");
        limit.className = "comparison-limit";
        const summary = document.createElement("summary");
        summary.textContent = "確認が必要";
        const text = document.createElement("p");
        text.textContent = item.limitation;
        limit.append(summary, text);
        card.append(limit);
      }
      list.append(card);
    }
    section.append(list);
    comparisonOutput.append(section);
    if (actionGroup === "materials") {
      if (detailed) comparisonOutput.append(renderEnglishPreparation(detailed, englishEntries));
      if (application) comparisonOutput.append(renderApplicationPreparation(application, applicationEntries));
    }
  }
  const boundary = document.createElement("p");
  boundary.className = "final-notice";
  boundary.textContent = "準備状況は書類の提出済み・大学の受理を意味しません。";
  comparisonOutput.append(boundary);
  filterEmpty.hidden = true;
  comparisonComplete = true;
  comparisonEverLoaded = true;
  updateApplicantStepSummary();
}

function renderSliceReadiness(report, mapped) {
  const panel = byId("readiness-panel");
  panel.classList.add("slice-readiness");
  panel.querySelector(".readiness-counts").hidden = true;
  panel.querySelector(".action-summary-total").hidden = true;
  byId("readiness-filters").hidden = true;
  comparisonOutput.replaceChildren();
  readinessTarget.textContent = referenceCore.scopeLabel(mapped.scope);
  partialChecklistStatement.textContent = `書類${report.topics.length}項目のみが対象で、完全な一覧ではありません。計画書の要否は、今回の在職条件によって変わります。`;
  const priority = byId("priority-actions");
  priority.replaceChildren();
  priority.hidden = true;
  for (const topic of report.topics) {
    const mappedTopic = mapped.topics.find((entry) => entry.title === topic.title);
    const sources = mappedTopic?.sources || [];
    const evidence = topic.citations.map((cite) => {
      const source = sources.find((candidate) => candidate.record_id === cite.record_id);
      return sourceAsEvidence(source, mapped.scope);
    });
    const requirement = {
      category: "materials", title: topic.title, material_code: topic.id,
      description: topic.explanation,
      official_status: topic.status_code, evidence, graphTopic: mappedTopic,
      graphScope: mapped.scope, conditionResultLoaded: true
    };
    const card = renderRequirementCard(requirement, {scope: mapped.scope});
    if (Object.hasOwn(report.preparation || {}, topic.id)) {
      const preparation = document.createElement("p");
      preparation.className = "material-condition";
      const names = {unknown: "準備状況が未入力", available: "準備済み（自己申告）", not_yet: "準備が必要（未準備と申告）"};
      preparation.textContent = `準備状況：${names[report.preparation[topic.id]]}。自己申告は提出済み・受理済みを意味しません。`;
      card.append(preparation);
    }
    if (topic.explanation) {
      const result = document.createElement("p");
      result.className = "material-condition";
      result.textContent = topic.explanation;
      card.append(result);
    }
    if (topic.status_code === "rule_not_applicable") {
      const boundary = document.createElement("p");
      boundary.className = "material-condition";
      boundary.textContent = "この条件の対象外です。提出全般が免除される意味ではありません。";
      card.append(boundary);
    }
    for (const value of topic.missing_fields) {
      const note = document.createElement("p");
      note.className = "comparison-reason";
      note.textContent = `確認待ちの条件：${sliceConditionLabel(value)}`;
      card.append(note);
    }
    for (const value of topic.limitations) {
      const note = document.createElement("p");
      note.className = "final-notice";
      note.textContent = value;
      card.append(note);
    }
    comparisonOutput.append(card);
  }
  comparisonComplete = true;
  comparisonEverLoaded = true;
  updateApplicantStepSummary();
}

function sliceConditionLabel(value) {
  const labels = {
    "employment.currently_employed_in_organization": "現在、組織に在職していますか",
    "employment.retain_employment_at_enrollment": "入学後も在職を継続しますか"
  };
  return labels[value] || "公式の条件全体の確認が必要";
}

function renderReferenceReport(report) {
  referenceBody.replaceChildren();
  byId("reference-report-title").textContent = "出願準備レポート";
  const available = referenceCore.readerReportOptions(report);
  const selected = {...available, exams: false};
  const options = document.createElement("fieldset");
  options.className = "reader-report-options";
  const legend = document.createElement("legend");
  legend.textContent = "レポートに含める内容";
  options.append(legend);
  const content = document.createElement("article");
  content.className = "reader-report-paper";
  const compareButton = document.createElement("button");
  compareButton.type = "button";
  compareButton.className = "secondary";
  compareButton.textContent = "本人情報を照合してレポートを作成";
  const addSection = (title, rows, empty) => {
    const section = document.createElement("section");
    section.className = "reader-report-section";
    section.append(heading(3, title));
    if (rows.length) {
      const list = document.createElement("ul");
      for (const row of rows) {
        const item = document.createElement("li");
        item.textContent = row;
        list.append(item);
      }
      section.append(list);
    } else {
      const note = document.createElement("p");
      note.textContent = empty;
      section.append(note);
    }
    content.append(section);
  };
  const draw = () => {
    referenceReader = null;
    byId("reference-copy").disabled = true;
    const fallback = byId("reference-copy-fallback");
    fallback.value = "";
    fallback.hidden = true;
    byId("reference-copy-fallback-label").hidden = true;
    byId("reference-report-status").textContent = "";
    content.replaceChildren();
    if (!Object.values(selected).some(Boolean)) {
      content.append(heading(3, "レポートに含める項目を1つ以上選択してください。"));
      compareButton.hidden = true;
      return;
    }
    const needsComparison = report.kind === "legacy_applicant"
      && report.profileDisclosure.length > 0 && !report.comparison
      && (selected.dates || selected.materials || selected.other);
    compareButton.hidden = !needsComparison;
    if (needsComparison) {
      const note = document.createElement("p");
      note.className = "reader-report-note";
      note.textContent = "本人情報が入力されています。日程・書類・その他の要件は、本人情報の照合後に表示します。"
        + (available.exams ? "試験日程のみであれば、そのまま表示・コピーできます。" : "照合できなかった場合は、ここから再試行できます。");
      content.append(note);
      return;
    }
    const view = referenceCore.readerReport(report, selected);
    const title = document.createElement("header");
    title.className = "reader-report-title";
    title.append(heading(3, view.target));
    const focus = document.createElement("p");
    focus.textContent = `選択した内容：${view.selected.map((key) => ({dates: "重要な日程", materials: "書類・次にすること", other: "読み込み済みのその他の要件", exams: "試験日程"})[key]).join("、")}`;
    title.append(focus);
    content.append(title);
    if (view.priorityRows.length) addSection("次に準備すること", view.priorityRows, "");
    if (selected.dates) {
      addSection("重要な日程", view.dates.map((item) =>
        `${item.label}：${item.value}${item.note ? `；${item.note}` : ""}`),
      "対象資料の日程はまだ整理されていません。募集要項全体をご確認ください。");
      if (view.dateNote) {
        const dateNote = document.createElement("p");
        dateNote.className = "reader-report-note";
        dateNote.textContent = view.dateNote;
        content.append(dateNote);
      }
    }
    if (selected.materials) addSection("書類の準備リスト", view.materials.map((item) => item.line),
      "選択した資料に、レポートに含められる書類項目がありません。");
    if (selected.materials && view.english.length)
      addSection("英語スコア・証明書", view.english, "");
    if (selected.materials && view.submission.length)
      addSection("卒業・提出に関する確認事項", view.submission, "");
    if (selected.other) addSection("読み込み済みのその他の要件", view.other.map((item) =>
      `${item.title}：${item.summary}（${item.status}）`), "その他の項目はありません。");
    if (selected.exams) addSection("試験日程", view.exams, "");
    const limit = document.createElement("p");
    limit.className = "reader-report-note";
    limit.textContent = `対象範囲：${view.limitation}`;
    content.append(limit);
    const sampleNotice = "【保存済みサンプル】過去の募集資料とサンプルケースを整理したものです。リアルタイムの審査や最新の募集情報を網羅するものではありません。";
    const sampleLabel = document.createElement("p");
    sampleLabel.className = "demo-report-label";
    sampleLabel.textContent = sampleNotice;
    content.prepend(sampleLabel);
    referenceReader = {...view, text: `${sampleNotice}\n\n${view.text}`};
    byId("reference-copy").disabled = false;
  };
  for (const [key, label] of Object.entries({dates: "重要な日程", materials: "書類・次にすること", other: "読み込み済みのその他の要件", exams: "試験日程"})) {
    if (!available[key]) continue;
    const wrapper = document.createElement("label");
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = selected[key];
    checkbox.addEventListener("change", () => { selected[key] = checkbox.checked; draw(); });
    wrapper.append(checkbox, document.createTextNode(label));
    options.append(wrapper);
  }
  compareButton.addEventListener("click", async () => {
    if (referenceReportController || !applicationDatesReconcile()) {
      if (!referenceReportController) byId("reference-report-status").textContent = "卒業日と書類の到着日を確認してから照合してください。";
      return;
    }
    const requestId = referenceReportRequestId;
    const scopeSnapshot = referenceCore.scopeKey(report.scope);
    const profileSnapshot = JSON.stringify(demoComparisonRequest());
    const controller = new AbortController();
    referenceReportController = controller;
    compareButton.disabled = true;
    byId("reference-report-status").textContent = "本人の状況を照合しています。";
    const current = () => requestId === referenceReportRequestId && referenceDialog.open
      && currentReferenceScope() && referenceCore.scopeKey(currentReferenceScope()) === scopeSnapshot
      && JSON.stringify(demoComparisonRequest()) === profileSnapshot
      && loadedReference && referenceCore.scopeKey(loadedReference.scope) === scopeSnapshot;
    try {
      const response = await fetch(APPLICANT_COMPARISON_ENDPOINT, {
        method: "POST", headers: {Accept: "application/json", "Content-Type": "application/json"},
        body: profileSnapshot, cache: "no-store", credentials: "same-origin", signal: controller.signal
      });
      if (!response.ok) throw new Error();
      const comparison = await response.json();
      if (!current()) return;
      report = referenceCore.legacyReport(loadedReference, comparison,
        legacyProfileDisclosure(), loadedReference.exam || null);
      referenceReport = report;
      draw();
      byId("reference-report-status").textContent = "照合が完了しました。レポートを表示・コピーできます。";
    } catch (error) {
      if (error?.name !== "AbortError" && current())
        byId("reference-report-status").textContent = "本人情報を照合できなかったため、レポートは未作成です。再試行してください"
          + (available.exams ? "。または試験日程のみを選び、表示・コピーできます。" : "。");
    } finally {
      if (requestId === referenceReportRequestId) {
        referenceReportController = null;
        compareButton.disabled = false;
      }
    }
  });
  options.append(compareButton);
  referenceBody.append(options, content);
  referenceDialog.showModal();
  draw();
  byId("reference-close").focus();
}

function legacyProfileDisclosure() {
  const fields = [];
  for (const control of byId("legacy-profile-grid").querySelectorAll("select, input")) {
    if (!control.value) continue;
    const label = control.closest("label")?.firstChild?.textContent?.trim()
      || byId("legacy-profile-grid").querySelector(`label[for="${control.id}"]`)?.textContent?.trim();
    const value = control.tagName === "SELECT"
      ? control.selectedOptions[0].textContent.trim() : control.value;
    if (label && value) fields.push({label, value});
  }
  return fields;
}

async function generateReferenceReport(event) {
  if (referenceReportController) return;
  if (!baseRequirementsLoaded || !loadedReference) {
    setReferenceActionState("initial", "志望先の基本要件を読み込んでから、レポートを作成してください。", false);
    return;
  }
  const trigger = event.currentTarget;
  const scope = currentReferenceScope();
  if (!scope || referenceCore.scopeKey(scope) !== referenceCore.scopeKey(loadedReference.scope)) {
    setReferenceActionState("error", "選択内容と読み込み済み要件が一致しません。要件を読み込み直してください。", false);
    return;
  }
  referenceTrigger = trigger;
  if (referenceReport && referenceReport.kind === scope.kind
    && referenceCore.scopeKey(referenceReport.scope) === referenceCore.scopeKey(scope)) {
    renderReferenceReport(referenceReport);
    setReferenceActionState("success", "レポートを開きました。内容を選んでコピーできます。");
    return;
  }
  clearReferenceReport("確認済みの結果と公式資料を整理しています。");
  if (scope.kind === "legacy_applicant") {
    const disclosure = legacyProfileDisclosure();
    try {
      referenceReport = referenceCore.legacyReport(loadedReference,
        disclosure.length ? comparisonResponse : null, disclosure, loadedReference.exam || null);
      renderReferenceReport(referenceReport);
      setReferenceActionState("success", "レポートを開きました。本人情報に関する項目は、必要な照合を行ってからコピーできます。");
    } catch {
      setReferenceActionState("error", "レポートを作成できないか、根拠が不足しています。志望先を読み込み直してください。", true);
    }
    return;
  }
  const requestId = referenceReportRequestId;
  const profileSnapshot = JSON.stringify([byId("slice-current-employed").value, byId("slice-retain-employed").value]);
  const scopeSnapshot = referenceCore.scopeKey(scope);
  referenceReportController = new AbortController();
  setReferenceActionState("loading", "レポートを作成しています。再度クリックしても処理は重複しません。", false);
  const current = () => requestId === referenceReportRequestId
    && currentReferenceScope() && referenceCore.scopeKey(currentReferenceScope()) === scopeSnapshot
    && JSON.stringify([byId("slice-current-employed").value, byId("slice-retain-employed").value]) === profileSnapshot
    && loadedReference && referenceCore.scopeKey(loadedReference.scope) === scopeSnapshot;
  try {
    const employment = {current: byId("slice-current-employed").value, retain: byId("slice-retain-employed").value};
    const response = await fetch(`/v1/reference-slices/${encodeURIComponent(scope.entry_id)}/reports`, {
      method: "POST", headers: {Accept: "application/json", "Content-Type": "application/json"},
      body: JSON.stringify(referenceCore.sliceReportRequest(scope, employment)),
      cache: "no-store", credentials: "same-origin", signal: referenceReportController.signal
    });
    if (!response.ok) throw new Error();
    const report = referenceCore.sliceReport(scope, loadedReference, await response.json(), employment,
      slicePreparationValues());
    if (!current()) return;
    referenceReport = report;
    renderReferenceReport(report);
    setReferenceActionState("success", "レポートを表示しました。内容を選んでコピーできます。志望先・条件を変えると前のレポートはクリアされます。");
  } catch (error) {
    if (error?.name !== "AbortError" && current())
      setReferenceActionState("error", "レポートを作成できないか、根拠が不足しています。入力は保持しています。「レポートの作成を再試行」を押してください。", true);
  } finally {
    if (requestId === referenceReportRequestId) {
      referenceReportController = null;
      if (!referenceDialog.open) trigger.focus();
    }
  }
}

async function copyReferenceReport() {
  if (!referenceReport || !referenceReader || !loadedReference
    || referenceCore.scopeKey(referenceReport.scope) !== referenceCore.scopeKey(currentReferenceScope())) return;
  try {
    await navigator.clipboard.writeText(referenceReader.text);
    byId("reference-report-status").textContent = "選択した内容のレポートをコピーしました。";
  } catch {
    const fallback = byId("reference-copy-fallback");
    fallback.value = referenceReader.text;
    fallback.hidden = false;
    byId("reference-copy-fallback-label").hidden = false;
    fallback.focus();
    fallback.select();
    byId("reference-report-status").textContent = "自動コピーできません。Ctrl+Cでコピーしてください。";
  }
}

function applyReadinessFilter() {
  const selected = readinessFilters.querySelector('input[name="readiness-filter"]:checked').value;
  const englishReference = comparisonOutput.querySelector(".english-reference-details");
  if (englishReference && selected === "recorded") englishReference.open = true;
  let visible = 0;
  for (const card of comparisonOutput.querySelectorAll(".comparison-card")) {
    card.hidden = selected !== "all" && card.dataset.actionGroup !== selected;
    if (!card.hidden) visible += 1;
  }
  for (const group of comparisonOutput.querySelectorAll(".comparison-group, .english-preparation-group, .application-preparation-group")) {
    group.hidden = !Array.from(group.querySelectorAll(".comparison-card")).some((card) => !card.hidden);
  }
  filterEmpty.hidden = visible !== 0;
}

async function submitApplicantComparison() {
  if (comparisonPending || !baseRequirementsLoaded || !demoTargetComplete()) return;
  const scope = currentReferenceScope();
  if (scope?.kind === "reviewed_material_slice" && referenceReport?.kind === scope.kind
    && referenceCore.scopeKey(referenceReport.scope) === referenceCore.scopeKey(scope)
    && loadedReference && referenceCore.scopeKey(loadedReference.scope) === referenceCore.scopeKey(scope)
    && referenceReport.employment.current === byId("slice-current-employed").value
    && referenceReport.employment.retain === byId("slice-retain-employed").value) {
    referenceReport = referenceCore.withSlicePreparation(referenceReport, slicePreparationValues());
    renderSliceReadiness(referenceReport, loadedReference);
    setReferenceActionState("success", "準備状況を更新しました。確認済みの公式条件は変わりません。レポートを表示・コピーできます。", true);
    setMessage(comparisonStatus, "success", `書類${referenceReport.topics.length}項目の確認結果を使用しています。準備状況は今回の自己申告です。`);
    activateStep(4, true);
    return;
  }
  if (scope?.kind === "legacy_applicant" && !applicationDatesReconcile()) {
    byId("demo-arrival-date").focus();
    return;
  }
  clearReferenceReport("本人の条件を再照合しています。前のレポートは無効になりました。");
  if (scope?.kind === "reviewed_material_slice") {
    await submitSliceComparison(scope);
    return;
  }
  const requestSnapshot = JSON.stringify(demoComparisonRequest());
  const requestId = ++comparisonRequestId;
  comparisonController = new AbortController();
  clearComparison("このケースの保存済み照合結果を読み込んでいます。");
  comparisonPending = true;
  comparisonSubmit.disabled = true;
  comparisonRetry.hidden = true;
  setMessage(comparisonStatus, "loading", "このケースの保存済み照合結果を読み込んでいます。");
  try {
    const response = await fetch(APPLICANT_COMPARISON_ENDPOINT, { method: "POST", headers: { Accept: "application/json", "Content-Type": "application/json" }, body: requestSnapshot, cache: "no-store", credentials: "same-origin", signal: comparisonController.signal });
    if (!response.ok) throw new Error();
    const payload = await response.json();
    if (!payload || !Array.isArray(payload.items) || !payload.counts
      || payload.counts.total !== payload.items.length || !baseResponse?.target
      || ["school_name", "degree_name", "intake_name", "college_name", "department_name", "application_route_name"]
        .some((field) => payload.target?.[field] !== baseResponse.target[field])) throw new Error();
    if (payload.english_preparation_result)
      referenceCore.validateEnglishPreparationResult(scope, payload);
    if (payload.application_preparation_result)
      referenceCore.validateApplicationPreparationResult(scope, payload);
    if (requestId !== comparisonRequestId || requestSnapshot !== JSON.stringify(demoComparisonRequest())) return;
    renderComparison(payload, scope);
    comparisonResponse = payload;
    setMessage(comparisonStatus, "success", "保存済みの結果を表示しました。今回の操作で審査を実行したものではありません。");
    activateStep(4, true);
  } catch (error) {
    if (error && error.name === "AbortError") return;
    if (requestId !== comparisonRequestId) return;
    clearComparison("本人情報を照合できません。入力内容をご確認のうえ、再試行してください。");
    comparisonRetry.hidden = false;
    setMessage(comparisonStatus, "error", "本人情報を照合できません。入力内容をご確認のうえ、再試行してください。", true);
  } finally {
    if (requestId === comparisonRequestId) {
      comparisonPending = false;
      comparisonController = null;
      comparisonSubmit.disabled = !baseRequirementsLoaded;
    }
  }
}

async function submitSliceComparison(scope) {
  const employment = {
    current: byId("slice-current-employed").value,
    retain: byId("slice-retain-employed").value
  };
  const snapshot = JSON.stringify([referenceCore.scopeKey(scope), employment]);
  const requestId = ++comparisonRequestId;
  comparisonController = new AbortController();
  comparisonPending = true;
  comparisonSubmit.disabled = true;
  clearComparison("対象書類の在職条件を照合しています。");
  setMessage(comparisonStatus, "loading", "対象書類の在職条件を照合しています。");
  try {
    const response = await fetch(`/v1/reference-slices/${encodeURIComponent(scope.entry_id)}/reports`, {
      method: "POST", headers: {Accept: "application/json", "Content-Type": "application/json"},
      body: JSON.stringify(referenceCore.sliceReportRequest(scope, employment)),
      cache: "no-store", credentials: "same-origin", signal: comparisonController.signal
    });
    if (!response.ok) throw new Error();
    const payload = await response.json();
    if (requestId !== comparisonRequestId || snapshot !== JSON.stringify([
      referenceCore.scopeKey(currentReferenceScope()),
      {current: byId("slice-current-employed").value, retain: byId("slice-retain-employed").value}
    ])) return;
    const report = referenceCore.sliceReport(scope, loadedReference, payload, employment,
      slicePreparationValues());
    renderSliceReadiness(report, loadedReference);
    referenceReport = report;
    setReferenceActionState("success", "条件の確認結果を表示しました。レポートを表示・コピーできます。", true);
    setMessage(comparisonStatus, "success", `書類${report.topics.length}項目を確認しました。必要に応じてレポートを表示・コピーできます。`);
    activateStep(4, true);
  } catch (error) {
    if (error?.name === "AbortError" || requestId !== comparisonRequestId) return;
    clearComparison("書類の条件を照合できません。入力を保持したまま再試行してください。");
    comparisonRetry.hidden = false;
    setMessage(comparisonStatus, "error", "書類の条件を照合できません。入力を保持したまま再試行してください。", true);
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
  comparisonResponse = null;
  clearReferenceReport();
  clearComparison(message);
}

async function submitBaseRequirements() {
  if (requirementsPending || !demoTargetComplete()) return;
  discardEvidenceDrawer();
  const scope = currentReferenceScope();
  if (!scope) return;
  activateStep(1);
  const requestSnapshot = referenceCore.scopeKey(scope);
  const requestId = ++requirementsRequestId;
  requirementsController = new AbortController();
  baseRequirementsLoaded = false;
  loadedReference = null;
  baseResponse = null;
  comparisonResponse = null;
  clearReferenceReport("志望先を読み込んでいます。要件の読み込み後にレポートを作成できます。");
  clearGroundedAnswer("基本要件を更新しています。");
  updateGroundedContext();
  invalidateComparison("基本要件を更新しています。");
  clearDemoResults("保存済みの基本要件を読み込んでいます。");
  requirementsPending = true;
  updateRequirementsSubmit();
  requirementsRetry.hidden = true;
  setMessage(targetStatus, "loading", "確認済みの条件と公式資料を照合しています。");
  try {
    const response = scope.kind === "legacy_applicant"
      ? await fetch(`${BASE_REQUIREMENTS_ENDPOINT}?include_examination_information=true${scope.request.school_id === "isct" ? "&exam_presentation_version=2" : ""}`, { method: "POST", headers: { Accept: "application/json", "Content-Type": "application/json" }, body: JSON.stringify(scope.request), cache: "no-store", credentials: "same-origin", signal: requirementsController.signal })
      : await fetch(`/v1/reference-slices/${encodeURIComponent(scope.entry_id)}/evidence`, { method: "GET", headers: { Accept: "application/json" }, cache: "no-store", credentials: "same-origin", signal: requirementsController.signal });
    if (!response.ok) throw new Error();
    const payload = await response.json();
    const mapped = scope.kind === "legacy_applicant"
      ? referenceCore.mapLegacyBase(scope, payload) : referenceCore.mapSliceEvidence(scope, payload);
    if (requestId !== requirementsRequestId || referenceCore.scopeKey(currentReferenceScope()) !== requestSnapshot) return;
    const exam = scope.kind === "legacy_applicant"
      ? referenceCore.validateExamInformation(scope, payload.examination_information) : null;
    if (scope.kind === "legacy_applicant") renderRequirements(payload, scope, exam);
    else renderSliceRequirements(mapped);
    loadedReference = mapped;
    if (scope.kind === "legacy_applicant") loadedReference.exam = exam;
    baseResponse = payload;
    refreshMaterialInputLabels(scope);
    baseRequirementsLoaded = true;
    requirementsEverLoaded = true;
    comparisonSubmit.disabled = false;
    setReferenceActionState("initial", "要件を読み込みました。ここからレポートを作成・コピーできます。", true);
    clearComparison();
    clearGroundedAnswer("選択した志望先と本人情報について質問できます。");
    updateGroundedContext();
    setMessage(targetStatus, "success", "基本要件を読み込みました。各項目の公式資料をご確認ください。");
    activateStep(2, true);
  } catch (error) {
    if (error && error.name === "AbortError") return;
    if (requestId !== requirementsRequestId) return;
    clearDemoResults("基本要件を読み込めません。");
    loadedReference = null;
    baseResponse = null;
    clearReferenceReport("要件が未読み込みのため、レポートを作成できません。");
    requirementsRetry.hidden = false;
    setMessage(targetStatus, "error", "基本要件を読み込めません。選択内容をご確認のうえ再試行してください。", true);
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
  discardEvidenceDrawer();
  cancelPendingRequirements();
  baseRequirementsLoaded = false;
  loadedReference = null;
  baseResponse = null;
  comparisonResponse = null;
  clearReferenceReport();
  invalidateComparison("志望先が変更されました。基本要件を読み込み直してください。");
  clearDemoResults("志望先が変更されました。選択を完了し、要件を読み込み直してください。");
  resetApplicantInputs();
  clearGroundedAnswer("志望先が変更されました。基本要件を読み込み直してから質問してください。");
  updateGroundedContext();
  requirementsRetry.hidden = true;
  setMessage(targetStatus, "initial", "志望先が変更されました。選択を完了し、要件を読み込み直してください。");
  activateStep(1);
  next();
  updateProfileCapability();
}

targetForm.addEventListener("submit", (event) => { event.preventDefault(); submitBaseRequirements(); });
applicantForm.addEventListener("submit", (event) => { event.preventDefault(); submitApplicantComparison(); });
applicantForm.addEventListener("input", (event) => {
  if (event.target.matches("[data-slice-material-code]")) {
    refreshSlicePreparation();
    return;
  }
  updateProfileGroupStates();
  updateEnglishInputHint();
  applicationDatesReconcile();
  invalidateComparison("本人情報が変更されました。再照合してください。");
  clearGroundedAnswer("本人情報が変更されました。次回は最新の入力内容を使用します。");
  updateGroundedContext();
  if (baseRequirementsLoaded) activateStep(3);
});
applicantForm.addEventListener("change", () => {
  updateProfileGroupStates();
  updateEnglishInputHint();
  updateEnglishProofVisibility();
  updateApplicationPreparationVisibility();
  applicationDatesReconcile();
});
let previousCompletionState = byId("demo-completion-state").value;
byId("demo-completion-state").addEventListener("change", () => {
  const state = byId("demo-completion-state").value;
  if (state !== previousCompletionState) {
    byId("demo-completion-date").value = "";
    byId("demo-expected-completion-date").value = "";
    previousCompletionState = state;
  }
  updateApplicationPreparationVisibility();
  updateProfileGroupStates();
});
let previousCredentialBasis = byId("demo-credential-basis").value;
byId("demo-credential-basis").addEventListener("change", () => {
  const basis = byId("demo-credential-basis").value;
  if (basis !== previousCredentialBasis) {
    byId("demo-review-status").value = "";
    previousCredentialBasis = basis;
  }
  updateApplicationPreparationVisibility();
  updateProfileGroupStates();
});
let previousEnglishKind = byId("demo-english-kind").value;
byId("demo-english-kind").addEventListener("change", () => {
  const kind = byId("demo-english-kind").value;
  if (kind !== previousEnglishKind) {
    for (const id of ["demo-english-score", "demo-english-date", "demo-english-report", ...englishProofControls])
      byId(id).value = "";
    previousEnglishKind = kind;
    updateEnglishInputHint();
    updateEnglishProofVisibility();
  }
});
comparisonRetry.addEventListener("click", submitApplicantComparison);
readinessFilters.addEventListener("change", applyReadinessFilter);
requirementsContinue.addEventListener("click", () => {
  if (baseRequirementsLoaded) activateStep(3, true);
});
editTarget.addEventListener("click", () => activateStep(1, true));
changeSchool.addEventListener("click", () => activateStep(1, true));
editRequirements.addEventListener("click", () => activateStep(2, true));
editApplicant.addEventListener("click", () => { resetChecklistProgress(); activateStep(3, true); });
schoolSelect.addEventListener("change", () => handleDemoTargetChange(populateDegreeSelect));
demoDegreeSelect.addEventListener("change", () => handleDemoTargetChange(populateIntakeSelect));
intakeSelect.addEventListener("change", () => handleDemoTargetChange(populateCollegeSelect));
collegeSelect.addEventListener("change", () => handleDemoTargetChange(populateDepartmentSelect));
departmentSelect.addEventListener("change", () => handleDemoTargetChange(populateRouteSelect));
routeSelect.addEventListener("change", () => handleDemoTargetChange(updateRequirementsSubmit));
requirementsRetry.addEventListener("click", () => { if (demoCatalog.length) submitBaseRequirements(); else loadDemoCatalog(); });
groundedQuestion.addEventListener("input", () => {
  groundedQuestionCount.textContent = `${groundedQuestion.value.length} / ${MAX_QUERY_LENGTH}`;
});
groundedForm.addEventListener("submit", (event) => { event.preventDefault(); submitGroundedAnswer(); });
groundedRetry.addEventListener("click", () => { if (groundedCanRetry) submitGroundedAnswer(); });
referenceButtons.forEach((button) => button.addEventListener("click", generateReferenceReport));
byId("reference-copy").addEventListener("click", copyReferenceReport);
byId("reference-close").addEventListener("click", () => {
  cancelPendingReferenceComparison();
  referenceDialog.close();
});
referenceDialog.addEventListener("cancel", cancelPendingReferenceComparison);
referenceDialog.addEventListener("close", () => {
  cancelPendingReferenceComparison();
  if (referenceTrigger?.isConnected && !referenceTrigger.disabled && referenceReport
    && currentReferenceScope() && referenceCore.scopeKey(referenceReport.scope)
      === referenceCore.scopeKey(currentReferenceScope())) referenceTrigger.focus({preventScroll: true});
  referenceTrigger = null;
});
drawerClose.addEventListener("click", () => evidenceDrawer.close());
evidenceDrawer.addEventListener("close", () => {
  const scope = currentReferenceScope();
  if (drawerTrigger?.isConnected && (!drawerScopeKey || (scope
    && referenceCore.scopeKey(scope) === drawerScopeKey))) drawerTrigger.focus({preventScroll: true});
  drawerTrigger = null;
  drawerGraph = null;
  drawerScopeKey = null;
  evidenceDrawer.classList.remove("relationship-window");
});

updateFlowPresentation();
initializeProfileGroups();
clearGroundedAnswer();
updateGroundedContext();
loadGenerationStatus();
import("./unified-core.mjs").then((module) => {
  referenceCore = module;
  loadDemoCatalog();
}).catch(() => setMessage(targetStatus, "error", "対象一覧を読み込めません。ページを再読み込みしてください。"));
