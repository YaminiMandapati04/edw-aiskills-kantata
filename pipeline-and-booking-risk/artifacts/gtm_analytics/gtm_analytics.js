/* GTM diagnostic renderer 1.11.0 (contract sda.gtm-analysis/2.0.0). Three tabs on the finance renderer 1.6.0 layout:
   Pipeline (opens first), Bookings, Outlook. Each tab leads with an executive summary of 3 to 5 bullets and side cards,
   then a strip of figures "at a glance", then one chart beside the decisions for management; every table and deal list
   sits in a drill-down. The renderer computes nothing economic: it formats, arranges, filters and sorts values the engine
   emitted. Permitted arithmetic: chart geometry, sums of engine-emitted monthly series over a driver's members.
   Null renders as "—", never as zero. Negatives print in brackets. */
'use strict';
const P = window.__SDA_PAYLOAD__;
if (!P || P.contract_version !== 'sda.gtm-analysis/2.0.0') { document.body.innerHTML = '<div style="padding:40px;font-family:sans-serif">Refused: payload contract is not sda.gtm-analysis/2.0.0.</div>'; throw new Error('contract'); }
const META = P.meta, PIPE = P.pipeline, SIG = P.signals, SER = P.series, OUT = P.outlook, RK = P.risk || null;
const MONTHS = META.months, AS = MONTHS.length - 1, MONTH = META.as_of.month;
const DRV_BY = Object.fromEntries(P.drivers.map(d => [d.id, d]));
const KPI_SERIES = { total: ['total'], arr_new: ['m:arr_new'], arr_upsell: ['m:arr_upsell'], non_recurring: ['m:non_recurring'], recurring: ['m:arr_new', 'm:arr_upsell'] };
const PERSIST = { one_off_candidate: ['One-off', 'amb'], recurring_level_change: ['New level', 'sky'], seasonal: ['Seasonal', 'sky'], undetermined: null };
const DIM_LABEL = { measure: 'Measure', product: 'Product', subsidiary: 'Subsidiary' };
const VERSION = '1.11.0';

/* ---------- formatting ---------- */
const $ = (s, r = document) => r.querySelector(s);
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const isNum = v => typeof v === 'number' && isFinite(v);
function money(v, { sign = false } = {}) {
  if (!isNum(v)) return '—';
  const a = Math.abs(v); let s;
  if (a < 1000) s = '$' + a.toFixed(0); else if (a < 10000) s = '$' + (a / 1e3).toFixed(1) + 'k'; else if (a < 1e6) s = '$' + Math.round(a / 1e3).toLocaleString('en-US') + 'k';
  else if (a < 10e6) s = '$' + (a / 1e6).toFixed(2) + 'mn'; else if (a < 100e6) s = '$' + (a / 1e6).toFixed(1) + 'mn'; else s = '$' + Math.round(a / 1e6).toLocaleString('en-US') + 'mn';
  if (v < 0 && a >= 0.5) return '(' + s + ')';
  return (sign && v >= 0.5) ? '+' + s : s;
}
function full(v, { sign = false } = {}) {
  if (!isNum(v)) return '—';
  const s = '$' + Math.abs(Math.round(v)).toLocaleString('en-US');
  if (v < -0.5) return '(' + s + ')';
  return (sign && v > 0.5) ? '+' + s : s;
}
function pct(v, { sign = false, dec = 1 } = {}) {
  if (!isNum(v)) return '—';
  if (Math.abs(v) >= 10) return 'n.m.';
  const s = (Math.abs(v) * 100).toFixed(dec) + '%';
  if (v < 0 && Math.abs(v) * 100 >= 0.05) return '(' + s + ')';
  return (sign && v > 0) ? '+' + s : s;
}
/* a change in a rate or margin, in basis points (0.011 -> +110 bps; 100 bps = 1 percentage point) */
function pts(v) {
  if (!isNum(v)) return '—';
  const b = Math.round(Math.abs(v) * 10000), s = b.toLocaleString('en-US') + ' bps';
  if (b === 0) return '0 bps';
  return v < 0 ? '(' + b.toLocaleString('en-US') + ') bps' : '+' + s;
}
const days = v => isNum(v) ? `${v.toFixed(0)} days` : '—';
const dDays = v => !isNum(v) ? '—' : Math.abs(v) < 0.5 ? '0 days' : v < 0 ? `(${Math.abs(v).toFixed(0)}) days` : `+${v.toFixed(0)} days`;
const mult = v => isNum(v) ? v.toFixed(1) + '×' : '—';
const tone = (v, floor) => !isNum(v) || Math.abs(v) < (floor ?? L().materiality.monitoring_abs) ? 'neu' : (v > 0 ? 'fav' : 'unf');
const toneWord = t => ({ fav: 'Favourable', unf: 'Unfavourable', neu: 'In line' })[t];
const tag = (t, word) => `<span class="tag ${t}">${esc(word || toneWord(t))}</span>`;
const persistTag = h => PERSIST[h] ? tag(PERSIST[h][1], PERSIST[h][0]) : '';
const cap = s => s ? s[0].toUpperCase() + s.slice(1) : s;
const pl = (n, one, many) => `${n} ${n === 1 ? one : (many || one + 's')}`;
/* engine prose in the finance page's plain words: brackets for negatives, mn not mm, no "adverse", no "mechanical" */
const clean = t => String(t || '').replace(/adverse/g, 'unfavourable').replace(/Adverse/g, 'Unfavourable').replace(/(\d)mm\b/g, '$1mn')
  .replace(/A mechanical range/g, 'A straight-line range').replace(/\bmechanical\b/g, 'straight-line')
  .replace(/−\s?(\$?[\d.,]+(?:k|mn|%)?)/g, '($1)');
/* data state, as on the finance page: governed and tied to both KPI marts = verified */
const CHK = id => ((P.qc.checks || []).find(c => c.id === id) || {}).result;
const VERIFIED = META.data_mode !== 'local' && CHK('mart_tie_out') === 'PASS' && (CHK('as_of_alignment') === 'PASS' || CHK('open_pipeline_tie_out') === 'PASS') && CHK('as_of_alignment') !== 'FAIL';
const baseMark = () => META.data_mode === 'local' ? '<span class="tag unf">Test data</span>' : VERIFIED ? '<span class="tag fav">Data verified</span>' : '<span class="tag amb">From the data</span>';

/* ---------- state and lens access ---------- */
const S = { tab: 'pipeline', lens: META.primary_lens.id, drawer: null, drawerTab: null, moveMode: 'by_product', opener: null, hvList: 'all', hvOpen: false };
const L = () => P.lenses[S.lens];
const kpi = id => L().kpis.find(k => k.id === id);
const dimOf = mode => ({ by_measure: 'measure', by_product: 'product', by_subsidiary: 'subsidiary' })[mode];
const ldrv = id => { for (const k of ['measure', 'product', 'subsidiary']) { const r = L().drivers[k].find(d => d.id === id); if (r) return r; } return null; };
const rangeLabel = () => L().range.label;
/* Compare basis: the same months one quarter earlier (lenses <WINDOW>_pq; year to date has none) */
const CMP = () => L().cmp_short || 'last quarter', CMPN = (META.basis_labels && META.basis_labels.pq) || 'Prior quarter';
/* open pipeline (unweighted) dated to close in the quarter, and by fiscal close quarter. The view holds no pipeline
   target, so there is no coverage ratio, floor or target anywhere on the page */
const IQ = PIPE.in_quarter || {}, BCQ = PIPE.by_close_quarter || [], LATE = PIPE.late_stage_label || 'late stage';
const CAN_LOSS = !(P.capabilities && P.capabilities.loss_reasons) || P.capabilities.loss_reasons.state === 'available';
const FY = META.fiscal || null;
const pyNote = k => PIPE.py && isNum(PIPE.py[k]) ? `${pct(PIPE.py[k + '_var_pct'], { sign: true })} <span class="cmp">vs ${esc(money(PIPE.py[k]))} a year earlier</span>` : '';
const sumSeries = ids => { const n = MONTHS.length, out = { actual: Array(n).fill(null), py: Array(n).fill(null) }; ids.forEach(id => { const s = SER[id]; if (!s) return; ['actual', 'py'].forEach(k => { for (let i = 0; i < n; i++) if (isNum(s[k][i])) out[k][i] = (out[k][i] || 0) + s[k][i]; }); }); return out; };
const ROY = P.rest_of_year || null;
const VEL = () => L().velocity || null;
/* the AI review: diagnoses admitted by the gate (scripts/gtm/diagnosis.py), one per view; the page shows them and derives nothing */
const DIAGS = P.diagnoses || {};
const D = () => DIAGS[S.lens] || null;
const readout = () => (D() && D().readout) || {};
const findingById = id => D() ? (D().findings || []).find(f => f.id === id) : null;
/* the pipeline snapshot and the outlook do not change with the window, so their reviewed reading shows on every view (this view's review first, then the opening view's) */
const anyReadout = name => { const ids = [S.lens, META.primary_lens.id, ...Object.keys(DIAGS)], d = ids.map(k => DIAGS[k]).find(x => x && ((x.readout || {})[name] || []).length); return d ? d.readout[name] : []; };
const SUM_TONE = { favourable: 'fav', unfavourable: 'unf', neutral: 'neu', outlook: 'ink' };
/* the written executive summary for a tab (readout.summary.pipeline / .bookings) replaces the engine's bullets; the engine's stay as the fallback */
const writtenSummary = tab => { const w = (readout().summary || {})[tab]; return w && (w.bullets || []).length >= 3 ? w : null; };
const writtenBullets = tab => { const w = writtenSummary(tab); return w ? w.bullets.slice(0, 5).map((b, i) => ({ lead: i === 0, rv: true, ref: b.ref, tone: SUM_TONE[b.tone] || 'neu', head: String(b.head || '').replace(/[.:]?$/, '.'), short: b.text, text: b.detail || b.text })) : null; };
const writtenAsks = tab => { const w = writtenSummary(tab); return w && (w.decisions || []).length ? w.decisions.slice(0, 3).map(d => ({ ref: d.ref, short: d.text, question: d.detail || d.text, owner: d.owner, exposure: d.amount && isNum(d.amount.value) ? Math.abs(d.amount.value) : null })) : null; };
const aiReview = (id, title, items, tagHtml = '') => (items || []).length ? `<div class="aird" id="${id}"><div class="airh"><span>${esc(title)}</span>${tagHtml}</div><ul class="say">${items.map(x => `<li>${esc(clean(x.text))}</li>`).join('')}</ul></div>` : '';

/* ---------- header, tabs, footer, glossary ---------- */
function renderHeader() {
  $('#pageTitle').textContent = `GTM review · ${META.as_of.name}`;
  $('#scope').innerHTML = `<span class="chip">Scope <b>${esc(META.scope.filtered_to || 'All products')} · ${META.scope.subsidiaries.length} subsidiaries</b></span><span class="chip">USD</span>${FY ? `<span class="chip">Fiscal year Feb–Jan · <b>${esc(FY.year)} Q${esc(String(FY.quarter).slice(-1))}</b></span>` : ''}<span class="chip">${META.months_of_history} months of history</span>`;
  const curW = L().window;
  $('#lens').innerHTML = `<div class="lrow"><span class="lab">Window</span><span class="seg" id="segWin">${['MTD', 'QTD'].map(w => `<button data-w="${w}" class="${w === curW ? 'on' : ''}" ${P.lenses[`${w}_pq`] && P.lenses[`${w}_pq`].available ? '' : `disabled title="${esc((P.lenses[`${w}_pq`] || {}).reason || 'not available')}"`}>${esc(META.window_labels[w])}</button>`).join('')}</span></div>
    <div class="lrow"><span class="lab">Compare</span><span class="seg"><button class="on">vs ${esc(CMPN)}</button></span></div>`;
  $('#segWin').onclick = e => { const b = e.target.closest('button'); if (b && !b.disabled) setLens(`${b.dataset.w}_pq`); };
  const qc = P.qc, sb = $('#stateBadge');
  sb.className = 'state' + (VERIFIED ? ' ok' : '');
  sb.innerHTML = `${VERIFIED ? '✓ Data verified' : META.data_mode === 'local' ? '! Test data' : '! Data checks'}${qc.caveats.length ? ` · ${qc.caveats.length} note${qc.caveats.length > 1 ? 's' : ''}` : ''}${D() ? ' · AI reviewed' : ' · this view not AI reviewed'}`;
  sb.onclick = () => openDrawer('qc');
  $('#foot').innerHTML = `<span>Source: ${esc(META.sources.join(', '))}</span><span>Generated ${esc(String(META.generated_at).slice(0, 10))}</span><span>${D() ? 'AI reviewed' : 'This view not AI reviewed'}</span>`;
}
const TABQ = { pipeline: 'Will the pipeline turn into bookings, and what needs a decision?', bookings: 'Where do bookings stand, why, and what needs a decision?', outlook: 'What could the pipeline deliver in the quarters ahead?' };
function setTab(t) { S.tab = t; document.querySelectorAll('nav.tabs button[data-tab]').forEach(b => b.classList.toggle('active', b.dataset.tab === t)); document.querySelectorAll('.view').forEach(v => v.classList.toggle('active', v.id === 'view-' + t)); $('#tabQ').textContent = TABQ[t]; try { history.replaceState(null, '', '#' + t); } catch (e) { /* sandboxed preview frame: no URL to update */ } renderGlossary(); }
$('#tabs').addEventListener('click', e => { const b = e.target.closest('button[data-tab]'); if (b) setTab(b.dataset.tab); });
function setLens(id) { if (!P.lenses[id] || !P.lenses[id].available) return; S.lens = id; closeDrawer(); renderAll(); }
/* glossary: every label on the page, grouped; "This tab" shows the shared groups plus the open tab's own labels,
   "All labels" shows everything. Detail-panel labels always show, since panels open from every tab. */
