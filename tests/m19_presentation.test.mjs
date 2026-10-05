import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import test from "node:test";
import {scopesFor, mapSliceEvidence, materialGuide, slicePreparationControls,
  sliceReport, readerReport, withSlicePreparation} from "../src/jgrad_admission_rag/service/static/unified-core.mjs";
import {combineMaterialCatalogs, reviewedMaterialPresentation} from "../src/jgrad_admission_rag/service/static/material-presentation-catalog.mjs";

const read = (name) => JSON.parse(readFileSync(new URL(`../docs/onboarding/m19-evidence/${name}`,import.meta.url)));
const entry = read("live-catalog.json").items.find(r=>r.kind==="reviewed_material_slice");
const scope = scopesFor(entry)[0];
const evidence = read("live-evidence.json");

test("v2 and v3 retain their guides; a duplicate catalog identity is refused",()=>{
  assert.equal(reviewedMaterialPresentation.entries.length,2);
  assert.throws(()=>combineMaterialCatalogs(reviewedMaterialPresentation,reviewedMaterialPresentation),/身份重复/);
  assert.throws(()=>combineMaterialCatalogs({schema_version:"broken",entries:[]}),/格式错误/);
  const mapped = mapSliceEvidence(scope,evidence);
  assert.equal(mapped.topics.length,5);
  assert.equal(mapped.topics.flatMap(t=>t.sources).flatMap(s=>s.fragments).length,51);
  assert.deepEqual(mapped.topics.map(t=>Boolean(materialGuide(scope,t))),[false,false,false,true,true]);
  assert.deepEqual(slicePreparationControls(mapped).map(r=>r.id),["application-essay","application-questionnaire"]);
});

test("all new fragments, table attribution, stage, relations and snapshot are guarded",()=>{
  for (const record of evidence.topics.at(-1).records) {
    for (const fragment of record.fragments) {
      const value=structuredClone(evidence);
      value.topics.at(-1).records.find(r=>r.record_id===record.record_id).fragments=
        record.fragments.filter(f=>f.fragment_id!==fragment.fragment_id);
      assert.throws(()=>mapSliceEvidence(scope,value));
    }
    for (const [field,value] of [["physical_page",3],["stage","enrollment_context_only"],["source_id","other"],["official_heading_path",[]]]) {
      const changed=structuredClone(evidence);
      changed.topics.at(-1).records.find(r=>r.record_id===record.record_id)[field]=value;
      assert.throws(()=>mapSliceEvidence(scope,changed));
    }
  }
  const missing=structuredClone(evidence); missing.topics.at(-1).relations=[];
  assert.throws(()=>mapSliceEvidence(scope,missing));
  const wrong={...scope,item:{...scope.item,snapshot_id:"0".repeat(64)}};
  assert.throws(()=>mapSliceEvidence(wrong,evidence));
});

test("self-report leaves official required results intact; empty topic selection refuses output",()=>{
  const mapped=mapSliceEvidence(scope,evidence);
  const original=sliceReport(scope,mapped,read("live-desktop-report.json"));
  for (const q of ["available","not_yet","unknown"]) for (const e of ["available","not_yet","unknown"]) {
    const result=withSlicePreparation(original,{"application-questionnaire":q,"application-essay":e});
    assert.deepEqual(result.topics,original.topics);
    assert.deepEqual(result.raw,original.raw);
    assert.equal(result.topics.at(-1).status_code,"submission_required");
    assert.equal(result.topics.at(-2).status_code,"submission_required");
    const included=readerReport(result,{dates:false,materials:true,other:false}).text;
    assert.match(included,/报考志愿调查表/); assert.match(included,/第4志愿/);
    assert.throws(()=>readerReport(result,{dates:false,materials:false,other:false}),/至少选择/);
  }
  assert.throws(()=>withSlicePreparation(original,{"application-questionnaire":true}));
  const stale=read("live-desktop-report.json"); stale.snapshot_id="0".repeat(64);
  assert.throws(()=>sliceReport(scope,mapped,stale));
});
