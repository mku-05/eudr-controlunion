/* EUDR console — vanilla JS over the REST API. Hash routes: #/cases, #/case/:id[/tab], #/review, #/exceptions, #/documents, #/roi */
const $ = (s, el = document) => el.querySelector(s);
const view = $('#view'), titleEl = $('#title'), caseBadge = $('#casebadge');
const state = { caseId: localStorage.getItem('eudr.case') || null, cases: [] };
const reviewerInput = $('#reviewer');
reviewerInput.value = localStorage.getItem('eudr.reviewer') || '';
reviewerInput.addEventListener('change', () => localStorage.setItem('eudr.reviewer', reviewerInput.value.trim()));
const reviewer = () => reviewerInput.value.trim();

async function api(path, opts = {}) {
  const r = await fetch(path, { headers: { 'Content-Type': 'application/json' }, ...opts });
  if (!r.ok) { let m = r.statusText; try { m = (await r.json()).detail || m; } catch {} throw new Error(m); }
  return r.headers.get('content-type')?.includes('json') ? r.json() : r;
}
function toast(msg, ms = 3200) { const t = $('#toast'); t.textContent = msg; t.hidden = false; clearTimeout(t._t); t._t = setTimeout(() => t.hidden = true, ms); }
function modal(html) { $('#modal-body').innerHTML = html; $('#modal').hidden = false; }
$('#modal').addEventListener('click', e => { if (e.target.id === 'modal') $('#modal').hidden = true; });
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const pill = (v, cls) => `<span class="pill pill-${cls || v || 'none'}">${esc(v || 'no geometry')}</span>`;
const fmt = n => n == null ? '–' : (typeof n === 'number' ? n.toLocaleString(undefined, { maximumFractionDigits: 1 }) : n);
const fname = u => String(u || '').split('/').pop();
const evidenceUrl = (cid, pid, name) => `/cases/${cid}/evidence/${pid}/${name}`;
const citationUrl = (cid, uri) => `/cases/${cid}/citations/${fname(uri)}`;

function setActive(route) { document.querySelectorAll('#nav .nav-item').forEach(a => a.classList.toggle('active', a.dataset.route === route)); }
function needCase() {
  if (state.caseId) return true;
  view.innerHTML = `<div class="card p-8 text-center"><div class="eyebrow">No case selected</div><p class="mt-2 text-sm text-slate-500">Open a case from the Cases page first.</p><a href="#/cases" class="btn btn-primary mt-4">Go to cases</a></div>`;
  return false;
}
function selectCase(id) { state.caseId = id; localStorage.setItem('eudr.case', id); }

/* ---------- routes ---------- */
async function route() {
  const h = location.hash || '#/cases';
  const [, r, a, b] = h.split('/');
  caseBadge.hidden = !state.caseId; caseBadge.textContent = state.caseId || '';
  try {
    if (r === 'cases') { setActive('cases'); titleEl.textContent = 'Cases'; await pageCases(); }
    else if (r === 'case') { selectCase(a); setActive('cases'); await pageCase(a, b || 'plots'); }
    else if (r === 'review') { setActive('review'); titleEl.textContent = 'Review queue'; if (needCase()) await pageReview(state.caseId); }
    else if (r === 'exceptions') { setActive('exceptions'); titleEl.textContent = 'Exception ledger'; if (needCase()) await pageExceptions(state.caseId); }
    else if (r === 'documents') { setActive('documents'); titleEl.textContent = 'Documents & citations'; if (needCase()) await pageDocuments(state.caseId); }
    else if (r === 'roi') { setActive('roi'); titleEl.textContent = 'ROI report'; await pageRoi(); }
  } catch (e) { view.innerHTML = `<div class="card p-6 text-rose-600 text-sm">${esc(e.message)}</div>`; }
}
window.addEventListener('hashchange', route);