const TAB_NAME = { pipeline: 'Pipeline', bookings: 'Bookings', outlook: 'Outlook' };
const sw = st => `<i class="sw" style="${st}"></i>`;
function glossaryRows() {
  const v = VEL();
  return [
    ['all', 'Direction', [
      [tag('fav'), 'Better than the same months last quarter: higher bookings or win rate; fewer days to win; less lost.'],
      [tag('unf'), 'Worse than the same months last quarter.'],
      [tag('neu'), `Within the smallest amount we report (${esc(META.materiality.basis)}).`]]],
    ['all', 'Figures', [
      ['($76k) · (420) bps', 'Brackets mark a negative figure. bps is a change in a rate or share in basis points (100 bps = 1 percentage point).'],
      ['+$510 · $143k · $1.92mn', 'A plus sign marks an increase; k and mn are thousands and millions of US dollars (ACV).'],
      ['FY2027-Q3', 'A fiscal quarter. The fiscal year runs 1 February to 31 January and is named by the year it ends: Q1 Feb–Apr, Q2 May–Jul, Q3 Aug–Oct, Q4 Nov–Jan. Quarter and year to date are fiscal.'],
      ['n.m. · —', 'n.m.: not meaningful (a percentage of 1,000% or more). —: not available, never zero.']]],
    ['all', 'Where the numbers come from', [
      ['Bookings', 'Recurring: Salesforce won New Sales and Seat Expansion opportunities (blended ARR) on the close date. Non-recurring: NetSuite non-recurring revenue from the income statement, on the period end date. Credits net off.'],
      ['Pipeline, win rate, days to win', 'Salesforce opportunity ACV (blended ARR), unweighted: New Sales and Seat Expansion deals. Never added to bookings.'],
      ['Recurring ACV', RK ? `${esc(cap(RK.recurring_rule))}.` : 'Opportunity ACV.'],
      ['<span class="tag sky">proxy</span>', 'Stage age and close-date moves stand in for "stalled": the view has no activity or next-step data.'],
      ['<span class="tag sky">scenario</span>', 'A straight-line range from pipeline and win rate. Not a forecast; nothing is credited to it.']]],
    ['pipeline', 'Pipeline tab', [
      ['High value contracts', RK ? `${esc(cap(RK.high_value.rule))}. The four cards and the deal tables read only these deals.` : 'Open deals of $100k ACV or more.'],
      ['Days to win · high value', v ? esc(cap(v.rule)) + `; the card shows ${esc(v.hv_rule)}.` : 'Average days from opportunity created to closed won.'],
      ['Not closing · high value', 'A high-value open deal whose expected close date has passed, or whose close date was pushed out at least once.'],
      ['Stuck in stage · high value', RK ? 'A high-value deal: ' + esc(RK.stuck.rule) + '.' : 'Longer in its stage than usual.'],
      ['High-value deals at risk', RK ? `${esc(cap(RK.high_value.rule))} that are not closing or stuck, as a share of high-value pipeline.` : 'The largest open deals that are not closing or stuck.'],
      ['Pipeline at a glance', `Open pipeline as of ${esc(PIPE.as_of)}, what is dated to close in ${esc(IQ.quarter || 'the quarter')}, and pipeline created, win rate and lost ACV for the window. Unweighted; there is no pipeline target in the view.`],
      ['Where the pipeline is at risk', 'Open ACV that is not closing or stuck, by the stage each deal sits in.']]],
    ['bookings', 'Bookings tab', [
      ['<span class="opx">+  =</span>', 'Bookings at a glance, in order of build-up: new sales plus seat expansion gives recurring bookings, plus non-recurring gives total bookings; recurring share and average deal value follow.'],
      ['Top two · top five customers', 'The share of recurring bookings in the window from the two and the five largest customers (non-recurring revenue has no account): how much one delayed deal would move the result.'],
      ['Largest deal', 'The largest single booked opportunity in the window (re-papered pairs left out) as a share of recurring bookings; click for the deal list.'],
      ['What moved bookings', 'Each measure, product or subsidiary against the same months last quarter; click a bar for its monthly trend and usual range.']]],
    ['outlook', 'Outlook tab', [
      ['Closing this quarter', `The open pipeline dated to close in ${esc(IQ.quarter || 'the quarter')}; past-due deals excluded.`],
      [`${sw('background:var(--dark);width:10px;height:10px')} Open pipeline by close quarter`, 'Open pipeline (unweighted) by the fiscal quarter of its close date. No target or coverage: the view holds no pipeline target.'],
      ['What the pipeline could deliver', 'A range per quarter from open pipeline and win rate. Not a forecast; nothing is credited to it.'],
      ['What the remaining months must deliver', 'Bookings the rest of the fiscal year (to 31 January) needs to match last fiscal year, or to hold the fiscal-year-to-date growth rate. A scenario with credit 0, not a forecast.']]],
    ['all', 'Thresholds', (META.thresholds || []).map(t => [esc(t.id.replace(/_/g, ' ')), `${esc(String(t.value))}: ${esc(t.basis)}${t.sensitivity && Object.keys(t.sensitivity).length ? ` · sensitivity (days, P90 / P75 / mean): ${esc(Object.entries(t.sensitivity).map(([k, v]) => `${k} ${Math.round(v.p90)}/${Math.round(v.p75)}/${Math.round(v.mean)}`).join(', '))}` : ''}`])
    ],
    ['panel', 'Detail panels (open from any tab)', [
      ['Panel tabs', 'Each panel opens on the figures, with further tabs for the trend, the split and the deal list where they apply.'],
      ['▸ section', 'A collapsed list inside a panel: click to open the deals behind a figure.'],
      ['Last 13 months', 'The figure by month against the same month last year.']]],
    ['all', 'Publication state', [
      [baseMark(), META.data_mode === 'local' ? 'Local sample figures from a workbook; never present them as real.' : VERIFIED ? `Every figure comes from ${esc(META.view)} through governed semantic-view statements, and the lines tie to both KPI marts.` : 'From governed statements; a tie-out check did not pass (open the data badge).'],
      ['AI reviewed · This view not AI reviewed', 'AI reviewed: the executive summaries, decisions and "What this means" readings were written by Claude for this view and admitted only after every figure in them was checked against the data; causes stay hypotheses for the suggested owners to confirm. A view without a review shows the engine reading, which names no business cause. Owners are suggested functions and dates are rule-generated targets.'],
      ['Data · notes', 'The data badge: click it for the checks, the notes and what the data cannot answer.']]]];
}
/* the sign and colour legend, open above How to read this page on every tab (as on the finance page) */
const signLegend = () => { const mon = money(L().materiality.monitoring_abs);
  return `<section class="sgn" id="signLegend" aria-label="Variance legend"><h2>Variance legend: how favourable and unfavourable moves are shown</h2>
  <table class="gls-t sgn-t"><thead><tr><th>Outcome</th><th>Bar</th><th>Text colour and sign</th><th>Meaning</th></tr></thead><tbody>
  <tr data-t="fav"><td>Favourable</td><td><i class="sw fav"></i></td><td><span class="fav">Green, with a plus sign: +$92k</span></td><td>Helps against the comparison: more bookings, pipeline or deals won; fewer deals lost; fewer days to win.</td></tr>
  <tr data-t="unf"><td>Unfavourable</td><td><i class="sw unf"></i></td><td><span class="unf">Red, in brackets: ($297k)</span></td><td>Hurts against the comparison: less bookings, pipeline or deals won; more deals lost or at risk; more days to win.</td></tr>
  <tr data-t="neu"><td>In line</td><td><i class="sw neu"></i></td><td><span class="neu">Grey, either sign: +$4k</span></td><td>Smaller than ${esc(mon)}, the smallest move we report.</td></tr>
  <tr data-t="lvl"><td>Negative amount</td><td><span class="mut">—</span></td><td><span class="ink">Black, in brackets: ($4.49mn)</span></td><td>A cancellation or a reduction, not a judgement.</td></tr>
  </tbody></table></section>`; };
function renderGlossary() {
  const host = $('#glossary'), open = !!(host.querySelector('.gls-d') || {}).open, all = !!S.glsAll, groups = glossaryRows();
  const shown = groups.filter(([sc]) => all || sc === 'all' || sc === 'panel' || sc === S.tab).sort((x, y) => all ? 0 : (y[0] === S.tab) - (x[0] === S.tab)), n = g => g.reduce((s, x) => s + x[2].length, 0);
  host.innerHTML = signLegend() + `<details class="gls-d"${open ? ' open' : ''}><summary><h2>How to read this page</h2><span class="hint">${all ? 'all tabs' : esc(TAB_NAME[S.tab] || '') + ' tab'} · ${n(shown)} labels · click to show or hide</span><span class="chev">▾</span></summary>
    <div class="gls-bar"><span class="tog" id="glsMode"><button data-m="tab" class="${all ? '' : 'on'}">This tab (${n(groups.filter(([sc]) => sc === 'all' || sc === 'panel' || sc === S.tab))})</button><button data-m="all" class="${all ? 'on' : ''}">All labels (${n(groups)})</button></span></div>
    <table class="gls-t"><thead><tr><th>Label</th><th>Meaning</th></tr></thead><tbody>${shown.map(([, grp, rows]) => `<tr class="grp"><td colspan="2">${esc(grp)}</td></tr>${rows.map(r => `<tr><td>${r[0]}</td><td>${r[1]}</td></tr>`).join('')}`).join('')}</tbody></table></details>`;
  $('#glsMode').onclick = e => { const b = e.target.closest('button'); if (!b) return; S.glsAll = b.dataset.m === 'all'; renderGlossary(); };
  renderAssumptions(host);
}
/* the Assumptions dropdown, as on the finance page: every threshold, test and rule in use, from the engine (META.assumptions) */
function renderAssumptions(host) {
  const A = META.assumptions || [], open = !!S.asmOpen, n = A.reduce((t, g) => t + g.rows.length, 0);
  if (!A.length) return;
  host.insertAdjacentHTML('beforeend', `<details class="gls-d asm" id="assumptions"${open ? ' open' : ''}><summary><h2>Assumptions</h2><span class="hint">${n} rules and thresholds · all tabs · click to show or hide</span><span class="chev">▾</span></summary>
    <table class="gls-t"><thead><tr><th>Rule</th><th>Value in use</th></tr></thead><tbody>${A.map(g => `<tr class="grp"><td colspan="2">${esc(g.group)}</td></tr>${g.rows.map(r => `<tr><td>${esc(r.label)}</td><td>${esc(r.value)}</td></tr>`).join('')}`).join('')}</tbody></table></details>`);
  $('#assumptions').addEventListener('toggle', e => { S.asmOpen = e.target.open; });
}

/* ---------- tooltip ---------- */
const tip = $('#tip');
document.addEventListener('pointerover', e => { const el = e.target.closest && e.target.closest('[data-tip]'); if (!el) { tip.style.display = 'none'; return; } const parts = el.dataset.tip.split('|'); tip.innerHTML = `<div class="t">${esc(parts[0])}</div>` + parts.slice(1).map(p => `<div>${esc(p)}</div>`).join(''); tip.style.display = 'block'; });
document.addEventListener('pointermove', e => { if (tip.style.display !== 'block') return; tip.style.left = Math.min(window.innerWidth - tip.offsetWidth - 12, e.clientX + 14) + 'px'; tip.style.top = Math.min(window.innerHeight - tip.offsetHeight - 12, e.clientY + 14) + 'px'; });

