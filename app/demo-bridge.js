/* Public portfolio edition. This bridge replays reviewed, saved responses only.
 * It never sends an application profile or question to a backend. */
(() => {
  "use strict";
  const nativeFetch = window.fetch.bind(window);
  const dataRoot = new URL("../data/", document.currentScript.src);
  const cache = new Map();
  let manifest;
  let activeScenario;
  let activeSchool;
  const entryParams = new URLSearchParams(location.search);
  let initialScenario = entryParams.get("scenario");
  const $ = (id) => document.getElementById(id);
  function dataFile(name) {
    const url = new URL(name, dataRoot);
    if (url.origin !== dataRoot.origin || !url.pathname.startsWith(dataRoot.pathname)
      || !url.pathname.endsWith(".json")) throw new Error("Invalid sample asset");
    if (!cache.has(url.href)) cache.set(url.href, nativeFetch(url, {credentials: "omit"})
      .then((response) => { if (!response.ok) throw new Error("Sample unavailable"); return response.json(); }));
    return cache.get(url.href).then((value) => structuredClone(value));
  }
  const ready = dataFile("manifest.json").then((value) => { manifest = value; return value; });
  function schoolKey() {
    return $("school-select")?.value === "isct" ? "isct"
      : $("school-select")?.value ? "gsfs" : null;
  }
  function scenario() {
    const school = schoolKey();
    const choices = manifest?.schools?.[school]?.scenarios || [];
    return choices.find((item) => item.id === activeScenario) || choices[0];
  }
  const jsonResponse = (body, status = 200) => new Response(JSON.stringify(body), {
    status, headers: {"Content-Type": "application/json", "X-Portfolio-Demo": "saved-sample"}
  });
  window.fetch = async function(input, options = {}) {
    const url = new URL(typeof input === "string" || input instanceof URL ? input : input.url, location.href);
    const signal = options.signal;
    if (signal?.aborted) throw new DOMException("Aborted", "AbortError");
    const path = url.pathname;
    // The production UI uses absolute API paths. They are answered locally here.
    if (path.startsWith("/v1/")) {
      await ready;
      const school = manifest.schools[schoolKey()];
      const selected = scenario();
      let result;
      if (path === "/v1/reference-targets") result = await dataFile(manifest.catalog);
      else if (path === "/v1/generation-status") result = {configured: false, request_timeout_seconds: 30, label: "保存済みサンプル"};
      else if (path === "/v1/base-requirements" && schoolKey() === "isct") result = await dataFile(school.base);
      else if (path === "/v1/applicant-comparison" && schoolKey() === "isct" && selected?.comparison)
        result = await dataFile(selected.comparison);
      else if (path === `/v1/reference-slices/${encodeURIComponent(school?.entryId)}/evidence` && schoolKey() === "gsfs")
        result = await dataFile(school.evidence);
      else if (path === `/v1/reference-slices/${encodeURIComponent(school?.entryId)}/reports` && schoolKey() === "gsfs" && selected?.report)
        result = await dataFile(selected.report);
      else return jsonResponse({error: "This public demonstration has no live backend."}, 409);
      if (signal?.aborted) throw new DOMException("Aborted", "AbortError");
      if (path.endsWith("/evidence") || path === "/v1/base-requirements")
        setTimeout(() => applyScenario(false), 0);
      return jsonResponse(result);
    }
    // Fail closed: this copy only fetches the public JSON sample package.
    if (url.origin === dataRoot.origin && url.pathname.startsWith(dataRoot.pathname)
      && url.pathname.endsWith(".json") && (!options.method || options.method === "GET"))
      return nativeFetch(url, {...options, credentials: "omit"});
    throw new Error("Network request disabled in public demonstration");
  };
  function applyScenario(invalidate) {
    const selected = scenario();
    if (!selected) return;
    $("demo-scenario").value = selected.id;
    for (const control of document.querySelectorAll("#legacy-profile-grid input, #legacy-profile-grid select")) control.value = "";
    for (const control of document.querySelectorAll("#slice-profile select")) control.value = "unknown";
    for (const [key, value] of Object.entries(selected.fields || {})) {
      const control = $(key) || document.querySelector(key);
      if (control) control.value = String(value);
    }
    for (const [code, value] of Object.entries(selected.materials || {})) {
      const control = Array.from(document.querySelectorAll("[data-material-code]"))
        .find((item) => item.dataset.materialCode === code);
      if (control) control.value = value;
    }
    $("demo-scenario-description").textContent = selected.description;
    $("demo-scenario-description").setAttribute("data-scenario", selected.id);
    $("applicant-form").dispatchEvent(new Event("change", {bubbles: true}));
    if (invalidate) $("applicant-form").dispatchEvent(new Event("input", {bubbles: true}));
  }
  function refreshScenario() {
    const key = schoolKey();
    if (key === activeSchool) return;
    activeSchool = key;
    const choices = manifest.schools[key]?.scenarios || [];
    const select = $("demo-scenario");
    select.replaceChildren();
    for (const item of choices) select.add(new Option(item.label, item.id));
    activeScenario = choices.find((item) => item.id === initialScenario)?.id || choices[0]?.id;
    if (choices.length) initialScenario = null;
    if (activeScenario) select.value = activeScenario;
    select.disabled = !choices.length;
    applyScenario(false);
    installSamples();
  }
  function installSamples() {
    const target = $("demo-qa-samples");
    target.replaceChildren();
    if (schoolKey() !== "isct") {
      target.textContent = schoolKey() === "gsfs"
        ? "東京大学の例では、確認済みの提出書類・条件・資料間の関係を体験できます。質問・回答の保存例は、東京科学大学を選ぶと表示されます。"
        : "東京科学大学を選ぶと、収録した過去の募集資料に関する質問・回答例を確認できます。";
      return;
    }
    const samples = manifest.qaSamples || [];
    for (const sample of samples) {
      const details = document.createElement("details");
      const summary = document.createElement("summary");
      summary.textContent = sample.question;
      const body = document.createElement("div");
      body.className = "demo-qa-answer";
      const context = document.createElement("p");
      context.className = "demo-sample-context";
      context.textContent = [sample.scope, sample.label].filter(Boolean).join(" · ")
        || "保存済みの質問・回答例。現在の学校選択に対するリアルタイム回答ではありません。";
      body.append(context);
      for (const paragraph of String(sample.answer || "").split(/\n\s*\n/)) {
        const p = document.createElement("p"); p.textContent = paragraph; body.append(p);
      }
      details.append(summary, body); target.append(details);
      if (sample.sourceUrl?.startsWith("https://github.com/yasu-isct/")) {
        const source = document.createElement("a");
        source.href = sample.sourceUrl; source.target = "_blank"; source.rel = "noopener noreferrer";
        source.textContent = "元のテスト記録を見る"; body.append(source);
      }
    }
    if (!samples.length) target.textContent = "この公開デモでは自由質問を実行しません。募集資料の構造化表示と参考レポートをお試しください。";
  }
  document.addEventListener("DOMContentLoaded", async () => {
    document.body.classList.add("public-demo");
    try { await ready; }
    catch { $("demo-loading-status").textContent = "サンプルを読み込めませんでした。ページを再読み込みしてください。"; return; }
    $("demo-loading-status").textContent = "保存済みサンプルのみを表示 · 個人情報の入力・送信なし";
    $("school-select").addEventListener("change", () => {
      refreshScenario();
      // Only one target per school is included. Make its fixed identity explicit.
      for (const id of ["demo-degree-select", "intake-select", "college-select", "department-select", "route-select"]) {
        const control = $(id);
        const values = Array.from(control.options).filter((option) => option.value);
        if (values.length === 1 && !control.disabled) {
          control.value = values[0].value; control.dispatchEvent(new Event("change", {bubbles: true}));
        }
      }
      applyScenario(false);
    });
    $("demo-scenario").addEventListener("change", (event) => {
      activeScenario = event.target.value; applyScenario(true);
    });
    $("requirements-continue").addEventListener("click", () => applyScenario(false), true);
    $("applicant-form").addEventListener("submit", () => applyScenario(false), true);
    installSamples();
    refreshScenario();
    const requestedSchool = entryParams.get("school");
    const requestedValue = requestedSchool === "isct" ? "isct"
      : requestedSchool === "gsfs" ? manifest.schools.gsfs.entryId : null;
    if (requestedValue) {
      const chooseInitialSchool = () => {
        if (!Array.from($("school-select").options).some((option) => option.value === requestedValue)) return false;
        $("school-select").value = requestedValue;
        $("school-select").dispatchEvent(new Event("change", {bubbles: true}));
        return true;
      };
      if (!chooseInitialSchool()) {
        const observer = new MutationObserver(() => { if (chooseInitialSchool()) observer.disconnect(); });
        observer.observe($("school-select"), {childList: true});
      }
    }
  });
})();