/* ---------- cases ---------- */
async function pageCases() {
  const cases = await api('/cases'); state.cases = cases;
  view.innerHTML = `
  <div class="grid grid-cols-1 xl:grid-cols-3 gap-6">
    <div class="xl:col-span-2 card">
      <div class="flex items-center justify-between px-5 py-4 border-b border-slate-100"><div><div class="font-semibold">Submittal packages</div><div class="text-xs text-slate-400 mt-0.5">${cases.length} case(s)</div></div></div>
      <table><thead><tr><th>Case</th><th>Operator</th><th>Status</th><th>Updated</th></tr></thead><tbody>
      ${cases.map(c => `<tr class="row" onclick="location.hash='#/case/${c.id}'"><td class="mono">${c.id}</td><td class="font-medium">${esc(c.operator)}</td><td>${pill(c.status.replace(/_/g, ' '), 'minor')}</td><td class="text-slate-400 text-xs">${c.updated_at.replace('T', ' ').slice(0, 16)}</td></tr>`).join('') || '<tr><td colspan="4" class="text-slate-400 text-center py-10">No cases yet — create one on the right.</td></tr>'}
      </tbody></table>
    </div>
    <div class="card p-5">
      <div class="eyebrow">New case</div>
      <div class="font-semibold mt-1">Ingest a package folder</div>
      <p class="text-xs text-slate-500 mt-1">Polygons (GeoJSON/SHP/KML/CSV), supplier &amp; lot tables, PDFs (contracts, CoC manifests, trace certificates, scanned CAR receipts), brief.md.</p>
      <label class="eyebrow block mt-4">Folder path on the engine host</label>
      <input id="nc-folder" class="mt-1" placeholder="/path/to/package">
      <label class="eyebrow block mt-3">Operator (optional)</label>
      <input id="nc-operator" class="mt-1" placeholder="Read from brief if empty">
      <label class="flex items-center gap-2 mt-3 text-xs text-slate-600"><input type="checkbox" id="nc-agent" checked style="width:auto"> Use Intake agent</label>
      <label class="flex items-center gap-2 mt-2 text-xs text-slate-600"><input type="checkbox" id="nc-run" checked style="width:auto"> Run the workflow after ingest</label>
      <button class="btn btn-primary mt-4 w-full justify-center" id="nc-go">Create case</button>
      <div id="nc-status" class="text-xs text-slate-500 mt-3"></div>
    </div>
  </div>`;
  $('#nc-go').onclick = async () => {
    const folder = $('#nc-folder').value.trim(); if (!folder) return toast('Folder path required');
    $('#nc-go').disabled = true; $('#nc-status').textContent = 'Ingesting…';
    try {
      const c = await api('/cases', { method: 'POST', body: JSON.stringify({ folder, operator: $('#nc-operator').value || null, use_agent: $('#nc-agent').checked }) });
      selectCase(c.id);
      if ($('#nc-run').checked) { $('#nc-status').textContent = 'Running workflow (screening, analyst, drafting)…'; await api(`/cases/${c.id}/run`, { method: 'POST' }); }
      location.hash = `#/case/${c.id}`;
    } catch (e) { toast(e.message); $('#nc-go').disabled = false; $('#nc-status').textContent = ''; }
  };
}

