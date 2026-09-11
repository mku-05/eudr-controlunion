/* EUDR console — vanilla JS over the REST API. Routes: #/, #/cases, #/case/:id[/tab], #/review, #/exceptions, #/documents, #/roi */
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const view = $('#view'), titleEl = $('#title'), subEl = $('#subtitle'), caseBadge = $('#casebadge');
const state = { caseId: localStorage.getItem('eudr.case') || null, poll: null, map: null, charts: [], plotLayers: {} };
const reviewerInput = $('#reviewer');
reviewerInput.value = localStorage.getItem('eudr.reviewer') || '';
reviewerInput.addEventListener('change', () => localStorage.setItem('eudr.reviewer', reviewerInput.value.trim()));
const reviewer = () => reviewerInput.value.trim();
const COLORS = { PASS: '#059669', EXCEPTION: '#d97706', CRITICAL: '#e11d48', none: '#94a3b8' };
const STEPS = [['intake', 'Intake'], ['collecting', 'Collect'], ['screening', 'Screen'], ['adjudicating', 'Adjudicate'], ['drafting', 'Draft'], ['awaiting_acknowledgement', 'Review'], ['acknowledged', 'Acknowledged'], ['monitoring', 'Monitoring']];

async function api(path, opts = {}) {
  const r = await fetch(path, { headers: opts.body instanceof FormData ? {} : { 'Content-Type': 'application/json' }, ...opts });
  if (!r.ok) { let m = r.statusText; try { m = (await r.json()).detail || m; } catch {} throw new Error(m); }
  return r.headers.get('content-type')?.includes('json') ? r.json() : r;
}
function toast(msg, ms = 3200) { const t = $('#toast'); t.textContent = msg; t.hidden = false; clearTimeout(t._t); t._t = setTimeout(() => t.hidden = true, ms); }
function modal(html) { $('#modal-body').innerHTML = html; $('#modal').hidden = false; }
function closeModal() { $('#modal').hidden = true; }
$('#modal').addEventListener('click', e => { if (e.target.id === 'modal') closeModal(); });
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const pill = (v, cls) => `<span class="pill pill-${cls || v || 'none'}">${esc(v || 'no geometry')}</span>`;
const fmt = (n, d = 1) => n == null ? '–' : (typeof n === 'number' ? n.toLocaleString(undefined, { maximumFractionDigits: d }) : n);
const fname = u => String(u || '').split('/').pop();
const ago = ts => { const s = (Date.now() - new Date(ts)) / 1000; return s < 60 ? 'just now' : s < 3600 ? `${Math.floor(s / 60)} min ago` : s < 86400 ? `${Math.floor(s / 3600)} h ago` : `${Math.floor(s / 86400)} d ago`; };
const evidenceUrl = (cid, pid, name) => `/cases/${cid}/evidence/${pid}/${name}`;
const citationUrl = (cid, uri) => `/cases/${cid}/citations/${fname(uri)}`;
const statusLabel = s => ({ awaiting_acknowledgement: 'awaiting review', acknowledged: 'acknowledged' }[s] || (s || '').replace(/_/g, ' '));
const setActive = r => $$('#nav .nav-item').forEach(a => a.classList.toggle('active', a.dataset.route === r));
function selectCase(id) { state.caseId = id; localStorage.setItem('eudr.case', id); caseBadge.hidden = false; caseBadge.textContent = id; caseBadge.href = `#/case/${id}`; }
function cleanup() { closeDrawer(); closeModal(); clearInterval(state.poll); state.poll = null; state.charts.forEach(c => c.destroy()); state.charts = []; if (state.map) { state.map.remove(); state.map = null; } state.plotLayers = {}; document.onkeydown = null; }
function needCase() {
  if (state.caseId) return true;
  view.innerHTML = `<div class="card p-10 text-center max-w-lg mx-auto"><div class="eyebrow">No case selected</div><p class="mt-2 text-sm text-slate-500">Open a case from the Cases page first.</p><a href="#/cases" class="btn btn-primary mt-4">Go to cases</a></div>`;
  return false;
}
const skeleton = (n = 3) => `<div class="grid gap-4">${Array.from({ length: n }, () => '<div class="skeleton h-28"></div>').join('')}</div>`;

/* ---------- routing ---------- */
async function route() {
  cleanup();
  const [, r, a, b] = (location.hash || '#/').split('/');
  if (state.caseId) selectCase(state.caseId); else caseBadge.hidden = true;
  view.innerHTML = skeleton();
  try {
    if (!r) { setActive(''); head('Overview'); await pageOverview(); }
    else if (r === 'cases') { setActive('cases'); head('Cases'); await pageCases(); }
    else if (r === 'case') { selectCase(a); setActive('cases'); await pageCase(a, b || 'plots'); }
    else if (r === 'review') { setActive('review'); head('Review workspace'); if (needCase()) await pageReview(state.caseId); }
    else if (r === 'exceptions') { setActive('exceptions'); head('Exception ledger'); if (needCase()) await pageExceptions(state.caseId); }
    else if (r === 'documents') { setActive('documents'); head('Documents & citations'); if (needCase()) await pageDocuments(state.caseId); }
    else if (r === 'roi') { setActive('roi'); head('ROI report'); await pageRoi(); }
  } catch (e) { view.innerHTML = `<div class="card p-6 text-rose-600 text-sm">${esc(e.message)}</div>`; }
}
function head(t, sub) { titleEl.textContent = t; if (sub !== undefined) subEl.innerHTML = sub; else subEl.innerHTML = `<span class="eyebrow">Framework</span><span class="pill pill-indigo">EUDR (EU) 2023/1115</span><span class="pill pill-info">Advisory · human sign-off</span>`; }
window.addEventListener('hashchange', route);

/* ---------- shared widgets ---------- */
const kpi = (label, v, cls = 'text-ink', sub = '') => `<div class="card p-4"><div class="eyebrow">${label}</div><div class="kpi ${cls} mt-2">${v}</div>${sub ? `<div class="text-[11px] text-slate-400 mt-1">${sub}</div>` : ''}</div>`;
function flagBar(f) { const t = (f.PASS || 0) + (f.EXCEPTION || 0) + (f.CRITICAL || 0) || 1; return `<div class="bar">${['PASS', 'EXCEPTION', 'CRITICAL'].map(k => `<i style="width:${(f[k] || 0) / t * 100}%;background:${COLORS[k]}"></i>`).join('')}</div>`; }
function gauge(score, level) {
  const col = { high: '#e11d48', medium: '#d97706', low: '#059669', negligible: '#059669' }[level] || '#94a3b8';
  const r = 50, c = 2 * Math.PI * r, v = Math.max(0, Math.min(1, score || 0));
  return `<div class="gauge"><svg viewBox="0 0 120 120" width="120" height="120"><circle cx="60" cy="60" r="${r}" fill="none" stroke="#f1f5f9" stroke-width="10"/><circle cx="60" cy="60" r="${r}" fill="none" stroke="${col}" stroke-width="10" stroke-linecap="round" stroke-dasharray="${c}" stroke-dashoffset="${c * (1 - v)}"/></svg><div class="v" style="color:${col}">${score == null ? '–' : Math.round(v * 100)}</div></div>`;
}
function stepper(status, running) {
  const idx = STEPS.findIndex(s => s[0] === status);
  return `<div class="stepper">${STEPS.map(([k, l], i) => { const cls = i < idx ? 'done' : i === idx ? 'cur' + (running ? ' busy' : '') : ''; return `<div class="step ${cls}"><span class="dot">${i < idx ? '✓' : i + 1}</span><span>${l}</span></div>${i < STEPS.length - 1 ? `<div class="step-line ${i < idx ? 'done' : ''}"></div>` : ''}`; }).join('')}</div>`;
}
const feedColor = k => ({ human_action: '#e11d48', agent_step: '#4f46e5', agent_error: '#f59e0b', state_change: '#059669' }[k] || '#cbd5e1');
function feedItem(e) {
  const p = e.payload || {};
  const what = e.kind === 'state_change' ? `→ ${statusLabel(p.to)}` : e.kind === 'human_action' ? `${p.action} ${p.verdict || p.to || ''}` : e.actor === 'geo.screen' ? `screened → ${p.verdict}` : e.actor === 'adjudicate' ? `analyst → ${p.recommended}` : e.kind === 'agent_error' ? `⚠ ${(p.error || '').slice(0, 60)}` : e.actor;
  return `<div class="feed-item"><i class="feed-dot" style="background:${feedColor(e.kind)}"></i><div class="min-w-0"><div class="font-medium truncate">${esc(e.actor)} <span class="text-slate-400 font-normal">${esc(what)}</span></div><div class="text-[11px] text-slate-400">${e.operator ? esc(e.operator) + ' · ' : ''}${ago(e.ts)}</div></div></div>`;
}

