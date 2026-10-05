"""Bounded, externally approved authoring -> existing configs (development only).

generate/check are pure with respect to candidates; publication is explicit and immutable.
No source acquisition, extraction, model calls, semantic approval or activation.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
from contextlib import contextmanager
from hashlib import sha256
import json
import os
from pathlib import Path
from uuid import uuid4
from time import monotonic
from types import MappingProxyType
from types import SimpleNamespace

from jgrad_admission_rag.reviewed_source_evidence import canonical_json_bytes, parse_json
from jgrad_admission_rag.reviewed_fragment_import import (
    ImportTrust,
    load_inputs,
    map_candidate,
    publish_candidate,
    validate_candidate,
)
from jgrad_admission_rag.reasoning.material_slice_report import (
    load_plan,
    verify_evidence_bytes,
    read_pdf_bytes,
)
from jgrad_admission_rag.schemas.document_kb import load_document_kb_bytes
from jgrad_admission_rag.service.reference_workspace import (
    ReferenceSliceSnapshot,
    ReferenceWorkspaceConfig,
    _presentation,
    load_reference_config,
)
from scripts import m18_presentation as display

DOCS = Path(__file__).resolve().parents[1] / "docs/onboarding"
PREFIX = "m19-"
META = dict(
    plan_path="plan.json",
    trust_path="plan-trust.json",
    policy_path="policy.json",
    policy_trust_path="policy-trust.json",
    seed_path="seed.json",
)


def digest(raw):
    return sha256(raw).hexdigest()


def encode(value):
    return canonical_json_bytes(value)


def checked(condition, message):
    display.checked(condition, message)


def inputs(docs, approval_path=None, *, synthetic=False):
    """Approval is a preexisting external input, never written by this compiler."""
    approval_path = approval_path or docs / "m19-design-approval.json"
    approval, approval_raw = display.read_json(approval_path)
    checked(approval["artifact_role"] == "design-source-and-semantic-approval", "approval role")
    checked(approval["production_activation_approved"] is False, "activation not supported")
    if approval.get("synthetic"):
        checked(
            synthetic and "tests" in approval_path.resolve().parts,
            "synthetic approval only in tests",
        )
    else:
        checked(not synthetic, "synthetic fixture must be marked synthetic")
    raws = {}
    for name, expected in approval["base_inputs"].items():
        checked(Path(name).name == name, "unsafe approval input path")
        raw = (docs / name).read_bytes()
        checked(digest(raw) == expected, f"approved base input mismatch: {name}")
        raws[name] = raw
    for name, field in [
        ("m19-questionnaire-evidence-seed-v3.json", "approved_seed_sha256"),
        ("m19-questionnaire-authoring.json", "approved_authoring_sha256"),
    ]:
        raw = (docs / name).read_bytes()
        checked(digest(raw) == approval[field], f"external approval hash mismatch: {name}")
        raws[name] = raw
    for name in [
        "m19-source-review.json",
        "m19-source-review-pin-v3.json",
        "utokyo-gsfs-complex-2027.sources.json",
        "gsfs-source-set-contract-v0.1.examples.json",
    ]:
        raws[name] = (docs / name).read_bytes()
    seed = parse_json(raws["m19-questionnaire-evidence-seed-v3.json"])
    author = parse_json(raws["m19-questionnaire-authoring.json"])
    for value in [seed, author]:
        checked(value["target"] == approval["target"], "approved target mismatch")
        checked(value["source_set"] == approval["source_set"], "approved source set mismatch")
    checked(author["production_enabled"] is False, "author activation forbidden")
    checked(author["seed"]["sha256"] == approval["approved_seed_sha256"], "author seed mismatch")
    checked(author["seed"]["revision"] == seed["revision"], "author revision mismatch")
    pin = parse_json(raws["m19-source-review-pin-v3.json"])
    checked(
        pin
        == dict(
            bundle_id=seed["bundle_id"],
            revision=seed["revision"],
            bundle_sha256=approval["approved_seed_sha256"],
        ),
        "external source pin mismatch",
    )
    review = parse_json(raws["m19-source-review.json"])
    checked(
        review["seed_sha256"] == approval["approved_seed_sha256"]
        and review["authoring_sha256"] == approval["approved_authoring_sha256"],
        "source review mismatch",
    )
    base_seed = parse_json(raws["author01-essay-evidence-seed-v2.json"])
    old = {r["record_id"]: r for r in base_seed["records"]}
    current = {r["record_id"]: r for r in seed["records"]}
    checked(
        set(old) == set(approval["old_records_must_remain_identical"]), "old record set mismatch"
    )
    checked(all(current.get(k) == v for k, v in old.items()), "old record semantic drift")
    checked(
        seed["relations"][: len(base_seed["relations"])] == base_seed["relations"],
        "old relation drift",
    )
    checked(seed["topics"][: len(base_seed["topics"])] == base_seed["topics"], "old topic drift")
    checked(set(current) - set(old) == set(approval["approved_new_records"]), "unapproved records")
    checked(
        set(author["required_context"]) == set(approval["approved_new_records"]), "new context set"
    )
    for rid, ids in author["required_context"].items():
        record = current[rid]
        checked(record["topic_id"] == author["topic_id"], "context belongs to another topic")
        checked(
            ids
            == record["required_fragment_ids"]
            == [f["fragment_id"] for f in record["fragments"]],
            "incomplete new context",
        )
    checked(
        author["condition"]["template"]
        == approval["allowed_new_condition_template"]
        == "required_for_all_in_exact_target",
        "unsupported condition template",
    )
    claims = {c["field"]: c for c in author["claims"]}
    checked(len(claims) == len(author["claims"]), "duplicate claim")
    checked(
        claims[author["condition"]["audience_claim"]]["value"] == "all_in_exact_target",
        "audience template mismatch",
    )
    checked(
        claims[author["condition"]["stage_claim"]]["value"] == "application",
        "stage template mismatch",
    )
    checked(
        author["control"] == dict(type="self_report_tri_state", claim="preparation_status")
        and claims["preparation_status"]["value"] == "self_report_only",
        "unsupported control",
    )
    checked(
        set(author["condition"]["basis_record_ids"]) == set(author["required_context"]),
        "basis context mismatch",
    )
    raws["external_approval"] = approval_raw
    return approval, raws, seed, author


def author_projection(author):
    """Convert the bounded reader contract into the established M18 projection shape."""
    value = deepcopy(author)
    reader = author["reader"]
    value["guide"] = dict(
        what=reader["summary"]["text"],
        preparation=[s["text"] for s in reader["steps"]],
        attention=[s["text"] for s in reader["notes"]],
    )
    bindings = {"guide.what": reader["summary"]["claims"]}
    for key, field in [("preparation", "steps"), ("attention", "notes")]:
        for index, row in enumerate(reader[field]):
            bindings[f"guide.{key}.{index}"] = row["claims"]
    return value, dict(guide_bindings=bindings, preparation_control=author["control"]["type"])


def projected_catalog(snapshot, authors, displays):
    """Use M18's validated projection once per author and combine guides by topic key."""
    topics = snapshot.plan.model_dump(mode="json")["topics"]
    authored = {a["topic_id"]: (a, d) for a, d in authors}
    checked(len(authored) == len(authors), "duplicate author topic")
    names = {
        a["topic_id"]: next(c["value"] for c in a["claims"] if c["field"] == "material_name")
        for a, _ in authors
    }
    migrations = {r["topic_id"]: r for r in displays["materials"]}
    catalog, mapping = None, []
    for author, descriptor in authors:
        rows = []
        for topic in topics:
            tid = topic["topic_id"]
            if tid == author["topic_id"]:
                continue
            if tid in migrations:
                rows.append(migrations[tid])
            else:
                name = names[tid]
                a = authored[tid][0]
                rows.append(
                    dict(
                        topic_id=tid,
                        name=name["zh"],
                        official=name["ja"],
                        description=a["guide"]["what"],
                    )
                )
        projected, fields = display.project(snapshot, author, dict(materials=rows), descriptor)
        if catalog is None:
            catalog = projected
        else:
            own = next(
                r for r in projected["entries"][0]["topics"] if r["id"] == author["topic_id"]
            )
            catalog["entries"][0]["topics"] = [
                own if r["id"] == own["id"] else r for r in catalog["entries"][0]["topics"]
            ]
        mapping.extend(dict(topic_id=author["topic_id"], **f) for f in fields)
    return catalog, mapping