/* ---------- case detail ---------- */
async function pageCase(id, tab) {
  const s = await api(`/cases/${id}`);
  titleEl.textContent = s.operator;
  const counts = { PASS: 0, EXCEPTION: 0, CRITICAL: 0, none: 0 };
  s.plots.forEach(p => counts[p.verdict || 'none']++);
  const risk = s.risk;
  const tabs = [['plots', 'Plots'], ['review', 'Review queue'], ['exceptions', 'Exceptions'], ['trace', 'Chain of custody'], ['documents', 'Documents'], ['ledger', 'Ledger']];
  view.innerHTML = `
  <div class="flex items-start justify-between gap-4 flex-wrap">
    <div>
      <a href="#/cases" class="text-xs text-slate-400 hover:text-indigo-600">‹ Back to cases</a>
      <div class="flex items-center gap-3 mt-1"><span class="mono text-slate-400">${id}</span>${pill(s.status.replace(/_/g, ' '), 'minor')}</div>
      <div class="text-sm text-slate-500 mt-1">${esc(s.origin)} → ${esc(s.destination || '–')} · ${esc(s.shipment || '')} · ${s.suppliers.length} suppliers · ${s.lots.length} lots</div>
    </div>
    <div class="flex gap-2">
      <button class="btn" id="btn-run">Run / resume</button>
      <button class="btn" id="btn-redraft">Redraft dossier</button>
      <a class="btn" href="/cases/${id}/dossier" target="_blank">Evidence pack PDF</a>
      <a class="btn" href="/cases/${id}/exceptions.csv">Exception CSV</a>
      <button class="btn btn-primary" id="btn-ack" ${s.status !== 'awaiting_acknowledgement' ? 'disabled' : ''}>Acknowledge dossier</button>
    </div>
  </div>
  <div class="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-4 mt-6">
    ${kpi('Pass', counts.PASS, 'text-emerald-600')}${kpi('Exception', counts.EXCEPTION, 'text-amber-600')}${kpi('Critical', counts.CRITICAL, 'text-rose-600')}
    ${kpi('Open gaps', s.open_gaps.length, 'text-ink')}${kpi('Exceptions', s.exceptions?.total ?? 0, 'text-ink')}
    <div class="card p-4"><div class="eyebrow">Risk (Art. 10)</div><div class="kpi ${risk ? ({ high: 'text-rose-500', medium: 'text-amber-500' }[risk.criteria.level] || 'text-emerald-600') : 'text-slate-300'} mt-2">${risk ? Math.round(risk.score * 100) : '–'}</div><div class="score-bar mt-2"><div class="h-full rounded-full ${risk ? ({ high: 'bg-rose-500', medium: 'bg-amber-500' }[risk.criteria.level] || 'bg-emerald-500') : ''}" style="width:${risk ? risk.score * 100 : 0}%"></div></div><div class="text-[11px] text-slate-400 mt-1">${risk ? esc(risk.criteria.level) + ' · ' + esc(risk.country_risk) + ' risk country' : 'not scored yet'}</div></div>
  </div>
  <div class="flex gap-1 mt-6 bg-slate-100/70 p-1 rounded-2xl w-fit">${tabs.map(([k, l]) => `<a class="tab ${k === tab ? 'active' : ''}" href="#/case/${id}/${k}">${l}</a>`).join('')}</div>
  <div id="tabview" class="mt-4"></div>`;
  $('#btn-run').onclick = async () => { toast('Running…'); try { const r = await api(`/cases/${id}/run`, { method: 'POST' }); toast(`Status: ${r.status}`); route(); } catch (e) { toast(e.message); } };
  $('#btn-redraft').onclick = async () => { toast('Redrafting…'); try { await api(`/cases/${id}/redraft`, { method: 'POST' }); toast('Dossier rebuilt'); route(); } catch (e) { toast(e.message); } };
  $('#btn-ack').onclick = () => acknowledgeDialog(id, s);
  const tv = $('#tabview');
  if (tab === 'plots') renderPlots(tv, id, s);
  else if (tab === 'review') await renderReview(tv, id);
  else if (tab === 'exceptions') await renderExceptions(tv, id);
  else if (tab === 'trace') await renderTrace(tv, id, s);
  else if (tab === 'documents') await renderDocuments(tv, id);
  else if (tab === 'ledger') await renderLedger(tv, id);
}
const kpi = (label, v, cls) => `<div class="card p-4"><div class="eyebrow">${label}</div><div class="kpi ${cls} mt-2">${v}</div></div>`;

