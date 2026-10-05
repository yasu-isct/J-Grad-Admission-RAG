"""Generate bounded display data using the existing complete, read-only reference loader.

No publication, extraction, embedding, trust creation or admission decision happens here.
"""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
from time import monotonic

from jgrad_admission_rag.reviewed_source_evidence import canonical_json_bytes, parse_json
from jgrad_admission_rag.service.reference_workspace import (
    ReferenceWorkspaceConfig,
    load_reference_config,
)


MODULE = "reviewed-material-presentation.mjs"
MANIFEST = "reviewed-material-presentation.manifest.json"
MAPPING = "reviewed-material-presentation.sources.json"
FILES = (MODULE, MANIFEST, MAPPING)


def checked(condition, message):
    if not condition:
        raise ValueError(message)


def read_json(path):
    raw = path.read_bytes()
    checked(len(raw) <= 256 * 1024, "input exceeds size limit")
    return parse_json(raw), raw


def preview_config(descriptor_path, candidate_root, pdf_dir):
    descriptor, _ = read_json(descriptor_path)
    checked(descriptor["schema_version"] == "1.0", "unsupported build descriptor")
    base = descriptor_path.parent
    config, _ = read_json(base / descriptor["preview_template"])
    checked(len(config["slices"]) == 1, "one explicit reviewed slice required")
    row = config["slices"][0]
    for field, relative in descriptor["metadata"].items():
        row[field] = str((base / relative).resolve())
    row["candidate_root"] = str(candidate_root.resolve())
    row["pdf_dir"] = str(pdf_dir.resolve())
    return config


def load_snapshot(descriptor_path, candidate_root, pdf_dir):
    config = preview_config(descriptor_path, candidate_root, pdf_dir)
    # The existing loader verifies pins, all candidate bytes, PDF hashes, pages,
    # full target, scope reviews and complete context. Paths never become identity.
    return load_reference_config(ReferenceWorkspaceConfig.model_validate(config))[0]


