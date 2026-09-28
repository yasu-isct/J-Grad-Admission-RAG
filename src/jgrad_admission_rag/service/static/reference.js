"use strict";

const element = (id) => document.getElementById(id);
const selector = element("reference-select");
const employment = element("employment-select");
const retain = element("retain-select");
const generate = element("generate-report");
const copy = element("copy-report");
let entries = [];
let selected = null;
let evidence = null;
let currentReport = null;
let generation = 0;
let pending = null;
let browsing = null;

function node(tag, content, className) {
  const result = document.createElement(tag);
  result.textContent = content;
  if (className) result.className = className;
  return result;
}

function validOfficialUrl(raw) {
  try {
    const url = new URL(raw);
    return url.protocol === "https:" && !url.username && !url.password ? url.href : null;
  } catch { return null; }
}

function description(item) {
  const target = item.target;
  if (!target) return item.institution_name;
  const degree = target.degree_level === "master" ? "修士" : target.degree_level;
  const route = target.selection_route_id === "general-ordinary" ? "一般选拔" : target.selection_route_id;
  return `${item.institution_name}／${item.organization_name}／${item.program_name}／${target.admission_cycle}年度${degree}／${route} ${target.examination_schedule_id} 日程／${target.intake.year}年${target.intake.month}月入学`;
}

function condition(value) { return value === "yes" ? true : value === "no" ? false : null; }
function conditionLabel(value) { return value === "yes" ? "是" : value === "no" ? "否" : "未知"; }

function invalidate() {
  generation += 1;
  if (pending) pending.abort();
  pending = null;
  currentReport = null;
  element("report-output").hidden = true;
  element("report-summary").replaceChildren();
  element("copy-fallback").hidden = true;
  element("copy-fallback-label").hidden = true;
  element("copy-fallback").value = "";
  element("copy-status").textContent = "";
  element("report-status").textContent = "";
  generate.disabled = false;
}

function resetSelection() {
  invalidate();
  if (browsing) browsing.abort();
  browsing = null;
  evidence = null;
  selected = entries.find((item) => item.entry_id === selector.value) || null;
  employment.value = "unknown";
  retain.value = "unknown";
  element("capability-panel").hidden = !selected;
  element("evidence-panel").hidden = true;
  element("report-panel").hidden = true;
  element("capability-detail").replaceChildren();
  element("evidence-topics").replaceChildren();
  if (!selected) return;
  const detail = element("capability-detail");
  detail.append(node("p", description(selected)));
  if (selected.kind === "legacy_applicant") {
    detail.append(node("p", "已审核的申请检查流程可在原入口使用；此页不会自动运行对照或报告。"));
    const link = node("a", "打开申请检查");
    link.href = selected.href === "/app" ? "/app" : "/app";
    detail.append(link);
    return;
  }
  if (selected.availability !== "ready") {
    detail.append(node("p", "此审核切片当前不可用。", "reference-limit"));
    return;
  }
  detail.append(node("p", `固定快照 ${selected.snapshot_id}；计划修订 ${selected.revision}。重启服务后才会读取新的本地源文件。`, "reference-meta"));
  for (const limit of selected.limitations_zh || []) detail.append(node("p", limit, "reference-limit"));
  element("report-panel").hidden = false;
  loadEvidence(selected);
}

async function loadEvidence(item) {
  const sequence = generation;
  const controller = new AbortController();
  browsing = controller;
  element("reference-status").textContent = "正在读取已审核的官方依据";
  try {
    const response = await fetch(`/v1/reference-slices/${encodeURIComponent(item.entry_id)}/evidence`, {signal: controller.signal});
    if (!response.ok) throw new Error("evidence unavailable");
    const payload = await response.json();
    if (sequence !== generation || item !== selected || payload.snapshot_id !== item.snapshot_id) return;
    evidence = payload;
    renderEvidence(payload);
    element("evidence-panel").hidden = false;
    element("reference-status").textContent = `已加载 ${payload.topics.length} 个材料主题的官方依据；浏览不会生成报告。`;
  } catch (error) {
    if (error.name !== "AbortError" && sequence === generation) element("reference-status").textContent = "官方依据暂时不可用。";
  } finally { if (browsing === controller) browsing = null; }
}

function renderEvidence(payload) {
  const host = element("evidence-topics");
  host.replaceChildren();
  for (const topic of payload.topics) {
    const section = node("section", "");
    section.append(node("h3", topic.material_name_zh));
    section.append(node("p", topic.context_note_zh));
    for (const record of topic.records) {
      const details = node("details", "");
      const role = record.role === "basis" ? "本条依据" : "关联上下文";
      const stage = record.stage === "enrollment_context_only" ? "／入学手续关联" : "";
      details.append(node("summary", `${role}${stage} · ${record.source_title} · 物理页 ${record.physical_page}${record.printed_page_label ? `（印刷页 ${record.printed_page_label}）` : ""}`));
      details.append(node("p", record.scope_note_zh));
      details.append(node("p", record.official_heading_path.join(" › ")));
      for (const fragment of record.fragments) {
        details.append(node("p", `片段：${fragment.fragment_role}`, "reference-meta"));
        details.append(node("blockquote", fragment.quote_text));
      }
      const href = validOfficialUrl(record.official_source_url);
      if (href) {
        const link = node("a", "打开官方来源（页码跳转视浏览器而定）");
        link.href = `${href}#page=${record.physical_page}`;
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        details.append(link);
      }
      section.append(details);
    }
    host.append(section);
  }
}