function renderPlots(el, id, s) {
  el.innerHTML = `<div class="grid grid-cols-1 xl:grid-cols-3 gap-6">
    <div class="xl:col-span-2 card"><table><thead><tr><th>Plot</th><th>Supplier</th><th class="text-right">Area ha</th><th>Flag</th><th>Reviewer</th></tr></thead><tbody>
    ${s.plots.map(p => `<tr class="row" data-plot="${p.id}"><td class="font-medium">${esc(p.name || p.id)}</td><td class="text-slate-500">${esc(p.supplier)}</td><td class="text-right mono">${fmt(p.area_ha)}</td><td>${pill(p.verdict)}</td><td class="text-xs text-slate-400">${esc(p.reviewer || '–')}</td></tr>`).join('')}
    </tbody></table></div>
    <div class="flex flex-col gap-4">
      <div class="card p-5"><div class="eyebrow">Open gaps</div>${s.open_gaps.length ? s.open_gaps.map(g => `<div class="mt-3 text-[13px]"><span class="pill pill-major">${esc(g.kind.replace(/_/g, ' '))}</span><div class="mt-1 text-slate-600">${esc(g.description)}</div><div class="text-[11px] text-slate-400">owner: ${esc(g.owner)}</div></div>`).join('') : '<div class="mt-2 text-sm text-slate-400">None</div>'}</div>
      <div class="card p-5"><div class="eyebrow">Legality findings</div>${(() => { const main = s.legality.filter(f => f.severity !== 'info'), info = s.legality.filter(f => f.severity === 'info'); const item = f => `<div class="mt-3 text-[13px]"><span class="pill pill-${{ blocking: 'critical', warning: 'major', info: 'info' }[f.severity]}">${esc(f.severity)} · ${esc(f.layer)}</span><div class="mt-1 text-slate-600">${esc(f.detail)}</div></div>`; return (main.map(item).join('') || '<div class="mt-2 text-sm text-slate-400">No blocking or warning findings</div>') + (info.length ? `<details class="mt-3"><summary class="text-xs text-indigo-600 cursor-pointer">${info.length} informational overlay(s)</summary>${info.map(item).join('')}</details>` : ''); })()}</div>
      <div class="card p-5"><div class="eyebrow">Volume reconciliation</div>${s.volume.length ? s.volume.map(v => `<div class="mt-2 text-[13px] ${v.flag ? 'text-rose-600' : 'text-slate-600'}">${v.flag ? '⚠ ' : ''}${esc(v.detail)}</div>`).join('') : '<div class="mt-2 text-sm text-slate-400">None</div>'}</div>
      ${s.risk?.narrative ? `<div class="card p-5"><div class="eyebrow">AI risk narrative (Art. 10)</div><p class="mt-2 text-[13px] text-slate-600 leading-relaxed">${esc(s.risk.narrative)}</p>${(s.risk.mitigation || []).map(m => `<div class="mt-2 text-[13px] text-slate-600">• ${esc(m)}</div>`).join('')}</div>` : ''}
    </div></div>`;
  el.querySelectorAll('tr[data-plot]').forEach(tr => tr.onclick = () => plotDialog(id, tr.dataset.plot));
}

async function plotDialog(id, pid) {
  const d = await api(`/cases/${id}/plots/${pid}`);
  const a = d.assessment, m = a?.metrics, op = a?.analyst_opinion;
  const imgs = (a?.evidence || []).filter(e => ['chip_before', 'chip_after', 'loss_overlay', 'ndvi_chart'].includes(e.type));
  modal(`
  <div class="flex items-start justify-between"><div><div class="eyebrow">Plot</div><div class="text-xl font-semibold">${esc(d.plot.name || pid)}</div><div class="text-xs text-slate-400 mono">${pid} · ${fmt(d.plot.computed_area_ha)} ha · ${esc(d.plot.production_start || '?')} → ${esc(d.plot.production_end || '?')}</div></div>
    <div class="text-right">${a ? pill(a.override_verdict || a.verdict) : pill(null)}<div class="text-[11px] text-slate-400 mt-1">${a ? 'engine ' + a.verdict + ' · conf ' + a.confidence : ''}</div></div></div>
  ${m ? `<div class="grid grid-cols-2 md:grid-cols-5 gap-3 mt-5">${[['Forest at cut-off', m.forest_2020_ha], ['Loss after cut-off', m.loss_after_cutoff_ha], ['Converted', m.converted_ha], ['First loss', m.first_loss_year || '–'], ['Native veg. loss', m.native_vegetation_loss_ha]].map(([l, v]) => `<div class="bg-slate-50 rounded-xl p-3"><div class="eyebrow">${l}</div><div class="text-lg font-semibold mt-1">${fmt(v)}${typeof v === 'number' && l !== 'First loss' ? ' <span class="text-xs text-slate-400">ha</span>' : ''}</div></div>`).join('')}</div>` : '<div class="mt-4 text-sm text-slate-400">Not screened (no polygon).</div>'}
  <div class="grid grid-cols-2 md:grid-cols-4 gap-3 mt-5">${imgs.map(e => `<div class="thumb"><img src="${evidenceUrl(id, pid, fname(e.uri))}" alt="${e.type}"><div class="px-2 py-1.5 text-[10px] text-slate-500">${e.type.replace('_', ' ')} · ${esc(e.captured_at || e.source)}${e.meta?.scene ? ' · ' + esc(e.meta.scene) : ''}</div></div>`).join('')}</div>
  ${op ? `<div class="mt-5 card p-4 bg-indigo-50/40 border-indigo-100"><div class="eyebrow text-indigo-500">AI analyst opinion · ${esc(op.model)}</div><div class="mt-1 text-sm"><b>${esc(op.recommended_verdict)}</b> at ${(op.confidence * 100).toFixed(0)}% — ${esc(op.rationale)}</div>${op.flags?.length ? `<div class="mt-2 text-[11px] text-slate-500">flags: ${op.flags.map(esc).join(', ')}</div>` : ''}</div>` : ''}
  ${a?.reviewer ? `<div class="mt-3 text-xs text-slate-500">Reviewed by ${esc(a.reviewer)} at ${esc(a.reviewed_at)}${a.override_verdict ? ` — override → ${a.override_verdict}: ${esc(a.override_reason)}` : a.override_reason ? ' — ' + esc(a.override_reason) : ''}</div>` : (a && ['EXCEPTION', 'CRITICAL'].includes(a.verdict) ? reviewForm(id, a.id) : '')}
  <div class="mt-4 text-[11px] text-slate-400">Datasets: ${(a?.evidence || []).filter(e => e.type === 'dataset').map(e => esc(e.source + ' ' + (e.source_version || ''))).join(' · ')}</div>`);
  bindReviewForm(id);
}

