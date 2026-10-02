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
