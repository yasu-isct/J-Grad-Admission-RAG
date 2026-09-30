/* Compare the old and new report projection using the same saved real HTTP responses. */
import {execFileSync} from "node:child_process";
import {createHash} from "node:crypto";
import {readFileSync, writeFileSync} from "node:fs";
import {fileURLToPath} from "node:url";
import {resolve} from "node:path";

const tree = resolve(fileURLToPath(new URL("../..", import.meta.url)));
const evidence = resolve(tree, "docs/onboarding/prep01-evidence");
const source = "src/jgrad_admission_rag/service/static/unified-core.mjs";
const original = execFileSync("git", ["show", `origin/main:${source}`], {cwd: tree, encoding: "utf8"});
const before = await import(`data:text/javascript;base64,${Buffer.from(original).toString("base64")}`);
const after = await import(new URL(`../../${source}`, import.meta.url));
const read = (name) => readFileSync(resolve(evidence, name));
const catalog = JSON.parse(read("reference-targets.json"));
const base = JSON.parse(read("isct-base.json"));
const comparison = JSON.parse(read("isct-comparison.json"));
const scope = after.scopesFor(after.readyEntries(catalog).find((entry) => entry.entry_id === "legacy-isct"))
  .find((item) => item.request.document_id === "isct_2027_4_2026_9_master"
    && item.request.college_id === "情報理工学院"
    && item.request.department_id === "情報工学系"
    && item.request.intake.month === 4 && item.request.application_route === "b_schedule");
if (!scope) throw new Error("Saved real target absent from catalog");
const chosen = {dates: false, materials: true, other: false};
const hash = (bytes) => createHash("sha256").update(bytes).digest("hex");
const results = {};
for (const [label, core] of [["before", before], ["after", after]]) {
  const mapped = core.mapLegacyBase(scope, base);
  const report = core.legacyReport(mapped, comparison);
  const copy = core.readerReport(report, chosen).text;
  writeFileSync(resolve(evidence, `${label}-materials-copy.txt`), `${copy}\n`, "utf8");
  results[label] = {copy_sha256: hash(Buffer.from(copy)), chars: copy.length};
}
const desktop = read("desktop-materials-copy.txt").toString("utf8").replace(/\r/g, "").trimEnd();
if (desktop !== read("after-materials-copy.txt").toString("utf8").trimEnd())
  throw new Error("New projection differs from browser clipboard");
results.saved_response_hashes = {
  catalog: hash(read("reference-targets.json")),
  base: hash(read("isct-base.json")),
  comparison: hash(read("isct-comparison.json")),
};
writeFileSync(resolve(evidence, "copy-comparison.json"), `${JSON.stringify(results, null, 2)}\n`);
console.log(JSON.stringify(results, null, 2));
