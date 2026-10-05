// Compare current display/report output to exact main bytes, without product HTTP.
import assert from "node:assert/strict";
import {execFileSync} from "node:child_process";
import {readFileSync, writeFileSync, mkdtempSync, rmSync, rmdirSync} from "node:fs";
import {tmpdir} from "node:os";
import {join, resolve} from "node:path";
import {pathToFileURL, fileURLToPath} from "node:url";
import * as current from "../src/jgrad_admission_rag/service/static/unified-core.mjs";

const root = resolve(fileURLToPath(new URL("..", import.meta.url)));
const out = join(root, "docs/onboarding/m18-evidence");
const read = (name) => JSON.parse(readFileSync(join(root, "docs/onboarding", name)));
const catalog = read("author01-evidence/live-catalog.json");
const evidence = read("m18-evidence/direct-evidence.json");
const entry = catalog.items.find((row) => row.kind === "reviewed_material_slice");
const scope = current.scopesFor(entry)[0];
const temp = mkdtempSync(join(tmpdir(), "m18-before-"));
try {
  const oldPath = join(temp, "before.mjs");
  writeFileSync(oldPath, execFileSync("git", ["show", "8aa4e812:src/jgrad_admission_rag/service/static/unified-core.mjs"], {cwd: root}));
  const before = await import(pathToFileURL(oldPath));
  const oldMapped = before.mapSliceEvidence(scope, evidence);
  const newMapped = current.mapSliceEvidence(scope, evidence);
  const rows = [];
  for (const [currentValue, retain] of [["yes", "yes"], ["no", "unknown"], ["unknown", "unknown"]]) {
    const payload = read(`m18-evidence/direct-report-${currentValue}-${retain}.json`);
    // Historical core compares JSON key order; HTTP canonicalizes these keys.
    payload.report.target = evidence.target;
    const employment = {current: currentValue, retain};
    const selected = {dates: false, materials: true, other: false};
    for (const state of ["unknown", "available", "not_yet"]) {
      const preparation = {"application-essay": state};
      const oldReport = before.sliceReport(scope, oldMapped, payload, employment, preparation);
      const newReport = current.sliceReport(scope, newMapped, payload, employment, preparation);
      const oldText = before.readerReport(oldReport, selected).text;
      const newText = current.readerReport(newReport, selected).text;
      assert.equal(newText, oldText);
      if (state === "not_yet") {
        writeFileSync(join(out, `before-${currentValue}-${retain}-copy.txt`), oldText + "\n");
        writeFileSync(join(out, `after-${currentValue}-${retain}-copy.txt`), newText + "\n");
      }
      rows.push({employment: [currentValue, retain], preparation: state,
        copied_text_byte_identical: true, method: "same_real_source_direct_projection_in_old_and_new_core", actual_product_post: 0});
    }
  }
  const displays = oldMapped.topics.map((topic) => {
    const a = before.materialDisplay(scope, topic.id, topic.title);
    const b = current.materialDisplay(scope, topic.id, topic.title);
    assert.deepEqual(a, b);
    const oldGuide = before.materialGuide(scope, topic);
    const newGuide = current.materialGuide(scope, topic);
    if (oldGuide) for (const field of ["purpose", "steps", "warnings", "conditions"]) assert.deepEqual(newGuide[field], oldGuide[field]);
    return {id: topic.id, before: a, after: b, author_guide_byte_identical: true,
      source_note_change: oldGuide ? "sourceNote now derives complete official titles/pages, body and rules unchanged" : null};
  });
  writeFileSync(join(out, "before-after-journal.json"), JSON.stringify({baseline: "8aa4e812f4e8c5e1483161e6c5074d224d67feb3", displays, reports: rows}, null, 2) + "\n");
  process.stdout.write("Four displays and nine report projections match exact main; zero HTTP\n");
} finally {
  rmSync(join(temp, "before.mjs"), {force: true});
  rmdirSync(temp);
}