const reviewForm = (id, aid) => `<div class="mt-5 border-t border-slate-100 pt-4" data-review="${aid}">
  <div class="eyebrow">Reviewer decision</div>
  <div class="flex flex-wrap gap-2 mt-2 items-start">
    <button class="btn btn-primary" data-act="approve">Approve engine flag</button>
    <select data-field="verdict" style="width:auto"><option value="PASS">Override → PASS</option><option value="EXCEPTION">Override → EXCEPTION</option><option value="CRITICAL">Override → CRITICAL</option></select>
    <input data-field="reason" placeholder="Justification (required for override)" style="flex:1;min-width:240px">
    <button class="btn btn-danger" data-act="override">Override</button>
  </div></div>`;
function bindReviewForm(id) {
  document.querySelectorAll('[data-review]').forEach(box => {
    const aid = box.dataset.review;
    box.querySelector('[data-act="approve"]').onclick = async () => {
      if (!reviewer()) return toast('Enter your reviewer identity in the sidebar first');
      try { await api(`/cases/${id}/assessments/${aid}/approve`, { method: 'POST', body: JSON.stringify({ reviewer: reviewer() }) }); toast('Approved'); $('#modal').hidden = true; route(); } catch (e) { toast(e.message); }
    };
    box.querySelector('[data-act="override"]').onclick = async () => {
      if (!reviewer()) return toast('Enter your reviewer identity in the sidebar first');
      const verdict = box.querySelector('[data-field="verdict"]').value, reason = box.querySelector('[data-field="reason"]').value.trim();
      try { await api(`/cases/${id}/assessments/${aid}/override`, { method: 'POST', body: JSON.stringify({ reviewer: reviewer(), verdict, reason }) }); toast(`Overridden → ${verdict}`); $('#modal').hidden = true; route(); } catch (e) { toast(e.message); }
    };
  });
}

