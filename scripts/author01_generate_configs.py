"""Generate AUTHOR-01 opt-in metadata without publishing or copying assets."""

from __future__ import annotations

import argparse
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

from jgrad_admission_rag.reasoning.material_conditions import MaterialConditionPolicy
from jgrad_admission_rag.reasoning.material_slice_report import MaterialSlicePlan, load_plan
from jgrad_admission_rag.reviewed_fragment_import import ImportConfig
from jgrad_admission_rag.reviewed_source_evidence import canonical_json_bytes

PREFIX = "author01-"
SEED_HASH = "96b5944a18e24cb2f65020dd3e7affb909522322ab8172ca5d9b375c56aea5ab"
POLICY_ID = "utokyo-gsfs-complex-2027-a-material-conditions-author01-v2"
PLAN_ID = "utokyo-gsfs-complex-2027-material-report-author01-v2"


def digest(raw: bytes) -> str:
    return sha256(raw).hexdigest()


def read_json(path: Path) -> dict:
    return json.loads(path.read_bytes())


def write_json(path: Path, value: dict) -> bytes:
    raw = canonical_json_bytes(value)
    path.write_bytes(raw)
    return raw


def import_metadata(docs: Path) -> dict:
    seed_raw = (docs / "author01-essay-evidence-seed-v2.json").read_bytes()
    if digest(seed_raw) != SEED_HASH:
        raise ValueError("revision-2 seed differs from design source pin")
    seed = json.loads(seed_raw)
    config = read_json(docs / "reviewed-fragment-import-v1.json")
    config.update(bundle_revision=2, bundle_sha256=SEED_HASH)
    if config["target"] != seed["target"] or config["source_set"] != seed["source_set"]:
        raise ValueError("AUTHOR-01 target/source set mismatch")
    ImportConfig.model_validate(config)
    raw = write_json(docs / f"{PREFIX}reviewed-fragment-import-v2.json", config)
    trust = dict(
        bundle_id=seed["bundle_id"],
        revision=2,
        bundle_sha256=SEED_HASH,
        import_config_sha256=digest(raw),
    )
    write_json(docs / f"{PREFIX}reviewed-fragment-import-trust-v2.json", trust)
    return trust


def binding_for(record: dict, fragment: dict, kb_hash: str) -> dict:
    return {
        "document_id": record["source_id"],
        "source_kb_sha256": kb_hash,
        "source_pdf_sha256": record["source_pdf_sha256"],
        "fact_id": f"fact:reviewed:{record['source_id']}:{record['record_id']}:r{record['revision']}:{fragment['fragment_id']}",
        "authoritative_fact_text_sha256": digest(fragment["text"].encode("utf-8")),
        "source_pages": [record["physical_page"]],
    }