/* ---------- charts (string-built SVG and CSS bars; geometry only) ---------- */
function wrap(s, n) { const out = []; let line = ''; String(s || '').split(' ').forEach(w => { if ((line + ' ' + w).trim().length > n && line) { out.push(line); line = w; } else line = (line + ' ' + w).trim(); }); if (line) out.push(line); return out.slice(0, 3); }
function waterfall({ id, start, steps, end, height = 300, W = 900 }) {
  const items = [{ label: start.label, short: start.short, value: start.value, base: true }, ...steps, { label: end.label, short: end.short, value: end.value, base: true }];
  const H = height, padL = 58, padR = 10, padT = 26, padB = 46;
  const n = items.length, slot = (W - padL - padR) / n, bw = Math.min(slot * 0.64, 84);
  let run = start.value; const rects = []; let lo = Math.min(0, start.value || 0), hi = Math.max(0, start.value || 0);
  items.forEach(it => { let y0, y1; if (it.base) { y0 = 0; y1 = it.value || 0; } else { y0 = run; y1 = run + (it.value || 0); run = y1; } rects.push({ it, y0, y1 }); lo = Math.min(lo, y0, y1); hi = Math.max(hi, y0, y1); });
  const span = (hi - lo) || 1; lo -= span * 0.05; hi += span * 0.12;
  const sy = v => padT + (hi - v) / (hi - lo) * (H - padT - padB);
  let g = ''; for (let t = 0; t <= 4; t++) { const v = lo + (hi - lo) * t / 4, y = sy(v); g += `<line class="grid" x1="${padL}" x2="${W - padR}" y1="${y.toFixed(1)}" y2="${y.toFixed(1)}"/><text class="ax" x="${padL - 6}" y="${(y + 3.5).toFixed(1)}" text-anchor="end" style="font-size:9.5px;fill:var(--muted)">${esc(money(v))}</text>`; }
  let bars = '', conns = '';
  rects.forEach((r, i) => {
    const x = padL + slot * i + (slot - bw) / 2, cx = x + bw / 2, yA = sy(Math.max(r.y0, r.y1)), yB = sy(Math.min(r.y0, r.y1)), h = Math.max(1.5, yB - yA);
    const cl = r.it.base ? 'base' : ((r.it.value || 0) >= 0 ? 'fav' : 'unf');
    const label = r.it.base ? money(r.it.value) : money(r.it.value, { sign: true }), labY = (r.it.base || (r.it.value || 0) >= 0) ? yA - 6 : yB + 13;
    const dense = n > 9, words = r.it.short ? [r.it.short] : wrap(r.it.label, dense ? 11 : 18);
    bars += `<g class="bar" data-ref="${esc(r.it.ref || '')}" data-tip="${esc(r.it.label)}|${esc(r.it.base ? full(r.it.value) : full(r.it.value, { sign: true }) + ' · running ' + full(r.y1))}">
      <rect x="${x.toFixed(1)}" y="${padT}" width="${bw.toFixed(1)}" height="${H - padT - padB}" fill="transparent"/>
      <rect class="body ${cl}" rx="2" x="${x.toFixed(1)}" y="${yA.toFixed(1)}" width="${bw.toFixed(1)}" height="${h.toFixed(1)}"/>
      <text x="${cx.toFixed(1)}" y="${labY.toFixed(1)}" text-anchor="middle" style="font-size:${dense ? 10 : 11.5}px;font-weight:600">${esc(label)}</text>
      ${words.map((w, j) => `<text class="lbl" x="${cx.toFixed(1)}" y="${H - padB + 16 + j * 11}" text-anchor="middle" style="font-size:${dense ? 9.5 : 11}px">${esc(w)}</text>`).join('')}</g>`;
    if (i < rects.length - 1) { const yc = sy(r.it.base ? r.it.value : r.y1); conns += `<line class="conn" x1="${(x + bw).toFixed(1)}" x2="${(x + slot).toFixed(1)}" y1="${yc.toFixed(1)}" y2="${yc.toFixed(1)}"/>`; }
  });
  return `<svg class="wf" id="${esc(id)}" viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid meet">${g}<line class="zero" x1="${padL}" x2="${W - padR}" y1="${sy(0)}" y2="${sy(0)}"/>${conns}${bars}</svg>`;
}
function lineChart({ labels, series, height = 210, fmt = money, cur = null, W = 640 }) {
  const H = height, pl_ = 54, pr = 14, pt = 14, pb = 26;
  const nums = series.flatMap(s => s.vals).filter(isNum); if (!nums.length) return '<div class="empty">No series.</div>';
  let lo = Math.min(0, ...nums), hi = Math.max(...nums); const sp = (hi - lo) || Math.abs(hi) || 1; hi += sp * 0.12;
  const n = labels.length, x = i => pl_ + i * (W - pl_ - pr) / Math.max(1, n - 1), y = v => pt + (hi - v) / (hi - lo) * (H - pt - pb);
  let g = ''; for (let t = 0; t <= 3; t++) { const v = lo + (hi - lo) * t / 3, yy = y(v); g += `<line class="grid" x1="${pl_}" x2="${W - pr}" y1="${yy.toFixed(1)}" y2="${yy.toFixed(1)}"/><text class="ax" x="${pl_ - 6}" y="${(yy + 3.5).toFixed(1)}" text-anchor="end">${esc(fmt(v))}</text>`; }
  const paths = series.map(s => { const segs = []; let c = []; s.vals.forEach((v, i) => { if (isNum(v)) c.push(`${x(i).toFixed(1)},${y(v).toFixed(1)}`); else if (c.length) { segs.push(c); c = []; } }); if (c.length) segs.push(c); return segs.map(p => p.length === 1 ? `<circle cx="${p[0].split(',')[0]}" cy="${p[0].split(',')[1]}" r="2.5" class="${s.cls}"/>` : `<polyline class="${s.cls}" points="${p.join(' ')}"/>`).join(''); }).join('');
  const step = Math.ceil(n / 7);
  const xl = labels.map((l, i) => ((i % step === 0 && (n - 1 - i >= step || i === 0)) || i === n - 1) ? `<text class="ax" x="${x(i).toFixed(1)}" y="${H - 8}" text-anchor="${i === 0 ? 'start' : i === n - 1 ? 'end' : 'middle'}">${esc(l)}</text>` : '').join('');
  const mark = isNum(cur) && isNum(series[0].vals[cur]) ? `<circle class="cur" cx="${x(cur).toFixed(1)}" cy="${y(series[0].vals[cur]).toFixed(1)}" r="5"/>` : '';
  const hit = labels.map((l, i) => `<rect class="hit" x="${(x(i) - (W - pl_ - pr) / Math.max(1, n - 1) / 2).toFixed(1)}" y="${pt}" width="${((W - pl_ - pr) / Math.max(1, n - 1)).toFixed(1)}" height="${H - pt - pb}" fill="transparent" data-tip="${esc(l)}|${esc(series.map(s => `${s.name}: ${fmt(s.vals[i])}`).join('|'))}"/>`).join('');
  return `<svg class="ch" viewBox="0 0 ${W} ${H}">${g}${paths}${mark}${xl}${hit}</svg>`;
}
const legend = items => `<div class="legend">${items.map(([cls, name]) => `<span><i style="${cls}"></i>${esc(name)}</span>`).join('')}</div>`;
function divBars(items, { left = 'Unfavourable', right = 'Favourable', floor } = {}) {
  if (!items.length) return '<div class="empty">Nothing moved in this view.</div>';
  const mx = Math.max(...items.map(i => Math.abs(i.value || 0)), 1);
  return `<div class="dvh"><span></span><span><span>◂ ${esc(left)}</span><span>${esc(right)} ▸</span></span><span></span></div><div class="dv">${items.map(i => { const w = Math.abs(i.value || 0) / mx * 50, t = tone(i.value, floor);
    return `<div class="dvr" ${i.ref ? `data-ref="${esc(i.ref)}"` : ''} data-tip="${esc(i.name)}|${esc(full(i.value, { sign: true }))}"><span class="nm">${esc(i.name)}</span><span class="tr"><i class="${t}" style="${(i.value || 0) >= 0 ? 'left:50%' : `left:${(50 - w).toFixed(2)}%`};width:${Math.max(w, .6).toFixed(2)}%"></i></span><span class="vv ${t}">${esc(money(i.value, { sign: true }))}</span></div>`; }).join('')}</div>`;
}
function hBars(items, empty = 'Nothing to show.') {
  if (!items.length) return `<div class="empty">${esc(empty)}</div>`;
  const mx = Math.max(...items.map(i => Math.abs(i.value || 0)), 1e-9);
  return `<div class="hb">${items.map(i => `<div class="hbr" ${i.ref ? `data-ref="${esc(i.ref)}"` : ''} data-tip="${esc(i.name)}|${esc(i.tip || i.label || full(i.value))}"><span class="nm">${esc(i.name)}</span><span class="tr"><i class="${i.cls || ''}" style="width:${(Math.abs(i.value || 0) / mx * 100).toFixed(1)}%"></i></span><span class="vv ${i.vcls || ''}">${esc(i.label || money(i.value))}</span></div>`).join('')}</div>`;
}
/* latest month against the trailing six-month range, with the same month last year */
function rangeBar(did, { ref = true } = {}) {
  const rr = SIG[did] && SIG[did].runrate; if (!rr || !rr.eligible) return '';
  const act = SER[did].actual[AS], py = SER[did].py[AS], all = [rr.min, rr.max, rr.mean, act, py].filter(isNum);
  const mn = Math.min(...all), mx = Math.max(...all), sp = (mx - mn) || 1, pad = sp * 0.15, X = v => ((v - mn + pad) / (sp + 2 * pad) * 100).toFixed(1) + '%';
  const out = act > rr.max ? 'fav' : act < rr.min ? 'unf' : '';
  const label = did === 'total' ? 'Total bookings' : DRV_BY[did].label;
  return `<div class="rbr" ${ref && did !== 'total' ? `data-ref="driver:${esc(did)}"` : ''}><div class="rh"><b>${esc(label)}</b><span class="${out}">${esc(money(act))} <span class="mut">in ${esc(MONTH)}</span></span></div>
    <div class="rt"><div class="band" style="left:${X(rr.min)};width:${((rr.max - rr.min) / (sp + 2 * pad) * 100).toFixed(1)}%" data-tip="Usual range (six months)|${esc(money(rr.min))} – ${esc(money(rr.max))}"></div><div class="ref" style="left:${X(rr.mean)}" data-tip="Six-month average|${esc(money(rr.mean))}"></div>${isNum(py) ? `<div class="bud" style="left:${X(py)}" data-tip="${esc(MONTH)} last year|${esc(money(py))}"></div>` : ''}<div class="act ${out}" style="left:${X(act)}" data-tip="${esc(MONTH)}|${esc(money(act))}"></div></div></div>`;
}
const rangeLegend = () => legend([['background:var(--rng);height:6px', 'Usual six-month range'], ['background:var(--muted);width:2px;height:12px', 'Six-month average'], ['background:var(--budget);width:3px;height:12px', `${MONTH} last year`], ['background:var(--ink);width:9px;height:9px;transform:rotate(45deg)', MONTH]]);
/* side-card bar: this window against a reference mark (prior year or the floor); share = a bar of 0–100% with no mark */
function gauge(actual, comp, compName, fmt = v => pct(v), scaleMax = null) {
  const mx = scaleMax || Math.max(actual || 0, comp || 0) * 1.25 || 1;
  return `<div class="gauge"><i style="width:${Math.min(100, Math.max(0, (actual || 0) / mx * 100)).toFixed(1)}%"></i>${isNum(comp) ? `<b style="left:${Math.min(100, (comp || 0) / mx * 100).toFixed(1)}%" data-tip="${esc(compName)}|${esc(fmt(comp))}"></b>` : ''}</div><div class="gl"><span>${esc(fmt(0))}</span><span>${isNum(comp) ? `▮ ${esc(compName)} ${esc(fmt(comp))}` : esc(compName)}</span></div>`;
}
/* open pipeline (unweighted) by fiscal close quarter */
function closeQuarterChart(rows, { W = 760, H = 260 } = {}) {
  const padL = 58, padR = 12, padT = 18, padB = 44, vals = rows.map(r => r.open).filter(isNum), hi = Math.max(...vals, 1) * 1.12;
  const slot = (W - padL - padR) / rows.length, bw = Math.min(slot * 0.26, 46), sy = v => padT + (hi - v) / hi * (H - padT - padB);
  let g = ''; for (let t = 0; t <= 4; t++) { const v = hi * t / 4, y = sy(v); g += `<line class="grid" x1="${padL}" x2="${W - padR}" y1="${y.toFixed(1)}" y2="${y.toFixed(1)}"/><text class="ax" x="${padL - 6}" y="${(y + 3.5).toFixed(1)}" text-anchor="end">${esc(money(v))}</text>`; }
  const body = rows.map((r, i) => {
    const x0 = padL + slot * i + slot / 2 - bw / 2;
    const bar = (x, v, fill, name) => `<rect x="${x.toFixed(1)}" y="${sy(v || 0).toFixed(1)}" width="${bw.toFixed(1)}" height="${Math.max(1, sy(0) - sy(v || 0)).toFixed(1)}" rx="2" style="fill:${fill}" data-tip="${esc(r.quarter)}|${esc(name)}: ${esc(money(v))}"/>`;
    return `<g data-ref="quarter:${esc(r.quarter)}" style="cursor:pointer">${bar(x0, r.open, 'var(--dark)', 'Open pipeline')}
      <text x="${(padL + slot * i + slot / 2).toFixed(1)}" y="${H - padB + 16}" text-anchor="middle" style="font-size:11.5px;font-weight:600">${esc(r.quarter)}</text>
      <text x="${(padL + slot * i + slot / 2).toFixed(1)}" y="${H - padB + 31}" text-anchor="middle" style="font-size:11px;fill:var(--muted)">${esc(pl(r.count, 'deal'))}</text></g>`;
  }).join('');
  return `<svg class="ch" viewBox="0 0 ${W} ${H}">${g}<line class="zero" x1="${padL}" x2="${W - padR}" y1="${sy(0)}" y2="${sy(0)}"/>${body}</svg>`;
}

/* ---------- shared blocks: summary bullets, side cards, figure strips, decisions ---------- */
const mk = t => t === 'fav' ? '▲' : t === 'unf' ? '▼' : t === 'ink' ? '→' : '•';
/* the page shows the bold lead and the short line; the full sentence (or question) opens above the evidence when clicked */
const INTRO = {}; let introN = 0;
const keep = html => { const k = 'k' + (introN++); INTRO[k] = html; return k; };
const bullets = items => `<ul class="bul">${items.map(x => `<li class="${x.lead ? 'lead' : ''}${x.rv ? ' rv' : ''}" data-ref="${esc(x.ref)}" data-intro="${keep(`<b>${esc(x.head)}</b> ${esc(clean(x.text))}`)}"><span class="mk ${x.tone}">${mk(x.tone)}</span><span class="tx"><b>${esc(x.head)}</b> ${esc(clean(x.short || x.text))}</span><span class="go">›</span></li>`).join('')}</ul>`;
document.addEventListener('click', e => { const li = e.target.closest && e.target.closest('[data-intro]'); S.drawerIntro = li ? INTRO[li.dataset.intro] : null; }, true);
const ring = (ref, label, value, sub, bar, cls = '') => `<div class="ring" data-ref="${esc(ref)}"><div class="rl">${esc(label)}</div><div class="rv ${cls}">${value}</div><div class="rs">${sub}</div>${bar || ''}</div>`;
const fcell = (ref, label, v, sub, { cls = '', op = '', tot = false, end = false, meta = '' } = {}) => `<button class="fk${tot ? ' tot' : ''}${end ? ' end' : ''}" data-ref="${esc(ref)}">${op ? `<span class="op">${op}</span>` : ''}<div class="kl">${esc(label)}</div><div class="kv">${esc(v)}</div><div class="ks ${cls}">${sub}</div>${meta ? `<div class="km">${meta}</div>` : ''}</button>`;
function flowCell(k, op, { end = false, tot = false } = {}) {
  const ratio = k.kind === 'ratio', t = k.status === 'in_line' ? 'neu' : (k.status === 'ahead' ? 'fav' : 'unf');
  const chg = ratio ? pts(k.variance) : pct(k.variance_pct, { sign: true });
  return fcell('kpi:' + k.id, k.label, ratio ? pct(k.actual) : money(k.actual), `${esc(chg)} <span class="cmp">vs ${esc(CMP())}</span>`,
    { cls: t, op, tot, end, meta: k.small_sample ? `${esc(pl(k.closed, 'closed deal'))} · small sample` : `${esc(ratio ? pct(k.comparator) : money(k.comparator))} ${esc(CMP())}` });
}
const decisions = acts => acts.length ? `<ol class="dec">${acts.map(a => `<li data-ref="${esc(a.ref || 'action:' + a.id)}" data-intro="${keep(`<b>${esc(clean(a.question))}</b> <span class="mut">${esc(a.owner)} (suggested)</span>`)}"><div><div class="q">${esc(clean(a.short || a.question))}</div><div class="m">${esc(a.owner)} (suggested)${a.date ? ` · by ${esc(a.date)}` : ''}</div></div>${isNum(a.exposure) ? `<div class="amt">${esc(money(a.exposure))}<small>at stake</small></div>` : ''}</li>`).join('')}</ol>` : '<div class="empty">No decision needed: no rule reached the management threshold in this view.</div>';
const ACTIONS = () => [...(L().pipeline_actions || []), ...L().actions, ...(RK ? RK.actions : [])];
const secHead = (title, sub, mark = baseMark()) => `<div class="sh"><h2>${esc(title)}</h2><span class="sub">${sub}</span>${mark}</div>`;