/* ---------- review queue ---------- */
async function pageReview(id) { view.innerHTML = '<div id="tabview"></div>'; await renderReview($('#tabview'), id); }
async function renderReview(el, id) {
  const q = await api(`/cases/${id}/review`);
  if (!q.length) { el.innerHTML = `<div class="card p-8 text-center"><div class="text-emerald-600 font-semibold">Queue is empty</div><p class="text-sm text-slate-500 mt-1">Every EXCEPTION and CRITICAL plot has a named reviewer. Redraft, then acknowledge the dossier.</p></div>`; return; }
  el.innerHTML = q.map(x => `<div class="card p-5 mb-4">
    <div class="flex items-start justify-between gap-4 flex-wrap"><div><div class="text-lg font-semibold">${esc(x.plot)}</div><div class="text-xs text-slate-400 mono">${x.plot_id} · ${x.assessment_id}</div></div><div class="text-right">${pill(x.verdict)}<div class="text-[11px] text-slate-400 mt-1">engine confidence ${x.confidence}</div></div></div>
    ${x.metrics ? `<div class="flex flex-wrap gap-4 mt-3 text-[13px] text-slate-600"><span>Forest at cut-off <b>${fmt(x.metrics.forest_2020_ha)} ha</b></span><span>Loss after <b>${fmt(x.metrics.loss_after_cutoff_ha)} ha</b></span><span>Converted <b>${fmt(x.metrics.converted_ha)} ha</b></span><span>First loss <b>${x.metrics.first_loss_year || '–'}</b></span><span>Sources concordant <b>${x.metrics.sources_concordant}</b></span></div>` : ''}
    <div class="grid grid-cols-2 md:grid-cols-4 gap-3 mt-4">${x.evidence.filter(u => /chip_before|chip_after|loss_overlay|ndvi_chart/.test(u)).map(u => `<div class="thumb"><img src="${evidenceUrl(id, x.plot_id, fname(u))}"><div class="px-2 py-1.5 text-[10px] text-slate-500">${fname(u).replace('.png', '').replace('_', ' ')}</div></div>`).join('')}</div>
    ${x.analyst ? `<div class="mt-4 card p-4 bg-indigo-50/40 border-indigo-100"><div class="eyebrow text-indigo-500">AI analyst opinion · ${esc(x.analyst.model)}</div><div class="mt-1 text-sm"><b>${esc(x.analyst.recommended_verdict)}</b> at ${(x.analyst.confidence * 100).toFixed(0)}% — ${esc(x.analyst.rationale)}</div></div>` : ''}
    ${reviewForm(id, x.assessment_id)}
  </div>`).join('');
  bindReviewForm(id);
}

async function acknowledgeDialog(id, s) {
  const q = await api(`/cases/${id}/review`);
  const critic = s.dossier?.critic_report;
  modal(`<div class="eyebrow">Reviewer acknowledgement</div><div class="text-xl font-semibold mt-1">Acknowledge the advisory dossier</div>
  <p class="text-sm text-slate-500 mt-2">This records that the named reviewer has seen the evidence dossier. It is not a conformity decision, issues no certificate, and submits nothing (pilot mode).</p>
  <div class="mt-4 text-sm">${q.length ? `<div class="text-rose-600">⚠ ${q.length} plot(s) still unreviewed — acknowledgement will be refused.</div>` : '<div class="text-emerald-600">✓ All EXCEPTION/CRITICAL plots reviewed.</div>'}
  ${critic ? `<div class="mt-2 ${critic.ok ? 'text-emerald-600' : 'text-amber-600'}">${critic.ok ? '✓' : '⚠'} Critic: ${esc(critic.summary)}</div>${(critic.issues || []).map(i => `<div class="text-xs text-slate-500 mt-1">[${esc(i.severity)}] ${esc(i.subject_ref)}: ${esc(i.detail)}</div>`).join('')}` : ''}</div>
  <label class="flex items-center gap-2 mt-4 text-xs text-slate-600"><input type="checkbox" id="ack-critic" style="width:auto"> Acknowledge critic issues and proceed anyway</label>
  <div class="flex gap-2 mt-5"><button class="btn btn-primary" id="ack-go">Acknowledge as ${esc(reviewer() || '(set reviewer in sidebar)')}</button><button class="btn" onclick="document.getElementById('modal').hidden=true">Cancel</button></div>`);
  $('#ack-go').onclick = async () => {
    if (!reviewer()) return toast('Enter your reviewer identity in the sidebar first');
    try { await api(`/cases/${id}/acknowledge`, { method: 'POST', body: JSON.stringify({ reviewer: reviewer(), acknowledge_critic: $('#ack-critic').checked }) }); toast('Dossier acknowledged'); $('#modal').hidden = true; route(); } catch (e) { toast(e.message, 6000); }
  };
}

