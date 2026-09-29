import assert from "node:assert/strict";
import test from "node:test";
import {
  readyEntries, scopesFor, scopeKey, comparisonRequest, hasSuppliedProfile,
  sliceReportRequest, mapLegacyBase, mapSliceEvidence, legacyReport, sliceReport,
  readerReportOptions, readerReport
} from "../src/jgrad_admission_rag/service/static/unified-core.mjs";

const legacy = {
  entry_id: "legacy-renamed", kind: "legacy_applicant", availability: "ready",
  institution_name: "改名的学校", capabilities: {evidence_browse: true, reference_report: true},
  legacy_catalog: {school_id: "renamed", school_name: "改名的学校", degrees: [{
    degree_id: "master", degree_name: "修士课程", intakes: [
      {document_id: "doc-a", year: 2027, month: 4, intake_name: "2027 年 4 月",
        colleges: [{college_id: "c", college_name: "学院", departments: [
          {department_id: "d", department_name: "专攻", application_routes: [
            {route_id: "a_schedule", route_name: "A 日程"}, {route_id: "b_schedule", route_name: "B 日程"}
          ]}
        ]}]},
      {document_id: "doc-a", year: 2026, month: 9, intake_name: "2026 年 9 月",
        colleges: [{college_id: "c", college_name: "学院", departments: [
          {department_id: "d", department_name: "专攻", application_routes: []}
        ]}]}
    ]
  }]}
};
const slice = {
  entry_id: "slice-other", kind: "reviewed_material_slice", availability: "ready",
  institution_name: "另一所学校", organization_name: "研究科", program_name: "固定专攻",
  capabilities: {evidence_browse: true, reference_report: true},
  snapshot_id: "a".repeat(64), request_profile_target: {
    graduate_school_or_college: "研究科", department_or_program: "固定专攻",
    application_route: "ordinary"
  },
  target: {target_id: "target", institution_id: "other", organization_id: "org",
    program_id: "program", degree_level: "master", admission_cycle: 2027,
    selection_route_id: "general-ordinary", examination_schedule_id: "A",
    intake: {year: 2027, month: 4}}
};
const source = {document_id: "doc-a", school_name: "改名的学校", intake_name: "2027 年 4 月",
  official_title: "官方文件", official_text: "日文官方原文", source_url: "https://example.edu/a.pdf",
  pages: [4], limitation: "只涵盖本条", highlights: [{start: 0, end: 2, exact_text: "日文"}]};
const base = {
  schema_version: "1.0", target: {school_name: "改名的学校", degree_name: "修士课程",
    intake_name: "2027 年 4 月", college_name: "学院", department_name: "专攻",
    application_route_name: "A 日程"},
  coverage_statement: "部分已审核", limitation_statement: "其他事项待核对",
  requirements: [
    {requirement_id: "date", category: "dates", title: "申请截止", description: "以到达为准",
      reviewed_summary: "RULE-05A 必须在期限内到达", official_status: "required", deadline: "2026-12-01 17:00",
      evidence: [source], date_events: [{
        label: "到达截止", display_text: "2026-12-01 17:00", precision: "minute",
        unknown_fields: ["日期备注待确认"], uncertainty_note: "时区日本", evidence: [source]
      }], limitation: "只涵盖此批次"},
    {requirement_id: "language", category: "language", title: "语言", description: "未知情况待确认",
      official_status: "needs_information", evidence: [source], date_events: [], limitation: ""}
  ]
};
const comparison = {
  schema_version: "1.0", target: base.target, comparison_statement: "保守对照",
  partial_checklist_statement: "仅供准备", limitation_statement: "仍需学校确认",
  counts: {total: 1, recorded: 0, action_required: 1, review_required: 0},
  items: [{title: "英语成绩单", comparison_status: "needs_information",
    description: "尚未提供", action_group: "action_required", next_action: "补充信息",
    official_status: "required", preparation_status: "not_yet",
    evidence: [source], limitation: "不能判定有效性"}]
};
const evidence = {
  schema_version: "1.0", snapshot_id: slice.snapshot_id, target: slice.target,
  limitations_zh: ["历史资料，仅部分材料"], topics: [{
    topic_id: "english", material_name_zh: "英语成绩单", context_note_zh: "仅材料要求",
    records: [{record_id: "record", role: "basis", stage: "application",
      source_title: "东大官方文件", physical_page: 8, printed_page_label: "7",
      official_source_url: "https://example.edu/gsfs.pdf", scope_note_zh: "固定范围",
      official_heading_path: ["申请材料"], fragments: [{quote_text: "提出が必要"}]}]
  }]
};
const report = {
  schema_version: "1.0", slice_id: slice.entry_id, snapshot_id: slice.snapshot_id,
  markdown: "# Canonical\n完整官方原文",
  report: {status: "evaluated", target: slice.target, limitations_zh: ["历史资料"],
    topic_results: [{material_name_zh: "英语成绩单", disposition: "needs_information",
      condition_status: "needs_information", explanation_zh: "条件待确认",
      missing_fields: ["employment.currently_employed_in_organization"],
      limitations_zh: ["不可推定免交"], basis_citation_keys: ["C1"], context_citation_keys: []}],
    evidence_inventory: [{citation_key: "C1", record_id: "record", quote_text: "提出が必要",
      source_title: "东大官方文件", physical_pages: [8]}]}
};