def project(snapshot, author, displays, descriptor):
    """Pure projection after loader validation; also usable with isolated synthetic inputs."""
    plan = snapshot.plan.model_dump(mode="json")
    evidence = parse_json(snapshot.presentation)
    checked(author["target"] == plan["target"], "author target mismatch")
    checked(bool(author["source_set"]), "author source set missing")
    checked(
        all(author["source_set"][key] == value for key, value in plan["source_set"].items()),
        "author source set mismatch",
    )
    checked(
        author["seed"]["sha256"] == sha256(snapshot.seed_raw).hexdigest(), "author seed mismatch"
    )
    checked(
        author["seed"]["revision"] == plan["seed_reference"]["revision"], "author revision mismatch"
    )
    topics = plan["topics"]
    checked(len({row["topic_id"] for row in topics}) == len(topics), "duplicate topic")
    own = next((row for row in topics if row["topic_id"] == author["topic_id"]), None)
    checked(own and own["material_code"] == author["material_code"], "author material mismatch")
    records = {row["record_id"]: row for topic in evidence["topics"] for row in topic["records"]}
    context = {
        record_id: [row["fragment_id"] for row in records[record_id]["fragments"]]
        for record_id in own["required_context_record_ids"]
    }
    checked(author["required_context"] == context, "author complete context mismatch")
    fragments = {fragment_id for ids in context.values() for fragment_id in ids}
    claims = {row["field"]: row for row in author["claims"]}
    checked(len(claims) == len(author["claims"]), "duplicate claim")
    for claim in claims.values():
        refs = claim["fragment_ids"]
        checked(len(refs) == len(set(refs)) and set(refs) <= fragments, "unknown claim fragment")
        checked(
            bool(refs) or claim["field"] == "preparation_status", "official claim lacks sources"
        )
    name = claims["material_name"]["value"]
    checked(name["zh"] == own["material_name_zh"], "author name mismatch")
    guide = author["guide"]
    values = {"guide.what": guide["what"]}
    for key in ("preparation", "attention"):
        checked(isinstance(guide[key], list) and bool(guide[key]), "guide list missing")
        values.update({f"guide.{key}.{index}": value for index, value in enumerate(guide[key])})
    bindings = descriptor["guide_bindings"]
    checked(set(bindings) == set(values), "guide field mapping incomplete")
    mapping = []
    for path, value in values.items():
        checked(isinstance(value, str) and 0 < len(value) <= 2000, "invalid guide text")
        fields = bindings[path]
        checked(bool(fields) and all(field in claims for field in fields), "unknown mapped claim")
        refs = sorted({ref for field in fields for ref in claims[field]["fragment_ids"]})
        checked(bool(refs) or fields == ["preparation_status"], "guide field lacks sources")
        mapping.append(
            {
                "field": path,
                "claims": fields,
                "fragment_ids": refs,
                "role": "official_source_reference" if refs else "self_report_product_text",
            }
        )
    migrated = displays["materials"]
    checked(len({row["topic_id"] for row in migrated}) == len(migrated), "duplicate display topic")
    checked(
        {row["topic_id"] for row in migrated}
        == {row["topic_id"] for row in topics} - {own["topic_id"]},
        "migrated display topics mismatch",
    )
    result = []
    aliases = set()
    for topic, source_topic in zip(topics, evidence["topics"], strict=True):
        checked(topic["topic_id"] == source_topic["topic_id"], "evidence topic mismatch")
        if topic is own:
            display = [name["zh"], name["ja"], guide["what"]]
        else:
            migrated_row = next(row for row in migrated if row["topic_id"] == topic["topic_id"])
            display = [migrated_row[key] for key in ("name", "official", "description")]
        checked(
            all(isinstance(value, str) and 0 < len(value) <= 2000 for value in display),
            "invalid display text",
        )
        ids = [topic["topic_id"], topic["material_code"]]
        checked(not (aliases & set(ids)), "duplicate material alias")
        aliases.update(ids)
        row = {
            "id": topic["topic_id"],
            "material_code": topic["material_code"],
            "display": display,
            "records": source_topic["records"],
            "relations": source_topic["relations"],
            "guide": None,
            "preparation_control": None,
        }
        if topic is own:
            checked(
                descriptor["preparation_control"] == "self_report_tri_state", "unsupported control"
            )
            pages = [
                f"{record['source_title']}物理第{record['physical_page']}页"
                + (
                    f"（印刷{record['printed_page_label']}）"
                    if record["printed_page_label"]
                    else ""
                )
                for record in source_topic["records"]
            ]
            row["guide"] = {
                "purpose": guide["what"],
                "steps": guide["preparation"],
                "warnings": guide["attention"],
                "conditions": [],
                "sourceNote": "中文要点整理自" + "与".join(pages) + "；下方分别保留完整原文。",
            }
            row["preparation_control"] = descriptor["preparation_control"]
        result.append(row)
    return {
        "schema_version": "1.0",
        "role": "reviewed_display_projection_not_new_trust",
        "entries": [
            {
                "target": plan["target"],
                "snapshot_id": snapshot.snapshot_id,
                "revision": plan["revision"],
                "topics": result,
            }
        ],
    }, mapping


