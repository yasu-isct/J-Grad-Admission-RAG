/* Complete design specimen over the existing four-step page, never loaded by production. */
const pnode = (tag, text, cls) => { const e=document.createElement(tag); if(text!==undefined)e.textContent=text; if(cls)e.className=cls; return e; };
const materialNames = {'宛名ラベル':'邮寄地址标签','入学志願票':'入学志愿票','志望理由書':'志望理由书','学士課程の成績証明書':'学士课程成绩证明','学士課程の卒業証明書又は卒業見込み証明書':'毕业／预计毕业证明'};
const pname = text => materialNames[text] || text;
const noteText = '固定历史资料，仅整理当前已覆盖内容。个人状态为自报示例，不代表材料齐全、学校审核通过或已完成出愿。';
let previewGraph = null;

window.previewChoose = async kind => {
  for(let i=0;i<50 && (!referenceEntries?.length || !referenceCore);i++)await new Promise(r=>setTimeout(r,100));
  const entry=referenceEntries.find(x=>x.kind===kind);if(!entry)return;
  const select=(id,value)=>{const e=byId(id); const v=value || [...e.options].find(x=>x.value)?.value; if(v){e.value=v;e.dispatchEvent(new Event('change',{bubbles:true}));}};
  select('school-select',entry.kind==='legacy_applicant'?entry.legacy_catalog.school_id:entry.entry_id);
  select('demo-degree-select');
  const intake=[...byId('intake-select').options].find(x=>x.value.endsWith(':2027:4'));
  select('intake-select',intake?.value);select('college-select');select('department-select');select('route-select');
  byId('requirements-submit').click();
};

function reportRow(title,state,action) {
  const row=pnode('div',undefined,'preview-material');
  row.append(pnode('strong',pname(title)),pnode('span',state,'preview-pill'+(state==='待补材料'?' pending':state==='已自报准备'?' ready':'')),pnode('span',action));
  return row;
}

function preparation(item) {
  if(!item)return ['待填写准备情况','填写个人情况后，可进一步整理待办。'];
  if(item.official_status==='not_applicable' || item.comparison_status==='not_applicable')return ['本项不适用','保留当前已确认的适用条件。'];
  if(item.official_status!=='required')return ['待确认适用条件',item.next_action || '补充个人条件，确认是否需要提交。'];
  if(item.preparation_status==='not_yet')return ['待补材料','准备材料，并核对提交格式。'];
  if(item.preparation_status==='available')return ['已自报准备','提交前核对内容与格式。'];
  return ['待填写准备情况','还没有填写，暂不能算作缺失材料。'];
}