/* ---------- overview ---------- */
async function pageOverview() {
  const d = await api('/dashboard');
  const t = d.totals;
  view.innerHTML = `
  <div class="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-4">
    ${kpi('Packages', t.cases)}${kpi('Plots screened', t.screened, 'text-ink', `${fmt(t.hectares, 0)} ha under review`)}
    ${kpi('Pending reviews', t.pending_reviews, t.pending_reviews ? 'text-amber-600' : 'text-emerald-600', 'need a named reviewer')}
    ${kpi('Critical exceptions', t.critical, t.critical ? 'text-rose-600' : 'text-emerald-600')}${kpi('Exceptions', t.exceptions)}${kpi('Acknowledged', t.acknowledged, 'text-indigo-600', 'dossiers')}
  </div>
  <div class="grid grid-cols-1 xl:grid-cols-3 gap-6 mt-6">
    <div class="xl:col-span-2 card">
      <div class="card-hd"><div class="card-title">Submittal packages</div><a href="#/cases" class="btn btn-sm btn-primary">+ New package</a></div>
      <table><thead><tr><th>Operator</th><th>Route</th><th>Plots</th><th>Flags</th><th>Reviews</th><th>Risk</th><th>Status</th></tr></thead><tbody>
      ${d.cases.map(c => `<tr class="row" onclick="location.hash='#/case/${c.id}'"><td><div class="font-medium">${esc(c.operator)}</div><div class="mono text-slate-400">${c.id}</div></td><td class="text-slate-500 text-xs whitespace-nowrap">${esc(c.origin)} → ${esc((c.destination || "–").split(",")[0])}<br>${esc(c.shipment || "")}</td><td class="font-medium">${c.plots}</td><td style="min-width:140px">${flagBar(c.flags)}<div class="text-[10px] text-slate-400 mt-1">${c.flags.PASS} pass · ${c.flags.EXCEPTION} exc · ${c.flags.CRITICAL} crit</div></td><td>${c.pending_reviews ? `<span class="pill pill-major">${c.pending_reviews} pending</span>` : '<span class="pill pill-pass">clear</span>'}</td><td>${c.risk ? pill(c.risk, { high: 'critical', medium: 'major', low: 'pass' }[c.risk] || 'info') : '–'}</td><td>${c.running ? '<span class="pill pill-indigo">running…</span>' : pill(statusLabel(c.status), 'minor')}</td></tr>`).join('') || '<tr><td colspan="7" class="text-center text-slate-400 py-10">No packages yet.</td></tr>'}
      </tbody></table>
    </div>
    <div class="flex flex-col gap-6">
      <div class="card p-5"><div class="eyebrow">Flags across the portfolio</div><div class="flex items-center gap-5 mt-3"><div style="width:130px;height:130px"><canvas id="flagChart"></canvas></div><div class="text-sm flex flex-col gap-1.5">${['PASS', 'EXCEPTION', 'CRITICAL'].map(k => `<div class="flex items-center gap-2"><i class="w-2.5 h-2.5 rounded-sm" style="background:${COLORS[k]}"></i><span class="text-slate-500">${k.toLowerCase()}</span><b class="ml-auto pl-4">${d.flags[k]}</b></div>`).join('')}</div></div></div>
      <div class="card p-5"><div class="eyebrow">Recent activity</div><div class="mt-2">${d.recent.map(feedItem).join('') || '<div class="text-sm text-slate-400">Nothing yet</div>'}</div></div>
    </div>
  </div>`;
  donut('flagChart', ['PASS', 'EXCEPTION', 'CRITICAL'].map(k => d.flags[k]), ['PASS', 'EXCEPTION', 'CRITICAL'].map(k => COLORS[k]));
}
function donut(id, data, colors) {
  const el = $('#' + id); if (!el || !window.Chart) return;
  state.charts.push(new Chart(el, { type: 'doughnut', data: { labels: ['PASS', 'EXCEPTION', 'CRITICAL'], datasets: [{ data, backgroundColor: colors, borderWidth: 0 }] }, options: { cutout: '72%', plugins: { legend: { display: false } }, animation: { duration: 500 } } }));
}

/* ---------- cases ---------- */
async function pageCases() {
  const cases = await api('/cases');
  view.innerHTML = `
  <div class="grid grid-cols-1 xl:grid-cols-5 gap-6">
    <div class="xl:col-span-3 card">
      <div class="card-hd"><div><div class="card-title">All cases</div><div class="text-xs text-slate-400">${cases.length} package(s)</div></div></div>
      <table><thead><tr><th>Case</th><th>Operator</th><th>Status</th><th>Updated</th></tr></thead><tbody>
      ${cases.map(c => `<tr class="row" onclick="location.hash='#/case/${c.id}'"><td class="mono">${c.id}</td><td class="font-medium">${esc(c.operator)}</td><td>${pill(statusLabel(c.status), 'minor')}</td><td class="text-slate-400 text-xs">${ago(c.updated_at)}</td></tr>`).join('') || '<tr><td colspan="4" class="text-slate-400 text-center py-10">No cases yet — ingest a package on the right.</td></tr>'}
      </tbody></table>
    </div>
    <div class="xl:col-span-2 card p-5">
      <div class="eyebrow">New case</div>
      <div class="font-semibold mt-1 text-[15px]">Ingest a submittal package</div>
      <p class="text-xs text-slate-500 mt-1 leading-relaxed">Drop the raw package: polygons (GeoJSON, Shapefile zip, KML, CSV/XLSX), supplier and lot tables, PDFs — contracts, chain-of-custody manifests, trace certificates, scanned CAR receipts — and a brief. Dirty scans and Portuguese/Spanish are fine.</p>
      <div class="drop mt-4" id="drop"><input type="file" id="files" multiple hidden><div class="text-sm font-semibold text-indigo-600">Drop files here or click to choose</div><div class="text-xs text-slate-400 mt-1" id="drop-info">No files selected</div></div>
      <div class="eyebrow mt-4">or a folder on the engine host</div>
      <input id="nc-folder" class="mt-1" placeholder="/path/to/package">
      <label class="eyebrow block mt-3">Operator (optional)</label>
      <input id="nc-operator" class="mt-1" placeholder="Read from the brief if empty">
      <div class="flex flex-wrap gap-4 mt-3 text-xs text-slate-600"><label class="flex items-center gap-2"><input type="checkbox" id="nc-agent" checked> Intake agent</label><label class="flex items-center gap-2"><input type="checkbox" id="nc-run" checked> Run pipeline after ingest</label></div>
      <button class="btn btn-primary mt-4 w-full justify-center" id="nc-go">Create case</button>
      <div id="nc-status" class="text-xs text-slate-500 mt-3"></div>
    </div>
  </div>`;
  const drop = $('#drop'), files = $('#files');
  drop.onclick = () => files.click();
  files.onchange = () => $('#drop-info').textContent = files.files.length ? `${files.files.length} file(s): ${[...files.files].map(f => f.name).slice(0, 4).join(', ')}${files.files.length > 4 ? '…' : ''}` : 'No files selected';
  ['dragenter', 'dragover'].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.add('over'); }));
  ['dragleave', 'drop'].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.remove('over'); }));
  drop.addEventListener('drop', e => { files.files = e.dataTransfer.files; files.onchange(); });
  $('#nc-go').onclick = async () => {
    const folder = $('#nc-folder').value.trim(), run = $('#nc-run').checked, useAgent = $('#nc-agent').checked, op = $('#nc-operator').value.trim();
    if (!folder && !files.files.length) return toast('Choose files or give a folder path');
    $('#nc-go').disabled = true; $('#nc-status').textContent = 'Ingesting package (parsing polygons, OCR, intake agent)…';
    try {
      let c;
      if (files.files.length) { const fd = new FormData(); [...files.files].forEach(f => fd.append('files', f)); c = await api(`/cases/upload?use_agent=${useAgent}&run=${run}${op ? '&operator=' + encodeURIComponent(op) : ''}`, { method: 'POST', body: fd }); }
      else c = await api('/cases', { method: 'POST', body: JSON.stringify({ folder, operator: op || null, use_agent: useAgent, run }) });
      selectCase(c.id); location.hash = `#/case/${c.id}`;
    } catch (e) { toast(e.message, 6000); $('#nc-go').disabled = false; $('#nc-status').textContent = ''; }
  };
}

