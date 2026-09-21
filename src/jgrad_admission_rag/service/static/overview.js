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
    const profileInputGroups = profileGroups.filter((group) => (
      group
      && typeof group.key === "string"
      && typeof group.label === "string"
      && Array.isArray(group.requirementCategories)
      && requirements
      && group.requirementCategories.some((category) => (
        requirements.some((item) => item && item.category === category)
      ))
    ));
    const comparableCategories = new Set(profileInputGroups.flatMap(
      (group) => group.requirementCategories
    ));
    const profileComparableRequirements = needsInformation.filter((item) => (
      comparableCategories.has(item.category)
    ));
    const otherConfirmationRequirements = needsInformation.filter((item) => (
      !comparableCategories.has(item.category)
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
      profileComparableCount: requirements ? profileComparableRequirements.length : null,
      otherConfirmationCount: requirements ? otherConfirmationRequirements.length : null,
      profileComparableRequirements: Object.freeze(profileComparableRequirements),
      otherConfirmationRequirements: Object.freeze(otherConfirmationRequirements),
      profileInputGroups: Object.freeze(profileInputGroups.map((group) => Object.freeze({
        key: group.key,
        label: group.label
      })))
    });
  }

  globalScope.JGradOverview = Object.freeze({ UNKNOWN, buildApplicationOverview });
})(globalThis);