/* ---------- PIPELINE ---------- */
/* high-value deal tables: five rows, then "Others" that opens the rest; a select switches the list */
const HV_LISTS = () => { const hv = RK.high_value; return [
  { id: 'all', label: `All high-value deals (${hv.deals.length})`, deals: hv.deals },
  { id: 'not_closing', label: `Not closing (${(hv.not_closing || { deals: [] }).deals.length})`, deals: (hv.not_closing || { deals: [] }).deals },
  { id: 'stuck', label: `Stuck in stage (${(hv.stuck || { deals: [] }).deals.length})`, deals: (hv.stuck || { deals: [] }).deals }]; };
function hvTableHtml() {
  const lists = HV_LISTS(), cur = lists.find(x => x.id === S.hvList) || lists[0], ds = cur.deals, head = ds.slice(0, 5), rest = ds.slice(5);
  const row = (d, cls = '') => `<tr class="${cls}"><td>${dealCell(d)}<div class="xs mut">${esc(d.owner || '')}</div></td><td>${esc(d.stage)}</td><td class="num">${closeCell(d)}</td><td class="num">${esc(d.pushes || '—')}</td><td class="num">${esc(money(d.acv))}</td><td class="num">${esc(money(d.recurring))}</td><td>${flagTags(d.flags) || '<span class="mut">—</span>'}</td></tr>`;
  const others = rest.length ? `<tr class="oth" id="hvOthers" tabindex="0" role="button" aria-expanded="${S.hvOpen ? 'true' : 'false'}"><td><b>${S.hvOpen ? '▾' : '▸'} Others</b><div class="xs mut">${esc(pl(rest.length, 'deal'))} · click to ${S.hvOpen ? 'hide' : 'show'}</div></td><td></td><td></td><td></td><td class="num"><b>${esc(money(rest.reduce((s, d) => s + d.acv, 0)))}</b></td><td class="num"><b>${esc(money(rest.reduce((s, d) => s + d.recurring, 0)))}</b></td><td></td></tr>${S.hvOpen ? rest.map(d => row(d, 'sub')).join('') : ''}` : '';
  return ds.length ? tbl([['Customer · deal'], ['Stage'], ['Close', 'num'], ['Pushes', 'num'], ['ACV', 'num'], ['Recurring', 'num'], ['Flag']], head.map(d => row(d)).join('') + others)
    : '<div class="empty">No high-value deal in this list.</div>';
}
function bindHvTable() {
  const sel = $('#hvList'); if (sel) sel.onchange = () => { S.hvList = sel.value; S.hvOpen = false; $('#hvBody').innerHTML = hvTableHtml(); bindHvTable(); };
  const o = $('#hvOthers'); if (o) { const go = () => { S.hvOpen = !S.hvOpen; $('#hvBody').innerHTML = hvTableHtml(); bindHvTable(); }; o.onclick = go; o.onkeydown = e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); go(); } }; }
}
function renderPipeline() {
  const host = $('#view-pipeline');
  if (!RK) { host.innerHTML = '<section class="sec"><div class="empty">This payload has no pipeline-risk block.</div></section>'; return; }
  const Lx = L(), v = VEL(), hv = RK.high_value, hnc = hv.not_closing, hst = hv.stuck, ar = RK.at_risk || { by_stage: [], acv: null, share: null, count: 0 }, lo = Lx.lost, cr = kpi('pipeline_created'), wr = kpi('win_rate');
  const HVC = money(hv.cutoff), vh = v ? v.hv : null;
  const vt = vh && isNum(vh.variance_days) && !vh.small_sample ? (vh.variance_days <= -3 ? 'fav' : vh.variance_days >= 3 ? 'unf' : 'neu') : 'neu';
  const pctHv = x => pct(x, { dec: 0 });
  const cards = [
    vh ? ring('velocity', 'Days to win · high value', `${esc(isNum(vh.avg_days) ? vh.avg_days.toFixed(0) : '—')}<small>days</small>`, `<span class="${vt}">${esc(dDays(vh.variance_days))}</span> <span class="mut">vs ${esc(CMP())} · ${esc(pl(vh.n, 'deal'))} of ${esc(HVC)} or more won${vh.small_sample ? ' · small sample' : ''}</span>`, gauge(vh.avg_days, v.cmp.hv.avg_days, CMPN, days)) : '',
    ring('rk:high_value', 'High-value deals at risk', esc(pctHv(hv.flagged.share_of_hv)), `<span class="mut">of high-value pipeline: ${esc(String(hv.flagged.count))} of ${esc(pl(hv.count, 'deal'))} of ${esc(HVC)} or more, ${esc(money(hv.flagged.acv))}</span>`, gauge(hv.flagged.share_of_hv, null, `${money(hv.acv)} high-value pipeline`, pctHv, 1), hv.flagged.count ? 'unf' : ''),
    hnc ? ring('rk:hv_not_closing', 'Not closing · high value', esc(money(hnc.recurring)), `<span class="mut">recurring ACV · ${esc(pctHv(hnc.share_of_hv))} of high-value pipeline · ${esc(pl(hnc.count, 'deal'))}</span>`, gauge(hnc.share_of_hv, null, `${hnc.past_due.count} past due · ${hnc.pushed.count} pushed out`, pctHv, 1), hnc.count ? 'unf' : '') : '',
    hst && RK.stuck.available ? ring('rk:hv_stuck', 'Stuck in stage · high value', esc(money(hst.recurring)), `<span class="mut">recurring ACV at stake · ${esc(pl(hst.customer_count, 'customer'))} ${RK.stuck.benchmark === 'p90' ? 'past the 90th-percentile stay' : `over ${esc(mult(RK.stuck.multiple))} the usual stay`}</span>`, gauge(hst.share_of_hv, null, `${pctHv(hst.share_of_hv)} of high-value pipeline`, pctHv, 1), hst.count ? 'unf' : '') : ''].filter(Boolean);
  const cardCls = cards.length < 4 ? ` c${cards.length}` : '';  /* the cards fill the row when one is not shown */
  const lostCell = lo ? fcell('rk:lost', `Lost · ${Lx.window_label}`, money(lo.acv), `${esc(pct(lo.variance_pct, { sign: true }))} <span class="cmp">vs ${esc(CMP())}</span>`, { cls: isNum(lo.variance) && Math.abs(lo.variance) >= Lx.materiality.monitoring_abs ? (lo.variance > 0 ? 'unf' : 'fav') : 'neu', meta: `${esc(pl(lo.count, 'deal'))} · ${esc(money(lo.cmp.acv))} ${esc(CMP())}` }) : fcell('rk:lost', 'Lost', '—', 'not supplied');
  host.innerHTML = `
    <section class="sec" id="pipe-exec">${secHead('Executive summary', `${esc(rangeLabel())} vs ${esc(Lx.range.cmp_label)} · open pipeline as of ${esc(PIPE.as_of)} · click any point for the detail`)}
      ${bullets(writtenBullets('pipeline') || Lx.pipeline_insights || RK.insights)}</section>
    <section class="sec" id="pipe-hv"><div class="sh"><h2>High value contracts at a glance</h2><span class="sub">open deals of ${esc(HVC)} ACV or more · ${esc(pl(hv.count, 'deal'))}, ${esc(money(hv.acv))}, ${esc(pct(hv.share, { dec: 0 }))} of open pipeline · deal lists as at ${esc(PIPE.deals_as_of || PIPE.as_of)}</span></div>
      <div class="cards${cardCls}" id="pipe-cards">${cards.join('')}</div>
      <div class="panel" id="hv-tables" style="margin-top:12px"><h3>High-value deals <span><select class="ctl" id="hvList" aria-label="Choose the list">${HV_LISTS().map(x => `<option value="${x.id}"${x.id === (S.hvList || 'all') ? ' selected' : ''}>${esc(x.label)}</option>`).join('')}</select></span></h3>
        <div id="hvBody">${hvTableHtml()}</div>
        <p class="xs mut" style="margin-top:8px">Largest first by ACV. Not closing = past the expected close date or the close date pushed out at least once; stuck = ${esc(RK.stuck.rule)}. Recurring = ${esc(RK.recurring_rule)}.</p></div></section>
    <section class="sec"><div class="sh"><h2>Pipeline at a glance</h2><span class="sub">pipeline as at ${esc(PIPE.as_of)} · created, win rate and lost for the window · Salesforce ACV</span></div>
      <div class="flow f5" id="kpis-pipe">
        ${fcell('pipe:open', 'Open pipeline', money(PIPE.open), PIPE.py ? pyNote('open') : `<span class="cmp">${esc(pl(PIPE.open_count, 'deal'))}</span>`, { meta: `${esc(pl(PIPE.open_count, 'deal'))} · average ${esc(money(PIPE.avg_value))}` })}
        ${fcell('quarter:' + (IQ.quarter || ''), `Closing in ${IQ.quarter || 'quarter'}`, money(IQ.open), `<span class="cmp">${esc(pct(isNum(IQ.open) && PIPE.open ? IQ.open / PIPE.open : null, { dec: 0 }))} of open pipeline</span>`, { meta: `${esc(pl(IQ.count || 0, 'deal'))} · past-due deals excluded` })}
        ${flowCell(cr, '')}
        ${Lx.conv_size && isNum(Lx.conv_size.value_win_rate) ? fcell('conv:win', 'Win rate by value', pct(Lx.conv_size.value_win_rate, { dec: 0 }), Lx.conv_size_cmp && isNum(Lx.conv_size_cmp.value_win_rate) ? `${esc(pts(Lx.conv_size.value_win_rate - Lx.conv_size_cmp.value_win_rate))} <span class="cmp">vs ${esc(CMP())}</span>` : '', { meta: `deals of $5k or more: ${esc(pct(Lx.conv_size.win_rate_5k, { dec: 0 }))} by count` }) : flowCell(wr, '')}
        ${lostCell}
      </div>${PIPE.current ? `<p class="xs mut" style="margin-top:8px">Headline pipeline is the snapshot at ${esc(PIPE.as_of)}; deal lists, stage age and past-due are current state: ${esc(PIPE.current.note)}.</p>` : ''}</section>
    <section class="sec"><div class="grid g-3-2">
      <div class="panel" id="pipe-risk"><h3>Where the pipeline is at risk <small>all open deals not closing or stuck, by stage</small></h3>
        ${hBars(ar.by_stage.map(r => ({ name: r.label, value: r.acv, ref: 'rk:at_risk', cls: 'unf', label: `${pl(r.count, 'deal')} · ${money(r.acv)}`, tip: `${pl(r.count, 'deal')} · ${money(r.recurring)} recurring` })), RK.at_risk ? 'No open deal is flagged.' : 'Not in this payload: rebuild the page with the 1.4.0 engine to see it.')}
        <div class="gtot"><span>Total at risk</span><span>${esc(pl(ar.count, 'deal'))} · <b>${esc(money(ar.acv))}</b> · ${esc(pct(ar.share, { dec: 0 }))} of open pipeline</span></div>${aiReview('pipe-reading', 'What this means', anyReadout('pipeline_meaning'))}</div>
      <div class="panel" id="pipe-asks"><h3>Decisions for management <small>suggested owners · for discussion</small></h3>${decisions(writtenAsks('pipeline') || Lx.pipeline_actions || RK.actions)}</div>
    </div></section>`;
  bindRefs(host); bindHvTable();
}

/* ---------- BOOKINGS ---------- */
const meaningBookings = () => { const rv = readout().bookings_meaning || []; if (rv.length) return rv;
  return L().drivers.measure.filter(d => Math.abs(d.variance) >= 0.5 && (d.reading || [])[1]).sort((a, b) => Math.abs(b.variance) - Math.abs(a.variance)).slice(0, 3).map(d => ({ text: `${d.label}: ${d.reading[1]}` })); };