/* ---------- exceptions ---------- */
async function pageExceptions(id) { view.innerHTML = '<div id="tabview"></div>'; await renderExceptions($('#tabview'), id); }
async function renderExceptions(el, id) {
  const ex = await api(`/cases/${id}/exceptions`);
  const by = {}; ex.forEach(e => by[e.severity] = (by[e.severity] || 0) + 1);
  el.innerHTML = `<div class="flex items-center gap-3 mb-4">${['critical', 'major', 'minor', 'info'].map(s => `<span class="pill pill-${s}">${s} ${by[s] || 0}</span>`).join('')}<a class="btn ml-auto" href="/cases/${id}/exceptions.csv">Download CSV</a></div>
  <div class="card"><table><thead><tr><th>Sev</th><th>Category</th><th>Subject</th><th>Detail</th><th>Owner</th><th>Citations</th></tr></thead><tbody>
  ${ex.map(e => `<tr><td>${pill(e.severity, e.severity)}</td><td class="text-slate-500">${esc(e.category)}</td><td class="font-medium">${esc(e.subject_label)}</td><td class="text-slate-600 max-w-xl">${esc(e.detail)}</td><td class="text-xs text-slate-400">${esc(e.owner)} · ${esc(e.status)}</td>
   <td>${e.citations.map(c => `<a href="#" class="text-indigo-600 text-xs block" data-cite='${esc(JSON.stringify({ u: c.image_uri, f: c.file, p: c.page, s: c.snippet }))}'>${esc(c.file)} p${c.page}</a>`).join('')}${e.evidence_uris?.length ? `<span class="text-[10px] text-slate-400">${e.evidence_uris.length} evidence files</span>` : ''}</td></tr>`).join('') || '<tr><td colspan="6" class="text-center text-slate-400 py-8">No exceptions yet — run the case.</td></tr>'}
  </tbody></table></div>`;
  bindCitations(el, id);
}
function bindCitations(el, id) {
  el.querySelectorAll('[data-cite]').forEach(a => a.onclick = ev => { ev.preventDefault(); const c = JSON.parse(a.dataset.cite);
    modal(`<div class="eyebrow">Visual citation</div><div class="font-semibold mt-1">${esc(c.f)} · page ${c.p}</div><div class="text-sm text-slate-500 mt-1">“${esc(c.s)}”</div>${c.u ? `<img class="mt-4 rounded-xl border border-slate-200 w-full" src="${citationUrl(id, c.u)}">` : '<div class="mt-3 text-sm text-slate-400">No rendered image for this citation.</div>'}`); });
}

/* ---------- trace ---------- */
async function renderTrace(el, id, s) {
  const t = await api(`/cases/${id}/trace`);
  if (!t || !t.edges.length) { el.innerHTML = '<div class="card p-8 text-center text-slate-400 text-sm">No chain-of-custody documents parsed.</div>'; return; }
  const names = Object.fromEntries(t.nodes.map(n => [n.id, n]));
  el.innerHTML = `<div class="grid grid-cols-1 xl:grid-cols-3 gap-6"><div class="xl:col-span-2 card"><table><thead><tr><th>From</th><th>To</th><th class="text-right">Tonnes</th><th>Lot</th><th>Document</th><th>Citation</th></tr></thead><tbody>
  ${t.edges.map(e => `<tr><td>${esc(names[e.source]?.name)} <span class="text-[10px] text-slate-400">${esc(names[e.source]?.tier)}</span></td><td>${esc(names[e.target]?.name)} <span class="text-[10px] text-slate-400">${esc(names[e.target]?.tier)}</span></td><td class="text-right mono">${fmt(e.tonnes)}</td><td class="text-xs">${esc(e.lot_reference || '')}</td><td class="text-xs text-slate-500">${esc(e.doc_ref || '')}</td><td>${e.citation ? `<a href="#" class="text-indigo-600 text-xs" data-cite='${esc(JSON.stringify({ u: e.citation.image_uri, f: e.citation.file, p: e.citation.page, s: e.citation.snippet }))}'>${esc(e.citation.file)} p${e.citation.page}</a>` : ''}</td></tr>`).join('')}
  </tbody></table></div>
  <div class="card p-5"><div class="eyebrow">Mass balance checks</div>${t.checks.map(c => `<div class="mt-3 text-[13px] ${c.flag ? 'text-rose-600' : 'text-slate-600'}">${c.flag ? '⚠ ' : '✓ '}${esc(c.detail)}</div>`).join('') || '<div class="text-sm text-slate-400 mt-2">None</div>'}</div></div>`;
  bindCitations(el, id);
}