test("catalog and request mapping work for renamed schools and a second slice", () => {
  const entries = readyEntries({schema_version: "1.0", items: [legacy, slice]});
  assert.equal(entries.length, 2);
  const scopes = scopesFor(entries[0]);
  assert.equal(scopes.length, 3);
  assert.equal(scopes[0].request.document_id, "doc-a");
  assert.deepEqual(scopes[2].request.intake, {year: 2026, month: 9});
  assert.notEqual(scopeKey(scopes[0]), scopeKey(scopes[2]));
  const fixed = scopesFor(entries[1]);
  assert.equal(fixed.length, 1);
  assert.equal(fixed[0].request, null);
  assert.equal(sliceReportRequest(fixed[0], {current: "unknown", retain: "no"}).employment.retain_employment_at_enrollment, false);
  assert.equal(sliceReportRequest(fixed[0], {current: "unknown", retain: "no"}).employment.currently_employed_in_organization, null);
  assert.throws(() => readyEntries({schema_version: "1.0", items: [legacy, legacy]}));
  assert.throws(() => readyEntries({schema_version: "1.0", items: [{...legacy, capabilities: {...legacy.capabilities, reference_report: false}}]}));
});

test("full base export preserves dates, all categories, citations and optional comparison", () => {
  const scope = scopesFor(legacy)[0];
  const mapped = mapLegacyBase(scope, base);
  const noProfile = legacyReport(mapped);
  assert.match(noProfile.text, /2026-12-01 17:00/);
  assert.match(noProfile.text, /日文官方原文/);
  assert.match(noProfile.text, /语言/);
  assert.doesNotMatch(noProfile.text, /RULE-05A|ApplicantReport|类别：dates/);
  assert.match(noProfile.text, /日期：到达截止 · 2026-12-01 17:00 · 精度 minute/);
  assert.match(noProfile.text, /未知时间字段：日期备注待确认/);
  assert.match(noProfile.presentation.topics[0].lines.join(" "), /日期备注待确认/);
  assert.match(noProfile.text, /不作个人适用性判断/);
  assert.equal(hasSuppliedProfile({credential_basis: "", materials: [{code: "address_label", value: ""}]}), false);
  assert.equal(hasSuppliedProfile({credential_basis: "ui_unknown", materials: []}), true);
  const supplied = legacyReport(mapped, comparison);
  assert.match(supplied.text, /保守对照/);
  assert.match(supplied.text, /补充信息/);
  assert.match(supplied.text, /官方适用性：需要提交／满足对应条件时适用/);
  assert.match(supplied.text, /自报准备状态：尚未取得/);
  for (const item of supplied.presentation.comparison.items)
    for (const line of item.lines) assert.ok(supplied.text.includes(line));
  const request = comparisonRequest(scope, {credential_basis: "ui_unknown", english_test_kind: "toeic_lr",
    english_score: "810", materials: [{code: "address_label", value: "not_yet"}]});
  assert.equal(request.applicant.credential_basis, null);
  assert.equal(request.applicant.english_score, 810);
  assert.equal(request.applicant.materials[0].preparation, "not_yet");
  assert.throws(() => comparisonRequest(scope, {english_score: "810", materials: []}));
  assert.throws(() => mapLegacyBase(scopesFor(legacy)[1], base));
  assert.throws(() => legacyReport(mapped, {...comparison, counts: {...comparison.counts, total: 2}}));
  assert.throws(() => mapLegacyBase(scope, {...base, requirements: [{...base.requirements[0], evidence: [], date_events: []}]}));
});