function renderBookings() {
  const Lx = L(), rs = kpi('recurring_share'), aov = kpi('aov'), c = Lx.concentration, o1 = c.top_orders[0];
  const seq = [['arr_new', ''], ['arr_upsell', '+'], ['recurring', '='], ['non_recurring', '+'], ['total', '='], ['recurring_share', ''], ['aov', '']];
  const dim = dimOf(S.moveMode), moves = Lx.drivers[dim].filter(d => Math.abs(d.variance) >= 0.5).sort((a, b) => Math.abs(b.variance) - Math.abs(a.variance)).slice(0, 9);
  const top2 = c.top_customers.slice(0, 2).map(x => x.label);
  const p0 = v => pct(v, { dec: 0 });
  const ordersRing = o1 ? ring('conc:customers', 'Largest deal', esc(p0(o1.share)), `<span class="mut">of recurring bookings in the window: ${esc(money(o1.acv))}, ${esc(o1.customer)} · ${esc(o1.product)}</span>`, gauge(o1.share, c.top5_share, 'Top five customers', p0, 1), isNum(o1.share) && o1.share >= 0.1 ? 'unf' : '').replace('<div class="ring"', '<div class="ring" data-dtab="Deals"') : '';
  $('#view-bookings').innerHTML = `
    <section class="sec" id="book-exec">${secHead('Executive summary', `${esc(rangeLabel())} vs ${esc(Lx.range.cmp_label)} · click any point for the detail`)}
      ${bullets(writtenBullets('bookings') || Lx.insights)}</section>
    <section class="sec"><div class="cards c5" id="book-cards">
        ${ring('kpi:recurring_share', 'Recurring share of bookings', esc(pct(rs.actual)), `<span class="${tone(rs.variance, 0.01)}">${esc(pts(rs.variance))}</span> <span class="mut">vs ${esc(CMP())}</span>`, gauge(rs.actual, rs.comparator, CMPN, v => pct(v), 1))}
        ${ring('kpi:aov', 'Average deal value', esc(money(aov.actual)), `<span class="${aov.status === 'in_line' ? 'neu' : aov.status === 'ahead' ? 'fav' : 'unf'}">${esc(pct(aov.variance_pct, { sign: true }))}</span> <span class="mut">vs ${esc(CMP())} · ${esc(pl(aov.orders, 'deal'))}</span>`, gauge(aov.actual, aov.comparator, CMPN, money))}
        ${ring('conc:customers', 'Top two customers', esc(p0(c.top2_share)), `<span class="mut">of recurring bookings in the window: ${esc(top2.join(' and '))}</span>`, gauge(c.top2_share, c.top5_share, 'Top five', p0, 1), isNum(c.top2_share) && c.top2_share >= 0.3 ? 'unf' : '')}
        ${ring('conc:customers', 'Top five customers', esc(p0(c.top5_share)), `<span class="mut">of recurring bookings in the window · ${esc(pl(c.customers, 'customer'))} booked</span>`, gauge(c.top5_share, null, `top two ${p0(c.top2_share)}`, p0, 1), isNum(c.top5_share) && c.top5_share >= 0.5 ? 'unf' : '')}
        ${ordersRing}
      </div></section>
    <section class="sec"><div class="sh"><h2>Bookings at a glance</h2><span class="sub">in order of build-up · change vs ${esc(CMP())} · recurring: Salesforce won ACV · non-recurring: NetSuite revenue</span></div>
      <div class="flow" id="kpis">${seq.map(([id, op]) => flowCell(kpi(id), op, { tot: op === '=', end: id === 'total' })).join('')}</div></section>
    ${Lx.gross_to_net && Lx.gross_to_net.total ? `<section class="sec"><div class="grid g2">
      ${Lx.gross_to_net && Lx.gross_to_net.total ? `<div class="panel" id="book-g2n"><h3>Gross to net <small>derived · subscription-line grain</small></h3>
        ${hBars([{ name: 'Gross bookings', value: Lx.gross_to_net.total.gross, label: money(Lx.gross_to_net.total.gross) }, { name: 'Cancellations', value: Lx.gross_to_net.total.negative, cls: 'unf', label: `${Lx.gross_to_net.total.neg_lines.toLocaleString('en-US')} lines · ${money(Lx.gross_to_net.total.negative)}` }, { name: 'Net bookings', value: Lx.gross_to_net.total.net, label: money(Lx.gross_to_net.total.net) }])}
        <p class="xs mut" style="margin-top:8px">Cancellations are ${esc(pct(Lx.gross_to_net.total.negative_share, { dec: 0 }))} of gross; the net ties to total bookings (difference ${esc(full(Lx.gross_to_net.control))}).${Lx.concentration.repapered_orders ? ` ${Lx.concentration.repapered_orders} orders are re-papered pairs (same customer, measure and amount, opposite sign).` : ''}</p></div>` : '<div></div>'}
    </div></section>` : ''}
    <section class="sec"><div class="grid g-3-2">
      <div class="panel" id="book-movers"><h3>What moved bookings <span class="tog" id="moveMode">${['by_measure', 'by_product', 'by_subsidiary'].map(m => `<button data-m="${m}" class="${S.moveMode === m ? 'on' : ''}">By ${esc(DIM_LABEL[dimOf(m)].toLowerCase())}</button>`).join('')}</span></h3>
        ${divBars(moves.map(d => ({ name: d.label, value: d.variance, ref: 'driver:' + d.id })))}
        <div class="gtot" data-ref="kpi:total"><span>Total bookings</span><span><b>${esc(money(kpi('total').variance, { sign: true }))}</b> vs ${esc(CMP())} · open the bridge ›</span></div>${aiReview('book-reading', 'What this means', meaningBookings())}</div>
      <div class="panel" id="book-asks"><h3>Decisions for management <small>suggested owners · for discussion</small></h3>${decisions(writtenAsks('bookings') || Lx.actions)}</div>
    </div></section>`;
  $('#moveMode').onclick = e => { const b = e.target.closest('button'); if (!b) return; S.moveMode = b.dataset.m; renderBookings(); };
  bindRefs($('#view-bookings'));
}

/* ---------- OUTLOOK ---------- */
/* What could the pipeline deliver, in 3-5 drillable bullets: each quarter's range against what was won in the same quarter
   last year (and what is already won), what the rest of the fiscal year must deliver, pipeline creation, and the risks in
   the open pipeline. Selection and phrasing of engine fields only; no new economics. */