def finalize_metadata(docs: Path, candidate_root: Path, pdf_dir: Path) -> dict:
    seed = read_json(docs / "author01-essay-evidence-seed-v2.json")
    authoring = read_json(docs / "author01-essay-authoring-input.json")
    if authoring["target"] != seed["target"]:
        raise ValueError("authoring target must equal the pinned seed target")
    if digest((docs / "author01-essay-evidence-seed-v2.json").read_bytes()) != SEED_HASH:
        raise ValueError("revision-2 seed differs from design source pin")
    config_raw = (docs / f"{PREFIX}reviewed-fragment-import-v2.json").read_bytes()
    candidate_raw = (candidate_root / "candidate.json").read_bytes()
    lineage_raw = (candidate_root / "lineage.json").read_bytes()
    candidate, lineage = json.loads(candidate_raw), json.loads(lineage_raw)
    if (
        candidate["build_id"] != candidate_root.name
        or lineage["build_id"] != candidate["build_id"]
        or candidate["input_descriptor"]["bundle_sha256"] != SEED_HASH
        or candidate["input_descriptor"]["import_config_sha256"] != digest(config_raw)
        or candidate["lineage_sha256"] != digest(lineage_raw)
    ):
        raise ValueError("candidate does not bind AUTHOR-01 inputs")
    files = {"candidate.json": candidate_raw, "lineage.json": lineage_raw}
    kb_hashes = {}
    for row in candidate["documents"]:
        raw = (candidate_root / row["relative_path"]).read_bytes()
        if digest(raw) != row["kb_sha256"]:
            raise ValueError("candidate KB hash mismatch")
        files[row["relative_path"]] = raw
        kb_hashes[row["document_id"]] = row["kb_sha256"]
    records = {row["record_id"]: row for row in seed["records"]}
    bindings = {
        rid: [binding_for(row, f, kb_hashes[row["source_id"]]) for f in row["fragments"]]
        for rid, row in records.items()
    }
    policy = read_json(docs / "material-condition-policy-v1.json")
    policy.update(policy_id=POLICY_ID, revision=2)
    policy["evidence_prerequisites"].update(
        bundle_revision=2,
        bundle_sha256=SEED_HASH,
        candidate_build_id=candidate["build_id"],
        candidate_manifest_sha256=digest(candidate_raw),
        lineage_sha256=digest(lineage_raw),
    )
    for document in policy["evidence_prerequisites"]["documents"]:
        document["kb_sha256"] = kb_hashes[document["source_id"]]
    for rule in policy["rules"]:
        for record in rule["required_context_records"]:
            record["required_bindings"] = bindings[record["record_id"]]
    rule = deepcopy(authoring["configuration_projection"]["condition_rule"])
    rule["required_context_records"] = [
        dict(
            record_id=rid, record_revision=records[rid]["revision"], required_bindings=bindings[rid]
        )
        for rid in ("E09", "E10")
    ]
    policy["rules"].append(rule)
    MaterialConditionPolicy.model_validate(policy)
    policy_raw = write_json(docs / f"{PREFIX}material-condition-policy-v2.json", policy)
    policy_trust_raw = write_json(
        docs / f"{PREFIX}material-condition-trust-v2.json",
        dict(policy_id=POLICY_ID, revision=2, policy_sha256=digest(policy_raw)),
    )

    plan = read_json(docs / "material-slice-report-plan-v1.json")
    plan.update(plan_id=PLAN_ID, revision=2)
    plan["candidate_reference"].update(
        build_id=candidate["build_id"],
        import_config_sha256=digest(config_raw),
        files=[dict(relative_path=name, sha256=digest(raw)) for name, raw in sorted(files.items())],
    )
    plan["policy_reference"] = dict(policy_id=POLICY_ID, revision=2, sha256=digest(policy_raw))
    plan["seed_reference"].update(revision=2, sha256=SEED_HASH)
    for source in plan["sources"]:
        source["kb_sha256"] = kb_hashes[source["source_id"]]
    for scope in plan["scope_reviews"]:
        scope["required_bindings"] = bindings[scope["record_id"]]
    sources = {row["source_id"]: row for row in plan["sources"]}
    review_images = {
        row["record_id"]: row["review_image_sha256"]
        for row in read_json(docs / "author01-source-review.json")["checks"]
    }
    for rid in ("E09", "E10"):
        record = records[rid]
        plan["scope_reviews"].append(
            {
                "record_id": rid,
                "record_revision": record["revision"],
                "source_id": record["source_id"],
                "source_role": sources[record["source_id"]]["source_role"],
                "stage": "application",
                "use": "basis",
                "physical_page": record["physical_page"],
                "printed_page_label": record["printed_page_label"],
                "manual_anchor": record["manual_anchor"],
                "official_heading_path": authoring["configuration_projection"][
                    "headings_by_record"
                ][rid],
                "required_bindings": bindings[rid],
                "review_image_sha256": review_images[rid],
                "review_status": "reviewed_for_selected_target",
                "reviewed_target_id": seed["target"]["target_id"],
                "scope_note_zh": record["review_note_zh"],
            }
        )
    plan["relations"] = deepcopy(seed["relations"])
    plan["topics"][1]["context_note_zh"] = (
        "参照清单与提交清单是两件事。本报告只核对所列材料主题，不判断材料是否全部齐全。"
    )
    plan["topics"].append(deepcopy(authoring["configuration_projection"]["plan_topic"]))
    plan["limitations_zh"][1] = (
        "只覆盖英语成绩单、检查表本身、在职计划书和申请小论文四个主题，不是完整材料清单或资格判断。"
    )
    plan["review"] = {
        "reviewer_kind": "agent",
        "reviewer_id": "design-main-agent",
        "reviewed_on": "2026-10-03",
        "status": "design_reviewed_for_teacher_slice_not_full_kb_approval",
        "image_origin": "Locked retained images cited by author01-source-review.json; old image pins retained",
        "method": "Design approved exact fixed-target fragments for isolated candidate; development assembled bindings, not implementation acceptance or activation",
    }
    MaterialSlicePlan.model_validate(plan)
    plan_raw = write_json(docs / f"{PREFIX}material-slice-report-plan-v2.json", plan)
    trust_raw = write_json(
        docs / f"{PREFIX}material-slice-report-trust-v2.json",
        dict(plan_id=PLAN_ID, revision=2, plan_sha256=digest(plan_raw)),
    )
    load_plan(
        plan_raw,
        trust_raw,
        policy_raw,
        policy_trust_raw,
        (docs / "author01-essay-evidence-seed-v2.json").read_bytes(),
    )
    fragment_rows = {
        fragment["fragment_id"]: {
            "record_id": record["record_id"],
            "source_id": record["source_id"],
            "physical_page": record["physical_page"],
            "printed_page_label": record["printed_page_label"],
            "fragment_id": fragment["fragment_id"],
            "fragment_role": fragment["role"],
            "quote_text": fragment["text"],
            "binding": binding,
        }
        for record in records.values()
        for fragment, binding in zip(
            record["fragments"], bindings[record["record_id"]], strict=True
        )
    }
    write_json(
        docs / "author01-field-source-map.json",
        {
            "artifact_role": "development-authoring-field-source-map",
            "production_enabled": False,
            "target": seed["target"],
            "seed_sha256": SEED_HASH,
            "candidate_build_id": candidate["build_id"],
            "authoring_input_sha256": digest(
                (docs / "author01-essay-authoring-input.json").read_bytes()
            ),
            "claims": [
                dict(claim, sources=[fragment_rows[fid] for fid in claim["fragment_ids"]])
                for claim in authoring["claims"]
            ],
            "all_fragment_bindings": list(fragment_rows.values()),
        },
    )
    names = {
        "plan_path": "material-slice-report-plan",
        "trust_path": "material-slice-report-trust",
        "policy_path": "material-condition-policy",
        "policy_trust_path": "material-condition-trust",
    }
    paths = {
        key: str((docs / f"{PREFIX}{name}-v2.json").resolve()).replace("\\", "/")
        for key, name in names.items()
    }
    paths.update(
        seed_path=str((docs / "author01-essay-evidence-seed-v2.json").resolve()).replace("\\", "/"),
        candidate_root=str(candidate_root.resolve()).replace("\\", "/"),
        pdf_dir=str(pdf_dir.resolve()).replace("\\", "/"),
    )
    write_json(
        docs / f"{PREFIX}reference-workspace-preview-v2.json",
        {
            "schema_version": "1.0",
            "slices": [
                {
                    "slice_id": "gsfs-complex-2027-a-author01",
                    "institution_name": "东京大学",
                    "organization_name": "新领域创成科学研究科",
                    "program_name": "複雑理工学专攻",
                    **paths,
                }
            ],
        },
    )
    return dict(
        build_id=candidate["build_id"],
        policy_sha256=digest(policy_raw),
        plan_sha256=digest(plan_raw),
        topic_count=len(plan["topics"]),
        fragment_count=sum(len(r["fragments"]) for r in records.values()),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("import", "finalize"))
    parser.add_argument(
        "--docs", type=Path, default=Path(__file__).resolve().parents[1] / "docs/onboarding"
    )
    parser.add_argument("--candidate-root", type=Path)
    parser.add_argument("--pdf-dir", type=Path)
    args = parser.parse_args()
    if args.stage == "import":
        result = import_metadata(args.docs)
    else:
        if args.candidate_root is None or args.pdf_dir is None:
            parser.error("finalize requires --candidate-root and --pdf-dir")
        result = finalize_metadata(args.docs, args.candidate_root, args.pdf_dir)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