/* ---------- case ---------- */
async function pageCase(id, tab) {
  const [s, prog] = await Promise.all([api(`/cases/${id}`), api(`/cases/${id}/progress`)]);
  head(s.operator, `<span class="mono text-slate-400">${id}</span>${pill(statusLabel(s.status), 'minor')}<span class="text-xs text-slate-500">${esc(s.origin)} → ${esc(s.destination || '–')} · ${esc(s.shipment || '')}</span>`);
  const counts = { PASS: 0, EXCEPTION: 0, CRITICAL: 0, none: 0 }; s.plots.forEach(p => counts[p.verdict || 'none']++);
  const pending = s.plots.filter(p => p.verdict && p.verdict !== 'PASS' && !p.reviewer).length;
  const risk = s.risk;
  const tabs = [['plots', 'Plots', s.plots.length], ['review', 'Review', pending], ['exceptions', 'Exceptions', s.exceptions?.total ?? 0], ['trace', 'Chain of custody', s.trace?.edges ?? 0], ['documents', 'Documents', s.documents?.length ?? 0], ['ledger', 'Ledger', null]];
  const canAck = s.status === 'awaiting_acknowledgement';
  view.innerHTML = `
  <div class="card hero p-5">
    <div id="stepper">${stepper(s.status, prog.running)}</div>
    <div class="flex items-center justify-between gap-4 flex-wrap mt-4 pt-4 border-t border-slate-100">
      <div class="text-xs text-slate-500">${s.suppliers.length} suppliers · ${s.plots.length} plots · ${s.lots.length} lots · ${s.documents?.length ?? 0} documents${s.acknowledgement ? ` · acknowledged by <b>${esc(s.acknowledgement.reviewer)}</b>` : ''}</div>
      <div class="flex gap-2 flex-wrap">
        <button class="btn" id="btn-run" ${prog.running ? 'disabled' : ''}>${prog.running ? 'Pipeline running…' : (s.status === 'monitoring' || s.status === 'acknowledged' ? 'Check alerts' : 'Run pipeline')}</button>
        <button class="btn" id="btn-redraft">Redraft dossier</button>
        <a class="btn" href="/cases/${id}/dossier" target="_blank">Evidence pack</a>
        <a class="btn" href="/cases/${id}/exceptions.csv">Exception CSV</a>
        <button class="btn ${canAck ? 'btn-primary' : ''}" id="btn-ack" ${canAck ? '' : 'disabled'}>Acknowledge dossier</button>
      </div>
    </div>
    <div id="live" class="mt-3" ${prog.running ? '' : 'hidden'}></div>
  </div>
  <div class="grid grid-cols-1 xl:grid-cols-3 gap-6 mt-6">
    <div class="xl:col-span-2 card overflow-hidden" style="min-height:460px">
      <div class="card-hd"><div><div class="card-title">Plot map</div><div class="text-xs text-slate-400">Polygons coloured by flag · loss overlay where forest changed after the cut-off</div></div><div class="flex gap-2"><span class="pill pill-pass">${counts.PASS} pass</span><span class="pill pill-major">${counts.EXCEPTION} exc</span><span class="pill pill-critical">${counts.CRITICAL} crit</span></div></div>
      <div class="relative"><div id="map" style="height:420px"></div>
        <div class="map-legend"><span><i style="background:${COLORS.PASS}"></i>Pass</span><span><i style="background:${COLORS.EXCEPTION}"></i>Exception</span><span><i style="background:${COLORS.CRITICAL}"></i>Critical</span><span><i style="background:#c23b2d"></i>Converted after cut-off</span><span><i style="background:#3b7a4e"></i>Forest at cut-off</span></div>
        <div class="map-ctl"><button class="btn btn-sm" id="map-sat">Satellite</button><button class="btn btn-sm" id="map-light">Light</button><button class="btn btn-sm" id="map-ov">Overlays</button></div>
      </div>
    </div>
    <div class="flex flex-col gap-4">
      <div class="card p-5 flex items-center gap-5">${gauge(risk?.score, risk?.criteria?.level)}<div><div class="eyebrow">Risk (Art. 10)</div><div class="text-lg font-semibold mt-1 capitalize">${risk ? esc(risk.criteria.level) : 'Not scored'}</div><div class="text-xs text-slate-500 mt-1">${risk ? `${esc(risk.country_risk)}-risk origin · ${risk.criteria.red_plots ?? 0} critical, ${risk.criteria.amber_plots ?? 0} exception plots · ${risk.criteria.legality_blocking ?? 0} blocking legality` : 'Run the pipeline to score.'}</div></div></div>
      <div class="grid grid-cols-3 gap-3">${kpi('Open gaps', s.open_gaps.length, s.open_gaps.length ? 'text-amber-600' : 'text-emerald-600')}${kpi('Pending', pending, pending ? 'text-amber-600' : 'text-emerald-600', 'reviews')}${kpi('Critical', s.exceptions?.by_severity?.critical ?? 0, (s.exceptions?.by_severity?.critical ?? 0) ? 'text-rose-600' : 'text-emerald-600', 'exceptions')}</div>
      <div class="card p-5 flex-1"><div class="eyebrow">What needs attention</div>${attention(s, pending).map(x => `<div class="mt-3 flex gap-3 text-[13px]"><i class="feed-dot mt-1.5" style="background:${x.c}"></i><div><div class="font-medium">${esc(x.t)}</div><div class="text-slate-500 text-xs">${esc(x.d)}</div></div></div>`).join('') || '<div class="mt-2 text-sm text-emerald-600">Nothing outstanding.</div>'}</div>
    </div>
  </div>
  <div class="flex gap-1 mt-6 bg-slate-100/70 p-1 rounded-2xl w-fit flex-wrap">${tabs.map(([k, l, n]) => `<a class="tab ${k === tab ? 'active' : ''}" href="#/case/${id}/${k}">${l}${n != null ? `<span class="n">${n}</span>` : ''}</a>`).join('')}</div>
  <div id="tabview" class="mt-4">${skeleton(2)}</div>`;
  $('#btn-run').onclick = () => startRun(id);
  $('#btn-redraft').onclick = async () => { toast('Redrafting…'); try { await api(`/cases/${id}/redraft`, { method: 'POST' }); toast('Dossier rebuilt'); route(); } catch (e) { toast(e.message); } };
  $('#btn-ack').onclick = () => acknowledgeDialog(id, s);
  if (prog.running) watchRun(id);
  initMap(id, s);
  const tv = $('#tabview');
  if (tab === 'plots') renderPlots(tv, id, s);
  else if (tab === 'review') await renderReview(tv, id);
  else if (tab === 'exceptions') await renderExceptions(tv, id);
  else if (tab === 'trace') await renderTrace(tv, id);
  else if (tab === 'documents') await renderDocuments(tv, id);
  else if (tab === 'ledger') await renderLedger(tv, id);
}
function attention(s, pending) {
  const out = [];
  if (pending) out.push({ c: COLORS.EXCEPTION, t: `${pending} plot(s) need a reviewer decision`, d: 'Open the Review tab — CRITICAL and unresolved EXCEPTION flags are never closed by the engine.' });
  s.legality.filter(f => f.severity === 'blocking').forEach(f => out.push({ c: COLORS.CRITICAL, t: 'Blocking legality finding', d: f.detail }));
  (s.trace?.flags || []).forEach(f => out.push({ c: COLORS.EXCEPTION, t: 'Chain-of-custody imbalance', d: f }));
  s.volume.filter(v => v.flag).forEach(v => out.push({ c: COLORS.EXCEPTION, t: 'Volume does not reconcile', d: v.detail }));
  s.open_gaps.filter(g => g.owner === 'supplier').slice(0, 3).forEach(g => out.push({ c: '#64748b', t: `Owed by supplier: ${g.kind.replace(/_/g, ' ')}`, d: g.description }));
  return out.slice(0, 7);
}

async function startRun(id) {
  try { await api(`/cases/${id}/run?background=true`, { method: 'POST' }); $('#btn-run').disabled = true; $('#btn-run').textContent = 'Pipeline running…'; $('#live').hidden = false; watchRun(id); } catch (e) { toast(e.message); }
}
function watchRun(id) {
  clearInterval(state.poll);
  const tick = async () => {
    const p = await api(`/cases/${id}/progress`);
    $('#stepper').innerHTML = stepper(p.status, p.running);
    const live = $('#live'); live.hidden = false;
    live.innerHTML = `<div class="flex items-center gap-4 text-xs text-slate-500 flex-wrap"><span class="pill pill-indigo">${p.running ? 'running' : 'idle'}</span><span>Screened <b>${p.screened}/${p.plots_with_geometry}</b> plots</span><span>Analyst opinions <b>${p.adjudicated}</b></span><span class="truncate max-w-md">${p.recent.length ? esc(p.recent[p.recent.length - 1].actor) + ' · ' + ago(p.recent[p.recent.length - 1].ts) : ''}</span></div>`;
    if (!p.running) { clearInterval(state.poll); state.poll = null; toast(`Pipeline finished: ${statusLabel(p.status)}`); route(); }
  };
  tick(); state.poll = setInterval(tick, 2500);
}

