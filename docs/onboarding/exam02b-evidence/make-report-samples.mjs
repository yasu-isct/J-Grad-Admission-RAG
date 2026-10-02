// Produce actual readerReport copy text from real base responses kept in memory.
import assert from "node:assert/strict";
import {readFileSync, writeFileSync} from "node:fs";
import {readyEntries, scopesFor, mapLegacyBase, validateExamInformation,
  legacyReport, readerReportOptions, readerReport} from
  "../../../src/jgrad_admission_rag/service/static/unified-core.mjs";

let payloads;
if (process.argv[2]) payloads = [JSON.parse(readFileSync(process.argv[2], "utf8"))];
else {
  const chunks = [];
  for await (const chunk of process.stdin) chunks.push(chunk);
  payloads = JSON.parse(Buffer.concat(chunks).toString("utf8"));
}
const catalog = JSON.parse(readFileSync("docs/onboarding/prep01-evidence/reference-targets.json", "utf8"));
const item = readyEntries(catalog).find((entry) => entry.entry_id === "legacy-isct");
const scopes = scopesFor(item);
const copies = [];
for (const payload of payloads) {
  const target = payload.examination_information?.target_identity;
  const scope = scopes.find((entry) => entry.request.document_id === target.document_id
    && entry.request.department_id === target.department_id
    && entry.request.intake.year === target.intake.year
    && entry.request.intake.month === target.intake.month);
  assert.ok(scope, "target absent from current catalog");
  const mapped = mapLegacyBase(scope, payload);
  const exam = validateExamInformation(scope, payload.examination_information);
  assert.equal(exam?.status, "available", `${target.department_id}: examination evidence failed`);
  const report = legacyReport(mapped, null, [], exam);
  assert.equal(readerReportOptions(report).exams, true);
  const copy = readerReport(report, {dates: false, materials: false, other: false, exams: true}).text;
  assert.ok(copy.includes("考试安排"));
  assert.ok(copy.includes("学校公布的 A 日程") && copy.includes("学校公布的 B 日程"));
  assert.ok(!copy.includes("待补材料"), "exam-only copy leaked material conclusion");
  copies.push({department_id: target.department_id, intake: target.intake, copy});
}
const sections = copies.map((row, index) =>
  `===== ${index + 1}. ${row.department_id} / ${row.intake.year}年${row.intake.month}月入学 =====\n${row.copy}`);
writeFileSync("docs/onboarding/exam02b-evidence/exam-only-report-copy-samples.txt",
  `${sections.join("\n\n")}\n`, "utf8");
process.stdout.write(`${copies.length} real-response exam-only report copies generated\n`);