def compile_configs(
    docs=DOCS, *, pdf_dir=None, pdf_bytes=None, approval_path=None, synthetic=False
):
    started = monotonic()
    approval, raws, seed, author = inputs(docs, approval_path, synthetic=synthetic)
    old_policy = parse_json(raws["author01-material-condition-policy-v2.json"])
    old_plan = parse_json(raws["author01-material-slice-report-plan-v2.json"])
    config = parse_json(raws["author01-reviewed-fragment-import-v2.json"])
    config.update(bundle_revision=seed["revision"], bundle_sha256=approval["approved_seed_sha256"])
    config_raw = encode(config)
    trust = dict(
        bundle_id=seed["bundle_id"],
        revision=seed["revision"],
        bundle_sha256=digest(raws["m19-questionnaire-evidence-seed-v3.json"]),
        import_config_sha256=digest(config_raw),
    )
    manifest_raw = raws["utokyo-gsfs-complex-2027.sources.json"]
    contract_raw = raws["gsfs-source-set-contract-v0.1.examples.json"]
    evidence, import_config = load_inputs(
        raws["m19-questionnaire-evidence-seed-v3.json"],
        manifest_raw,
        contract_raw,
        config_raw,
        ImportTrust.model_validate(trust),
    )
    candidate_files = map_candidate(evidence, import_config, manifest_raw, contract_raw, config_raw)
    candidate = parse_json(candidate_files["candidate.json"])
    lineage = parse_json(candidate_files["lineage.json"])
    records = {r["record_id"]: r for r in seed["records"]}
    facts = {
        f.fact_id: f
        for d in candidate["documents"]
        for f in load_document_kb_bytes(candidate_files[d["relative_path"]]).facts
    }
    bindings = {}
    for record in lineage["records"]:
        bindings[record["record_id"]] = []
        for fragment in record["fragments"]:
            q = fragment["qualified_fact"]
            fact = facts[q["fact_id"]]
            source_fragment = next(
                f
                for f in records[record["record_id"]]["fragments"]
                if f["fragment_id"] == fragment["fragment_id"]
            )
            bindings[record["record_id"]].append(
                dict(
                    document_id=q["document_id"],
                    source_kb_sha256=q["kb_sha256"],
                    source_pdf_sha256=record["source_pdf_sha256"],
                    fact_id=fact.fact_id,
                    authoritative_fact_text_sha256=digest(source_fragment["text"].encode("utf-8")),
                    source_pages=[record["physical_page"]],
                )
            )
    kb_hashes = {d["document_id"]: d["kb_sha256"] for d in candidate["documents"]}
    policy = deepcopy(old_policy)
    policy.update(
        policy_id=old_policy["policy_id"] + "-r" + str(seed["revision"]), revision=seed["revision"]
    )
    pre = policy["evidence_prerequisites"]
    pre.update(
        bundle_revision=seed["revision"],
        bundle_sha256=trust["bundle_sha256"],
        candidate_build_id=candidate["build_id"],
        candidate_manifest_sha256=digest(candidate_files["candidate.json"]),
        lineage_sha256=digest(candidate_files["lineage.json"]),
        source_manifest_sha256=digest(manifest_raw),
        target_contract_sha256=digest(contract_raw),
    )
    for row in pre["documents"]:
        row["kb_sha256"] = kb_hashes[row["source_id"]]
    for rule in policy["rules"]:
        for row in rule["required_context_records"]:
            row["required_bindings"] = bindings[row["record_id"]]
    condition = author["condition"]
    claims = {c["field"]: c for c in author["claims"]}
    reader = author["reader"]
    context_note = " ".join(r["text"] for r in reader["notes"])
    rule = dict(
        condition_rule_id=author["condition_rule_id"],
        topic_id=author["topic_id"],
        material_code=author["material_code"],
        stage=claims[condition["stage_claim"]]["value"],
        mode="all",
        predicates=[],
        proposed_effect_when_matched="required",
        basis_record_ids=condition["basis_record_ids"],
        limitation_zh=context_note,
        required_context_records=[
            dict(
                record_id=rid,
                record_revision=records[rid]["revision"],
                required_bindings=bindings[rid],
            )
            for rid in author["required_context"]
        ],
    )
    policy["rules"].append(rule)
    policy_raw = encode(policy)
    policy_trust = dict(
        policy_id=policy["policy_id"], revision=policy["revision"], policy_sha256=digest(policy_raw)
    )
    plan = deepcopy(old_plan)
    plan.update(
        plan_id=old_plan["plan_id"] + "-r" + str(seed["revision"]), revision=seed["revision"]
    )
    plan["candidate_reference"].update(
        build_id=candidate["build_id"],
        import_config_sha256=digest(config_raw),
        source_manifest_sha256=digest(manifest_raw),
        target_contract_sha256=digest(contract_raw),
        files=[
            dict(relative_path=name, sha256=digest(raw))
            for name, raw in sorted(candidate_files.items())
        ],
    )
    plan["policy_reference"] = dict(
        policy_id=policy["policy_id"], revision=policy["revision"], sha256=digest(policy_raw)
    )
    plan["seed_reference"].update(revision=seed["revision"], sha256=trust["bundle_sha256"])
    for row in plan["sources"]:
        row["kb_sha256"] = kb_hashes[row["source_id"]]
    for row in plan["scope_reviews"]:
        row["required_bindings"] = bindings[row["record_id"]]
    source_roles = {s["source_id"]: s["source_role"] for s in plan["sources"]}
    review = parse_json(raws["m19-source-review.json"])
    images = {r["record_id"]: r["render_sha256"] for r in review["checks"]}
    for rid in author["required_context"]:
        record = records[rid]
        headings = [
            f["text"]
            for f in record["fragments"]
            if f["role"] in ("context", "table_group_header", "table_row_label")
        ]
        plan["scope_reviews"].append(
            dict(
                record_id=rid,
                record_revision=record["revision"],
                source_id=record["source_id"],
                source_role=source_roles[record["source_id"]],
                stage=rule["stage"],
                use="basis",
                physical_page=record["physical_page"],
                printed_page_label=record["printed_page_label"],
                manual_anchor=record["manual_anchor"],
                official_heading_path=headings,
                required_bindings=bindings[rid],
                review_image_sha256=images[rid],
                review_status="reviewed_for_selected_target",
                reviewed_target_id=seed["target"]["target_id"],
                scope_note_zh=record["review_note_zh"],
            )
        )
    plan["relations"] = deepcopy(seed["relations"])
    plan["topics"].append(
        dict(
            topic_id=author["topic_id"],
            material_code=author["material_code"],
            material_name_zh=claims["material_name"]["value"]["zh"],
            condition_rule_id=author["condition_rule_id"],
            stage=rule["stage"],
            proposed_effect_when_matched="required",
            basis_record_ids=rule["basis_record_ids"],
            required_context_record_ids=list(author["required_context"]),
            matched_explanation_zh=reader["summary"]["text"],
            context_note_zh=context_note,
            not_matched_explanation_zh="当前条件不适用；不能据此推定其他材料要求或申请资格。",
            needs_information_explanation_zh="信息不足，尚不能判断本条条件；不推定申请资格或材料已完成。",
        )
    )
    plan["limitations_zh"][1] = (
        f"只覆盖本固定目标的{len(plan['topics'])}个已审核材料主题，不是完整材料清单或资格判断。"
    )
    plan["review"] = dict(
        reviewer_kind="agent",
        reviewer_id=approval["reviewer_role"],
        reviewed_on=review["date"],
        status="design_reviewed_for_teacher_slice_not_full_kb_approval",
        image_origin="External source review; old image pins retained unchanged",
        method="External exact input approval "
        + approval["approval_id"]
        + "; mechanically derived development bindings await independent PR acceptance, never activation",
    )
    plan_raw = encode(plan)
    plan_trust = dict(
        plan_id=plan["plan_id"], revision=plan["revision"], plan_sha256=digest(plan_raw)
    )
    plan_model, policy_model, bundle, plan_sha, policy_sha = load_plan(
        plan_raw,
        encode(plan_trust),
        policy_raw,
        encode(policy_trust),
        raws["m19-questionnaire-evidence-seed-v3.json"],
    )
    if pdf_bytes is None:
        checked(pdf_dir is not None, "explicit existing PDF directory required")
        pdf_bytes = read_pdf_bytes(pdf_dir, plan_model)
    verified = verify_evidence_bytes(
        plan_model,
        policy_model,
        bundle,
        plan_sha256=plan_sha,
        policy_sha256=policy_sha,
        candidate_files=candidate_files,
        pdf_bytes=pdf_bytes,
    )
    identity = dict(
        plan=plan_sha,
        policy=policy_sha,
        seed=trust["bundle_sha256"],
        candidate={n: digest(r) for n, r in sorted(candidate_files.items())},
        pdf={n: digest(r) for n, r in sorted(pdf_bytes.items())},
    )
    snapshot_id = digest(encode(identity))
    snapshot = ReferenceSliceSnapshot(
        SimpleNamespace(slice_id="m19-reviewed-preview"),
        plan_model,
        snapshot_id,
        MappingProxyType(
            {key: value[0] for key, value in policy["profile_target_aliases"].items()}
        ),
        plan_raw,
        encode(plan_trust),
        policy_raw,
        encode(policy_trust),
        raws["m19-questionnaire-evidence-seed-v3.json"],
        MappingProxyType(candidate_files),
        MappingProxyType(pdf_bytes),
        _presentation(plan_model, verified, snapshot_id),
    )
    legacy_author = parse_json(raws["author01-essay-authoring-input.json"])
    adaptation = dict(
        original_authoring_sha256=digest(raws["author01-essay-authoring-input.json"]),
        original_seed=deepcopy(legacy_author["seed"]),
        derived_seed=deepcopy(author["seed"]),
        unchanged_record_ids=list(legacy_author["required_context"]),
    )
    legacy_author["seed"] = deepcopy(author["seed"])
    old_descriptor = parse_json(raws["m18-presentation-build.json"])
    catalog, fields = projected_catalog(
        snapshot,
        [(legacy_author, old_descriptor), author_projection(author)],
        parse_json(raws["m18-migrated-material-displays.json"]),
    )
    encoded = json.dumps(catalog, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    for c in ("<", ">", "&", "\u2028", "\u2029"):
        encoded = encoded.replace(c, f"\\u{ord(c):04x}")
    files = {
        "import.json": config_raw,
        "import-trust.json": encode(trust),
        "plan.json": plan_raw,
        "plan-trust.json": encode(plan_trust),
        "policy.json": policy_raw,
        "policy-trust.json": encode(policy_trust),
        "seed.json": raws["m19-questionnaire-evidence-seed-v3.json"],
        "m19-material-presentation.mjs": (
            "// Generated development display; independent review required.\n"
            "export const reviewedMaterialPresentation = " + encoded + ";\n"
        ).encode("utf-8"),
        "sources.json": encode(
            dict(
                external_approval_sha256=digest(raws["external_approval"]),
                old_author_adaptation=adaptation,
                guide_fields=fields,
                claims=author["claims"],
                unknowns=author["unknowns"],
                scope_limitations=author["scope_limitations"],
                record_bindings=bindings,
                condition_template=condition,
                origins=dict(
                    summary="reader.summary.text -> plan.matched_explanation_zh + guide.purpose",
                    notes="reader.notes in order -> plan.context_note_zh + guide.warnings",
                    steps="reader.steps in order -> guide.steps + reader report",
                ),
            )
        ),
    }
    files["differences.json"] = encode(
        dict(
            binding_changes=dict(
                policy=[
                    "policy_id",
                    "revision",
                    "evidence_prerequisites",
                    "rules.*.required_context_records.*.required_bindings",
                ],
                plan=[
                    "plan_id",
                    "revision",
                    "candidate_reference",
                    "policy_reference",
                    "seed_reference",
                    "sources.*.kb_sha256",
                    "scope_reviews.*.required_bindings",
                ],
            ),
            new_semantics=dict(rule=rule, topic=plan["topics"][-1]),
            plan_metadata_changes=dict(
                limitations_zh=plan["limitations_zh"], review=plan["review"]
            ),
            old_rules_unchanged_except_bindings=True,
            old_topics_unchanged=True,
        )
    )
    manifest = dict(
        schema_version="1.0",
        role="development_only_not_independent_acceptance",
        production_enabled=False,
        tool_sha256=digest(Path(__file__).read_bytes()),
        m18_tool_sha256=digest(Path(display.__file__).read_bytes()),
        input_hashes={name: digest(raw) for name, raw in sorted(raws.items())},
        snapshot_id=snapshot_id,
        build_id=candidate["build_id"],
        outputs={name: digest(raw) for name, raw in sorted(files.items())},
    )
    files["manifest.json"] = encode(manifest)
    checked(sum(map(len, files.values())) <= 1024**2, "config output exceeds 1 MiB")
    checked(monotonic() - started < 60, "configuration compilation exceeds 60 seconds")
    return files, snapshot, (evidence, import_config, manifest_raw, contract_raw, config_raw)


@contextmanager
def workspace_staging(output):
    # Windows TemporaryDirectory applies a private ACL. Inherit the workspace
    # permissions for both first publication and explicit refresh, never edit ACLs.
    staging = output.parent / (".m19-config-" + uuid4().hex)
    staging.mkdir()
    try:
        yield staging
    finally:
        if staging.exists():
            for path in staging.iterdir():
                path.unlink()
            staging.rmdir()


def write_or_check(files, output, *, check=False):
    if check:
        checked(
            output.is_dir() and {p.name for p in output.iterdir()} == set(files),
            "output file set drift",
        )
        display.write_or_check(files, output, True)
        return
    # Stage complete bytes first; refresh only this explicit generated directory.
    if output.exists():
        if {p.name for p in output.iterdir()} == set(files) and all(
            (output / n).read_bytes() == r for n, r in files.items()
        ):
            return
        checked(
            {p.name for p in output.iterdir()} <= set(files) | {"incomplete.json"},
            "output contains unowned files",
        )
        with workspace_staging(output) as staging:
            for name, raw in files.items():
                (Path(staging) / name).write_bytes(raw)
            (output / "incomplete.json").write_bytes(
                encode(dict(status="incomplete_do_not_enable"))
            )
            for name in sorted(files, key=lambda n: n == "manifest.json"):
                os.replace(Path(staging) / name, output / name)
            (output / "incomplete.json").unlink()
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    with workspace_staging(output) as staging:
        for name, raw in files.items():
            (staging / name).write_bytes(raw)
        os.rename(staging, output)


def preview_config(output, candidate_root, pdf_dir, docs=DOCS):
    template = parse_json((docs / "author01-reference-workspace-preview-v2.json").read_bytes())
    row = template["slices"][0]
    row["slice_id"] = "m19-reviewed-preview"
    row.update({field: str((output / name).resolve()) for field, name in META.items()})
    row.update(candidate_root=str(candidate_root.resolve()), pdf_dir=str(pdf_dir.resolve()))
    return template


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["generate", "check", "publish", "preview-config"])
    parser.add_argument("--docs", type=Path, default=DOCS)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--pdf-dir", type=Path, required=True)
    parser.add_argument("--candidate-store", type=Path)
    parser.add_argument("--preview-path", type=Path)
    parser.add_argument("--static-dir", type=Path, help="Install/check only the generated module")
    args = parser.parse_args()
    started = monotonic()
    files, snapshot, mapper_inputs = compile_configs(args.docs, pdf_dir=args.pdf_dir)
    write_or_check(files, args.output, check=args.operation != "generate")
    if args.static_dir:
        module = args.static_dir / "m19-material-presentation.mjs"
        if args.operation == "generate":
            module.write_bytes(files[module.name])
        else:
            checked(module.read_bytes() == files[module.name], "installed static module drift")
    if args.operation in ("publish", "preview-config"):
        checked(args.candidate_store is not None, "explicit candidate store required")
        candidate_root = args.candidate_store / parse_json(files["manifest.json"])["build_id"]
        if args.operation == "publish":
            from scripts.m19_budget import update

            update(
                "reserve immutable candidate publication",
                resource="candidate_publications",
                identity=snapshot.plan.candidate_reference.build_id,
            )
            paths = {
                s.source_id: args.pdf_dir / f"{s.identity.source_pdf_sha256}.pdf"
                for s in snapshot.plan.sources
            }
            candidate_root, status, _ = publish_candidate(
                args.candidate_store, *mapper_inputs, paths
            )
            print(json.dumps(dict(candidate_status=status, candidate_root=str(candidate_root))))
        else:
            validate_candidate(candidate_root, *mapper_inputs)
        config = preview_config(args.output, candidate_root, args.pdf_dir, args.docs)
        loaded = load_reference_config(ReferenceWorkspaceConfig.model_validate(config))[0]
        checked(
            loaded.snapshot_id == snapshot.snapshot_id, "complete disk loader snapshot mismatch"
        )
        if args.preview_path:
            checked(args.operation == "preview-config", "preview path only in preview-config")
            args.preview_path.parent.mkdir(parents=True, exist_ok=True)
            args.preview_path.write_bytes(encode(config))
    print(
        json.dumps(
            dict(
                operation=args.operation,
                seconds=monotonic() - started,
                bytes=sum(map(len, files.values())),
                snapshot_id=snapshot.snapshot_id,
            )
        )
    )
    from scripts.m19_budget import update

    update(
        args.operation,
        seconds=monotonic() - started,
        bytes=sum(map(len, files.values())),
        snapshot_id=snapshot.snapshot_id,
    )


if __name__ == "__main__":
    main()