function initMap(id, s) {
  if (!window.L) return;
  const map = L.map('map', { zoomControl: true, attributionControl: true });
  state.map = map;
  const sat = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', { maxZoom: 18, attribution: 'Esri, Maxar, Earthstar Geographics' });
  const light = L.tileLayer('https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png', { maxZoom: 19, attribution: '© OpenStreetMap, © CARTO' });
  sat.addTo(map);
  const overlays = L.layerGroup().addTo(map);
  $('#map-sat').onclick = () => { map.removeLayer(light); sat.addTo(map); };
  $('#map-light').onclick = () => { map.removeLayer(sat); light.addTo(map); };
  let ovOn = true; $('#map-ov').onclick = () => { ovOn = !ovOn; ovOn ? overlays.addTo(map) : map.removeLayer(overlays); };
  api(`/cases/${id}/geojson`).then(fc => {
    if (!fc.features.length) { map.setView([-13, -55.8], 6); return; }
    const marks = L.layerGroup().addTo(map);
    const layer = L.geoJSON(fc, {
      pointToLayer: (f, ll) => L.circleMarker(ll, { radius: 7, color: '#fff', weight: 2, fillColor: COLORS[f.properties.verdict || 'none'], fillOpacity: .95 }),
      style: f => ({ color: COLORS[f.properties.verdict || 'none'], weight: 2.5, fillColor: COLORS[f.properties.verdict || 'none'], fillOpacity: .15 }),
      onEachFeature: (f, l) => {
        const p = f.properties;
        const tip = `<b>${esc(p.name)}</b><br>${esc(p.supplier)} · ${fmt(p.area_ha)} ha<br><span style="color:${COLORS[p.verdict || 'none']};font-weight:700">${p.verdict || 'not screened'}</span>${p.metrics ? ` · forest ${fmt(p.metrics.forest_2020_ha)} ha · converted ${fmt(p.metrics.converted_ha)} ha` : ''}`;
        l.bindTooltip(tip, { sticky: true, className: 'plot-popup' });
        l.on('click', () => openPlot(id, p.id));
        if (f.geometry.type !== 'Point') {
          l.on('mouseover', () => l.setStyle({ weight: 4, fillOpacity: .3 })); l.on('mouseout', () => l.setStyle({ weight: 2.5, fillOpacity: .15 }));
          const c = l.getBounds().getCenter();
          const m = L.circleMarker(c, { radius: 6, color: '#fff', weight: 2, fillColor: COLORS[p.verdict || 'none'], fillOpacity: .95 }).bindTooltip(tip, { sticky: true, className: 'plot-popup' }).on('click', () => openPlot(id, p.id));
          marks.addLayer(m); state.plotLayers[p.id] = l;
        }
        if (p.overlay && p.metrics && (p.metrics.loss_after_cutoff_ha > 0 || p.metrics.forest_2020_ha > 0)) {
          const b = p.overlay.bounds; L.imageOverlay(p.overlay.url, [[b[1], b[0]], [b[3], b[2]]], { opacity: .6, interactive: false }).addTo(overlays);
        }
      }
    }).addTo(map);
    const cents = fc.features.filter(f => f.geometry.type !== 'Point').map(f => { const b = L.geoJSON(f).getBounds(); return b.getCenter(); });
    const med = a => { const s = [...a].sort((x, y) => x - y); return s[Math.floor(s.length / 2)]; };
    const mx = med(cents.map(c => c.lng)), my = med(cents.map(c => c.lat));
    const near = fc.features.filter(f => { if (f.geometry.type === 'Point') return false; const c = L.geoJSON(f).getBounds().getCenter(); return Math.abs(c.lng - mx) < 2 && Math.abs(c.lat - my) < 2; });
    const far = fc.features.length - near.length - fc.features.filter(f => f.geometry.type === 'Point').length;
    map.fitBounds(L.geoJSON({ type: 'FeatureCollection', features: near.length ? near : fc.features }).getBounds().pad(0.12));
    const sync = () => { const z = map.getZoom(); z >= 11 ? map.removeLayer(marks) : marks.addTo(map); };
    map.on('zoomend', sync); sync();
    const ctl = $('.map-ctl'); const fit = document.createElement('button'); fit.className = 'btn btn-sm'; fit.textContent = far ? `All plots (${far} outside view)` : 'All plots'; fit.onclick = () => map.fitBounds(layer.getBounds().pad(0.1)); ctl.appendChild(fit);
  });
}
function zoomPlot(pid) { const l = state.plotLayers[pid]; if (l && state.map) { state.map.fitBounds(l.getBounds().pad(0.6)); l.setStyle({ weight: 5 }); setTimeout(() => l.setStyle({ weight: 2.5 }), 1600); document.getElementById('map').scrollIntoView({ behavior: 'smooth', block: 'center' }); } }

function renderPlots(el, id, s) {
  el.innerHTML = `<div class="grid grid-cols-1 xl:grid-cols-3 gap-6">
    <div class="xl:col-span-2 card"><table><thead><tr><th>Plot</th><th>Supplier</th><th class="text-right">Area ha</th><th>Flag</th><th>Reviewer</th><th></th></tr></thead><tbody>
    ${s.plots.map(p => `<tr class="row" data-plot="${p.id}"><td class="font-medium">${esc(p.name || p.id)}</td><td class="text-slate-500">${esc(p.supplier)}</td><td class="text-right mono">${fmt(p.area_ha)}</td><td>${pill(p.verdict)}</td><td class="text-xs text-slate-400">${esc(p.reviewer || '–')}</td><td class="text-right whitespace-nowrap">${p.has_geometry ? `<button class="btn btn-sm" data-zoom="${p.id}">Map</button> ` : ''}<button class="btn btn-sm btn-primary" data-open="${p.id}">Open</button></td></tr>`).join('')}
    </tbody></table></div>
    <div class="flex flex-col gap-4">
      <div class="card p-5"><div class="eyebrow">Open gaps</div>${s.open_gaps.length ? s.open_gaps.map(g => `<div class="mt-3 text-[13px]"><span class="pill pill-major">${esc(g.kind.replace(/_/g, ' '))}</span><div class="mt-1 text-slate-600">${esc(g.description)}</div><div class="text-[11px] text-slate-400">owner: ${esc(g.owner)}</div></div>`).join('') : '<div class="mt-2 text-sm text-emerald-600">None</div>'}</div>
      <div class="card p-5"><div class="eyebrow">Legality findings</div>${legalityList(s.legality)}</div>
      <div class="card p-5"><div class="eyebrow">Volume reconciliation</div>${s.volume.length ? s.volume.map(v => `<div class="mt-2 text-[13px] ${v.flag ? 'text-rose-600' : 'text-slate-600'}">${v.flag ? '⚠ ' : '✓ '}${esc(v.detail)}</div>`).join('') : '<div class="mt-2 text-sm text-slate-400">None</div>'}</div>
      ${s.risk?.narrative ? `<div class="card p-5 border-indigo-100 bg-indigo-50/30"><div class="eyebrow text-indigo-500">AI risk narrative · Art. 10</div><p class="mt-2 text-[13px] text-slate-600 leading-relaxed">${esc(s.risk.narrative)}</p>${(s.risk.mitigation || []).map(m => `<div class="mt-2 text-[13px] text-slate-600">• ${esc(m)}</div>`).join('')}</div>` : ''}
    </div></div>`;
  $$('[data-open]', el).forEach(b => b.onclick = e => { e.stopPropagation(); openPlot(id, b.dataset.open); });
  $$('[data-zoom]', el).forEach(b => b.onclick = e => { e.stopPropagation(); zoomPlot(b.dataset.zoom); });
  $$('tr[data-plot]', el).forEach(tr => tr.onclick = () => openPlot(id, tr.dataset.plot));
}
function legalityList(legality) {
  const main = legality.filter(f => f.severity !== 'info'), info = legality.filter(f => f.severity === 'info');
  const item = f => `<div class="mt-3 text-[13px]"><span class="pill pill-${{ blocking: 'critical', warning: 'major', info: 'info' }[f.severity]}">${esc(f.severity)} · ${esc(f.layer)}</span><div class="mt-1 text-slate-600">${esc(f.detail)}</div></div>`;
  return (main.map(item).join('') || '<div class="mt-2 text-sm text-emerald-600">No blocking or warning findings</div>') + (info.length ? `<details class="mt-3"><summary class="text-xs text-indigo-600 cursor-pointer">${info.length} informational overlay(s)</summary>${info.map(item).join('')}</details>` : '');
}

