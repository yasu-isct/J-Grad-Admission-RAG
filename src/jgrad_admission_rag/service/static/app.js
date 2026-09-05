"use strict";

const CATALOG_ENDPOINT = "/v1/reviewed-documents";
const QUERY_ENDPOINT = "/v1/corpus/query";
const MAX_QUERY_LENGTH = 1000;
const TOP_K = 5;
const CANDIDATE_K = 20;

const form = document.getElementById("evidence-form");
const documentSelect = document.getElementById("document-select");
const documentDetail = document.getElementById("document-detail");
const queryInput = document.getElementById("query-input");
const queryCount = document.getElementById("query-count");
const submitButton = document.getElementById("submit-button");
const retryButton = document.getElementById("retry-button");
const statusMessage = document.getElementById("status-message");
const evidenceList = document.getElementById("evidence-list");
const resultCount = document.getElementById("result-count");

let catalogItems = [];
let lastAction = "catalog";

function setStatus(state, message, focus = false) {
  statusMessage.dataset.state = state;
  statusMessage.textContent = message;
  statusMessage.hidden = false;
  if (focus) {
    statusMessage.focus();
  }
}

function clearResults() {
  evidenceList.replaceChildren();
  resultCount.textContent = "";
  resultCount.hidden = true;
}

function setBusy(busy) {
  documentSelect.disabled = busy || catalogItems.length === 0;
  queryInput.disabled = busy || catalogItems.length === 0;
  submitButton.disabled = busy || catalogItems.length === 0;
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
    return;
  }
  const categoryLabels = {
    eligibility: "出願資格",
    documents: "提出書類",
    application_dates: "出願日程",
    fees: "費用",
    language_tests: "語学試験",
    selection_exams: "選抜試験",
    results: "結果発表",
    enrollment: "入学手続",
    contacts_forms: "連絡先・様式",
    department_requirements: "系・コース要件"
  };
  const categories = item.covered_categories
    .map((category) => categoryLabels[category] || category)
    .join("、");
  documentDetail.textContent = `部分的な審査済み規則 | 対象: ${categories} | ${item.limitation_statement}`;
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

function publicErrorMessage(status, code) {
  if (status === 422 || code === "invalid_request") {
    return "入力内容を確認して、もう一度検索してください。";
  }
  if (status === 404) {
    return "選択した募集要項が見つかりません。募集要項を選び直してください。";
  }
  if (status === 409) {
    return "募集要項の状態が更新されました。再読み込みして選び直してください。";
  }
  if (status === 503) {
    return "検索サービスを利用できません。しばらく待って再試行してください。";
  }
  return "検索を完了できませんでした。再試行してください。";
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
    const response = await fetch(CATALOG_ENDPOINT, {
      method: "GET",
      headers: { Accept: "application/json" },
      cache: "no-store",
      credentials: "same-origin"
    });
    if (!response.ok) {
      const code = await safeErrorCode(response);
      throw { publicMessage: publicErrorMessage(response.status, code) };
    }
    const payload = await response.json();
    if (!payload || !Array.isArray(payload.items)) {
      throw { publicMessage: "募集要項一覧を確認できませんでした。再試行してください。" };
    }
    populateCatalog(payload.items);
  } catch (error) {
    catalogItems = [];
    documentSelect.replaceChildren();
    setBusy(false);
    retryButton.hidden = false;
    const message = error && typeof error.publicMessage === "string"
      ? error.publicMessage
      : "募集要項一覧を読み込めませんでした。再試行してください。";
    setStatus("error", message, true);
  }
}

function searchRequest(item, query) {
  return {
    schema_version: "1.0",
    selection: {
      schema_version: "1.0",
      document_ids: [item.identity.document_id],
      institution_ids: [],
      document_family_ids: [],
      degree_levels: [],
      intake_terms: [],
      version_mode: item.version_classification === "historical" ? "historical_only" : "active_only",
      allow_multiple_documents: false
    },
    search: {
      query,
      top_k: TOP_K,
      candidate_k: CANDIDATE_K,
      metadata_filter: {
        fact_types: [],
        scope_types: [],
        scope_targets: [],
        parent_colleges: []
      },
      scope_preference: {
        preferred_scope_targets: [],
        preferred_parent_colleges: []
      }
    }
  };
}

function pageCitation(hit) {
  const pages = hit.source_pages;
  const pageLabel = pages.length === 1 ? `p.${pages[0]}` : `pp.${pages.join(", ")}`;
  return `[${hit.key.fact_id}, ${pageLabel}]`;
}

function score(value) {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric.toFixed(4) : "-";
}

function channelText(hit) {
  const details = [];
  if (hit.matched_channels.includes("vector")) {
    details.push(`vector #${hit.vector_rank} (${score(hit.vector_score)})`);
  }
  if (hit.matched_channels.includes("lexical")) {
    details.push(`lexical #${hit.lexical_rank} (${score(hit.lexical_score)})`);
  }
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
  const scopeTargets = hit.scope_targets.length > 0 ? hit.scope_targets.join(" / ") : "指定なし";
  const parent = hit.parent_college ? ` | ${hit.parent_college}` : "";
  addMetadata(metadata, "適用範囲", `${hit.scope_type} | ${scopeTargets}${parent}`);
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
  for (const hit of hits) {
    evidenceList.append(renderHit(hit));
  }
  resultCount.textContent = `${hits.length}件`;
  resultCount.hidden = false;
  setStatus("success", `${hits.length}件の根拠候補が見つかりました。`, true);
}

async function submitSearch() {
  const item = selectedCatalogItem();
  const query = queryInput.value.trim();
  if (!item) {
    setStatus("error", "募集要項を選択してください。", true);
    documentSelect.focus();
    return;
  }
  if (!query || query.length > MAX_QUERY_LENGTH) {
    setStatus("error", `質問は1文字以上${MAX_QUERY_LENGTH}文字以内で入力してください。`, true);
    queryInput.focus();
    return;
  }

  lastAction = "search";
  retryButton.hidden = true;
  clearResults();
  setBusy(true);
  setStatus("loading", "公式文書から根拠候補を検索しています。");
  try {
    const response = await fetch(QUERY_ENDPOINT, {
      method: "POST",
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json"
      },
      body: JSON.stringify(searchRequest(item, query)),
      cache: "no-store",
      credentials: "same-origin"
    });
    if (!response.ok) {
      const code = await safeErrorCode(response);
      throw { publicMessage: publicErrorMessage(response.status, code) };
    }
    const payload = await response.json();
    renderResults(payload);
  } catch (error) {
    retryButton.hidden = false;
    const message = error && typeof error.publicMessage === "string"
      ? error.publicMessage
      : "検索サービスに接続できません。再試行してください。";
    setStatus("error", message, true);
  } finally {
    setBusy(false);
  }
}

queryInput.addEventListener("input", () => {
  queryCount.textContent = `${queryInput.value.length} / ${MAX_QUERY_LENGTH}`;
});

documentSelect.addEventListener("change", updateDocumentDetail);

form.addEventListener("submit", (event) => {
  event.preventDefault();
  submitSearch();
});

retryButton.addEventListener("click", () => {
  if (lastAction === "catalog") {
    loadCatalog();
  } else {
    submitSearch();
  }
});

loadCatalog();
