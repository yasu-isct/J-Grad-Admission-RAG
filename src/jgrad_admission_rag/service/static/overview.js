"use strict";

(function exposeApplicationOverview(globalScope) {
  const UNKNOWN = "暂无已审核数据";

  function safeRequirements(payload) {
    return payload && Array.isArray(payload.requirements) ? payload.requirements : null;
  }

  function buildApplicationOverview(payload, profileGroups = []) {
    const requirements = safeRequirements(payload);
    const target = payload && payload.target && typeof payload.target === "object"
      ? payload.target
      : {};
    const dateEvents = requirements
      ? requirements.flatMap((item) => Array.isArray(item.date_events) ? item.date_events : [])
      : [];
    const mustArrive = dateEvents.find((event) => event && event.nature === "must_arrive") || null;
    const hasMaterials = requirements
      ? requirements.some((item) => item && item.category === "materials")
      : false;
    const needsInformation = requirements
      ? requirements.filter((item) => item && item.official_status === "needs_information")
      : [];
    const pendingCategories = new Set(needsInformation.map((item) => item.category));
    const neededProfileGroups = profileGroups.filter((group) => (
      group
      && typeof group.key === "string"
      && typeof group.label === "string"
      && Array.isArray(group.requirementCategories)
      && group.requirementCategories.some((category) => pendingCategories.has(category))
    ));

    return Object.freeze({
      target: Object.freeze({
        schoolName: target.school_name || UNKNOWN,
        degreeName: target.degree_name || UNKNOWN,
        intakeName: target.intake_name || UNKNOWN,
        collegeName: target.college_name || UNKNOWN,
        departmentName: target.department_name || UNKNOWN,
        routeName: target.application_route_name || null
      }),
      mustArrive,
      deadlineText: mustArrive && typeof mustArrive.display_text === "string"
        ? mustArrive.display_text
        : UNKNOWN,
      materialCount: hasMaterials
        ? requirements.filter((item) => item && item.category === "materials").length
        : null,
      needsInformationCount: requirements ? needsInformation.length : null,
      neededProfileGroups: Object.freeze(neededProfileGroups.map((group) => Object.freeze({
        key: group.key,
        label: group.label
      })))
    });
  }

  globalScope.JGradOverview = Object.freeze({ UNKNOWN, buildApplicationOverview });
})(globalThis);