const lnk = (ref, text) => `<span class="lnk" data-ref="${esc(ref)}">${esc(text)}</span>`;
const cmtList = (id, items) => `<ul class="cmt" id="${id}">${items.filter(Boolean).slice(0, 5).map(x => `<li data-ref="${esc(x.ref)}"><span class="mk ${x.t || 'neu'}">${mk(x.t || 'neu')}</span><span class="tx">${x.html}</span><span class="go">›</span></li>`).join('')}</ul>`;
const meaningOutlook = () => { const rv = anyReadout('outlook_meaning'); return rv.length ? rv : [{ text: 'A straight-line range at last-twelve-month win rates: no seasonality, deal-by-deal judgement or management view is included, and nothing is added to a forecast until an owner accepts it.' }]; };
function outlookCommentary() {
  const out = [], scs = OUT.scenario || [], cr = kpi('pipeline_created'), ar = (RK && RK.at_risk) || null, ag = PIPE.ageing, ny = PIPE.not_yet_created;
  scs.slice(0, 2).forEach((x, i) => {
    const vsPy = !isNum(x.py_won) ? null : x.low >= x.py_won ? 'above' : x.high < x.py_won ? 'below' : 'around';
    const won = isNum(x.won_since) ? (x.quarter_ended ? `; ${esc(money(x.won_since))} was won by the quarter end` : `; ${esc(money(x.won_since))} won so far (to ${esc(x.won_since_to)})`) : '';
    const t = x.quarter_ended && isNum(x.won_since) && isNum(x.py_won) ? (x.won_since >= x.py_won ? 'fav' : 'unf') : vsPy === 'above' ? 'fav' : vsPy === 'below' ? 'unf' : 'neu';
    out.push({ t, ref: 'scenario:' + x.quarter, html: `<b>${i === 0 ? 'This quarter' : 'Next quarter'}:</b> ${lnk('quarter:' + x.quarter, x.quarter)} could deliver ${esc(money(x.low))} – ${esc(money(x.high))} from ${esc(money(x.open))} open${vsPy ? `, ${vsPy} the ${esc(money(x.py_won))} won in ${esc(x.py_quarter)}` : ''}${won}.` });
  });
  if (ROY && isNum(ROY.to_match_py)) {
    const rest = isNum(ROY.still_to_match) ? ROY.still_to_match : ROY.to_match_py, t = isNum(ROY.py_rest) ? (rest <= ROY.py_rest ? 'fav' : 'unf') : 'neu';
    out.push({ t, ref: 'pipe:open', html: `<b>Rest of the year:</b> ${esc(ROY.months)} must deliver ${esc(money(ROY.to_match_py))} to match last fiscal year${isNum(ROY.to_hold_growth) ? ` (${esc(money(ROY.to_hold_growth))} to hold ${esc(pct(ROY.growth, { sign: true, dec: 0 }))} growth)` : ''}${isNum(ROY.won_since) ? `; ${esc(money(ROY.won_since))} of recurring deals already won leaves ${esc(money(ROY.still_to_match))}` : ''}${isNum(ROY.py_rest) ? `, against ${esc(money(ROY.py_rest))} delivered in the same months last year` : ''}.` });
  }
  if (cr && isNum(cr.actual)) out.push({ t: cr.status === 'in_line' ? 'neu' : cr.status === 'ahead' ? 'fav' : 'unf', ref: 'kpi:pipeline_created', html: `<b>Pipeline created:</b> ${esc(money(cr.actual))} ${esc(L().window_label)}, ${esc(pct(cr.variance_pct, { sign: true }))} vs ${esc(CMP())}${isNum(cr.count) ? ` (${esc(pl(cr.count, 'deal'))}${isNum(cr.count_cmp) ? ` against ${cr.count_cmp}` : ''})` : ''}${ny && isNum(ny.acv) ? `; ${lnk('pipe:open', money(ny.acv))} more is open but not yet at 03 - EVALUATE` : ''}.` });
  const risks = [ar && isNum(ar.acv) ? `${lnk('rk:at_risk', money(ar.acv))} (${esc(pct(ar.share, { dec: 0 }))}) of open pipeline is not closing or stuck` : null,
    ag && ag.buckets ? (b => b ? `${lnk('pipe:open', money(b.acv))} is over a year old` : null)(ag.buckets.find(b => /^over/.test(b.label))) : null,
    (q => q && isNum(q.open) && q.open >= 0.5 ? `${lnk('quarter:' + q.quarter, money(q.open))} is past due` : null)(BCQ.find(r => r.id === 'past-due'))].filter(Boolean);
  if (risks.length) out.push({ t: 'unf', ref: ar ? 'rk:at_risk' : 'pipe:open', html: `<b>Watch:</b> ${risks.join('; ')}.` });
  return cmtList('out-commentary-list', out);
}
function renderOutlook() {
  const scs = OUT.scenario, cr = kpi('pipeline_created'), s0 = scs[0];
  const tile = (ref, l, v, sub, dark) => `<button class="tile${dark ? ' dark' : ''}" data-ref="${esc(ref)}"><div class="kl">${esc(l)}</div><div class="kv">${esc(v)}</div><div class="ks">${sub}</div></button>`;
  /* what the rest of the fiscal year must deliver (the same scenario as on the Bookings tab, credit 0) */
  const roySec = ROY ? `<section class="sec"><div class="panel" id="out-roy"><h3>What ${esc(ROY.months)} must deliver <small><span class="tag sky">scenario</span> credit 0</small></h3>
        ${hBars([ROY.to_match_py != null ? { name: "To match last fiscal year", value: ROY.to_match_py, label: money(ROY.to_match_py) } : null, ROY.to_hold_growth != null ? { name: `To hold ${pct(ROY.growth, { sign: true, dec: 0 })} growth`, value: ROY.to_hold_growth, label: money(ROY.to_hold_growth) } : null, { name: `Last year's ${ROY.months}`, value: ROY.py_rest, label: money(ROY.py_rest) }, isNum(ROY.won_since) ? { name: `Recurring won since ${ROY.won_since_from.slice(0, 7)}`, value: ROY.won_since, cls: 'fav', label: money(ROY.won_since), tip: ROY.won_since_rule } : null].filter(Boolean))}
        <p class="xs mut" style="margin-top:8px">${esc(ROY.rule)}. Bookings to date in ${esc(ROY.fiscal_year || 'the fiscal year')}: ${esc(money(ROY.ytd))}.${isNum(ROY.won_since) ? ` Since the last closed month, ${esc(money(ROY.won_since))} of recurring deals has been won (to ${esc(ROY.won_since_to)}), leaving ${esc(money(ROY.still_to_match))} to match last fiscal year before non-recurring revenue, which arrives as NetSuite closes each month.` : ''}</p></div></section>` : '';
  const wvb = PIPE.won_vs_booked && PIPE.won_vs_booked.length ? `<div class="panel" id="out-wvb"><h3>Won opportunities vs recurring bookings <small>two Salesforce scopes · reconciliation</small></h3>${lineChart({ labels: PIPE.won_vs_booked.map(r => String(r.quarter).replace(/^FY20(\d\d)-(Q\d)$/, 'FY$1 $2')), series: [{ name: 'Won ACV', vals: PIPE.won_vs_booked.map(r => r.won), cls: 'l-act' }, { name: 'Recurring bookings', vals: PIPE.won_vs_booked.map(r => r.booked), cls: 'l-cmp' }], height: 190, W: 560 })}
        ${legend([['background:var(--ink)', 'Won opportunity ACV (pipeline segments)'], ['background:var(--budget)', 'Recurring bookings (bookings teams)']])}<p class="xs mut" style="margin-top:6px">Booked ÷ won has run ${esc(Math.min(...PIPE.won_vs_booked.map(r => r.ratio)).toFixed(2))}×–${esc(Math.max(...PIPE.won_vs_booked.map(r => r.ratio)).toFixed(2))}× over ${PIPE.won_vs_booked.length} quarters: won pipeline is a usable lead for bookings.</p></div>` : '';
  $('#view-outlook').innerHTML = `
    <section class="sec">${secHead('What is in the pipeline?', `pipeline as at ${esc(PIPE.as_of)} · unweighted ACV · no pipeline target in the view`)}
      <div class="out-top"><div class="panel out-cmt" id="out-commentary">${outlookCommentary()}${aiReview('out-reading', 'What this means', meaningOutlook(), '<span class="tag amb">for discussion</span>')}</div>
      <div class="kpi-col" id="out-tiles">
        ${tile('quarter:' + (IQ.quarter || ''), `Closing in ${IQ.quarter || 'quarter'}`, money(IQ.open), `open pipeline dated to close in ${esc(IQ.quarter || 'the quarter')}, as at ${esc(IQ.as_of || PIPE.as_of)}; past-due deals excluded`, true)}
        ${s0 ? tile('scenario:' + s0.quarter, `What ${s0.quarter} could deliver`, `${money(s0.low)} – ${money(s0.high)}`, `of ${esc(money(s0.open))} open closing in the quarter · not a forecast${isNum(s0.won_since) ? ` · <b>${esc(money(s0.won_since))} won</b> after ${esc(PIPE.as_of)}${s0.quarter_ended ? `; the quarter ended ${esc(s0.quarter_end)}` : ` (to ${esc(s0.won_since_to)})`}` : ''}`).replace('class="kv"', 'class="kv rng"') : ''}
        ${tile('pipe:open', 'Open pipeline', money(PIPE.open), `${esc(pl(PIPE.open_count, 'deal'))}, as at ${esc(PIPE.as_of)} · unweighted`)}
        ${tile('kpi:pipeline_created', `Pipeline created · ${L().window_label}`, money(cr.actual), `<span class="${cr.status === 'in_line' ? 'neu' : cr.status === 'ahead' ? 'fav' : 'unf'}">${esc(pct(cr.variance_pct, { sign: true }))}</span> vs ${esc(CMP())}`)}
      </div></div></section>
    ${roySec}
    <section class="sec"><div class="grid g2 eqh">
      ${wvb}
      <div class="panel" id="out-scenario"><h3>What the pipeline could deliver <small><span class="tag sky">scenario</span> not a forecast</small></h3>
        ${(() => { const mx = Math.max(...scs.flatMap(x => [x.open, x.high, x.py_won]).filter(isNum), 1) * 1.08, X = v => (v / mx * 100).toFixed(1) + '%';
          return scs.map(x => `<div class="rbr scn" data-ref="scenario:${esc(x.quarter)}"><div class="rh"><b>${esc(x.quarter)}</b><span><b>${esc(money(x.low))} – ${esc(money(x.high))}</b> <span class="mut">of ${esc(money(x.open))} open</span></span></div>
            <div class="rt"><div class="trk" style="width:${X(x.open)}" data-tip="Open pipeline closing in ${esc(x.quarter)}|${esc(money(x.open))}"></div><div class="band" style="left:${X(x.low)};width:calc(${X(x.high)} - ${X(x.low)} + 3px)" data-tip="Range|${esc(money(x.low))} – ${esc(money(x.high))}"></div>${isNum(x.py_won) ? `<div class="bud" style="left:${X(x.py_won)}" data-tip="Won in ${esc(x.py_quarter)}|${esc(money(x.py_won))}"></div>` : ''}</div>
            <div class="xs mut">${isNum(x.py_won) ? `won in ${esc(x.py_quarter)}: ${esc(money(x.py_won))}` : `no won figure for ${esc(x.py_quarter || 'last year')}`}${isNum(x.won_since) ? ` · actual so far: <b class="ink">${esc(money(x.won_since))}</b> won after ${esc(PIPE.as_of)}${x.quarter_ended ? ` (quarter ended ${esc(x.quarter_end)})` : ` (to ${esc(x.won_since_to)})`}` : ''}</div></div>`).join(''); })()}
        ${legend([['background:var(--surface2);width:14px;height:8px', 'Open pipeline closing in the quarter'], ['background:var(--ink);height:8px', 'Range at last-twelve-month win rates'], ['background:var(--budget);width:3px;height:12px', 'Won in the same quarter last year']])}
        <p class="xs mut" style="margin-top:10px">${esc(clean(OUT.rule))}. Salesforce opportunity ACV (recurring), not non-recurring revenue.</p></div>
    </div></section>
    <section class="sec"><div class="grid g2 eqh">
      <div class="panel" id="out-close"><h3>Open pipeline by close quarter <small>fiscal quarters · unweighted · as at ${esc(PIPE.close_quarters_as_of || PIPE.as_of)}</small></h3>${closeQuarterChart(BCQ, { W: 560 })}
        ${legend([['background:var(--dark);width:10px;height:10px', 'Open pipeline']])}
        <p class="xs mut" style="margin-top:8px">Fiscal quarters (Q1 Feb–Apr, Q2 May–Jul, Q3 Aug–Oct, Q4 Nov–Jan); past due = close date before ${esc(PIPE.close_quarters_as_of || PIPE.as_of)}; later = beyond the quarters shown. The bars add up to the ${esc(money(PIPE.open))} headline. No ratio: the view holds no pipeline target.</p></div>
      ${PIPE.ageing ? `<div class="panel" id="out-ageing"><h3>How old the open pipeline is <small>by ${esc(PIPE.ageing.basis || 'creation date')} · as at ${esc(PIPE.ageing.as_of)}</small></h3>${hBars(PIPE.ageing.buckets.map(b => ({ name: b.label, value: b.acv, ref: 'pipe:open', cls: b.label.startsWith('over') ? 'unf' : '', label: `${money(b.acv)} · ${pct(b.share, { dec: 0 })}` })))}
        <p class="xs mut" style="margin-top:8px">${esc(money(PIPE.ageing.far_out.acv))} (${esc(pct(PIPE.ageing.far_out.share, { dec: 0 }))}) is dated to close after ${esc(PIPE.ageing.far_out.beyond)}.${PIPE.not_yet_created ? ` ${esc(money(PIPE.not_yet_created.acv))} (${esc(pl(PIPE.not_yet_created.count, 'deal'))}) has not reached 03 - EVALUATE, so pipeline created does not count it yet.` : ''}</p></div>` : '<div></div>'}
    </div></section>`;
  bindRefs($('#view-outlook'));
}

/* ---------- PIPELINE RISK drill-downs ---------- */
const ddBlock = (title, meta, body, open = false) => `<details class="dd"${open ? ' open' : ''}><summary><span class="ddt">${esc(title)}</span><span class="ddm">${meta}</span></summary><div class="ddb">${body}</div></details>`;
const facts = arr => `<div class="facts">${arr.map(f => `<div><div class="l">${esc(f[0])}</div><div class="v ${f[2] || ''}">${esc(f[1])}</div></div>`).join('')}</div>`;
const say = arr => arr.filter(Boolean).length ? `<ul class="say">${arr.filter(Boolean).map(s => `<li>${s}</li>`).join('')}</ul>` : '';
const flagTags = fs => (fs || []).map(f => `<span class="tag ${f === 'past due' ? 'unf' : f === 'stuck' ? 'amb' : 'sky'}">${esc(f)}</span>`).join('');
const closeCell = d => d.pushes ? `${esc(d.close)}<div class="xs mut">was ${esc(d.orig_close)}</div>` : esc(d.close || '—');
const dealCell = d => `${esc(d.account)}<div class="xs mut">${esc(d.name)}</div>`;
const tbl = (head, rows) => `<div class="tscroll"><table class="mini"><thead><tr>${head.map(h => `<th class="${h[1] || ''}">${esc(h[0])}</th>`).join('')}</tr></thead><tbody>${rows}</tbody></table></div>`;
const notClosingTable = (ds, n) => tbl([['Customer · deal'], ['Stage'], ['Close', 'num'], ['Pushes', 'num'], ['ACV', 'num'], ['Recurring', 'num'], ['Flag']], ds.slice(0, n).map(d => `<tr><td>${dealCell(d)}<div class="xs mut">${esc(d.owner)}</div></td><td>${esc(d.stage)}</td><td class="num">${closeCell(d)}</td><td class="num">${esc(d.pushes || '—')}</td><td class="num">${esc(money(d.acv))}</td><td class="num">${esc(money(d.recurring))}</td><td>${flagTags(d.flags)}</td></tr>`).join(''));
const stuckDealTable = ds => tbl([['Deal'], ['Stage'], ['Days in stage', 'num'], ['× median', 'num'], ['ACV', 'num'], ['Close', 'num']], ds.map(d => `<tr><td>${esc(d.name)}<div class="xs mut">${esc(d.owner)} · ${esc(d.product)}</div></td><td>${esc(d.stage)}</td><td class="num">${esc(d.age_days ?? '—')}<div class="xs mut">median ${isNum(d.median_days) ? esc(d.median_days.toFixed(0)) : '—'}</div></td><td class="num unf">${esc(mult(d.ratio))}</td><td class="num">${esc(money(d.acv))}</td><td class="num">${closeCell(d)}</td></tr>`).join(''));
const hvTable = (ds, n) => tbl([['Customer · deal'], ['Stage'], ['Close', 'num'], ['Probability', 'num'], ['ACV', 'num'], ['Flag']], ds.slice(0, n).map(d => `<tr><td>${dealCell(d)}<div class="xs mut">${esc(d.owner)}</div></td><td>${esc(d.stage)}</td><td class="num">${closeCell(d)}</td><td class="num">${esc(pct(d.prob, { dec: 0 }))}</td><td class="num">${esc(money(d.acv))}</td><td>${flagTags(d.flags) || '<span class="mut">—</span>'}</td></tr>`).join(''));
const lostTable = (ds, n) => tbl([['Customer · deal'], ['Lost at'], ['Reason'], ['Closed', 'num'], ['ACV', 'num']], ds.slice(0, n).map(d => `<tr><td>${dealCell(d)}<div class="xs mut">${esc(d.owner)}</div></td><td>${esc(d.lost_stage)}</td><td>${esc(d.reason)}</td><td class="num">${esc(d.close)}</td><td class="num">${esc(money(d.acv))}</td></tr>`).join(''));
const grpBars = (rows, ref, key = 'acv') => hBars(rows.map(r => ({ name: r.label, value: r[key], ref, label: `${pl(r.count, 'deal')} · ${money(r[key])}`, tip: `${pl(r.count, 'deal')} · ${money(r.acv)} ACV · ${money(r.recurring)} recurring` })), 'Nothing in this view.');
function rkDrawer(id) {
  if (!RK || !id) return null;
  const nc = RK.not_closing, st = RK.stuck, hv = RK.high_value, lo = L().lost, ar = RK.at_risk, tags = [tag('sky', 'proxy'), baseMark()];
  if (id === 'at_risk' && !RK.at_risk) return null;
  if (id === 'at_risk') return { title: 'Where the pipeline is at risk', sub: ar.rule, tags,
    tabs: { Overview: () => `${facts([['At risk', money(ar.acv)], ['Recurring', money(ar.recurring)], ['Share of open', pct(ar.share, { dec: 0 })], ['Not closing', `${pl(nc.count, 'deal')} · ${money(nc.acv)}`], ['Stuck', `${pl(st.count, 'deal')} · ${money(st.acv)}`], ['Deals', String(ar.count)]])}
        <h4>By stage</h4>${grpBars(ar.by_stage, '')}
        ${ddBlock('Stuck customers', `${esc(money(st.recurring))} recurring · ${esc(pl(st.customer_count, 'customer'))}`, hBars(st.customers.map(c => ({ name: c.customer, value: c.recurring, ref: 'rk:cust:' + c.id, label: `${pl(c.count, 'deal')} · ${money(c.recurring)}` }))))}` } };
  if (id === 'not_closing') return { title: 'Deals not getting closed', sub: nc.rule, tags,
    tabs: { Overview: () => `${facts([['Deals', String(nc.count)], ['ACV', money(nc.acv)], ['Recurring', money(nc.recurring)], ['Share of open', pct(nc.share, { dec: 0 })], ['Past due', `${pl(nc.past_due.count, 'deal')} · ${money(nc.past_due.acv)}`], ['Pushed out', `${pl(nc.pushed.count, 'deal')} · ${money(nc.pushed.acv)}`]])}
        <h4>By stage</h4>${grpBars(nc.by_stage, '', 'recurring')}
        ${ddBlock('By owner', `${esc(pl(nc.by_owner.length, 'owner'))}`, grpBars(nc.by_owner, '', 'recurring'))}
        <p class="xs mut" style="margin-top:10px">Recurring = ${esc(RK.recurring_rule)}. A push is a later close date than the one recorded at the previous stage change.</p>` } };
  if (id === 'stuck') return { title: 'Customers stuck in the funnel', sub: st.rule, tags,
    tabs: { Customers: () => `${facts([['Customers', String(st.customer_count)], ['Deals', String(st.count)], ['Recurring at stake', money(st.recurring)], ['ACV', money(st.acv)]])}<h4>By customer</h4>${hBars(st.customers.map(c => ({ name: c.customer, value: c.recurring, ref: 'rk:cust:' + c.id, label: `${pl(c.count, 'deal')} · ${money(c.recurring)}`, tip: `${c.stages.join(', ')} · up to ${mult(c.max_ratio)} the median` })))}`,
      Stages: () => tbl([['Stage'], ['Stays', 'num'], ['Median', 'num'], ['Flag after', 'num'], ['Stuck', 'num'], ['Recurring', 'num']], st.stages.map(s => `<tr><td>${esc(s.stage)}</td><td class="num">${esc(String(s.stays))}</td><td class="num">${isNum(s.median_days) ? esc(s.median_days.toFixed(0)) : '—'}</td><td class="num">${isNum(s.threshold_days) ? esc(s.threshold_days.toFixed(0)) : '—'}</td><td class="num">${esc(String(s.stuck_deals))}</td><td class="num">${esc(money(s.stuck_recurring))}</td></tr>`).join('')) + `<p class="xs mut" style="margin-top:10px">Median of completed stays in each stage (at least ${esc(String(st.min_stays))}); each deal is compared with the median of other customers' stays.</p>` } };
  if (id.startsWith('cust:')) { const c = st.customers.find(x => x.id === id.slice(5)); if (!c) return null;
    return { title: c.customer, sub: `stuck in ${c.stages.join(', ')} · ${pl(c.count, 'deal')}`, tags,
      tabs: { Deals: () => `${facts([['Recurring at stake', money(c.recurring)], ['ACV', money(c.acv)], ['Longest stay', `${c.longest_days} days`], ['Up to', `${mult(c.max_ratio)} the median`]])}${stuckDealTable(c.deals)}
        <p class="xs mut" style="margin-top:10px">Potential loss is the recurring ACV of these deals if they don't convert; it is not a forecast.</p>` } }; }
  if (id === 'high_value') return { title: 'High-value opportunities', sub: `${hv.rule}: ${money(hv.cutoff)} or more`, tags: [baseMark()],
    tabs: { Overview: () => `${facts([['Deals', String(hv.count)], ['ACV', money(hv.acv)], ['Share of open', pct(hv.share, { dec: 0 })], ['Not closing or stuck', `${pl(hv.flagged.count, 'deal')} · ${money(hv.flagged.acv)}`], ['At-risk share of open', pct(hv.flagged.share, { dec: 0 }), hv.flagged.count ? 'unf' : ''], ['Recurring', money(hv.recurring)]])}
        ${VEL() && isNum(VEL().hv.avg_days) ? `<h4>How long they take</h4>${say([`Won deals of ${esc(money(100000))} or more took <b>${esc(days(VEL().hv.avg_days))}</b> from opportunity to close in the window, against ${esc(days(VEL().std.avg_days))} for smaller deals.`])}` : ''}
        <h4>Not closing or stuck, by stage</h4>${grpBars([...(hv.not_closing ? hv.not_closing.by_stage : [])], '')}
        <p class="xs mut" style="margin-top:10px">The deals are listed on the Pipeline tab under High value contracts at a glance.</p>` } };
  if (id === 'hv_not_closing' && hv.not_closing) { const x = hv.not_closing; return { title: 'High-value deals not closing', sub: `${hv.rule} · ${nc.rule}`, tags,
    tabs: { Overview: () => `${facts([['Deals', String(x.count)], ['ACV', money(x.acv)], ['Recurring', money(x.recurring)], ['Share of high value', pct(x.share_of_hv, { dec: 0 })], ['Past due', `${pl(x.past_due.count, 'deal')} · ${money(x.past_due.acv)}`], ['Pushed out', `${pl(x.pushed.count, 'deal')} · ${money(x.pushed.acv)}`]])}
        <h4>By stage</h4>${grpBars(x.by_stage, '', 'recurring')}
        ${ddBlock('By owner', `${esc(pl(x.by_owner.length, 'owner'))}`, grpBars(x.by_owner, '', 'recurring'))}
        <p class="xs mut" style="margin-top:10px">Recurring = ${esc(RK.recurring_rule)}. A push is a later close date than the one recorded at the previous stage change. The deals are listed on the Pipeline tab.</p>` } }; }
  if (id === 'hv_stuck' && hv.stuck) { const x = hv.stuck; return { title: 'High-value deals stuck in stage', sub: `${hv.rule} · ${st.rule}`, tags,
    tabs: { Overview: () => `${facts([['Deals', String(x.count)], ['Customers', String(x.customer_count)], ['Recurring at stake', money(x.recurring)], ['ACV', money(x.acv)], ['Share of high value', pct(x.share_of_hv, { dec: 0 })]])}
        <h4>By stage</h4>${grpBars(x.by_stage, '', 'recurring')}
        <button class="btnl" data-ref="rk:stuck">All stuck customers and the stage benchmarks ›</button>
        <p class="xs mut" style="margin-top:10px">Potential loss is the recurring ACV of these deals if they don't convert; it is not a forecast. The deals are listed on the Pipeline tab.</p>` } }; }
  if (id === 'lost') { if (!lo) return null; return { title: 'Lost opportunities', sub: `${rangeLabel()} vs ${L().range.cmp_label}`, tags: [baseMark()],
    tabs: { Overview: () => `${facts([['Lost ACV', money(lo.acv)], [CMPN, money(lo.cmp.acv)], ['Change', money(lo.variance, { sign: true }), lo.variance > 0 ? 'unf' : lo.variance < 0 ? 'fav' : ''], ['Deals', String(lo.count)], ['Recurring', money(lo.recurring)]])}
        ${say([esc(clean(lo.headline))])}
        <h4>By stage lost at</h4>${lo.stage_available ? grpBars(lo.by_stage, '') : '<div class="empty">The stage at loss was not supplied.</div>'}
        <h4>By reason</h4>${lo.reason_available ? grpBars(lo.by_reason, '') : '<div class="empty">No loss reasons supplied.</div>'}
        ${ddBlock('By product', `${esc(pl(lo.by_product.length, 'product'))}`, grpBars(lo.by_product, ''))}
        ${ddBlock('By deal source', `${esc(pl(lo.by_source.length, 'source'))}`, grpBars(lo.by_source, ''))}
        ${ddBlock(`Largest ${Math.min(lo.deals.length, 15)} lost deals`, 'by ACV', lostTable(lo.deals, 15))}` } }; }
  return null;
}

