import {reviewedMaterialPresentation as previous} from "./reviewed-material-presentation.mjs";
import {reviewedMaterialPresentation as current} from "./m19-material-presentation.mjs";

export function combineMaterialCatalogs(...catalogs) {
  const entries = [];
  const identities = new Set();
  for (const catalog of catalogs) {
    if (catalog?.schema_version !== "1.0" || !Array.isArray(catalog.entries)) {
      throw new Error("展示目录格式错误，请刷新后重试");
    }
    for (const entry of catalog.entries) {
      if (identities.has(entry.snapshot_id)) throw new Error("展示目录身份重复");
      identities.add(entry.snapshot_id);
      entries.push(entry);
    }
  }
  return {schema_version: "1.0", entries};
}

export const reviewedMaterialPresentation = combineMaterialCatalogs(previous, current);