/* ---------- documents ---------- */
async function pageDocuments(id) { view.innerHTML = '<div id="tabview"></div>'; await renderDocuments($('#tabview'), id); }
async function renderDocuments(el, id) {
  const docs = await api(`/cases/${id}/documents`);
  el.innerHTML = docs.map(d => `<div class="card p-5 mb-4">
    <div class="flex items-center justify-between flex-wrap gap-2"><div><div class="font-semibold">${esc(d.file)}</div><div class="text-xs text-slate-400 mt-0.5">${esc(d.kind.replace(/_/g, ' '))} · ${d.pages} page(s) · ${d.ocr_pages} OCR · ${d.citations.length} auto-citations</div></div>${d.ocr_pages ? '<span class="pill pill-minor">Scanned · OCR</span>' : '<span class="pill pill-info">Text layer</span>'}</div>
    <div class="grid grid-cols-2 md:grid-cols-4 xl:grid-cols-6 gap-3 mt-4">${d.citations.filter(c => c.image_uri).slice(0, 12).map(c => `<a href="#" class="thumb" data-cite='${esc(JSON.stringify({ u: c.image_uri, f: c.file, p: c.page, s: c.snippet }))}'><img src="${citationUrl(id, c.image_uri)}"><div class="px-2 py-1.5 text-[10px] text-slate-500"><b>${esc(c.field)}</b> ${esc(c.value).slice(0, 26)}</div></a>`).join('')}</div>
  </div>`).join('') || '<div class="card p-8 text-center text-slate-400 text-sm">No documents in this package.</div>';
  bindCitations(el, id);
}

/* ---------- ledger ---------- */
async function renderLedger(el, id) {
  const L = await api(`/cases/${id}/ledger?n=200`);
  el.innerHTML = `<div class="card"><table><thead><tr><th>Time</th><th>Kind</th><th>Actor</th><th>Payload</th><th>Hash</th></tr></thead><tbody>${L.slice().reverse().map(e => `<tr><td class="mono text-slate-400">${e.ts.slice(11, 19)}</td><td>${pill(e.kind.replace('_', ' '), { human_action: 'critical', agent_step: 'minor', agent_error: 'critical', tool_call: 'info', state_change: 'PASS' }[e.kind])}</td><td class="text-xs">${esc(e.actor)}</td><td class="text-xs text-slate-500 max-w-2xl truncate">${esc(JSON.stringify(e.payload)).slice(0, 180)}</td><td class="mono text-slate-300">${e.hash.slice(0, 10)}</td></tr>`).join('')}</tbody></table></div>`;
}

/* ---------- roi ---------- */
async function pageRoi() {
  const r = await api('/reports/roi');
  view.innerHTML = `<div class="grid grid-cols-2 md:grid-cols-4 gap-4">${kpi('Packages', r.cases, 'text-ink')}${kpi('Plots screened', r.plots_screened, 'text-ink')}${kpi('Pages parsed', r.pages_parsed, 'text-ink')}${kpi('OCR pages', r.ocr_pages, 'text-ink')}${kpi('Visual citations', r.citations, 'text-indigo-600')}${kpi('Exceptions', r.exceptions, 'text-amber-600')}${kpi('Agent steps', r.agent_steps, 'text-ink')}${kpi('Est. manual hours displaced', r.estimated_manual_hours, 'text-emerald-600')}</div>
  <div class="grid grid-cols-1 xl:grid-cols-2 gap-6 mt-6">
    <div class="card p-5"><div class="eyebrow">Flags across packages</div><div class="flex gap-3 mt-3">${Object.entries(r.flags).map(([k, v]) => `<span class="pill pill-${k}">${k} ${v}</span>`).join('')}</div>
      <div class="eyebrow mt-5">Exceptions by category</div><div class="mt-2 text-sm text-slate-600">${Object.entries(r.exceptions_by_category).map(([k, v]) => `${esc(k)} <b>${v}</b>`).join(' · ') || '–'}</div>
      <div class="eyebrow mt-5">Assumed minutes per item</div><div class="mt-2 text-xs text-slate-500">${Object.entries(r.assumptions_minutes).map(([k, v]) => `${esc(k.replace(/_/g, ' '))} ${v}`).join(' · ')}</div></div>
    <div class="card p-5 bg-[#1a1a1c] text-white border-0"><div class="eyebrow text-slate-400">Governance</div><p class="mt-2 text-sm text-slate-300 leading-relaxed">${esc(r.note)}</p><div class="mt-4 text-xs text-slate-500">Generated ${esc(r.generated_at)} · files: ${esc(r.files?.md || '')}</div></div>
  </div>`;
}

route();
