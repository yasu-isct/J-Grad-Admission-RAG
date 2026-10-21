/* Official-site page links for the fixed public samples. No PDF is hosted or fetched here. */
(() => {
  "use strict";
  const isctPage = "https://admissions.isct.ac.jp/ja/013/graduate/guideline";
  const isctPdf = "https://admissions.isct.ac.jp/plugins/cms/component_download_file.php?type=1&pageId=3176&contentsId=&contentsDataId=&prevId=&key=87362e797f9f0c9ac915675147239ea8.pdf&fileName=2027_4_2026_9_master";
  const gsfsSources = {
    "gsfs-master-2027": ["https://www.k.u-tokyo.ac.jp/assets/files/2027guidelines_for_applicants_to_mc.pdf", 22],
    "complex-guide-2027-revised": ["https://www.k.u-tokyo.ac.jp/complex/html/examinee/2027guidebook_rev.pdf", 45],
    "complex-master-a-additional": ["https://www.k.u-tokyo.ac.jp/assets/files/03CSE_AM_j.pdf", 1]
  };
  function officialPdfHref(scope, evidence, page) {
    if (!Number.isInteger(page) || page < 1 || !scope || !evidence) return null;
    let url;
    if (scope.kind === "legacy_applicant") {
      const target = scope.request;
      if (target?.school_id !== "isct" || target.document_id !== "isct_2027_4_2026_9_master"
        || evidence.document_id !== target.document_id || evidence.source_url !== isctPage
        || page > 85) return null;
      url = isctPdf;
    } else if (scope.kind === "reviewed_material_slice") {
      const item = scope.item;
      const target = item?.target;
      if (item?.revision !== 3
        || item.snapshot_id !== "4237c6f910448b2223e40b2f64ad0e9ee2de1e37bcc6c16596368d9879afa942"
        || target?.institution_id !== "utokyo" || target.organization_id !== "utokyo-gsfs"
        || target.program_id !== "utokyo-gsfs-complex" || target.degree_level !== "master"
        || target.admission_cycle !== 2027 || target.examination_schedule_id !== "A"
        || target.selection_route_id !== "general-ordinary"
        || target.intake?.year !== 2027 || target.intake?.month !== 4
        || target.target_id !== "utokyo-gsfs-complex-master-2027-general-a-202704") return null;
      const source = Object.hasOwn(gsfsSources, evidence.source_id) ? gsfsSources[evidence.source_id] : null;
      if (!source || evidence.source_url !== source[0] || page > source[1]) return null;
      url = source[0];
    } else return null;
    const link = new URL(url);
    link.hash = `page=${page}`;
    return link.href;
  }
  globalThis.publicDemoPdfHref = officialPdfHref;
})();
