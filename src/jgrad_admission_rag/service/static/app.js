"use strict";

const CATALOG_ENDPOINT = "/v1/reviewed-documents";
const QUERY_ENDPOINT = "/v1/corpus/query";
const INTENT_ENDPOINT = "/v1/query-intents/parse";
const REPORT_ENDPOINT = "/v1/applicant-reports";
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

let catalogItems = [];
let lastAction = "catalog";
let reportPending = false;
let reportCanRetry = false;

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
      current_residence_country_code: null,
      residence_status_category: null
    },
    academic_credentials: null,
    eligibility_facts: {
      age_at_enrollment: nullableInteger("age-at-enrollment"),
      professional_experience_months: nullableInteger("professional-months"),
      research_experience_months: nullableInteger("research-months"),
      individual_review_status: nullableText("review-status"),
      individual_review_requested: nullableBoolean("review-requested"),
      individual_review_completed: nullableBoolean("review-completed")
    },
    language_test_results: null
  };
}

function validateProfile(profile) {
  if (!reportForm.checkValidity()) return "入力値の範囲と形式を確認してください。";
  const facts = profile.eligibility_facts;
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
  reportOutput.append(coverage, readiness, findings, diagnostics, evidence, finalNotice);
  setMessage(reportStatus, report.report_status, `レポート準備状態: ${statusLabel(report.report_status)} (${report.report_status})`, true);
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

queryInput.addEventListener("input", () => { queryCount.textContent = `${queryInput.value.length} / ${MAX_QUERY_LENGTH}`; });
reportQuery.addEventListener("input", () => { reportQueryCount.textContent = `${reportQuery.value.length} / ${MAX_QUERY_LENGTH}`; });
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

loadCatalog();