test("slice evidence and canonical report keep unknown status, citation and raw Markdown", () => {
  const scope = scopesFor(slice)[0];
  const mapped = mapSliceEvidence(scope, evidence);
  assert.match(mapped.topics[0].sources[0].quote, /提出が必要/);
  assert.equal(mapped.topics[0].sources[0].printed, "7");
  const result = sliceReport(scope, mapped, report);
  assert.equal(result.topics[0].status_code, "needs_information");
  assert.match(result.text, /# Canonical/);
  assert.match(result.text, /提出が必要/);
  assert.equal(result.canonicalMarkdown, report.markdown);
  assert.throws(() => mapSliceEvidence(scope, {...evidence, snapshot_id: "b".repeat(64)}));
  assert.throws(() => sliceReport(scope, mapped, {...report, report: {...report.report, evidence_inventory: []}}));
  assert.throws(() => sliceReport(scope, mapped, {...report, snapshot_id: "b".repeat(64)}));
});

test("reader projection separates missing, self-reported ready, unfilled, and conditional materials", () => {
  const scope = scopesFor(legacy)[0];
  const required = (id, title) => ({...base.requirements[0], requirement_id: id,
    category: "materials", title, official_status: "required", date_events: []});
  const mapped = mapLegacyBase(scope, {...base, requirements: [base.requirements[0],
    required("missing", "未准备材料"), required("ready", "已有材料"),
    required("unfilled", "未填材料"),
    {...required("conditional", "条件材料"), official_status: "needs_information"}]});
  const items = [
    ["missing", "未准备材料", "required", "not_yet"],
    ["ready", "已有材料", "required", "available"],
    ["unfilled", "未填材料", "required", "unknown"],
    ["conditional", "条件材料", "needs_information", "not_yet"]
  ].map(([item_id, title, official_status, preparation_status]) => ({
    item_id, category: "materials", title, official_status, preparation_status,
    comparison_status: "needs_information", evidence: [source]
  }));
  const supplied = legacyReport(mapped, {...comparison, items,
    counts: {...comparison.counts, total: items.length}});
  const options = readerReportOptions(supplied);
  assert.deepEqual(options, {dates: true, materials: true, other: false});
  const view = readerReport(supplied, {dates: true, materials: true, other: false});
  assert.deepEqual(view.materials.map((item) => item.state),
    ["待补材料", "已自报准备", "待填写准备情况", "待确认适用"]);
  assert.ok(view.priorities.some((line) => line.includes("未准备材料：待补材料")));
  assert.ok(!view.priorities.some((line) => line.includes("已有材料")));
  assert.match(view.text, /已准备不代表有效、已提交或学校受理/);
  assert.doesNotMatch(view.text, /日文官方原文|RULE-05A|precision|record_id|物理页/);
  const onlyDates = readerReport(supplied, {dates: true, materials: false, other: false});
  assert.doesNotMatch(onlyDates.text, /未准备材料|材料准备清单/);
  const noProfile = readerReport(legacyReport(mapped), {dates: true, materials: true, other: false});
  assert.match(noProfile.text, /未填写准备情况，暂不能判断还缺哪些材料/);
  assert.ok(noProfile.materials.every((item) => item.state !== "待补材料"));
  assert.throws(() => readerReport(supplied, {dates: false, materials: false, other: false}));
});

test("slice reader projection respects conditional and non-submission results", () => {
  const scope = scopesFor(slice)[0];
  const mapped = mapSliceEvidence(scope, evidence);
  const unknown = readerReport(sliceReport(scope, mapped, report),
    {dates: false, materials: true, other: false});
  assert.match(unknown.text, /待确认适用/);
  assert.doesNotMatch(unknown.text, /# Canonical|提出が必要|物理页|record_id/);
  const requiredPayload = {...report, report: {...report.report, topic_results:
    [{...report.report.topic_results[0], disposition: "submission_required"}]}};
  const required = readerReport(sliceReport(scope, mapped, requiredPayload,
    {current: "yes", retain: "yes"}), {dates: false, materials: true, other: false});
  assert.match(required.text, /需要准备，完成情况未填写/);
  const exemptPayload = {...report, report: {...report.report, topic_results:
    [{...report.report.topic_results[0], disposition: "rule_not_applicable"}]}};
  const exempt = readerReport(sliceReport(scope, mapped, exemptPayload,
    {current: "no", retain: "unknown"}), {dates: false, materials: true, other: false});
  assert.match(exempt.text, /本条条件不适用/);
  assert.equal(exempt.materials[0].state, "本条条件不适用");
  assert.equal(exempt.priorities.length, 0);
});
