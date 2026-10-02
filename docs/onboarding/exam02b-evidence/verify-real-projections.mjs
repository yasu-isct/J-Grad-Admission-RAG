// Check the real-source Python projections against current catalog scopes in JS.
// This reads a stream, and does not save or copy full KB response payloads.
import assert from "node:assert/strict";
import {readFileSync, writeFileSync} from "node:fs";
import {readyEntries, scopesFor, validateExamInformation, examReportRows, examV2View} from
  "../../../src/jgrad_admission_rag/service/static/unified-core.mjs";

const input = [];
for await (const chunk of process.stdin) input.push(chunk);
const responses = JSON.parse(Buffer.concat(input).toString("utf8"));
const catalog = JSON.parse(readFileSync("docs/onboarding/prep01-evidence/reference-targets.json", "utf8"));
const item = readyEntries(catalog).find((entry) => entry.entry_id === "legacy-isct");
const scopes = scopesFor(item);
const summary = [];
const cards = [];
for (const response of responses) {
  const target = response.target_identity;
  const scope = scopes.find((entry) => entry.request.document_id === target.document_id
    && entry.request.department_id === target.department_id
    && entry.request.intake.year === target.intake.year
    && entry.request.intake.month === target.intake.month);
  assert.ok(scope, `${target.department_id}: catalog target missing`);
  const exam = validateExamInformation(scope, response);
  assert.equal(exam?.status, "available", `${target.department_id}: frontend evidence validation failed`);
  const rows = examReportRows(exam);
  assert.ok(rows.length >= 5);
  assert.ok(rows.some((row) => row.includes("学校公布的 A 日程")));
  assert.ok(rows.some((row) => row.includes("学校公布的 B 日程")));
  const joined = rows.join("\n");
  if (["地球惑星科学系", "応用化学系", "生命理工学系"].includes(target.department_id)) {
    assert.match(rows[1], /本册覆盖课程：/);
    assert.match(rows[1], /地球生命コース采用另册，当前未覆盖/);
  }
  if (target.department_id === "情報通信系") assert.match(joined, /微积分、线性代数.*信息通信领域论述题/);
  if (target.department_id === "数学系") assert.match(joined, /第12学季课程同等程度/);
  if (target.department_id === "社会・人間科学系") assert.match(joined, /线上以日语口头问答/);
  if (target.department_id === "システム制御系") assert.match(joined, /事先准备的资料发表/);
  if (target.department_id === "地球惑星科学系") assert.match(joined, /A 日程口述.*以英语口述/);
  summary.push({department_id: target.department_id, intake: target.intake,
    written_status: exam.pathways[1].written.status,
    subject_components: exam.pathways[1].written.subjects_zh.length,
    report_rows: rows.length});
  if (target.intake.year === 2027) {
    const view = examV2View(exam);
    cards.push(`===== ${target.department_id} / 2027年4月入学 =====\n${[
      view.lead, ...view.subjects, view.selection, view.points, view.aOral,
      view.bOral, view.specialist, view.english, view.language, view.course
    ].filter(Boolean).join("\n")}`);
  }
}
assert.equal(summary.length, 36);
assert.equal(new Set(summary.map((item) => item.department_id)).size, 18);
assert.equal(cards.length, 18);
writeFileSync("docs/onboarding/exam02b-evidence/teacher-card-samples.txt", `${cards.join("\n\n")}\n`, "utf8");
writeFileSync("docs/onboarding/exam02b-evidence/projection-summary.json", `${JSON.stringify(summary, null, 2)}\n`, "utf8");
process.stdout.write("36 real-source projections validated; 18 teacher-card samples saved\n");