renderReferenceReport = function(report) {
  referenceBody.replaceChildren();
  byId('reference-report-title').textContent='出愿准备参考';
  const options=pnode('div',undefined,'preview-report-options');
  const selections={dates:true,materials:true,other:false};
  const paper=pnode('article');
  const draw=()=>{
    paper.replaceChildren();
    const header=pnode('div',undefined,'preview-report-title');
    header.append(pnode('h3',[report.scope.school,report.scope.organization,report.scope.program,report.scope.degree,report.scope.intake,report.scope.route].filter(Boolean).join(' · ')),pnode('p','本次关注：'+Object.keys(selections).filter(k=>selections[k]).map(k=>({dates:'关键时间',materials:'材料与待办',other:'其他已加载要求'}[k])).join('、')));
    paper.append(header);
    if(selections.materials){
      const action=pnode('section',undefined,'preview-report-actions'); action.append(pnode('h3','接下来先做什么'));
      const rows=[];
      if(report.kind==='legacy_applicant') {
        const items=report.comparison?.items?.filter(x=>x.category==='materials') || [];
        if(!items.length)action.append(pnode('p','未填写个人准备情况，暂不能判断还缺哪些材料。你可以先保存下面的基础要求。'));
        else {
          const list=pnode('ol');
          for(const item of items){const [state,next]=preparation(item);if(state!=='已自报准备' && state!=='本项不适用')list.append(pnode('li',`${pname(item.title)}：${state}。${next}`));}
          action.append(list.children.length?list:pnode('p','本次已覆盖材料没有明确标记为尚未准备的项目；不代表全部申请材料齐全。'));
        }
        for(const topic of report.topics.filter(x=>x.category==='materials')){
          const item=items.find(x=>x.title===topic.title);
          const [state,next]=item ? preparation(item) : [topic.status_code==='required'?'基础要求':'适用条件待确认',topic.status_code==='required'?'填写准备情况后整理个人待办。':'先确认个人情况是否满足对应提交条件。'];
          rows.push({title:topic.title,state,next});
        }
      } else {
        const list=pnode('ol');
        for(const t of report.topics){
          const state=t.status_code==='submission_not_required'?'本项无需提交':t.status_code==='submission_required'?'需要准备，状态未填写':t.status_code==='rule_not_applicable'?'本条在职条件不适用':'待确认适用条件';
          rows.push({title:t.title,state,next:t.explanation});
          if(t.status_code==='submission_required' || t.status_code==='needs_information')list.append(pnode('li',`${t.title}：${state}。${t.explanation}`));
        }
        action.append(list.children.length?list:pnode('p','当前三个主题没有新增待补项目；其余申请材料尚未在本切片中核对。'));
      }
      paper.append(action);
      const section=pnode('section');section.append(pnode('h3','材料准备清单'));
      for(const row of rows)section.append(reportRow(row.title,row.state,row.next));
      paper.append(section);
    }
    if(selections.dates){
      const section=pnode('section');section.append(pnode('h3','关键时间'));
      const dates=report.kind==='legacy_applicant'?report.topics.flatMap(t=>t.dates || []):[];
      if(!dates.length)section.append(pnode('p','当前已覆盖资料尚未整理日期，请在完整募集要项中确认。'));
      else {const grid=pnode('div',undefined,'preview-date-grid');const seen=new Set();for(const d of dates){if(seen.has(d.label+d.display))continue;seen.add(d.label+d.display);const box=pnode('div',undefined,'preview-date');box.append(pnode('span',d.label),pnode('strong',d.display));if(d.uncertainty)box.append(pnode('p',d.uncertainty,'preview-note'));grid.append(box);}section.append(grid);}
      const materialsSection=paper.querySelector('section:not(.preview-report-actions)');
      paper.insertBefore(section,materialsSection);
    }
    if(selections.other && report.kind==='legacy_applicant'){
      const section=pnode('section');section.append(pnode('h3','其他已加载要求'));
      for(const t of report.topics.filter(t=>!['materials','dates'].includes(t.category)))section.append(pnode('h4',t.title),pnode('p',t.description || t.summary));
      paper.append(section);
    }
    paper.append(pnode('p',noteText,'preview-note'));
    const enabled=Object.values(selections).some(Boolean);byId('reference-copy').disabled=!enabled;
    if(!enabled)paper.replaceChildren(pnode('p','请至少选择一类报告内容。'));
    report.text=paper.innerText;
    byId('reference-report-status').textContent='样稿：仅复制当前选中的简洁报告内容，不含证据链。';
  };
  for(const [key,label] of Object.entries({dates:'关键时间',materials:'材料与待办',other:'其他已加载要求'})){
    const l=pnode('label'),c=pnode('input');c.type='checkbox';c.checked=selections[key];c.dataset.previewTopic=key;c.onchange=()=>{selections[key]=c.checked;draw();};l.append(c,document.createTextNode(label));options.append(l);
  }
  referenceBody.append(options,paper);referenceDialog.showModal();draw();byId('reference-close').focus();
};
byId('reference-copy').removeEventListener('click',copyReferenceReport);
byId('reference-copy').addEventListener('click',async()=>{
  if(!referenceReport)return;
  try{await navigator.clipboard.writeText(referenceReport.text);byId('reference-report-status').textContent='已复制当前简洁报告，不含引文或技术字段。';}
  catch{const f=byId('reference-copy-fallback');f.value=referenceReport.text;f.hidden=false;byId('reference-copy-fallback-label').hidden=false;f.focus();f.select();}
});

const relationLabels={department_specific_detail:'具体要求按专攻确认',cross_reference:'送付方法参照共通文件',consulting_is_distinct_from_submitting:'参照检查表 ≠ 提交表本身',shares_employment_context_but_separate_enrollment_stage:'入学手续关联，非出愿提交义务',corroborates_condition_with_submission_method:'补充提交条件与方式'};
const sourceNames={'gsfs-master-2027':'研究科共通募集要项','complex-guide-2027-revised':'复杂理工入试案内','complex-master-a-additional':'专攻追加材料表'};