/* ---------- plot drawer ---------- */
async function openPlot(id, pid, opts = {}) {
  const d = await api(`/cases/${id}/plots/${pid}`);
  const root = $('#drawer-root');
  root.innerHTML = `<div class="drawer-bg" id="drawer-bg"></div><div class="drawer"><div class="p-6" id="drawer-body">${plotDetail(id, pid, d, opts)}</div></div>`;
  $('#drawer-bg').onclick = closeDrawer;
  bindPlotDetail(id, pid, d, $('#drawer-body'), () => { closeDrawer(); route(); });
}
function closeDrawer() { $('#drawer-root').innerHTML = ''; }
document.addEventListener('keydown', e => { if (e.key === 'Escape') { closeDrawer(); closeModal(); } });

function plotDetail(id, pid, d, opts = {}) {
  const a = d.assessment, m = a?.metrics, op = a?.analyst_opinion;
  const ev = Object.fromEntries((a?.evidence || []).map(e => [e.type, e]));
  const url = t => ev[t] ? evidenceUrl(id, pid, fname(ev[t].uri)) : null;
  const final = a ? (a.override_verdict || a.verdict) : null;
  return `
  <div class="flex items-start justify-between gap-4">
    <div><div class="eyebrow">Plot · ${esc(d.plot.geometry_source || '')}</div><div class="text-[22px] font-semibold tracking-tight leading-tight">${esc(d.plot.name || pid)}</div><div class="text-xs text-slate-400 mono mt-1">${pid} · ${fmt(d.plot.computed_area_ha)} ha · production ${esc(d.plot.production_start || '?')} → ${esc(d.plot.production_end || '?')}</div></div>
    <div class="text-right flex flex-col items-end gap-1">${pill(final)}${a ? `<div class="text-[11px] text-slate-400">engine ${a.verdict} · conf ${a.confidence}</div>` : ''}${opts.close === false ? '' : '<button class="btn btn-sm mt-1" onclick="closeDrawer()">Close <span class="kbd">esc</span></button>'}</div>
  </div>
  ${m ? `<div class="grid grid-cols-2 md:grid-cols-5 gap-3 mt-5">${[['Forest at cut-off', m.forest_2020_ha, 'ha'], ['Loss after cut-off', m.loss_after_cutoff_ha, 'ha'], ['Converted', m.converted_ha, 'ha'], ['First loss', m.first_loss_year || '–', ''], ['Native veg. loss', m.native_vegetation_loss_ha, 'ha']].map(([l, v, u]) => `<div class="metric"><div class="l">${l}</div><div class="n">${fmt(v)}${u ? ` <span class="text-xs text-slate-400 font-medium">${u}</span>` : ''}</div></div>`).join('')}</div>` : '<div class="mt-4 card p-4 text-sm text-slate-500">Not screened — no polygon (or a point standing in for a plot over 4 ha).</div>'}
  ${url('chip_before') && url('chip_after') ? `<div class="grid grid-cols-1 md:grid-cols-2 gap-4 mt-5">
    <div><div class="eyebrow mb-2">Before / after · drag to compare</div><div class="compare" id="cmp"><img src="${url('chip_before')}" alt="before"><img class="after" src="${url('chip_after')}" alt="after"><div class="handle"></div><span class="lbl" style="left:.5rem">Before · ${esc(ev.chip_before.captured_at || '')}</span><span class="lbl" style="right:.5rem">After · ${esc(ev.chip_after.captured_at || '')}</span><input type="range" min="0" max="100" value="50" id="cmp-range"></div><div class="text-[10.5px] text-slate-400 mt-1">${esc(ev.chip_before.source)} · ${esc(ev.chip_before.meta?.scene || '')} → ${esc(ev.chip_after.meta?.scene || '')} · cloud ${ev.chip_after.meta?.cloud_pct ?? '–'}%</div></div>
    <div><div class="eyebrow mb-2">Change classification</div><div class="thumb" style="aspect-ratio:1;display:flex;align-items:center;justify-content:center;overflow:hidden"><img src="${url('loss_overlay')}" style="object-fit:contain;max-height:100%"></div><div class="text-[10.5px] text-slate-400 mt-1">Forest at 2020‑12‑31 (green) · loss after cut-off (orange) · converted to agriculture (red) · native vegetation → crop (tan)</div></div>
  </div>` : (url('loss_overlay') ? `<div class="mt-5 thumb"><img src="${url('loss_overlay')}"></div>` : '')}
  ${ev.ndvi_series ? `<div class="card p-4 mt-5"><div class="flex items-center justify-between"><div class="eyebrow">Mean NDVI inside the plot</div><div class="text-[10.5px] text-slate-400">${ev.ndvi_series.meta?.points ?? ''} cloud-free scenes · red line = cut-off</div></div><div style="height:170px"><canvas id="ndvi"></canvas></div></div>` : ''}
  ${op ? `<div class="mt-5 card p-4 border-indigo-100 bg-indigo-50/40"><div class="flex items-center justify-between"><div class="eyebrow text-indigo-500">AI analyst opinion · ${esc(op.model)}</div><span class="pill pill-${op.recommended_verdict}">${esc(op.recommended_verdict)} · ${(op.confidence * 100).toFixed(0)}%</span></div><div class="mt-2 text-sm leading-relaxed">${esc(op.rationale)}</div>${op.cited_evidence?.length ? `<div class="mt-2 text-[11px] text-slate-500">cited: ${op.cited_evidence.map(esc).join(', ')}</div>` : ''}${op.flags?.length ? `<div class="mt-1 text-[11px] text-slate-500">flags: ${op.flags.map(esc).join(', ')}</div>` : ''}</div>` : ''}
  ${a?.reviewer ? `<div class="mt-4 card p-4 border-emerald-100 bg-emerald-50/40 text-sm"><div class="eyebrow text-emerald-600">Reviewer decision</div><div class="mt-1">${esc(a.reviewer)} · ${esc((a.reviewed_at || '').replace('T', ' ').slice(0, 16))}${a.override_verdict ? ` — override → <b>${a.override_verdict}</b>: ${esc(a.override_reason)}` : a.override_reason ? ' — ' + esc(a.override_reason) : ' — approved engine flag'}</div></div>` : (a && ['EXCEPTION', 'CRITICAL'].includes(a.verdict) ? reviewForm(a.id) : '')}
  ${d.gaps?.length ? `<div class="mt-4"><div class="eyebrow">Gaps on this plot</div>${d.gaps.map(g => `<div class="text-[13px] text-slate-600 mt-1">• ${esc(g.description)}${g.resolved ? ' <span class="text-emerald-600">(resolved)</span>' : ''}</div>`).join('')}</div>` : ''}
  <div class="mt-5 text-[11px] text-slate-400">Datasets: ${(a?.evidence || []).filter(e => e.type === 'dataset').map(e => esc(e.source + ' ' + (e.source_version || ''))).join(' · ') || '–'} · assessment ${a?.id || '–'} · hash ${(a?.hash || '').slice(0, 12)}</div>`;
}
function bindPlotDetail(id, pid, d, root, onDecision) {
  const rng = $('#cmp-range', root); if (rng) rng.oninput = () => $('#cmp', root).style.setProperty('--x', rng.value + '%');
  const ev = (d.assessment?.evidence || []).find(e => e.type === 'ndvi_series');
  if (ev && $('#ndvi', root)) fetch(evidenceUrl(id, pid, fname(ev.uri))).then(r => r.json()).then(pts => ndviChart($('#ndvi', root), pts));
  bindReviewForm(id, root, onDecision);
}
function ndviChart(el, pts) {
  if (!window.Chart || !pts.length) return;
  const cutoff = new Date('2020-12-31');
  const labels = pts.map(p => p.date);
  const ci = labels.findIndex(l => new Date(l) > cutoff);
  state.charts.push(new Chart(el, { type: 'line', data: { labels, datasets: [{ data: pts.map(p => p.ndvi), borderColor: '#4f46e5', backgroundColor: 'rgba(79,70,229,.08)', fill: true, tension: .3, pointRadius: 2.5, pointBackgroundColor: '#4f46e5' }] },
    options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false }, tooltip: { callbacks: { label: c => `NDVI ${c.parsed.y.toFixed(2)} · ${pts[c.dataIndex].scene}` } } },
      scales: { y: { min: 0, max: 1, grid: { color: '#f1f5f9' }, ticks: { font: { size: 10 }, color: '#94a3b8' } }, x: { grid: { display: false }, ticks: { font: { size: 10 }, color: '#94a3b8', maxTicksLimit: 8 } } } },
    plugins: [{ id: 'cut', afterDraw: c => { if (ci < 0) return; const x = c.scales.x.getPixelForValue(Math.max(0, ci - .5)); const g = c.ctx; g.save(); g.strokeStyle = '#e11d48'; g.setLineDash([4, 3]); g.beginPath(); g.moveTo(x, c.chartArea.top); g.lineTo(x, c.chartArea.bottom); g.stroke(); g.restore(); } }] }));
}
const reviewForm = aid => `<div class="mt-5 card p-4" data-review="${aid}">
  <div class="eyebrow">Reviewer decision</div>
  <div class="flex flex-wrap gap-2 mt-3 items-center">
    <button class="btn btn-primary" data-act="approve">Approve engine flag</button>
    <span class="text-xs text-slate-400 px-1">or</span>
    <select data-field="verdict" style="width:auto"><option value="PASS">Override → PASS</option><option value="EXCEPTION">Override → EXCEPTION</option><option value="CRITICAL">Override → CRITICAL</option></select>
    <input data-field="reason" placeholder="Justification — required, goes on the ledger" style="flex:1;min-width:220px">
    <button class="btn btn-danger" data-act="override">Override</button>
  </div><div class="text-[11px] text-slate-400 mt-2">Recorded against <b>${esc(reviewer() || 'no reviewer set')}</b>. This is an evidence review, not a conformity decision.</div></div>`;