/* ---------- DRAWER ---------- */
function keyActivatable(el) { const tg = String(el.tagName || '').toUpperCase(); if (tg === 'BUTTON') return; if (!el.hasAttribute('tabindex')) el.setAttribute('tabindex', '0'); if (!el.getAttribute('role')) el.setAttribute('role', 'button'); el.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); e.stopPropagation(); el.click(); } }); }
function bindRefs(root) { root.querySelectorAll('[data-ref]').forEach(el => { if (el.dataset.bound || !el.dataset.ref) return; el.dataset.bound = '1'; el.addEventListener('click', e => { e.stopPropagation(); openDrawer(el.dataset.ref, el.dataset.dtab); }); keyActivatable(el); }); }
function closeDrawer() { S.drawer = null; S.drawerIntro = null; $('#drawer').classList.remove('open'); $('#app').classList.remove('drawer-open'); document.querySelectorAll('.fk.sel').forEach(x => x.classList.remove('sel')); const o = S.opener; S.opener = null; if (o && o.isConnected && o.focus) o.focus(); }
document.addEventListener('keydown', e => { if (e.key === 'Escape') closeDrawer(); });
function openDrawer(ref, tab) {
  if (!ref) return;
  if (S.drawer !== ref) S.drawerTab = tab || null; else if (tab) S.drawerTab = tab;
  if (!S.drawer && document.activeElement && document.activeElement !== document.body) S.opener = document.activeElement;
  const i = ref.indexOf(':'), kind = i < 0 ? ref : ref.slice(0, i), id = i < 0 ? null : ref.slice(i + 1);
  const b = { rk: rkDrawer, risk: rkDrawer, velocity: velocityDrawer, kpi: kpiDrawer, driver: driverDrawer, conc: concDrawer, conv: convDrawer, quarter: quarterDrawer, pipe: pipeDrawer, action: actionDrawer, qc: qcDrawer, scenario: scenarioDrawer }[kind];
  const spec = b ? b(id) : null; if (!spec) return;
  S.drawer = ref; $('#drawer').classList.add('open'); $('#app').classList.add('drawer-open');
  document.querySelectorAll('.fk').forEach(x => x.classList.toggle('sel', x.dataset.ref === ref));
  const names = Object.keys(spec.tabs); if (!S.drawerTab || !spec.tabs[S.drawerTab]) S.drawerTab = names[0];
  $('#dh').innerHTML = `<div class="top"><div><h2>${esc(spec.title)}</h2><div class="sub">${esc(spec.sub || '')}</div></div><button class="close" aria-label="Close" id="dclose">×</button></div><div class="badges">${(spec.tags || []).join('')}</div>${names.length > 1 ? `<div class="dtabs">${names.map(t => `<button data-t="${esc(t)}" class="${t === S.drawerTab ? 'on' : ''}">${esc(t)}</button>`).join('')}</div>` : '<div style="height:10px"></div>'}`;
  $('#dclose').onclick = closeDrawer;
  const dt = $('#dh .dtabs'); if (dt) dt.onclick = e => { const bb = e.target.closest('button'); if (bb) openDrawer(ref, bb.dataset.t); };
  $('#dbody').innerHTML = (S.drawerIntro ? `<div class="intro">${S.drawerIntro}<div class="xs mut" style="margin-top:6px">The evidence behind this point is below.</div></div>` : '') + spec.tabs[S.drawerTab]();
  bindRefs($('#dbody')); $('#dbody').scrollTop = 0;
}
function trendBlock(ids) {
  const s = sumSeries(ids), lo = Math.max(0, AS - 12);
  return lineChart({ labels: MONTHS.slice(lo), series: [{ name: 'Bookings', vals: s.actual.slice(lo), cls: 'l-act' }, { name: 'Last year', vals: s.py.slice(lo), cls: 'l-py' }], height: 190, W: 440, cur: AS - lo }) + legend([['background:var(--ink)', 'Bookings by month'], ['background:var(--ly)', 'Same month last year']]);
}
/* product and subsidiary bridges: the three largest steps by size and Others (the sum of the rest), keyed 1, 2, 3, Other on the axis */
function bridgeWf(mode) {
  const b = L().bridge[mode], keyed = mode !== 'by_measure';
  let steps = b.steps.map(s => ({ label: s.label, value: s.value, ref: 'driver:' + s.id })), key = '';
  if (keyed) {
    const ord = steps.slice().sort((x, y) => Math.abs(y.value) - Math.abs(x.value)), top = ord.slice(0, 3), rest = ord.slice(3);
    steps = top.map((s, i) => ({ ...s, short: String(i + 1) }));
    if (rest.length) steps.push({ label: `Others (${rest.length})`, short: 'Other', value: rest.reduce((t, s) => t + s.value, 0), ref: '', names: rest.map(s => s.label) });
    key = `<table class="mini wfkey"><tbody>${steps.map(s => `<tr${s.ref ? ` data-ref="${esc(s.ref)}"` : ''}><td style="width:46px"><b>${esc(s.short)}</b></td><td><span class="sw ${s.value >= 0 ? 'fav' : 'unf'}"></span>${esc(s.label)}${s.names ? `<div class="xs mut">${esc(s.names.join(', '))}</div>` : ''}</td><td class="num ${s.value >= 0 ? 'fav' : 'unf'}">${esc(money(s.value, { sign: true }))}</td></tr>`).join('')}</tbody></table>`;
  }
  return waterfall({ id: 'wf-' + mode, start: { label: `${CMPN} (${L().range.cmp_label})`, short: keyed ? CMPN : null, value: b.start.value }, end: { label: `This period (${L().range.label})`, short: keyed ? 'This period' : null, value: b.end.value }, steps, height: 300, W: 440 }) + key
    + `<p class="xs mut" style="margin-top:8px">The bridge reconciles to the dollar: the prior quarter plus every step equals this period (control ${esc(full(b.control))}).</p>`;
}
function velocityDrawer() {
  const v = VEL(), vt = PIPE.velocity_trend; if (!v) return null;
  return { title: 'Days to win', sub: `${rangeLabel()} vs ${L().range.cmp_label} · ${v.rule}`, tags: [baseMark()],
    tabs: { Overview: () => `${facts([['Average days', days(v.avg_days)], [CMPN, days(v.cmp.avg_days)], ['Change', dDays(v.variance_days), isNum(v.variance_days) && !v.small_sample ? (v.variance_days <= -3 ? 'fav' : v.variance_days >= 3 ? 'unf' : '') : ''], ['Deals won', String(v.n)], [`${money(100000)} or more`, `${pl(v.hv.n, 'deal')} · ${days(v.hv.avg_days)}`], ['Smaller deals', `${pl(v.std.n, 'deal')} · ${days(v.std.avg_days)}`]])}
        ${vt ? `<h4>Last 13 months</h4>${lineChart({ labels: vt.labels, series: [{ name: 'All won deals', vals: vt.actual, cls: 'l-act' }, { name: 'Last year', vals: vt.py, cls: 'l-py' }, { name: `${money(100000)} or more`, vals: vt.hv, cls: 'l-cmp' }], height: 190, W: 440, fmt: days, cur: vt.labels.length - 1 })}${legend([['background:var(--ink)', 'All won deals'], ['background:var(--ly)', 'Same month last year'], ['background:var(--budget)', `${money(100000)} or more`]])}` : ''}
        <h4>What it means</h4>${say([`${esc(money(IQ.open))} of ${esc(money(PIPE.open))} open pipeline is dated to close in ${esc(IQ.quarter || 'this quarter')}; a longer cycle moves more of the rest into later quarters' bookings.`, 'Days run from the opportunity\'s created date to its close date in Salesforce; recurring bookings are booked on that close date.', v.small_sample ? 'Fewer than eight deals won in this window: read the average with care.' : ''])}` } };
}
function kpiDrawer(id) {
  const k = kpi(id); if (!k) return null; const ratio = k.kind === 'ratio', t = k.status === 'in_line' ? 'neu' : (k.status === 'ahead' ? 'fav' : 'unf'), f = ratio ? v => pct(v) : money;
  const comps = id === 'total' ? L().drivers.measure : id === 'recurring' ? L().drivers.measure.filter(d => d.id !== 'm:non_recurring') : null;
  const extra = id === 'aov' ? [['Deals booked', String(k.orders)], [`Deals ${CMP()}`, String(k.orders_cmp)]] : id === 'pipeline_created' ? [['Deals created', String(k.count)], [cap(CMP()), String(k.count_cmp)]] : id === 'win_rate' ? [['Closed deals', String(k.closed)], [cap(CMP()), String(k.closed_cmp)]] : [];
  const tabs = { Overview: () => `${facts([['This period', f(k.actual)], [CMPN, f(k.comparator)], ['Change', ratio ? pts(k.variance) : money(k.variance, { sign: true }), t]].concat(extra))}
      ${id === 'total' ? `<h4>Reading</h4>${say([esc(clean(L().headline.text))])}` : ''}
      ${KPI_SERIES[id] ? `<h4>Last 13 months</h4>${trendBlock(KPI_SERIES[id])}` : ''}
      ${id === 'pipeline_created' && PIPE.created_trend ? `<h4>Pipeline created each month</h4>${lineChart({ labels: PIPE.created_trend.labels, series: [{ name: 'Created', vals: PIPE.created_trend.actual, cls: 'l-act' }, { name: 'Last year', vals: PIPE.created_trend.py, cls: 'l-py' }], height: 200, W: 440, cur: PIPE.created_trend.labels.length - 1 })}${legend([['background:var(--ink)', 'Created'], ['background:var(--ly)', 'Same month last year']])}<p class="xs mut" style="margin-top:6px">The leading indicator of future bookings. A deal counts as created when it reaches 03 - EVALUATE.${PIPE.not_yet_created ? ` ${esc(money(PIPE.not_yet_created.acv))} of open pipeline at ${esc(PIPE.not_yet_created.as_of)} (${esc(pl(PIPE.not_yet_created.count, 'deal'))}) has not reached it yet.` : ''}</p>` : ''}
      ${comps ? `<h4>Largest drivers</h4>${divBars(comps.map(d => ({ name: d.label, value: d.variance, ref: 'driver:' + d.id })))}` : ''}
      ${id === 'win_rate' ? `<button class="btnl" data-ref="conv:win">Win rate by source and product ›</button>` : ''}
      ${id === 'pipeline_created' || id === 'win_rate' ? `<p class="xs mut" style="margin-top:12px">Salesforce opportunity data (New Sales and Seat Expansion). Not comparable with booking ACV.</p>` : ''}
      ${k.small_sample ? `<div class="nx" style="margin-top:12px">Fewer than eight closed deals in this window: read the rate with care.</div>` : ''}` };
  if (id === 'total') { tabs['By measure'] = () => bridgeWf('by_measure'); tabs['By product'] = () => bridgeWf('by_product'); tabs['By subsidiary'] = () => bridgeWf('by_subsidiary'); }
  return { title: k.label, sub: `${rangeLabel()} vs ${L().range.cmp_label}`, tags: [tag(t, k.status === 'ahead' ? 'Ahead' : k.status === 'behind' ? 'Behind' : 'In line'), baseMark()], tabs };
}
function driverDrawer(id) {
  const d = ldrv(id); if (!d) return null; const dd = DRV_BY[id], sg = SIG[id], t = tone(d.variance);
  return { title: d.label, sub: `${DIM_LABEL[dd.dimension]} · ${rangeLabel()} vs ${L().range.cmp_label}`, tags: [tag(t), sg ? persistTag(sg.persistence_hint) : '', baseMark()],
    tabs: { Overview: () => `${facts([['This period', money(d.actual)], [CMPN, money(d.comparator)], ['Change', money(d.variance, { sign: true }), t], ['Change %', pct(d.variance_pct, { sign: true })], ['Share of movement', pct(d.share_of_abs_variance, { dec: 0 })], ['Tier', cap(d.tier)]])}
      <h4>What it means</h4>${say([...(D() ? (D().findings || []).filter(f => ((f.scope || {}).drivers || []).includes(id)) : []).map(f => { const st = (f.statements || []).find(x => x.state === 'analytical_inference' || x.state === 'hypothesis') || (f.statements || [])[0] || {}; return `<b>${esc(f.title)}.</b> ${esc(clean(st.text))}`; }), ...d.reading.map(x => esc(clean(x)))])}
      ${sg && sg.runrate.eligible ? `<h4>${esc(MONTH)} against its usual range</h4>${rangeBar(id, { ref: false })}${rangeLegend()}` : ''}
      <h4>Checks</h4><div class="chips">${(sg ? sg.tests : []).map(q => `<span class="cp ${q.state === 'fired' ? 'on' : ''}">${q.state === 'fired' ? '● ' : ''}${esc(q.label)}</span>`).join('') || '<span class="cp">None</span>'}</div>`,
      Trend: () => `<h4>Last 13 months</h4>${trendBlock([id])}` } };
}
function concDrawer() {
  const c = L().concentration;
  return { title: 'Customers and deals', sub: `${rangeLabel()} · ${pl(c.customers, 'customer')} booked`, tags: [baseMark()],
    tabs: { Customers: () => `${facts([['Top 2', pct(c.top2_share, { dec: 0 })], ['Top 5', pct(c.top5_share, { dec: 0 })], ['Largest deal', pct(c.largest_order_share, { dec: 0 })]])}
        <h4>Largest customers this window (net)</h4>${hBars(c.top_customers.map(x => ({ name: x.label + (x.repapered ? ' *' : ''), value: x.actual, label: `${money(x.actual)} · ${pct(x.share, { dec: 0 })}`, tip: `${cap(CMP())} ${money(x.cmp)}${x.repapered ? ' · ' + x.repapered.note : ''}` })))}
        ${c.top_customers.filter(x => x.repapered).map(x => `<p class="xs mut">* ${esc(x.label)}: ${esc(x.repapered.note)}</p>`).join('')}
        <h4>Change vs ${esc(CMP())}</h4>${divBars(c.customer_movers.map(m => ({ name: m.label, value: m.variance })))}`,
      Deals: () => tbl([['Opportunity'], ['Customer'], ['Product'], ['Measure'], ['ACV', 'num']], c.top_orders.map(o => `<tr><td>${esc(o.label)}</td><td>${esc(o.customer)}</td><td>${esc(o.product)}</td><td>${esc(o.split || o.measure)}</td><td class="num">${esc(money(o.acv))}</td></tr>`).join(''))
        + '<p class="xs mut" style="margin-top:10px">Recurring bookings are won opportunities; non-recurring revenue has no account or opportunity. There are no invoices in the view.</p>' } };
}
function convDrawer(id) {
  const cv = L().conversion, cp = L().conversion_cmp;
  return { title: id === 'loss' ? 'Why deals are lost' : 'Win rate', sub: `${rangeLabel()} · deals closed in the window`, tags: [baseMark()],
    tabs: { Overview: () => `${facts([['Win rate', pct(cv.win_rate, { dec: 0 })], [cap(CMP()), pct(cp.win_rate, { dec: 0 })], ['Change', pts(isNum(cv.win_rate) && isNum(cp.win_rate) ? kpi('win_rate').variance : null), tone(kpi('win_rate').variance, 0.01)], ['Won', `${pl(cv.won.count, 'deal')} · ${money(cv.won.acv)}`], ['Lost', `${pl(cv.lost.count, 'deal')} · ${money(cv.lost.acv)}`], ['By value', `${pct(cv.win_rate_value, { dec: 0 })} · last year ${pct(cp.win_rate_value, { dec: 0 })}`]])}
        <h4>By deal source</h4>${hBars(cv.by_source.filter(s => isNum(s.win_rate)).map(s => ({ name: s.label, value: s.win_rate, cls: s.win_rate < (cv.win_rate || 0) - 0.1 ? 'unf' : '', label: `${pct(s.win_rate, { dec: 0 })} · ${s.won + s.lost}` })))}
        ${ddBlock('By product', `${esc(pl(cv.by_product.length, 'product'))}`, hBars(cv.by_product.filter(s => isNum(s.win_rate)).map(s => ({ name: s.label, value: s.win_rate, label: `${pct(s.win_rate, { dec: 0 })} · ${s.won + s.lost}` }))))}
        ${CAN_LOSS ? ddBlock('Lost ACV by reason', esc(money(cv.lost.acv)), hBars(cv.loss_reasons.map(r => ({ name: r.label, value: r.acv, label: `${money(r.acv)} · ${pct(r.share, { dec: 0 })}` })), 'No deals lost in this window.')) : '<p class="xs mut" style="margin-top:12px">The view has no loss reason, so lost ACV is not split by reason.</p>'}
        ${L().lost ? `<button class="btnl" data-ref="rk:lost">The lost deals ›</button>` : ''}` } };
}
function quarterDrawer(q) {
  const r = BCQ.find(x => x.quarter === q); if (!r) return null;
  return { title: `Pipeline closing in ${q}`, sub: `open pipeline expected to close in ${q} (fiscal quarter) · as of ${PIPE.as_of}`, tags: [baseMark()],
    tabs: { Overview: () => `${facts([['Open pipeline', money(r.open)], ['Deals', String(r.count)], [`Late stage`, money(r.late_stage)]])}
      <h4>What it means</h4>${say([isNum(r.late_stage) ? `${esc(money(r.late_stage))} sits in late stage (${esc(LATE)}).` : '', 'Unweighted ACV; the view holds no pipeline target, so there is no coverage ratio.', 'Close quarters use the close date; deals already past due are counted as not closing, not here.'])}` } };
}
function pipeDrawer() {
  const grid = PIPE.by_stage_quarter, mx = Math.max(...grid.rows.flatMap(x => x.cells.map(c => c.acv)), 1);
  return { title: 'Open pipeline', sub: `as of ${PIPE.as_of} · Salesforce ACV, unweighted`, tags: [baseMark()],
    tabs: { Overview: () => `${facts([['Open', money(PIPE.open)], ['Deals', String(PIPE.open_count)], ['Average deal', money(PIPE.avg_value)], [`Late stage (${LATE})`, money(PIPE.late_stage)]])}
      ${PIPE.py ? `<h4>A year earlier</h4>${facts([['Open', money(PIPE.py.open)], ['Change', pct(PIPE.py.open_var_pct, { sign: true })], ['Deals', String(PIPE.py.open_count)], ['Average deal', money(PIPE.py.avg_value)]])}` : ''}
      <h4>By fiscal close quarter</h4>${hBars(BCQ.map(r => ({ name: r.quarter, value: r.open, ref: 'quarter:' + r.quarter, label: `${pl(r.count, 'deal')} · ${money(r.open)}` })))}
      <p class="xs mut" style="margin-top:12px">${PIPE.py ? `Prior year from ${esc(PIPE.py.source)}. ` : 'Open pipeline a year ago is not in the workbook, so no prior-year comparison is shown. '}No pipeline target is in the view, so there is no coverage ratio.</p>`,
      'By stage': () => `<h4>ACV by stage and expected close quarter · as at ${esc(PIPE.grid_as_of || PIPE.as_of)}</h4>` + tbl([['Stage'], ...grid.columns.map(c => [c, 'num'])], grid.rows.map(row => `<tr><td>${esc(row.stage)}</td>${row.cells.map(c => `<td class="num" style="background:color-mix(in srgb, var(--s1) ${(c.acv / mx * 55).toFixed(1)}%, transparent);color:${c.acv / mx > 0.45 ? 'var(--bg)' : 'inherit'}" data-tip="${esc(row.stage)} · ${esc(c.col)}|${esc(pl(c.count, 'deal'))} · ${esc(money(c.acv))}">${c.count ? esc(money(c.acv)) : '—'}</td>`).join('')}</tr>`).join(''))
        + `<p class="xs mut" style="margin-top:8px">Late stage = ${esc(LATE)}. Past due = expected close date before ${esc(PIPE.grid_as_of || PIPE.as_of)}.</p><h4>Typical days in each stage</h4>${hBars(PIPE.stage_days.map(s => ({ name: s.stage, value: s.days, label: `${s.days.toFixed(0)} days` })))}` } };
}
function actionDrawer(id) {
  const a = ACTIONS().find(x => x.id === id); if (!a) return null;
  return { title: clean(a.question), sub: 'Suggested owner · for discussion', tags: [baseMark()],
    tabs: { Overview: () => `${facts([['At stake', isNum(a.exposure) ? `${money(a.exposure)} ${a.exposure_label}` : '—'], ['Owner (suggested)', a.owner], ['Target date', a.date]])}
      <h4>Evidence needed</h4>${say(a.evidence.map(esc))}
      <button class="btnl" data-ref="${esc(a.ref)}">Open the evidence ›</button>` } };
}
function qcDrawer() {
  const qc = P.qc, dot = r => r === 'PASS' ? 'fav' : r === 'FAIL' ? 'unf' : r === 'WARN' ? 'amb' : 'neu';
  return { title: 'Data quality and scope', sub: `${VERIFIED ? 'data verified' : qc.status.toLowerCase()} · ${pl(qc.caveats.length, 'note')}`, tags: [],
    tabs: { Checks: () => `<table class="mini"><tbody>${qc.checks.map(c => `<tr><td style="width:90px">${tag(dot(c.result), c.result.toLowerCase())}</td><td><b class="ink">${esc(cap(c.id.replace(/_/g, ' ')))}</b><div class="xs mut">${esc(c.detail)}</div></td></tr>`).join('')}</tbody></table>
      <h4>Notes</h4>${say(qc.caveats.map(x => esc(clean(x))))}
      <h4>Not available in this data</h4>${say(Object.entries(P.capabilities).filter(([, v]) => v.state !== 'available').map(([k, v]) => `<b class="ink">${esc(v.label || cap(k.replace(/_/g, ' ')))}</b>: ${esc(v.reason)}`))}` } };
}
function scenarioDrawer(q) {
  const s = OUT.scenario.find(x => x.quarter === q); if (!s) return null;
  return { title: `What ${q} pipeline could deliver`, sub: 'a straight-line range · not a forecast', tags: [tag('sky', 'scenario')],
    tabs: { Overview: () => `${facts([['Open closing in the quarter', money(s.open)], ['At win rate by value', money(s.at_win_rate)], ['Rate by value', pct(s.win_rate_applied, { dec: 0 })], ['At win rate by count', money(s.at_count_rate)], ['Rate by count', pct(s.count_rate_applied, { dec: 0 })], [`Won in ${s.py_quarter || 'last year'}`, money(s.py_won)]])}
      <h4>How it is built</h4>${say([esc(clean(OUT.rule)) + '.', esc(clean(OUT.note))])}` } };
}

/* ---------- boot ---------- */
function renderAll() { renderHeader(); renderPipeline(); renderBookings(); renderOutlook(); renderGlossary(); }
renderAll();
const hashTab = String(location.hash || '').replace('#', '');
setTab(TABQ[hashTab] ? hashTab : S.tab);