function showGraph(focusRecord=null) {
  const {topic}=previewGraph;
  evidenceDrawer.classList.add('preview-graph-dialog','preview-evidence-dialog');byId('drawer-title').textContent=topic.material_name_zh+' · 依据关系';drawerContent.replaceChildren();
  drawerContent.append(pnode('p','东京大学 · 新领域 · CBMS复杂理工 · 2027年4月修士一般选拔A日程','preview-note'));
  drawerContent.append(pnode('p',topic.context_note_zh,'preview-context-box'));
  const map=new Map(topic.records.map(x=>[x.record_id,x]));
  const english=map.has('E01')&&map.has('E02')&&map.has('E03');
  const records=english?['E03','E01','E02'].map(k=>map.get(k)):map.has('E07')?['E07','E06','E08'].map(k=>map.get(k)):topic.records;
  const graph=pnode('div',undefined,'preview-graph');
  records.forEach((record,index)=>{
    if(index){const previous=records[index-1];const relation=PREVIEW_DATA.relations.find(r=>(r.from===previous.record_id&&r.to===record.record_id)||(r.to===previous.record_id&&r.from===record.record_id));if(relation){const stage=relation.kind==='shares_employment_context_but_separate_enrollment_stage';const edge=pnode('div',relationLabels[relation.kind],'preview-edge'+(stage?' separate-stage':''));edge.append(pnode('b',relation.from===previous.record_id?'→':'←'));graph.append(edge);}}
    const node=pnode('article',undefined,'preview-node'+(record.role==='basis'?' direct':''));
    node.append(pnode('p',(record.record_id==='E07'?'入学手续关联':record.role==='basis'?'直接依据':'关联说明')+' · 第'+record.physical_page+'页','preview-note'),pnode('h3',sourceNames[record.source_id] || record.source_title),pnode('p',record.scope_note_zh.replace(/E0[1-8]/g,id=>{const r=PREVIEW_DATA['gsfs-evidence'].topics.flatMap(t=>t.records).find(r=>r.record_id===id);return r ? sourceNames[r.source_id] : '关联条款';})));
    const button=pnode('button','查看原文','secondary');button.dataset.previewRecord=record.record_id;
    button.onclick=()=>{previewGraph.scroll=drawerContent.scrollTop;showGraphSource(record);};node.append(button);graph.append(node);
  });
  drawerContent.append(graph);
  if(!english){const list=pnode('ul',undefined,'preview-relation-rows');for(const r of PREVIEW_DATA.relations.filter(r=>map.has(r.from)&&map.has(r.to)))list.append(pnode('li',`${sourceNames[map.get(r.from).source_id]}第${map.get(r.from).physical_page}页 → ${sourceNames[map.get(r.to).source_id]}第${map.get(r.to).physical_page}页：${relationLabels[r.kind] || '已审核关联'}`));drawerContent.append(list);}
  drawerContent.append(pnode('p','箭头表示现有审核的引用或适用关系，不代表文件优先级。原文只在点击后显示；本样稿复用历史记录，没有运行新判断。','preview-note'));
  if(!evidenceDrawer.open)evidenceDrawer.showModal();
  if(focusRecord){drawerContent.scrollTop=previewGraph.scroll || 0;drawerContent.querySelector(`[data-preview-record="${focusRecord}"]`)?.focus({preventScroll:true});}
  else drawerClose.focus();
}
function showGraphSource(record){
  evidenceDrawer.classList.remove('preview-graph-dialog');byId('drawer-title').textContent=sourceNames[record.source_id] || record.source_title;drawerContent.replaceChildren();
  const back=pnode('button','← 返回依据关系','secondary');back.onclick=()=>showGraph(record.record_id);drawerContent.append(back,pnode('p',record.source_title),pnode('p',`PDF物理页 ${record.physical_page}${record.printed_page_label?' ／ 印刷页 '+record.printed_page_label:''}`,'preview-note'),pnode('blockquote',record.fragments.map(f=>f.quote_text).join('\n\n'),'preview-source-text'));
  const link=pnode('a','打开官方PDF（外部网站）');link.href=record.official_source_url;link.target='_blank';link.rel='noopener noreferrer';drawerContent.append(link);back.focus();
}
function addRelationButtons(container,mapped){
  for(const card of container.querySelectorAll('.requirement-card')){
    const title=card.querySelector('h3,h4')?.textContent;
    const topic=PREVIEW_DATA['gsfs-evidence'].topics.find(t=>t.material_name_zh===title);
    if(!topic)continue;
    card.querySelector('.requirement-evidence-actions')?.remove();
    const count=new Set(topic.records.map(r=>r.source_id)).size;
    const button=pnode('button',`查看依据关系（${count}份文件）`,'secondary');button.dataset.previewRelations=topic.topic_id;
    button.onclick=()=>{drawerTrigger=button;previewGraph={topic,scroll:0};showGraph();};card.append(button);
  }
}
const oldSliceRequirements=renderSliceRequirements;
renderSliceRequirements=function(mapped){oldSliceRequirements(mapped);addRelationButtons(requirementsOutput,mapped);};
const oldSliceReadiness=renderSliceReadiness;
renderSliceReadiness=function(report,mapped){oldSliceReadiness(report,mapped);addRelationButtons(comparisonOutput,mapped);};
evidenceDrawer.addEventListener('close',()=>{evidenceDrawer.classList.remove('preview-graph-dialog','preview-evidence-dialog');previewGraph=null;});
document.addEventListener('change',event=>{if(event.target.closest('#target-form') && previewGraph)evidenceDrawer.close();});
byId('grounded-answer-form').addEventListener('submit',event=>{event.preventDefault();event.stopImmediatePropagation();byId('grounded-answer-status').textContent='这是完整前端交互样板：问答区域保留原位置，本次不运行模型；问答修复仍暂停。';},true);
byId('grounded-question-help').textContent='前端样板保留问答区域布局，本次不启用问答、模型或检索；问答修复继续暂停。';