function bindReviewForm(id, root, onDone) {
  $$('[data-review]', root).forEach(box => {
    const aid = box.dataset.review;
    $('[data-act="approve"]', box).onclick = async () => {
      if (!reviewer()) return toast('Enter your reviewer identity in the sidebar first');
      try { await api(`/cases/${id}/assessments/${aid}/approve`, { method: 'POST', body: JSON.stringify({ reviewer: reviewer() }) }); toast('Approved'); onDone?.(); } catch (e) { toast(e.message); }
    };
    $('[data-act="override"]', box).onclick = async () => {
      if (!reviewer()) return toast('Enter your reviewer identity in the sidebar first');
      const verdict = $('[data-field="verdict"]', box).value, reason = $('[data-field="reason"]', box).value.trim();
      try { await api(`/cases/${id}/assessments/${aid}/override`, { method: 'POST', body: JSON.stringify({ reviewer: reviewer(), verdict, reason }) }); toast(`Overridden → ${verdict}`); onDone?.(); } catch (e) { toast(e.message, 5000); }
    };
  });
}

/* ---------- review workspace ---------- */
async function pageReview(id) { view.innerHTML = '<div id="tabview"></div>'; await renderReview($('#tabview'), id); }
async function renderReview(el, id) {
  const [q, s] = await Promise.all([api(`/cases/${id}/review`), api(`/cases/${id}`)]);
  const reviewed = s.plots.filter(p => p.verdict && p.verdict !== 'PASS' && p.reviewer);
  const total = q.length + reviewed.length;
  if (!q.length) { el.innerHTML = `<div class="card p-10 text-center"><div class="text-emerald-600 font-semibold text-lg">Queue is clear</div><p class="text-sm text-slate-500 mt-1">${reviewed.length} decision(s) recorded. Redraft the dossier, then acknowledge it from the case page.</p><div class="flex gap-2 justify-center mt-4"><a class="btn" href="#/case/${id}">Back to case</a></div></div>`; return; }
  let i = 0;
  el.innerHTML = `<div class="grid grid-cols-1 xl:grid-cols-[320px_1fr] gap-5">
    <div class="card"><div class="card-hd"><div><div class="card-title">Queue</div><div class="text-xs text-slate-400">${reviewed.length} of ${total} decided</div></div><span class="kbd">j</span><span class="kbd">k</span></div><div class="p-2" id="rq-list"></div><div class="px-4 pb-4">${flagBar({ PASS: reviewed.length, EXCEPTION: q.length, CRITICAL: 0 })}</div></div>
    <div id="rq-detail" class="card p-6"></div></div>`;
  const list = $('#rq-list'), detail = $('#rq-detail');
  const draw = () => { list.innerHTML = q.map((x, k) => `<div class="p-3 rounded-xl cursor-pointer ${k === i ? 'bg-indigo-50' : 'hover:bg-slate-50'}" data-k="${k}"><div class="flex items-center justify-between gap-2"><div class="font-medium text-[13px] truncate">${esc(x.plot)}</div>${pill(x.verdict)}</div><div class="text-[11px] text-slate-400 mt-1">${x.metrics ? `converted ${fmt(x.metrics.converted_ha)} ha · loss ${fmt(x.metrics.loss_after_cutoff_ha)} ha` : ''}${x.analyst ? ` · analyst ${x.analyst.recommended_verdict} ${(x.analyst.confidence * 100).toFixed(0)}%` : ''}</div></div>`).join(''); $$('[data-k]', list).forEach(n => n.onclick = () => { i = +n.dataset.k; show(); }); };
  const show = async () => { draw(); detail.innerHTML = skeleton(2); const d = await api(`/cases/${id}/plots/${q[i].plot_id}`); state.charts.forEach(c => c.destroy()); state.charts = []; detail.innerHTML = plotDetail(id, q[i].plot_id, d, { close: false }); bindPlotDetail(id, q[i].plot_id, d, detail, () => renderReview(el, id)); };
  document.onkeydown = e => { if (e.target.tagName === 'INPUT' || e.target.tagName === 'SELECT') return; if (e.key === 'j') { i = Math.min(q.length - 1, i + 1); show(); } if (e.key === 'k') { i = Math.max(0, i - 1); show(); } };
  show();
}

async function acknowledgeDialog(id, s) {
  const q = await api(`/cases/${id}/review`);
  const critic = s.dossier?.critic_report;
  modal(`<div class="eyebrow">Reviewer acknowledgement</div><div class="text-xl font-semibold mt-1">Acknowledge the advisory dossier</div>
  <p class="text-sm text-slate-500 mt-2 leading-relaxed">Records that the named reviewer has seen the evidence dossier. It is not a conformity decision, issues no certificate, and submits nothing in pilot mode.</p>
  <div class="mt-4 text-sm flex flex-col gap-1">${q.length ? `<div class="text-rose-600">⚠ ${q.length} plot(s) still unreviewed — acknowledgement will be refused.</div>` : '<div class="text-emerald-600">✓ Every EXCEPTION and CRITICAL plot has a reviewer decision.</div>'}
  ${critic ? `<div class="${critic.ok ? 'text-emerald-600' : 'text-amber-600'}">${critic.ok ? '✓' : '⚠'} Critic: ${esc(critic.summary)}</div>${(critic.issues || []).slice(0, 8).map(i => `<div class="text-xs text-slate-500">[${esc(i.severity)}] ${esc(i.subject_ref)}: ${esc(i.detail)}</div>`).join('')}` : ''}</div>
  <label class="flex items-center gap-2 mt-4 text-xs text-slate-600"><input type="checkbox" id="ack-critic"> Acknowledge critic issues and proceed anyway</label>
  <div class="flex gap-2 mt-5"><button class="btn btn-primary" id="ack-go">Acknowledge as ${esc(reviewer() || '(set reviewer in sidebar)')}</button><button class="btn" onclick="closeModal()">Cancel</button></div>`);
  $('#ack-go').onclick = async () => {
    if (!reviewer()) return toast('Enter your reviewer identity in the sidebar first');
    try { await api(`/cases/${id}/acknowledge`, { method: 'POST', body: JSON.stringify({ reviewer: reviewer(), acknowledge_critic: $('#ack-critic').checked }) }); toast('Dossier acknowledged'); closeModal(); route(); } catch (e) { toast(e.message, 6000); }
  };
}

