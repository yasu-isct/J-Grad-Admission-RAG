/* Design preview only: captured responses + explicit synthetic preparation interactions. */
window.previewState = {comparison: null, calls: [], prepared: false};
const previewClone = value => JSON.parse(JSON.stringify(value));
const previewOriginalFetch = window.fetch.bind(window);
window.fetch = async (input, init = {}) => {
  const path = new URL(typeof input === 'string' ? input : input.url, location.href).pathname;
  const data = window.PREVIEW_DATA;
  const request = init.body ? JSON.parse(init.body) : {};
  const response = body => Promise.resolve(new Response(JSON.stringify(body), {status:200,headers:{'Content-Type':'application/json'}}));
  if (!path.startsWith('/v1/')) return previewOriginalFetch(input, init);
  window.previewState.calls.push({path, method:init.method || 'GET'});
  if (path === '/v1/reference-targets') return response(data.catalog);
  if (path === '/v1/reviewed-documents') return response({items:[]});
  if (path === '/v1/generation-status') return response({schema_version:'1.0',provider:'reviewed-state-offline',model:'preview-no-model',mode:'offline_rules',configured:false,label:'样板预览 · 不运行问答模型',request_timeout_seconds:30});
  if (path === '/v1/base-requirements') {
    window.previewState.comparison = null;
    return response(data[request.intake.year === 2026 ? 'isct-base-2026' : 'isct-base-2027']);
  }
  if (path === '/v1/applicant-comparison') {
    const result = previewClone(data['isct-comparison']);
    const base = data[request.target.intake.year === 2026 ? 'isct-base-2026' : 'isct-base-2027'];
    result.target = previewClone(base.target);
    const statuses = Object.fromEntries((request.applicant.materials || []).map(x=>[x.code,x.preparation]));
    const names = {available:'已自报准备',not_yet:'尚未准备',unknown:'尚未填写／待确认'};
    for (const item of result.items) {
      for (const evidence of item.evidence || []) evidence.intake_name = result.target.intake_name;
      if (item.category !== 'materials') {
        item.description = '样板保留此项位置；没有重新执行学历或语言规则判断。';
        item.next_action = '正式程序中按实际个人输入核对。';
        continue;
      }
      const code = item.item_id.split(':')[1];
      const state = statuses[code] || 'unknown';
      item.preparation_status = state;
      item.description = `${names[state]}。这是前端交互示例，不是新运行的审核结果。`;
      item.comparison_status = state === 'available' && item.official_status === 'required' ? 'recorded' : 'needs_information';
      item.action_group = item.comparison_status === 'recorded' ? 'recorded' : 'action_required';
      item.next_action = item.official_status !== 'required' ? '先确认学历路径与本项适用条件。' : state === 'not_yet' ? '准备该材料并核对提交要求。' : state === 'available' ? '提交前核对内容和格式。' : '填写这项材料的准备情况。';
    }
    result.counts = {total:result.items.length,recorded:0,action_required:0,review_required:0};
    for (const item of result.items) result.counts[item.action_group]++;
    window.previewState.comparison = result;
    return response(result);
  }
  if (path.endsWith('/evidence')) return response(data['gsfs-evidence']);
  if (path.endsWith('/reports')) {
    const e=request.employment;
    const key=e.currently_employed_in_organization === false || e.retain_employment_at_enrollment === false ? 'gsfs-no-unknown' : e.currently_employed_in_organization === true && e.retain_employment_at_enrollment === true ? 'gsfs-yes-yes' : 'gsfs-unknown-unknown';
    return response(data[key]);
  }
  return new Response(JSON.stringify({detail:'完整前端样稿不运行此后台能力。'}),{status:409,headers:{'Content-Type':'application/json'}});
};