def build(descriptor_path, candidate_root, pdf_dir):
    started = monotonic()
    descriptor, descriptor_raw = read_json(descriptor_path)
    base = descriptor_path.parent
    author, author_raw = read_json(base / descriptor["authoring"])
    displays, display_raw = read_json(base / descriptor["displays"])
    snapshot = load_snapshot(descriptor_path, candidate_root, pdf_dir)
    catalog, mapping = project(snapshot, author, displays, descriptor)
    source_map = {
        "schema_version": "1.0",
        "guide_fields": mapping,
        "display_migration": displays["provenance"],
        "identity_source": "verified plan/seed/candidate/PDF content; never local paths",
        "records": [
            {
                "topic_id": topic["id"],
                "material_code": topic["material_code"],
                "record_ids": [r["record_id"] for r in topic["records"]],
            }
            for topic in catalog["entries"][0]["topics"]
        ],
    }
    # Serialize data only; escape JS line separators and HTML delimiters.
    encoded = json.dumps(catalog, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    for character in ("<", ">", "&", "\u2028", "\u2029"):
        encoded = encoded.replace(character, f"\\u{ord(character):04x}")
    module = (
        "// Generated display projection; do not edit. No new official trust is granted.\n"
        + "export const reviewedMaterialPresentation = "
        + encoded
        + ";\n"
    ).encode("utf-8")
    inputs = {
        "descriptor": sha256(descriptor_raw).hexdigest(),
        "authoring": sha256(author_raw).hexdigest(),
        "displays": sha256(display_raw).hexdigest(),
    }
    for field, relative in descriptor["metadata"].items():
        inputs[field] = sha256((base / relative).read_bytes()).hexdigest()
    # Preview template contains historical machine-local paths; capture only its
    # non-path labels/ID. The actual loader inputs above bind every trusted byte.
    template, _ = read_json(base / descriptor["preview_template"])
    labels = {
        key: value
        for key, value in template["slices"][0].items()
        if key in ("slice_id", "institution_name", "organization_name", "program_name")
    }
    inputs["preview_labels"] = sha256(canonical_json_bytes(labels)).hexdigest()
    inputs["candidate"] = {
        name: sha256(raw).hexdigest() for name, raw in sorted(snapshot.candidate_files.items())
    }
    inputs["pdf"] = {
        name: sha256(raw).hexdigest() for name, raw in sorted(snapshot.pdf_bytes.items())
    }
    files = {MODULE: module, MAPPING: canonical_json_bytes(source_map) + b"\n"}
    manifest = {
        "schema_version": "1.0",
        "input_hashes": inputs,
        "content_id": sha256(canonical_json_bytes(catalog)).hexdigest(),
        "snapshot_id": snapshot.snapshot_id,
        "outputs": {name: sha256(raw).hexdigest() for name, raw in files.items()},
    }
    files[MANIFEST] = canonical_json_bytes(manifest) + b"\n"
    checked(sum(map(len, files.values())) < 1024**2, "display outputs exceed 1 MiB")
    checked(monotonic() - started < 60, "display generation exceeded 60 seconds")
    return files


def write_or_check(files, output, check=False):
    if check:
        checked(
            all(
                (output / name).is_file() and (output / name).read_bytes() == raw
                for name, raw in files.items()
            ),
            "generated output drift; regenerate and review",
        )
    else:
        output.mkdir(parents=True, exist_ok=True)
        for name, raw in files.items():
            (output / name).write_bytes(raw)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--descriptor", type=Path, required=True)
    parser.add_argument("--candidate-root", type=Path, required=True)
    parser.add_argument("--pdf-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--check", action="store_true")
    parser.add_argument(
        "--preview-config",
        type=Path,
        help="Write local opt-in paths only; does not start or rebuild a service",
    )
    args = parser.parse_args()
    started = monotonic()
    files = build(args.descriptor.resolve(), args.candidate_root, args.pdf_dir)
    if args.preview_config:
        checked(not args.check, "--check never writes preview configuration")
        args.preview_config.parent.mkdir(parents=True, exist_ok=True)
        args.preview_config.write_bytes(
            canonical_json_bytes(
                preview_config(args.descriptor.resolve(), args.candidate_root, args.pdf_dir)
            )
        )
    if args.output_dir:
        write_or_check(files, args.output_dir, args.check)
    else:
        checked(bool(args.preview_config), "explicit output directory required")
    print(
        json.dumps(
            {
                "operation": "check" if args.check else "generate",
                "seconds": monotonic() - started,
                "bytes": sum(map(len, files.values())),
                "content_id": parse_json(files[MANIFEST])["content_id"],
            }
        )
    )


if __name__ == "__main__":
    main()