/* ---------- exceptions ---------- */
async function pageExceptions(id) { view.innerHTML = '<div id="tabview"></div>'; await renderExceptions($('#tabview'), id); }
async function renderExceptions(el, id) {
  const ex = await api(`/cases/${id}/exceptions`);
  const by = {}; ex.forEach(e => by[e.severity] = (by[e.severity] || 0) + 1);
  const cats = [...new Set(ex.map(e => e.category))];
  const f = { sev: new Set(), cat: new Set(), q: '' };
  el.innerHTML = `<div class="card"><div class="card-hd flex-wrap"><div class="flex gap-2 flex-wrap items-center"><span class="eyebrow mr-1">Severity</span>${['critical', 'major', 'minor', 'info'].map(s => `<button class="filter-chip" data-sev="${s}">${s} <b>${by[s] || 0}</b></button>`).join('')}<span class="eyebrow ml-3 mr-1">Category</span>${cats.map(c => `<button class="filter-chip" data-cat="${c}">${c}</button>`).join('')}</div><div class="flex gap-2 items-center"><input id="ex-q" placeholder="Search…" style="width:200px"><a class="btn btn-sm" href="/cases/${id}/exceptions.csv">CSV</a></div></div><div id="ex-body"></div></div>`;
  const body = $('#ex-body');
  const draw = () => {
    const rows = ex.filter(e => (!f.sev.size || f.sev.has(e.severity)) && (!f.cat.size || f.cat.has(e.category)) && (!f.q || (e.detail + e.subject_label).toLowerCase().includes(f.q)));
    body.innerHTML = `<table><thead><tr><th>Sev</th><th>Category</th><th>Subject</th><th>Detail</th><th>Owner</th><th>Evidence</th></tr></thead><tbody>${rows.map((e, k) => `<tr class="row" data-k="${k}"><td>${pill(e.severity, e.severity)}</td><td class="text-slate-500 text-xs">${esc(e.category)}</td><td class="font-medium">${esc(e.subject_label)}</td><td class="text-slate-600 max-w-2xl">${esc(e.detail)}</td><td class="text-xs text-slate-400">${esc(e.owner)}<br>${esc(e.status)}</td><td class="text-xs">${e.citations.length ? `<span class="pill pill-indigo">${e.citations.length} citation${e.citations.length > 1 ? 's' : ''}</span>` : ''}${e.evidence_uris?.length ? `<span class="pill pill-info">${e.evidence_uris.length} files</span>` : ''}</td></tr><tr class="ex-x" hidden><td colspan="6" class="bg-slate-50"><div class="flex gap-4 flex-wrap p-2">${e.citations.map(c => `<a class="thumb w-72 block" href="#" data-cite='${esc(JSON.stringify({ u: c.image_uri, f: c.file, p: c.page, s: c.snippet }))}'>${c.image_uri ? `<img src="${citationUrl(id, c.image_uri)}">` : ''}<div class="cap"><b>${esc(c.file)}</b> p${c.page} — “${esc(c.snippet).slice(0, 90)}…”</div></a>`).join('')}${(e.evidence_uris || []).filter(u => /png$/.test(u)).map(u => `<div class="thumb w-40"><img src="/cases/${id}/evidence/${e.subject_ref}/${fname(u)}"><div class="cap">${fname(u).replace('.png', '').replace('_', ' ')}</div></div>`).join('')}${!e.citations.length && !(e.evidence_uris || []).length ? '<div class="text-xs text-slate-400 p-2">No attached evidence — derived from tables or overlays.</div>' : ''}</div></td></tr>`).join('') || '<tr><td colspan="6" class="text-center text-slate-400 py-8">Nothing matches.</td></tr>'}</tbody></table>`;
    $$('tr.row', body).forEach(tr => tr.onclick = () => { const x = tr.nextElementSibling; x.hidden = !x.hidden; });
    bindCitations(body, id);
  };
  $$('[data-sev]', el).forEach(b => b.onclick = () => { b.classList.toggle('on'); b.classList.contains('on') ? f.sev.add(b.dataset.sev) : f.sev.delete(b.dataset.sev); draw(); });
  $$('[data-cat]', el).forEach(b => b.onclick = () => { b.classList.toggle('on'); b.classList.contains('on') ? f.cat.add(b.dataset.cat) : f.cat.delete(b.dataset.cat); draw(); });
  $('#ex-q').oninput = e => { f.q = e.target.value.toLowerCase(); draw(); };
  draw();
}
function bindCitations(el, id) {
  $$('[data-cite]', el).forEach(a => a.onclick = ev => { ev.preventDefault(); ev.stopPropagation(); const c = JSON.parse(a.dataset.cite);
    modal(`<div class="eyebrow">Visual citation</div><div class="font-semibold mt-1">${esc(c.f)} · page ${c.p}</div><div class="text-sm text-slate-500 mt-1">“${esc(c.s)}”</div>${c.u ? `<img class="mt-4 rounded-xl border border-slate-200 w-full" src="${citationUrl(id, c.u)}">` : '<div class="mt-3 text-sm text-slate-400">No rendered image for this citation.</div>'}`); });
}

/* ---------- trace ---------- */
async function renderTrace(el, id) {
  const t = await api(`/cases/${id}/trace`);
  if (!t || !t.edges.length) { el.innerHTML = '<div class="card p-10 text-center text-slate-400 text-sm">No chain-of-custody documents parsed in this package.</div>'; return; }
  const names = Object.fromEntries(t.nodes.map(n => [n.id, n]));
  const tiers = ['farm', 'cooperative', 'silo', 'crusher', 'trader', 'exporter', 'port', 'unknown'];
  const byTier = {}; t.nodes.forEach(n => (byTier[n.tier] = byTier[n.tier] || []).push(n));
  const flow = (nid, dir) => t.edges.filter(e => e[dir] === nid).reduce((a, e) => a + e.tonnes, 0);
  el.innerHTML = `<div class="grid grid-cols-1 xl:grid-cols-3 gap-6">
    <div class="xl:col-span-2 card p-5"><div class="eyebrow mb-3">Custody flow · tonnes by tier</div><div class="flex gap-6 overflow-x-auto pb-2">${tiers.filter(k => byTier[k]).map(k => `<div class="min-w-[200px]"><div class="eyebrow mb-2">${k}</div>${byTier[k].map(n => { const inn = flow(n.id, 'target'), out = flow(n.id, 'source'); const bad = t.checks.find(c => c.node_id === n.id && c.flag); return `<div class="card p-3 mb-2 ${bad ? 'border-rose-200 bg-rose-50/40' : ''}"><div class="font-medium text-[13px] truncate">${esc(n.name)}</div><div class="text-[11px] text-slate-500 mt-1">${inn ? `in ${fmt(inn, 0)} t` : ''}${inn && out ? ' · ' : ''}${out ? `out ${fmt(out, 0)} t` : ''}</div>${bad ? `<div class="text-[11px] text-rose-600 mt-1">⚠ ${fmt(bad.delta_t, 0)} t unexplained</div>` : ''}${n.supplier_id ? '<span class="pill pill-info mt-1">linked supplier</span>' : ''}</div>`; }).join('')}</div>`).join('<div class="self-center text-slate-300 text-2xl">→</div>')}</div>
      <table class="mt-4"><thead><tr><th>From</th><th>To</th><th class="text-right">Tonnes</th><th>Lot</th><th>Document</th><th>Citation</th></tr></thead><tbody>${t.edges.map(e => `<tr><td>${esc(names[e.source]?.name)}</td><td>${esc(names[e.target]?.name)}</td><td class="text-right mono">${fmt(e.tonnes, 0)}</td><td class="text-xs">${esc(e.lot_reference || '')}</td><td class="text-xs text-slate-500">${esc(e.doc_ref || '')}</td><td>${e.citation ? `<a href="#" class="text-indigo-600 text-xs font-semibold" data-cite='${esc(JSON.stringify({ u: e.citation.image_uri, f: e.citation.file, p: e.citation.page, s: e.citation.snippet }))}'>${esc(e.citation.file)} p${e.citation.page}</a>` : ''}</td></tr>`).join('')}</tbody></table></div>
    <div class="card p-5"><div class="eyebrow">Mass balance checks</div>${t.checks.map(c => `<div class="mt-3 text-[13px] ${c.flag ? 'text-rose-600' : 'text-slate-600'}">${c.flag ? '⚠ ' : '✓ '}${esc(c.detail)}</div>`).join('') || '<div class="text-sm text-slate-400 mt-2">None</div>'}<div class="text-[11px] text-slate-400 mt-4">Source: ${t.source_docs.map(esc).join(', ')}</div></div></div>`;
  bindCitations(el, id);
}

