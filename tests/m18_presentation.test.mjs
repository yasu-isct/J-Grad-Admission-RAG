import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import test from "node:test";
import {scopesFor, mapSliceEvidence, materialDisplay, materialGuide,
  slicePreparationControls, sliceReport, readerReport} from "../src/jgrad_admission_rag/service/static/unified-core.mjs";

const read = (name) => JSON.parse(readFileSync(new URL(`../docs/onboarding/author01-evidence/${name}`, import.meta.url)));
const catalog = read("live-catalog.json");
const entry = catalog.items.find((row) => row.kind === "reviewed_material_slice");
const scope = scopesFor(entry)[0];
const evidence = read("live-evidence.json");

test("four real topics share generated displays, full context, and only one self-report control", () => {
  const mapped = mapSliceEvidence(scope, evidence);
  assert.deepEqual(mapped.topics.map((topic) => materialDisplay(scope, topic.id, topic.title).name),
    ["英语成绩单", "提交材料检查表", "学业与职务兼顾计划书", "申请小论文"]);
  assert.equal(mapped.topics.flatMap((topic) => topic.sources).length, 10);
  assert.deepEqual(slicePreparationControls(mapped), [{id: "application-essay", name: "申请小论文", type: "self_report_tri_state"}]);
  assert.deepEqual(mapped.topics.map((topic) => Boolean(materialGuide(scope, topic))), [false, false, false, true]);
  const report = sliceReport(scope, mapped, read("live-desktop-report.json"));
  const text = readerReport(report, {dates: false, materials: true, other: false}).text;
  assert.match(text, /无需提交/);
  assert.match(text, /不表示免除英语相关考查|英语/);
  assert.match(text, /不是完整清单/);
});

test("all 37 fragments and every identity/source field are guarded", () => {
  for (const topic of evidence.topics) for (const record of topic.records) {
    for (const fragment of record.fragments) {
      const changed = structuredClone(evidence);
      const row = changed.topics.find((t) => t.topic_id === topic.topic_id).records.find((r) => r.record_id === record.record_id);
      row.fragments = row.fragments.filter((f) => f.fragment_id !== fragment.fragment_id);
      assert.throws(() => mapSliceEvidence(scope, changed));
    }
    for (const [field, value] of [["source_id", "wrong"], ["physical_page", 2], ["role", "wrong"],
      ["stage", "wrong"], ["printed_page_label", "wrong"], ["official_heading_path", []]]) {
      const changed = structuredClone(evidence);
      const row = changed.topics.find((t) => t.topic_id === topic.topic_id).records.find((r) => r.record_id === record.record_id);
      row[field] = value;
      assert.throws(() => mapSliceEvidence(scope, changed));
    }
  }
  const duplicate = structuredClone(evidence);
  duplicate.topics[1] = duplicate.topics[0];
  assert.throws(() => mapSliceEvidence(scope, duplicate));
  const missingRelation = structuredClone(evidence);
  missingRelation.topics[0].relations = [];
  assert.throws(() => mapSliceEvidence(scope, missingRelation));
  const wrong = {...scope, item: {...scope.item, snapshot_id: "0".repeat(64)}};
  assert.throws(() => mapSliceEvidence(wrong, evidence));
  assert.equal(materialDisplay(wrong, "application-essay", "原名").verified, false);
});