function requestBody(item) {
  const target = item.target;
  const aliases = item.request_profile_target;
  return {
    schema_version: "1.0", target,
    applicant_profile: {
      schema_version: "1.0",
      target_application: {
        graduate_school_or_college: aliases.graduate_school_or_college,
        department_or_program: aliases.department_or_program,
        requested_degree_level: target.degree_level,
        intake_year: target.intake.year, intake_month: target.intake.month,
        application_route: aliases.application_route,
      },
      citizenship_and_residence: {citizenship_country_codes: null, current_residence_country_code: null, residence_status_category: null},
      academic_credentials: null,
      eligibility_facts: {age_at_enrollment: null, professional_experience_months: null, research_experience_months: null, individual_review_status: null, individual_review_requested: null, individual_review_completed: null},
      language_test_results: null, application_submission: null, preapplication_actions: null,
    },
    employment: {currently_employed_in_organization: condition(employment.value), retain_employment_at_enrollment: condition(retain.value)},
  };
}

function renderReport(item, payload, employed, retained) {
  const host = element("report-summary");
  host.replaceChildren();
  host.append(node("h3", description(item)));
  host.append(node("p", `本次条件：目前受雇 ${conditionLabel(employed)}；入学后继续任职 ${conditionLabel(retained)}。`));
  const names = {submission_required: "需要提交", submission_not_required: "无需提交（仅此材料本身）", rule_not_applicable: "本条条件不适用，不能推定一般性免交", needs_information: "信息不足"};
  const fields = {"employment.currently_employed_in_organization": "目前是否受雇于单位", "employment.retain_employment_at_enrollment": "入学后是否继续在该单位任职"};
  if (payload.report.status !== "evaluated") host.append(node("p", "当前目标或申请信息不在本审核范围内，未生成材料结论。"));
  for (const result of payload.report.topic_results) {
    host.append(node("h4", result.material_name_zh));
    host.append(node("p", names[result.disposition] || result.disposition));
    host.append(node("p", result.explanation_zh));
    if (result.missing_fields.length) host.append(node("p", `待明确：${result.missing_fields.map((field) => fields[field] || field).join("、")}`));
  }
  host.append(node("p", `完整官方引用、页码及历史范围限制见下方可复制的原报告。`, "reference-limit"));
  host.append(node("pre", payload.markdown, "reference-report-text"));
  const textarea = element("copy-fallback");
  textarea.value = `${description(item)}\n本次条件：目前受雇 ${conditionLabel(employed)}；入学后继续任职 ${conditionLabel(retained)}。\n\n${payload.markdown}`;
  element("report-output").hidden = false;
}

async function submitReport() {
  if (!selected || selected.kind !== "reviewed_material_slice" || selected.availability !== "ready" || generate.disabled) return;
  invalidate();
  const item = selected;
  const employed = employment.value;
  const retained = retain.value;
  const sequence = generation;
  const controller = new AbortController();
  pending = controller;
  generate.disabled = true;
  element("report-status").textContent = "正在生成参考报告";
  try {
    const response = await fetch(`/v1/reference-slices/${encodeURIComponent(item.entry_id)}/reports`, {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify(requestBody(item)), signal: controller.signal,
    });
    if (!response.ok) throw new Error("report unavailable");
    const payload = await response.json();
    if (sequence !== generation || item !== selected || employed !== employment.value || retained !== retain.value || payload.snapshot_id !== item.snapshot_id) return;
    currentReport = payload;
    renderReport(item, payload, employed, retained);
    element("report-status").textContent = "参考报告已生成，可复制。";
  } catch (error) {
    if (error.name !== "AbortError" && sequence === generation) element("report-status").textContent = "报告生成失败；如需重试，请再次点击生成。";
  } finally {
    if (pending === controller) pending = null;
    if (sequence === generation) generate.disabled = false;
  }
}

async function copyReport() {
  if (!currentReport || element("report-output").hidden) return;
  const value = element("copy-fallback").value;
  try {
    await navigator.clipboard.writeText(value);
    element("copy-status").textContent = "已复制完整参考报告。";
  } catch {
    element("copy-status").textContent = "无法自动复制；请从下方文本框手动选择并复制。";
    element("copy-fallback-label").hidden = false;
    element("copy-fallback").hidden = false;
    element("copy-fallback").focus();
    element("copy-fallback").select();
  }
}

selector.addEventListener("change", resetSelection);
employment.addEventListener("change", invalidate);
retain.addEventListener("change", invalidate);
generate.addEventListener("click", submitReport);
copy.addEventListener("click", copyReport);

async function start() {
  try {
    const response = await fetch("/v1/reference-targets");
    if (!response.ok) throw new Error("catalog unavailable");
    const payload = await response.json();
    entries = payload.items;
    selector.replaceChildren(node("option", "请选择学校与能力"));
    selector.firstChild.value = "";
    for (const item of entries) {
      const option = node("option", item.institution_name + (item.program_name ? `／${item.program_name}` : ""));
      option.value = item.entry_id;
      option.disabled = item.availability !== "ready";
      selector.append(option);
    }
    selector.disabled = false;
    element("reference-status").textContent = entries.length ? "请选择一个可用的学校能力。" : "当前没有可用的审核能力。";
  } catch { element("reference-status").textContent = "能力目录暂时不可用。"; }
}

start();