/* ---------- documents ---------- */
async function pageDocuments(id) { view.innerHTML = '<div id="tabview"></div>'; await renderDocuments($('#tabview'), id); }
async function renderDocuments(el, id) {
  const docs = await api(`/cases/${id}/documents`);
  if (!docs.length) { el.innerHTML = '<div class="card p-10 text-center text-slate-400 text-sm">No documents in this package.</div>'; return; }
  let sel = 0, page = 1;
  el.innerHTML = `<div class="grid grid-cols-1 xl:grid-cols-[300px_1fr_300px] gap-5"><div class="card p-2" id="doc-list"></div><div class="card p-4" id="doc-page"></div><div class="card p-4" id="doc-cites"></div></div>`;
  const draw = () => {
    $('#doc-list').innerHTML = docs.map((d, k) => `<div class="p-3 rounded-xl cursor-pointer ${k === sel ? 'bg-indigo-50' : 'hover:bg-slate-50'}" data-k="${k}"><div class="font-medium text-[13px] truncate">${esc(d.file)}</div><div class="text-[11px] text-slate-400 mt-0.5">${esc(d.kind.replace(/_/g, ' '))} · ${d.pages} p · ${d.citations.length} citations</div>${d.ocr_pages ? '<span class="pill pill-minor mt-1">scanned · OCR</span>' : '<span class="pill pill-info mt-1">text layer</span>'}</div>`).join('');
    $$('[data-k]', $('#doc-list')).forEach(n => n.onclick = () => { sel = +n.dataset.k; page = 1; draw(); });
    const d = docs[sel]; const stem = d.file.replace(/\.[^.]+$/, '');
    const cites = d.citations.filter(c => c.page === page);
    $('#doc-page').innerHTML = `<div class="flex items-center justify-between mb-3"><div><div class="font-semibold">${esc(d.file)}</div><div class="text-xs text-slate-400">page ${page} of ${d.pages} · ${cites.length} citation(s) on this page</div></div><div class="flex gap-1"><button class="btn btn-sm" id="pg-prev" ${page <= 1 ? 'disabled' : ''}>‹</button><button class="btn btn-sm" id="pg-next" ${page >= d.pages ? 'disabled' : ''}>›</button></div></div>
      <div class="relative inline-block w-full border border-slate-200 rounded-xl overflow-hidden bg-white" id="pg-wrap"><img id="pg-img" src="/cases/${id}/pages/${encodeURIComponent(stem)}_p${page}.png" class="w-full block" alt="page ${page}"></div>`;
    $('#pg-prev').onclick = () => { page--; draw(); }; $('#pg-next').onclick = () => { page++; draw(); };
    const img = $('#pg-img');
    img.onload = () => { const s = img.clientWidth / img.naturalWidth * (110 / 72); cites.forEach((c, k) => { const b = document.createElement('div'); b.className = 'cite-box'; b.dataset.k = k; b.title = `${c.field}: ${c.value}`; b.style.left = c.bbox[0] * s + 'px'; b.style.top = c.bbox[1] * s + 'px'; b.style.width = (c.bbox[2] - c.bbox[0]) * s + 'px'; b.style.height = (c.bbox[3] - c.bbox[1]) * s + 'px'; b.onmouseenter = () => hl(k, true); b.onmouseleave = () => hl(k, false); $('#pg-wrap').appendChild(b); }); };
    const byField = {}; d.citations.forEach(c => (byField[c.field] = byField[c.field] || []).push(c));
    $('#doc-cites').innerHTML = `<div class="eyebrow mb-2">Extracted fields</div>${Object.entries(byField).map(([f, cs]) => `<div class="mb-3"><div class="text-[11px] font-semibold text-slate-500">${esc(f.replace(/_/g, ' '))}</div>${cs.map(c => `<div class="text-[12.5px] py-1 cursor-pointer rounded px-1 hover:bg-indigo-50 ${c.page === page ? '' : 'text-slate-400'}" data-cp="${c.page}" data-ck="${cites.indexOf(c)}"><span class="mono">${esc(c.value).slice(0, 44)}</span> <span class="text-[10px] text-slate-400">p${c.page}</span></div>`).join('')}</div>`).join('') || '<div class="text-sm text-slate-400">No fields recognised on this document.</div>'}`;
    $$('[data-cp]', $('#doc-cites')).forEach(n => { n.onclick = () => { if (+n.dataset.cp !== page) { page = +n.dataset.cp; draw(); } else hl(+n.dataset.ck, true, true); }; });
  };
  const hl = (k, on, scroll) => { const b = $(`.cite-box[data-k="${k}"]`); if (!b) return; b.classList.toggle('hl', on); if (scroll) b.scrollIntoView({ block: 'center', behavior: 'smooth' }); };
  draw();
}

/* ---------- ledger ---------- */
async function renderLedger(el, id) {
  const L = await api(`/cases/${id}/ledger?n=300`);
  el.innerHTML = `<div class="card"><div class="card-hd"><div><div class="card-title">Hash-chained ledger</div><div class="text-xs text-slate-400">${L.length} entries · every tool call, agent step and human action</div></div></div><table><thead><tr><th>Time</th><th>Kind</th><th>Actor</th><th>Payload</th><th>Hash</th></tr></thead><tbody>${L.slice().reverse().map(e => `<tr><td class="mono text-slate-400 whitespace-nowrap">${e.ts.slice(0, 19).replace('T', ' ')}</td><td>${pill(e.kind.replace('_', ' '), { human_action: 'critical', agent_step: 'minor', agent_error: 'major', tool_call: 'info', state_change: 'pass' }[e.kind])}</td><td class="text-xs font-medium">${esc(e.actor)}</td><td class="text-xs text-slate-500 max-w-2xl truncate">${esc(JSON.stringify(e.payload)).slice(0, 200)}</td><td class="mono text-slate-300">${e.hash.slice(0, 10)}</td></tr>`).join('')}</tbody></table></div>`;
}

/* ---------- roi ---------- */
async function pageRoi() {
  const r = await api('/reports/roi');
  view.innerHTML = `<div class="grid grid-cols-2 md:grid-cols-4 gap-4">${kpi('Packages', r.cases)}${kpi('Plots screened', r.plots_screened)}${kpi('Pages parsed', r.pages_parsed, 'text-ink', `${r.ocr_pages} via OCR`)}${kpi('Visual citations', r.citations, 'text-indigo-600')}${kpi('Exceptions raised', r.exceptions, 'text-amber-600')}${kpi('Automated steps', r.tool_calls + r.agent_steps, 'text-ink', `${r.agent_steps} agent · ${r.tool_calls} tool`)}${kpi('Engine time', `${fmt(r.wall_minutes_total, 0)}<span class="text-base text-slate-400"> min</span>`)}${kpi('Manual hours displaced', r.estimated_manual_hours, 'text-emerald-600', 'estimate — see assumptions')}</div>
  <div class="grid grid-cols-1 xl:grid-cols-3 gap-6 mt-6">
    <div class="card p-5"><div class="eyebrow">Exceptions by category</div><div style="height:220px"><canvas id="catChart"></canvas></div></div>
    <div class="card p-5"><div class="eyebrow">Flags across packages</div><div class="flex items-center gap-5 mt-3"><div style="width:130px;height:130px"><canvas id="flagChart2"></canvas></div><div class="text-sm flex flex-col gap-1.5">${['PASS', 'EXCEPTION', 'CRITICAL'].map(k => `<div class="flex items-center gap-2"><i class="w-2.5 h-2.5 rounded-sm" style="background:${COLORS[k]}"></i><span class="text-slate-500">${k.toLowerCase()}</span><b class="ml-auto pl-4">${r.flags[k]}</b></div>`).join('')}</div></div><div class="eyebrow mt-5">Assumed minutes per item</div><div class="mt-2 text-xs text-slate-500 leading-relaxed">${Object.entries(r.assumptions_minutes).map(([k, v]) => `${esc(k.replace(/_/g, ' '))} <b>${v}</b>`).join(' · ')}<br>To be replaced by Control Union's own benchmarks in Phase 1.</div></div>
    <div class="card p-5 bg-night text-white border-0"><div class="eyebrow text-slate-400">Governance</div><p class="mt-2 text-sm text-slate-300 leading-relaxed">${esc(r.note)}</p><div class="mt-4 text-xs text-slate-500">Generated ${esc(r.generated_at.slice(0, 16).replace('T', ' '))}</div><div class="mt-3 text-[11px] text-slate-500 break-all">${esc(r.files?.md || '')}</div></div>
  </div>`;
  donut('flagChart2', ['PASS', 'EXCEPTION', 'CRITICAL'].map(k => r.flags[k]), ['PASS', 'EXCEPTION', 'CRITICAL'].map(k => COLORS[k]));
  const cats = Object.entries(r.exceptions_by_category);
  if (window.Chart && cats.length) state.charts.push(new Chart($('#catChart'), { type: 'bar', data: { labels: cats.map(c => c[0]), datasets: [{ data: cats.map(c => c[1]), backgroundColor: '#4f46e5', borderRadius: 6 }] }, options: { indexAxis: 'y', plugins: { legend: { display: false } }, scales: { x: { grid: { color: '#f1f5f9' }, ticks: { font: { size: 10 }, color: '#94a3b8', precision: 0 } }, y: { grid: { display: false }, ticks: { font: { size: 11 }, color: '#475569' } } }, maintainAspectRatio: false } }));
}

route();
