// Reproject saved, real UI-02 HTTP responses without starting a service or calling a model.
// Usage: node docs/onboarding/report02-replay.mjs <saved-response-directory> <output-directory>
import {createHash} from "node:crypto";
import {readFileSync, mkdirSync, writeFileSync} from "node:fs";
import {join} from "node:path";
import {
  mapLegacyBase, mapSliceEvidence, legacyReport, sliceReport, readerReport, readerReportOptions
} from "../../src/jgrad_admission_rag/service/static/unified-core.mjs";

const [sourceDir, outputDir] = process.argv.slice(2);
if (!sourceDir || !outputDir) throw new Error("Provide saved-response and output directories");
mkdirSync(outputDir, {recursive: true});
const read = (name) => JSON.parse(readFileSync(join(sourceDir, name), "utf8"));
const sha = (value) => createHash("sha256").update(value).digest("hex");
const selection = (report) => readerReportOptions(report);
const cases = [];
const save = (name, sourceNames, report, expected) => {
  const view = readerReport(report, selection(report));
  for (const state of expected) {
    if (!view.materials.some((item) => item.state === state))
      throw new Error(`${name}: expected ${state}`);
  }
  if (/物理页|record_id|snapshot_id|RULE-\d|# 原始报告|官方原文：/.test(view.text))
    throw new Error(`${name}: internal evidence leaked`);
  writeFileSync(join(outputDir, `${name}-after-copy.txt`), `${view.text}\n`, "utf8");
  cases.push({name, sources: sourceNames.map((file) => ({file, sha256: sha(readFileSync(join(sourceDir, file)))})),
    beforeCopy: {sha256: sha(report.text), length: report.text.length, excerpt: report.text.slice(0, 700)},
    afterCopy: {sha256: sha(view.text), length: view.text.length, file: `${name}-after-copy.txt`},
    materials: view.materials.map(({title, state}) => ({title, state}))});
};

const base = read("isct-base-2027.json");
const comparison = read("isct-comparison.json");
const documentId = base.requirements.flatMap((item) => item.evidence)[0].document_id;
const legacyScope = {
  entry_id: "legacy-isct", kind: "legacy_applicant", school: base.target.school_name,
  organization: base.target.college_name, program: base.target.department_name,
  degree: base.target.degree_name,
  edition: "2027 April / 2026 September Master's Program Admission Guidelines",
  intake: base.target.intake_name, route: "一般选拔", request: {document_id: documentId}
};
const mapped = mapLegacyBase(legacyScope, base);
save("isct-no-profile", ["isct-base-2027.json"], legacyReport(mapped),
  ["待填写准备情况", "待确认适用"]);
save("isct-with-profile", ["isct-base-2027.json", "isct-comparison.json"],
  legacyReport(mapped, comparison), ["待补材料", "已自报准备", "待确认适用"]);

const evidence = read("gsfs-evidence.json");
const sliceId = "gsfs-complex-2027-a";
const sliceScope = {
  entry_id: sliceId, kind: "reviewed_material_slice",
  item: {snapshot_id: evidence.snapshot_id, target: evidence.target},
  school: "东京大学", organization: "新领域创成科学研究科",
  program: "CBMS / 複雑理工学専攻", degree: "修士",
  edition: "2027 年度 · 历史资料", intake: "2027 年 4 月", route: "一般选拔 · A 日程"
};
const sliceMapped = mapSliceEvidence(sliceScope, evidence);
for (const [name, current, retain, state] of [
  ["gsfs-unknown", "unknown", "unknown", "待确认适用"],
  ["gsfs-required", "yes", "yes", "需要准备，完成情况未填写"],
  ["gsfs-inapplicable", "no", "unknown", "本条条件不适用"]
]) {
  const filename = name === "gsfs-unknown" ? "gsfs-unknown-unknown.json"
    : name === "gsfs-required" ? "gsfs-yes-yes.json" : "gsfs-no-unknown.json";
  save(name, ["gsfs-evidence.json", filename],
    sliceReport(sliceScope, sliceMapped, read(filename), {current, retain}), [state]);
}
writeFileSync(join(outputDir, "replay.json"), `${JSON.stringify({
  method: "Existing real HTTP responses revalidated by unified-core, then projected before/after",
  cases
}, null, 2)}\n`, "utf8");
