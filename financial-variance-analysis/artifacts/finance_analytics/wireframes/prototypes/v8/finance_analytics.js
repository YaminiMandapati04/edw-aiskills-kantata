/* Finance diagnostic renderer 1.3.0, prototype v8 restyle (contract sda.finance-analysis/1.1.0).
   Insight-led layout: a bullet summary, a P&L flow strip, charts first, text only in the drill-down. Shows the
   admitted diagnosis where one exists for the selected lens; every other lens reads as the engine baseline.
   The renderer computes nothing economic. It formats, arranges, filters and sorts values the engine emitted.
   Permitted arithmetic: chart geometry, display sign flips, sums of engine-emitted facts for a dimension lens,
   shares for display. Null renders as "—", never as zero. Negatives print in brackets; "adverse" is never shown. */
'use strict';
const P = window.__SDA_PAYLOAD__;
if (!P || P.contract_version !== 'sda.finance-analysis/1.1.0') { document.body.innerHTML = '<div style="padding:40px;font-family:sans-serif">Refused: payload contract is not sda.finance-analysis/1.1.0.</div>'; throw new Error('contract'); }
const META = P.meta, PER = META.periods, AS = META.as_of.idx, ACC = P.accounts, SIG = P.signals, OUT = P.outlook, DIAG = P.diagnosis || null;
const MON = META.materiality.monitoring_abs;
const ACC_BY = Object.fromEntries(ACC.map(a => [a.id, a]));
const DRV_BY = Object.fromEntries(P.drivers.map(d => [d.id, d]));
const SS = Object.fromEntries(P.statement_series.map(s => [s.id, s]));
const SECTION_LABEL = { rev: 'Revenue', cos: 'Cost of sales', opex: 'Operating expenses', syn: 'Synergies and strategic investments', nonop: 'Non-operating income (expense)' };
const KPI_LINE = { revenue: 'rev', cogs: 'cos', gross_profit: 'gp', opex: 'opex', ebitda: 'ebitda', nonop: 'nonop', net_income: 'ni' };
const LINE_LABEL = { rev: 'Revenue', cos: 'Cost of sales', gp: 'Gross profit', gpm: 'Gross margin', opex: 'Operating expenses', ebitda: 'Adjusted EBITDA', ebm: 'Adjusted EBITDA margin', nonop: 'Non-operating income (expense)', ni: 'Net income', nim: 'Net income margin' };
const PERSIST = { one_off_candidate: ['One-off?', 'amb'], persistent: ['Recurring', 'unf'], recurring_level_change: ['New level', 'unf'], seasonal: ['Seasonal', 'sky'], timing_reversal: ['Timing', 'sky'], coverage: ['No budget line', 'amb'], undetermined: null };
const MONTH = META.as_of.name ? new Date(META.as_of.start + 'T00:00:00').toLocaleString('en-US', { month: 'long' }) : META.as_of.label;

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
function pts(v) {
  if (!isNum(v)) return '—';
  const s = (Math.abs(v) * 100).toFixed(1);
  if (v < 0 && Math.abs(v) * 100 >= 0.05) return '(' + s + ') pt';
  return (v > 0 ? '+' : '') + s + ' pt';
}
const tone = (v, floor = MON) => !isNum(v) || Math.abs(v) < floor ? 'neu' : (v > 0 ? 'fav' : 'unf');
const toneWord = t => ({ fav: 'Favourable', unf: 'Unfavourable', neu: 'In line' })[t];
const tag = (t, word) => `<span class="tag ${t}">${esc(word || toneWord(t))}</span>`;
const persistTag = h => PERSIST[h] ? tag(PERSIST[h][1], PERSIST[h][0]) : '';
/* engine prose: moderate words and bracketed negatives */
const clean = t => String(t || '').replace(/adverse/g, 'unfavourable').replace(/Adverse/g, 'Unfavourable').replace(/(\d)mm\b/g, '$1mn')
  .replace(/\(−\s?(\$?[\d.,]+(?:k|mn|%)?)\)/g, '($1)')
  .replace(/−\s?(\$?[\d.,]+(?:k|mn|%)?)( bps)?/g, (m, a, b) => '(' + a + ')' + (b || ''));
const cap = s => s ? s[0].toUpperCase() + s.slice(1) : s;
const joinAnd = arr => arr.length < 2 ? (arr[0] || '') : arr.slice(0, -1).join(', ') + ' and ' + arr[arr.length - 1];
const acctName = id => ACC_BY[id] ? ACC_BY[id].name : id;
const shortLbl = p => p.name ? p.name.slice(0, 3) + " '" + String(p.year).slice(2) : p.label;
const sumSeries = ids => { const n = PER.length; const out = { actual: Array(n).fill(null), py: Array(n).fill(null), budget: Array(n).fill(null) }; ids.forEach(id => { const s = ACC_BY[id] && ACC_BY[id].series; if (!s) return; ['actual', 'py', 'budget'].forEach(k => { for (let i = 0; i < n; i++) if (isNum(s[k][i])) out[k][i] = (out[k][i] || 0) + s[k][i]; }); }); return out; };

/* ---------- state and lens access ---------- */
const S = { tab: 'summary', lens: META.primary_lens.id, drawer: null, drawerTab: null, bridgeMode: 'reported', bridgeSel: null, dimDriver: null, opener: null };
const L = () => P.lenses[S.lens];
const X = () => L().explanations;
const lacct = id => L().accounts.find(a => a.id === id);
const ldrv = id => L().drivers.find(d => d.id === id);
const lline = id => L().lines.find(x => x.id === id);
const lkpi = id => L().kpis.find(k => k.id === id);
const xacct = id => X().accounts.find(x => x.id === id);
const actOf = did => L().actions.find(a => a.subject_ref === did);
const D = () => (DIAG && DIAG.lens && `${DIAG.lens.window}_${DIAG.lens.basis}` === S.lens) ? DIAG : null;
const readout = () => (D() && D().readout) || {};
const findingById = id => D() ? (D().findings || []).find(f => f.id === id) : null;
const diagMark = () => '<span class="tag fav">admitted diagnosis</span>';
const baseMark = () => '<span class="tag amb">engine baseline</span>';
const basisWord = () => L().basis_label;
const rangeLabel = () => L().window === 'MTD' ? META.as_of.name : (L().range ? L().range.label : S.lens);
/* the engine's budget reliability check: budget figures on failed lines reflect the load, not performance */
const BCHK = META.budget_check || null;
const budgetNote = (force = false) => (BCHK && !BCHK.reliable && (force || L().basis === 'budget')) ? `<div class="bnote" role="note"><b>Budget not meaningful</b><span>for ${esc(joinAnd(BCHK.failed.map(s => s.toLowerCase())))}: the budget is not in line with actuals (${esc(BCHK.rule)}). Variances against it reflect the budget load, not performance; read these lines against prior year.</span></div>` : '';
const twin = () => { const t = P.lenses[`${L().window}_${L().basis === 'budget' ? 'py' : 'budget'}`]; return t && t.available ? t : null; };

/* ---------- reasoning (selection and phrasing of engine signals only) ---------- */
function leadAccount(d) { const m = d.accounts.map(id => lacct(id)).filter(a => a && isNum(a.variance)); return m.length ? m.sort((a, b) => Math.abs(b.variance) - Math.abs(a.variance))[0] : null; }
function rangeOf(id) { const rr = SIG[id].runrate, ds = ACC_BY[id].display_sign; if (!isNum(rr.min)) return null; const a = rr.min * ds, b = rr.max * ds; return [Math.min(a, b), Math.max(a, b)]; }
/* short sentences about one account's latest month; window-aware */
function acctReasons(id, dActionRef) {
  const Lx = L(), a = lacct(id), s = SIG[id], t = Object.fromEntries(s.tests.map(x => [x.id, x])), f = new Set(s.fired), out = [];
  const act = dActionRef ? Lx.actions.find(x => x.subject_ref === dActionRef) : null, r = rangeOf(id);
  if (Lx.window !== 'MTD') {
    if (isNum(a.share_of_abs_variance)) out.push(`${pct(a.share_of_abs_variance, { dec: 0 })} of the total movement over the ${Lx.window_label}`);
    if (f.has('outlier_month') && r) out.push(`${MONTH} itself ran outside its usual ${money(r[0])}–${money(r[1])} monthly range`);
    return out;
  }
  if (f.has('persistent_gap') && Lx.basis === 'budget') {
    const ev = t.persistent_gap.evidence; let x = `${a.variance < 0 ? 'off' : 'ahead of'} budget in ${ev.months_same_side} of the last ${ev.months_compared} months, so a recurring gap, not noise`;
    const fx = act && act.forecast && act.forecast.remaining_months_effect; if (isNum(fx)) x += `; if it continues, another ${money(Math.abs(fx))} ${fx < 0 ? 'of shortfall' : 'of benefit'} by year end`;
    out.push(x);
  } else if (f.has('outlier_month') && r) {
    out.push(`${MONTH} came in at ${money(ACC_BY[id].series.actual[AS])} against a usual ${money(r[0])}–${money(r[1])} a month`);
    if (s.persistence_hint === 'one_off_candidate') out.push('likely a one-off, so little full-year impact if it does not repeat');
  } else if (f.has('seasonal_echo')) out.push(`the same move happened last ${MONTH}, so likely seasonal; check the budget phasing`);
  else if (f.has('budget_outside_run_rate')) out.push('the budget sits away from recent run-rate, so part of the gap is the plan, not the month');
  else if (f.has('step_change')) out.push('a new level that has held for two months');
  return out;
}
function driverReason(d) {
  const lead = leadAccount(d); if (!lead) return '';
  const parts = [];
  if (d.accounts.length > 1) parts.push(`mostly ${acctName(lead.id)} at ${money(lead.variance, { sign: true })}`);
  parts.push(...acctReasons(lead.id, d.id));
  if (parts.length === (d.accounts.length > 1 ? 1 : 0) && isNum(d.share_of_abs_variance)) parts.push(`${pct(d.share_of_abs_variance, { dec: 0 })} of the total movement`);
  return cap(parts.join('; ')) + '.';
}
const RULE_ASK = { outlier_month: 'Confirm whether the {m} spike in {l} is a one-off or a new run-rate', persistent_gap: 'Decide whether to re-plan {l} or act to close the gap', seasonal_echo: 'Check that the {l} budget phasing reflects the seasonal pattern', budget_outside_run_rate: 'Review the {l} budget assumption against recent run-rate', yoy_break: 'Explain the break in the year-on-year pace of {l}' };
const askText = a => (RULE_ASK[a.rule] || "Get the owner's explanation for the movement in {l}").replace('{m}', MONTH).replace('{l}', a.label);

/* ---------- header, tabs, footer, glossary ---------- */
function renderHeader() {
  $('#pageTitle').textContent = `Finance review · ${META.as_of.name || META.as_of.label}`;
  $('#scope').innerHTML = `<span class="chip">Scope <b>${esc(META.scope.filtered_to || 'All subsidiaries')}${META.scope.filtered_to ? '' : ` (${META.scope.subsidiaries.length})`}</b></span><span class="chip">${esc(String(META.currency).split(' ')[0])}</span><span class="chip">${META.months_of_history} months of history</span>`;
  const curW = L().window, curB = L().basis;
  $('#lens').innerHTML = `<div class="lrow"><span class="lab">Window</span><span class="seg" id="segWin">${['MTD', 'QTD', 'YTD', 'LTM'].map(w => `<button data-w="${w}" class="${w === curW ? 'on' : ''}" ${P.lenses[`${w}_${curB}`].available ? '' : 'disabled'}>${esc(META.window_labels[w])}</button>`).join('')}</span></div>
    <div class="lrow"><span class="lab">Compare</span><span class="seg" id="segBas">${['budget', 'py'].map(b => `<button data-b="${b}" class="${b === curB ? 'on' : ''}">vs ${esc(META.basis_labels[b])}</button>`).join('')}</span></div>`;
  $('#segWin').onclick = e => { const b = e.target.closest('button'); if (b && !b.disabled) setLens(`${b.dataset.w}_${curB}`); };
  $('#segBas').onclick = e => { const b = e.target.closest('button'); if (b) setLens(`${curW}_${b.dataset.b}`); };
  const qc = P.qc, sb = $('#stateBadge');
  sb.className = 'state' + (qc.status === 'CLEAN' ? ' ok' : '');
  sb.innerHTML = `${qc.status === 'CLEAN' ? '✓' : '!'} Data ${esc(qc.status.toLowerCase())} · ${qc.caveats.length} note(s) · ${D() ? 'reviewed' : 'engine reading'}`;
  sb.onclick = () => openDrawer('qc');
  $('#foot').innerHTML = `<span>Source: ${esc(META.sources.join(', '))}</span><span>Generated ${esc(String(META.generated_at).slice(0, 10))}</span><span>${D() ? 'Reviewed diagnosis admitted' : 'Engine reading; no reviewed diagnosis'}</span><span>Renderer 1.3.0 · analysis ${esc(String(P.analysis_hash).slice(0, 12))}</span>`;
}
const TABQ = { summary: 'Where do we stand, why, and what needs a decision?', drivers: 'What moved the result, and is it the plan or the month?', outlook: 'Where does the year land?' };
function setTab(t) { S.tab = t; document.querySelectorAll('nav.tabs button[data-tab]').forEach(b => b.classList.toggle('active', b.dataset.tab === t)); document.querySelectorAll('.view').forEach(v => v.classList.toggle('active', v.id === 'view-' + t)); $('#tabQ').textContent = TABQ[t]; history.replaceState(null, '', '#' + t); renderGlossary(); }
$('#tabs').addEventListener('click', e => { const b = e.target.closest('button[data-tab]'); if (b) setTab(b.dataset.tab); });
function setLens(id) { if (!P.lenses[id] || !P.lenses[id].available) return; S.lens = id; S.bridgeSel = null; closeDrawer(); renderAll(); }
/* glossary: every label on the page, grouped; "This tab" shows the shared groups plus the open tab's own labels,
   "All labels" shows everything. Detail-panel labels always show, since panels open from every tab. */
const TAB_NAME = { summary: 'Summary', drivers: 'Drivers', outlook: 'Outlook' };
const sw = st => `<i class="sw" style="${st}"></i>`;
function glossaryRows() {
  const m = META.materiality, mon = money(m.monitoring_abs), sens = OUT && OUT.state === 'calculated' ? OUT.lines.ebitda.mechanical.sensitivity.map(x => x.label) : [];
  return [
    ['all', 'Direction', [
      [tag('fav'), 'Helps profit against the comparator: more revenue, or less cost.'],
      [tag('unf'), 'Hurts profit against the comparator: less revenue, or more cost.'],
      [tag('neu'), `Within ${mon} of the comparator (the monitoring threshold); not treated as a driver.`],
      [`${tag('fav', 'Ahead')}${tag('unf', 'Behind')}`, 'Used on the P&L figures: the line is better or worse than the comparator by more than the threshold.']]],
    ['all', 'Persistence', [
      [persistTag('one_off_candidate'), 'The latest month sits outside its usual six-month range for the first time; a second month would make it a new level.'],
      [persistTag('persistent'), 'Off budget on the same side in most recent months; a structural gap rather than noise.'],
      [persistTag('recurring_level_change'), 'Has stepped to a new level and held it for two months or more.'],
      [persistTag('seasonal'), 'The same month last year moved the same way against its own run-rate.'],
      [persistTag('timing_reversal'), 'This month reverses last month\'s gap: likely a timing shift between months.'],
      [persistTag('coverage'), 'Activity on an account that has no budget line; a comparability gap, not performance.']]],
    ['all', 'Figures', [
      ['($76k) · (4.2) pt', 'Brackets mark a negative figure. pt is a change in percentage points of margin.'],
      ['+$510', 'A plus sign marks a favourable change.'],
      ['$143k · $1.92mn', 'Thousands (k) and millions (mn) of US dollars, converted as stored in the marts.'],
      ['n.m. · —', 'n.m.: not meaningful (a percentage of 1,000% or more). —: not available, never zero.'],
      ['Materiality', `Executive ${money(m.executive_abs)} · management ${money(m.management_abs)} · monitoring ${mon} (${esc(m.basis)}). Lines under the monitoring threshold read as in line.`]]],
    ['summary', 'Summary tab', [
      ['Bold lead of a bullet', 'The conclusion. The sentence after it is the evidence and what it means; click the bullet for the detail.'],
      ['<i class="rvt" style="font-style:normal;font-family:var(--mono);font-size:10px;text-transform:uppercase;background:var(--accent);color:var(--accent-ink);padding:1px 6px">reviewed</i>', 'A conclusion from the admitted diagnosis rather than the engine; it shows only on the view the diagnosis was written for.'],
      ['<span class="opx">−  =  ±</span>', 'In the P&L strip, the operators show the order of calculation: revenue less cost of sales gives gross profit, less opex gives Adjusted EBITDA, plus or minus non-operating items gives net income.'],
      [`${sw('background:var(--s1);width:22px;height:6px')}${sw('background:var(--budget);width:2px;height:12px')} Margin bars`, 'Margin bars: the dark bar is this view\'s margin; the gold mark is the comparator\'s margin.'],
      ['Full-year EBITDA (run-rate)', 'Year to date plus the remaining months at the run-rate rule; a projection rule, not a forecast.'],
      ['What moved net income', 'Each driver\'s variance against the comparator, from the EBITDA bridge and the steps down to net income.'],
      ['At stake · proposed, not approved', 'The amount behind a decision. Owners are suggested functions and dates are rule-generated targets.']]],
    ['drivers', 'Drivers tab', [
      ['By driver · Plan vs month · To net income', 'Three views of the bridge: each driver\'s step; the budget gap split into plan and month (Month vs Budget only); the steps from Adjusted EBITDA to net income.'],
      [`${sw('background:var(--s1);width:10px;height:10px')} Start / end`, 'The comparator\'s Adjusted EBITDA on the left, the actual on the right; the bars between are the steps.'],
      [`${sw('background:var(--pos);width:10px;height:10px')}${sw('background:var(--adv);width:10px;height:10px')} Green · gold steps`, 'Green steps add to profit, gold steps take away from it.'],
      ['Plan · Month · No budget line', 'In Plan vs month: Plan is the budget\'s distance from run-rate, Month is the month\'s move from run-rate, No budget line is activity on unbudgeted accounts.'],
      ['Driver', 'An account group (L4 in the chart of accounts) or a single account; the bridge has one step per driver.'],
      ['Share of movement', 'The driver\'s share of the total absolute variance across all accounts.'],
      [`${sw('background:var(--rng);width:22px;height:6px')} ${sw('background:var(--muted);width:2px;height:12px')} ${sw('background:var(--budget);width:3px;height:12px')} ${sw('background:var(--s1);width:9px;height:9px;transform:rotate(45deg)')} Range bars`, `Range bars: the band is the account's usual six-month range, the grey tick its run-rate, the gold tick its budget, the diamond ${esc(MONTH)}'s actual (red or green when it moves the result).`],
      [`Accounts above ${mon}`, 'Only accounts whose variance clears the monitoring threshold get a range bar.'],
      ['By subsidiary', 'The sum of each subsidiary\'s account variances for the chosen driver; the page scope does not change.']]],
    ['outlook', 'Outlook tab', [
      ['EBITDA year to date', 'Actual Adjusted EBITDA for the closed months of the fiscal year, against budget.'],
      ['Full-year EBITDA (run-rate)', 'Year to date plus the remaining months at the run-rate rule. A rule, not a forecast; nothing declared by management is included.'],
      ['Last year full year · Full-year budget', 'The comparators for the full year. "Not in the extract" means the query did not include future budget months.'],
      [`${sw('background:var(--s1);width:16px;height:3px')} ${sw('background:repeating-linear-gradient(90deg,var(--s1) 0 3px,transparent 3px 6px);width:16px;height:3px')} ${sw('background:repeating-linear-gradient(90deg,var(--budget) 0 5px,transparent 5px 8px);width:16px;height:3px')} ${sw('background:var(--ly);width:16px;height:3px')} Chart lines`, 'Monthly chart: actual, run-rate for the remaining months (dotted), budget (dashed gold), last year (grey). The lime dot is the analysis month.'],
      ['Run-rate rules', `${sens.length ? esc(sens.join(' · ')) + '. ' : ''}Different ways to project the remaining months; the lime bar is the rule behind the headline figure. The spread shows how much the choice of rule matters.`],
      ['Full-year bridge', 'From the full-year budget (or year to date when no budget is loaded) to the full-year run-rate figure.'],
      ['If current gaps continue', 'What each recurring driver gap would add over the remaining months if it persists. Not in the run-rate total; "no carry" means the gap is not expected to repeat.'],
      ['Proposals only · forecast credit 0', 'Nothing here changes a forecast until a named owner accepts it.']]],
    ['panel', 'Detail panels (open from any tab)', [
      ['Overview · Trend · Subsidiaries', 'Panel tabs: the reading, the last 13 months, and the split by subsidiary.'],
      ['Actual · Budget · Variance', 'The figures for the selected view; Variance follows the profit sign, so (…) is unfavourable.'],
      ['What it means · Next step', 'The engine\'s reading of the signals, and the proposed follow-up with its suggested owner and target date.'],
      ['Patterns found · other checks clear', 'The structural tests that fired on the account; hover "other checks clear" for those that did not.'],
      ['Where the figures come from', 'Each figure in the text with the payload field it was read from.']]],
    ['all', 'Publication state', [
      [baseMark(), 'Deterministic reading of the ledger by the engine; it names no business cause.'],
      [diagMark(), 'A reviewed reading that passed the validation gate for one view; still not independently verified.'],
      ['Data qualified · notes', 'The data-quality badge: click it for the checks, caveats and what the data cannot answer.'],
      ['<span class="tag unf">Test data</span>', 'Local sample figures from a workbook; never present them as real.']]]];
}
function renderGlossary() {
  const host = $('#glossary'), open = !!(host.querySelector('.gls-d') || {}).open, all = !!S.glsAll, groups = glossaryRows();
  const shown = groups.filter(([sc]) => all || sc === 'all' || sc === 'panel' || sc === S.tab).sort((x, y) => all ? 0 : (y[0] === S.tab) - (x[0] === S.tab)), n = g => g.reduce((s, x) => s + x[2].length, 0);
  host.innerHTML = `<details class="gls-d"${open ? ' open' : ''}><summary><h2>How to read this page</h2><span class="hint">${all ? 'all tabs' : esc(TAB_NAME[S.tab] || '') + ' tab'} · ${n(shown)} labels · click to show or hide</span><span class="chev">▾</span></summary>
    <div class="gls-bar"><span class="tog" id="glsMode"><button data-m="tab" class="${all ? '' : 'on'}">This tab (${n(groups.filter(([sc]) => sc === 'all' || sc === 'panel' || sc === S.tab))})</button><button data-m="all" class="${all ? 'on' : ''}">All labels (${n(groups)})</button></span></div>
    <table class="gls-t"><thead><tr><th>Label</th><th>Meaning</th></tr></thead><tbody>${shown.map(([, grp, rows]) => `<tr class="grp"><td colspan="2">${esc(grp)}</td></tr>${rows.map(r => `<tr><td>${r[0]}</td><td>${r[1]}</td></tr>`).join('')}`).join('')}</tbody></table></details>`;
  $('#glsMode').onclick = e => { const b = e.target.closest('button'); if (!b) return; S.glsAll = b.dataset.m === 'all'; renderGlossary(); };
}

/* ---------- tooltip ---------- */
const tip = $('#tip');
document.addEventListener('pointerover', e => { const el = e.target.closest && e.target.closest('[data-tip]'); if (!el) { tip.style.display = 'none'; return; } const parts = el.dataset.tip.split('|'); tip.innerHTML = `<div class="t">${esc(parts[0])}</div>` + parts.slice(1).map(p => `<div>${esc(p)}</div>`).join(''); tip.style.display = 'block'; });
document.addEventListener('pointermove', e => { if (tip.style.display !== 'block') return; tip.style.left = Math.min(window.innerWidth - tip.offsetWidth - 12, e.clientX + 14) + 'px'; tip.style.top = Math.min(window.innerHeight - tip.offsetHeight - 12, e.clientY + 14) + 'px'; });

/* ---------- charts (string-built SVG and CSS bars; geometry only) ---------- */
function wrap(s, n) { const out = []; let line = ''; String(s || '').split(' ').forEach(w => { if ((line + ' ' + w).trim().length > n && line) { out.push(line); line = w; } else line = (line + ' ' + w).trim(); }); if (line) out.push(line); return out.slice(0, 3); }
function waterfall({ id, start, steps, end, height = 300, selected = null, groups = null, W = 900 }) {
  const items = [{ label: start.label, value: start.value, base: true }, ...steps, { label: end.label, value: end.value, base: true }];
  const H = height, padL = 58, padR = 10, padT = 26, padB = groups ? 62 : 46;
  const n = items.length, slot = (W - padL - padR) / n, bw = Math.min(slot * 0.64, 84);
  let run = start.value; const rects = []; let lo = Math.min(0, start.value || 0), hi = Math.max(0, start.value || 0);
  items.forEach((it, i) => { let y0, y1; if (it.base) { y0 = 0; y1 = it.value || 0; } else { y0 = run; y1 = run + (it.value || 0); run = y1; } rects.push({ it, y0, y1 }); lo = Math.min(lo, y0, y1); hi = Math.max(hi, y0, y1); });
  const span = (hi - lo) || 1; lo -= span * 0.05; hi += span * 0.12;
  const sy = v => padT + (hi - v) / (hi - lo) * (H - padT - padB);
  let g = ''; for (let t = 0; t <= 4; t++) { const v = lo + (hi - lo) * t / 4, y = sy(v); g += `<line class="grid" x1="${padL}" x2="${W - padR}" y1="${y.toFixed(1)}" y2="${y.toFixed(1)}"/><text class="ax" x="${padL - 6}" y="${(y + 3.5).toFixed(1)}" text-anchor="end" style="font-size:9.5px;fill:var(--muted)">${esc(money(v))}</text>`; }
  let bars = '', conns = '';
  rects.forEach((r, i) => {
    const x = padL + slot * i + (slot - bw) / 2, cx = x + bw / 2, yA = sy(Math.max(r.y0, r.y1)), yB = sy(Math.min(r.y0, r.y1)), h = Math.max(1.5, yB - yA);
    const cl = r.it.base ? 'base' : (r.it.kind || ((r.it.value || 0) >= 0 ? 'fav' : 'unf')), sel = selected && r.it.ref === selected ? ' sel' : '';
    const label = r.it.base ? money(r.it.value) : money(r.it.value, { sign: true }), labY = (r.it.base || (r.it.value || 0) >= 0) ? yA - 6 : yB + 13;
    const dense = n > 9, words = wrap(r.it.label, dense ? 11 : 18);
    bars += `<g class="bar${sel}" data-ref="${esc(r.it.ref || '')}" tabindex="0" role="button" aria-label="${esc(r.it.label)} ${esc(label)}" data-tip="${esc(r.it.label)}|${esc(r.it.base ? full(r.it.value) : full(r.it.value, { sign: true }) + ' · running ' + full(r.y1))}">
      <rect x="${x.toFixed(1)}" y="${padT}" width="${bw.toFixed(1)}" height="${H - padT - padB}" fill="transparent"/>
      <rect class="body ${cl}" rx="2" x="${x.toFixed(1)}" y="${yA.toFixed(1)}" width="${bw.toFixed(1)}" height="${h.toFixed(1)}"/>
      <text x="${cx.toFixed(1)}" y="${labY.toFixed(1)}" text-anchor="middle" style="font-size:${dense ? 10 : 11.5}px;font-weight:600">${esc(label)}</text>
      ${words.map((w, j) => `<text class="lbl" x="${cx.toFixed(1)}" y="${H - padB + 16 + j * 11}" text-anchor="middle" style="font-size:${dense ? 9.5 : 11}px">${esc(w)}</text>`).join('')}</g>`;
    if (i < rects.length - 1) { const yc = sy(r.it.base ? r.it.value : r.y1); conns += `<line class="conn" x1="${(x + bw).toFixed(1)}" x2="${(x + slot).toFixed(1)}" y1="${yc.toFixed(1)}" y2="${yc.toFixed(1)}"/>`; }
  });
  let grp = '';
  if (groups) groups.forEach(gr => { const x0 = padL + slot * gr.from + (slot - bw) / 2, x1 = padL + slot * gr.to + (slot - bw) / 2 + bw, y = H - 8; grp += `<line x1="${x0}" x2="${x1}" y1="${y}" y2="${y}" style="stroke:var(--ink);stroke-width:1"/><text x="${(x0 + x1) / 2}" y="${y - 5}" text-anchor="middle" style="font-size:10px;font-weight:600">${esc(gr.label)} ${esc(money(gr.total, { sign: true }))}</text>`; });
  return `<svg class="wf" id="${esc(id)}" viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid meet">${g}<line class="zero" x1="${padL}" x2="${W - padR}" y1="${sy(0)}" y2="${sy(0)}"/>${conns}${bars}${grp}</svg>`;
}
/* multi-series line chart; series = [{name, vals, cls}] with nulls breaking the line */
function lineChart({ labels, series, height = 210, fmt = money, cur = null, W = 640 }) {
  const H = height, pl = 54, pr = 14, pt = 14, pb = 26;
  const nums = series.flatMap(s => s.vals).filter(isNum); if (!nums.length) return '<div class="empty">No series.</div>';
  let lo = Math.min(...nums), hi = Math.max(...nums); const sp = (hi - lo) || Math.abs(hi) || 1; lo -= sp * 0.12; hi += sp * 0.12;
  const n = labels.length, x = i => pl + i * (W - pl - pr) / Math.max(1, n - 1), y = v => pt + (hi - v) / (hi - lo) * (H - pt - pb);
  let g = ''; for (let t = 0; t <= 3; t++) { const v = lo + (hi - lo) * t / 3, yy = y(v); g += `<line class="grid" x1="${pl}" x2="${W - pr}" y1="${yy.toFixed(1)}" y2="${yy.toFixed(1)}"/><text class="ax" x="${pl - 6}" y="${(yy + 3.5).toFixed(1)}" text-anchor="end">${esc(fmt(v))}</text>`; }
  const paths = series.map(s => { let segs = [], cur2 = []; s.vals.forEach((v, i) => { if (isNum(v)) cur2.push(`${x(i).toFixed(1)},${y(v).toFixed(1)}`); else if (cur2.length) { segs.push(cur2); cur2 = []; } }); if (cur2.length) segs.push(cur2); return segs.map(p => p.length === 1 ? `<circle cx="${p[0].split(',')[0]}" cy="${p[0].split(',')[1]}" r="2.5" class="${s.cls}" style="fill:currentColor"/>` : `<polyline class="${s.cls}" points="${p.join(' ')}"/>`).join(''); }).join('');
  const step = Math.ceil(n / 7);
  const xl = labels.map((l, i) => ((i % step === 0 && (n - 1 - i >= step || i === 0)) || i === n - 1) ? `<text class="ax" x="${x(i).toFixed(1)}" y="${H - 8}" text-anchor="${i === 0 ? 'start' : i === n - 1 ? 'end' : 'middle'}">${esc(l)}</text>` : '').join('');
  const mark = isNum(cur) && isNum(series[0].vals[cur]) ? `<circle class="cur" cx="${x(cur).toFixed(1)}" cy="${y(series[0].vals[cur]).toFixed(1)}" r="5"/>` : '';
  const hit = labels.map((l, i) => `<rect class="hit" x="${(x(i) - (W - pl - pr) / Math.max(1, n - 1) / 2).toFixed(1)}" y="${pt}" width="${((W - pl - pr) / Math.max(1, n - 1)).toFixed(1)}" height="${H - pt - pb}" fill="transparent" data-tip="${esc(l)}|${esc(series.map(s => `${s.name}: ${fmt(s.vals[i])}`).join('|'))}"/>`).join('');
  return `<svg class="ch" viewBox="0 0 ${W} ${H}">${g}${paths}${mark}${xl}${hit}</svg>`;
}
const legend = items => `<div class="legend">${items.map(([cls, name]) => `<span><i style="${cls}"></i>${esc(name)}</span>`).join('')}</div>`;
/* diverging bars around zero: items = [{name, value, ref}] */
function divBars(items, { left = 'Unfavourable', right = 'Favourable' } = {}) {
  if (!items.length) return '<div class="empty">Nothing moved in this view.</div>';
  const mx = Math.max(...items.map(i => Math.abs(i.value || 0)), 1);
  return `<div class="dvh"><span></span><span><span>◂ ${esc(left)}</span><span>${esc(right)} ▸</span></span><span></span></div><div class="dv">${items.map(i => { const w = Math.abs(i.value || 0) / mx * 50, t = tone(i.value, i.floor ?? MON);
    return `<div class="dvr" data-ref="${esc(i.ref)}" data-tip="${esc(i.name)}|${esc(full(i.value, { sign: true }))}"><span class="nm">${esc(i.name)}</span><span class="tr"><i class="${t === 'neu' ? 'neu' : t}" style="${(i.value || 0) >= 0 ? 'left:50%' : `left:${(50 - w).toFixed(2)}%`};width:${Math.max(w, .6).toFixed(2)}%"></i></span><span class="vv ${t}">${esc(money(i.value, { sign: true }))}</span></div>`; }).join('')}</div>`;
}
/* magnitude bars: items = [{name, value, ref, cls, label}] */
function hBars(items) {
  if (!items.length) return '<div class="empty">Nothing to show.</div>';
  const mx = Math.max(...items.map(i => Math.abs(i.value || 0)), 1);
  return `<div class="hb">${items.map(i => `<div class="hbr" ${i.ref ? `data-ref="${esc(i.ref)}"` : ''} data-tip="${esc(i.name)}|${esc(i.label || full(i.value))}"><span class="nm">${esc(i.name)}</span><span class="tr"><i class="${i.cls || ''}" style="width:${(Math.abs(i.value || 0) / mx * 100).toFixed(1)}%"></i></span><span class="vv ${i.vcls || ''}">${esc(i.label || money(i.value))}</span></div>`).join('')}</div>`;
}
/* where the latest month and the budget sit against the trailing range */
function rangeBar(id, { ref = true } = {}) {
  const rr = SIG[id].runrate, r = rangeOf(id); if (!rr.eligible || !r) return '';
  const ds = ACC_BY[id].display_sign, rv = rr.reference * ds, bud = ACC_BY[id].series.budget[AS], act = ACC_BY[id].series.actual[AS], la = lacct(id);
  const all = [r[0], r[1], rv, bud, act].filter(isNum), mn = Math.min(...all), mx = Math.max(...all), sp = (mx - mn) || 1, pad = sp * 0.15, X = v => ((v - mn + pad) / (sp + 2 * pad) * 100).toFixed(1) + '%';
  const at = la && isNum(la.variance) ? tone(la.variance) : 'neu';
  return `<div class="rbr" ${ref ? `data-ref="acct:${esc(id)}"` : ''}><div class="rh"><b>${esc(acctName(id))}</b><span class="${at}">${esc(money(act))} <span class="mut">in ${esc(MONTH)}</span></span></div>
    <div class="rt"><div class="band" style="left:${X(r[0])};width:${((r[1] - r[0]) / (sp + 2 * pad) * 100).toFixed(1)}%" data-tip="Usual range|${esc(money(r[0]))} – ${esc(money(r[1]))}"></div><div class="ref" style="left:${X(rv)}" data-tip="Run-rate|${esc(money(rv))}"></div>${isNum(bud) ? `<div class="bud" style="left:${X(bud)}" data-tip="Budget|${esc(money(bud))}"></div>` : ''}<div class="act ${at}" style="left:${X(act)}" data-tip="${esc(MONTH)} actual|${esc(money(act))}"></div></div></div>`;
}
const rangeLegend = () => legend([['background:var(--rng);height:6px', 'Usual six-month range'], ['background:var(--muted);width:2px;height:12px', 'Run-rate'], ['background:var(--budget);width:3px;height:12px', 'Budget'], ['background:var(--ink);width:9px;height:9px;transform:rotate(45deg)', `${MONTH} actual`]]);
function gauge(actual, comp, compName) {
  const mx = Math.max(actual || 0, comp || 0) * 1.25 || 1;
  return `<div class="gauge"><i style="width:${Math.max(0, (actual || 0) / mx * 100).toFixed(1)}%"></i>${isNum(comp) ? `<b style="left:${((comp || 0) / mx * 100).toFixed(1)}%" data-tip="${esc(compName)}|${esc(pct(comp))}"></b>` : ''}</div><div class="gl"><span>0%</span><span>▮ ${esc(compName)} ${esc(pct(comp))}</span></div>`;
}

/* ---------- SUMMARY ---------- */
/* Executive summary as insights. Every bullet is an observation followed by what it means; the amounts are the
   evidence, never the point. Each insight is selected from engine fields (lines, drivers, signals, patterns,
   concentration, facts, outlook); the page only chooses and phrases, it derives no new economics. */
const pat = id => (L().patterns || []).find(p => p.id === id && p.fired);
const absSum = ds => ds.reduce((s, d) => s + Math.abs(d.variance || 0), 0);
const matDrivers = () => L().drivers.filter(d => isNum(d.variance) && Math.abs(d.variance) >= MON && d.section !== 'nonop').sort((a, c) => Math.abs(c.variance) - Math.abs(a.variance));
const labels = ds => joinAnd(ds.map(d => d.label));
const isBud = () => L().basis === 'budget';
function costMove(v) { return isBud() ? (v < 0 ? `ran ${money(-v)} over budget` : `came in ${money(v)} under budget`) : (v < 0 ? `rose ${money(-v)} on prior year` : `fell ${money(v)} on prior year`); }
function revMove(v) { return isBud() ? (v < 0 ? `fell ${money(-v)} short of budget` : `beat budget by ${money(v)}`) : (v < 0 ? `fell ${money(-v)} on prior year` : `grew ${money(v)} on prior year`); }

function insightLead() {
  const b = basisWord(), ni = lline('ni'), rev = lline('rev'), cv = (lline('cos').variance || 0) + (lline('opex').variance || 0);
  const rM = Math.abs(rev.variance) >= MON, cM = Math.abs(cv) >= MON, tw = twin(), tni = tw ? tw.lines.find(x => x.id === 'ni') : null;
  const where = Math.abs(ni.variance) < MON ? `in line with ${b}` : `${money(Math.abs(ni.variance))}${Math.abs(ni.variance_pct) < 10 ? ` (${pct(Math.abs(ni.variance_pct))})` : ''} ${ni.variance > 0 ? 'ahead of' : 'behind'} ${b}`;
  const twinTxt = tni && Math.abs(tni.variance) >= MON ? ` and ${tni.variance > 0 ? 'up' : 'down'} ${money(Math.abs(tni.variance))} on ${tw.basis_label}` : '';
  let head, mean;
  if (Math.abs(ni.variance) < MON) { head = 'On plan.'; mean = `no P&L line moved enough to change the picture, so the month needs monitoring, not intervention`; }
  else if (ni.variance < 0) {
    if (cM && !rM) { head = 'A cost problem, not a demand problem.'; mean = `costs ${costMove(cv)} while revenue held, so the gap sits in spending decisions that management controls`; }
    else if (rM && !cM) { head = 'A top-line shortfall.'; mean = `revenue ${revMove(rev.variance)} while costs held, so recovery depends on volume and pricing rather than cost action`; }
    else if (rM && cM && rev.variance > 0) { head = 'Growth absorbed by cost.'; mean = `revenue ${revMove(rev.variance)}, but costs ${costMove(cv)}, so growth is not reaching the bottom line`; }
    else if (rM && cM && cv > 0) { head = 'Savings could not cover the revenue gap.'; mean = `revenue ${revMove(rev.variance)} and lower costs (${money(cv)}) only partly offset it`; }
    else if (rM && cM) { head = 'A broad miss.'; mean = `revenue ${revMove(rev.variance)} and costs ${costMove(cv)}, so closing the gap needs action on both lines`; }
    else { head = 'A below-the-line miss.'; mean = `operating lines held; the gap comes from non-operating items, outside day-to-day control`; }
  } else {
    if (rM && !cM) { head = 'Revenue-led.'; mean = `revenue ${revMove(rev.variance)} with costs held, so the beat is driven by demand, the best-quality kind`; }
    else if (cM && !rM) { head = 'Cost-led.'; mean = `costs ${costMove(cv)} while revenue held, so the beat depends on spending staying low, which may be timing`; }
    else if (rM && cM && cv < 0) { head = 'Growth outpacing cost.'; mean = `revenue ${revMove(rev.variance)} while costs ${costMove(cv)}, so the business is scaling profitably`; }
    else if (rM && cM) { head = 'A broad beat.'; mean = `revenue ${revMove(rev.variance)} and costs ${costMove(cv)}`; }
    else { head = 'A below-the-line gain.'; mean = `operating lines held; the gain comes from non-operating items and may not repeat`; }
  }
  return { t: tone(ni.variance), lead: true, ref: 'kpi:net_income', html: `<b>${esc(head)}</b> Net income ${esc(money(ni.actual))} is ${esc(where)}${esc(twinTxt)}: ${esc(mean)}.` };
}

/* structural vs one-time: read from the lead account's persistence signal (latest-month view only) */
function insightPersistence() {
  if (L().window !== 'MTD' || !isBud()) return null;              // persistence signals are read against budget
  const md = matDrivers(); if (!md.length) return null;
  const cls = md.map(d => { const la = leadAccount(d); return { d, la, h: la ? SIG[la.id].persistence_hint : null }; });
  const str = cls.filter(x => x.h === 'persistent' || x.h === 'recurring_level_change'), one = cls.filter(x => x.h === 'one_off_candidate'), sea = cls.filter(x => x.h === 'seasonal' || x.h === 'timing_reversal');
  if (!str.length && !one.length && !sea.length) return null;
  const share = absSum(str.map(x => x.d)) / (absSum(md) || 1), parts = [];
  str.forEach(x => { const t = SIG[x.la.id].tests.find(q => q.id === 'persistent_gap' && q.state === 'fired'), act = actOf(x.d.id), fx = act && act.forecast ? act.forecast.remaining_months_effect : null;
    parts.push(`${x.d.label} is recurring${t && isBud() ? ` (${acctName(x.la.id)} off budget in ${t.evidence.months_same_side} of the last ${t.evidence.months_compared} months)` : ''}${isNum(fx) && fx < 0 ? ` and would cost another ${money(-fx)} by year end` : ''}`); });
  if (one.length) parts.push(`${labels(one.map(x => x.d))} ${one.length > 1 ? 'look' : 'looks'} one-off, outside ${one.length > 1 ? 'their' : 'its'} usual range for the first time`);
  if (sea.length) parts.push(`${labels(sea.map(x => x.d))} ${sea.length > 1 ? 'follow' : 'follows'} last year's seasonal pattern`);
  const head = !str.length ? 'Mostly temporary.' : share >= 0.5 ? 'Mostly structural.' : 'Partly structural.';
  const mean = !str.length ? 'little of this month\'s movement should carry into the rest of the year' : `about ${pct(share, { dec: 0 })} of the driver movement will repeat unless someone acts on it`;
  return { t: str.length ? 'unf' : 'neu', ref: 'driver:' + (str[0] || one[0] || sea[0]).d.id, html: `<b>${esc(head)}</b> ${esc(cap(parts.join('; ')))}: ${esc(mean)}.` };
}

/* concentration and actionability: how few drivers and units carry the movement */
function insightConcentration() {
  const md = matDrivers(); if (!md.length) return null;
  const top = md.slice(0, 3), sh = top.reduce((s, d) => s + (d.share_of_abs_variance || 0), 0), ni = lline('ni');
  const subs = dimRows('all'), tot = subs.reduce((s, r) => s + r.v, 0), lead = subs[0];
  const subTxt = subs.length > 1 && lead && Math.sign(lead.v) === Math.sign(tot) && Math.abs(tot) >= MON && lead.v / tot >= 0.6 && lead.v / tot <= 1 ? `, and ${lead.name} holds ${pct(lead.v / tot, { dec: 0 })} of the net movement` : '';
  if (pat('broad_based_variance') || sh < 0.5) return { t: 'neu', ref: 'driver:' + top[0].id, html: `<b>Broad-based.</b> No small group of drivers explains the result (the top three carry ${esc(pct(sh, { dec: 0 }))}): this points to a shared assumption, such as pricing, volume or the budget itself, rather than individual decisions.` };
  const who = top.length === 1 ? 'one owner' : `${top.length === 2 ? 'two' : 'three'} owners`;
  return { t: 'ink', ref: 'driver:' + top[0].id, html: `<b>${ni.variance < 0 ? 'Concentrated, so fixable.' : 'Gains come from a few lines.'}</b> ${esc(labels(top))} carry ${esc(pct(sh, { dec: 0 }))} of the movement${esc(subTxt)}: ${esc(ni.variance < 0 ? `${who} can close most of the gap, without a broad cost programme` : `${who} explain most of the beat, so confirm it repeats before relying on it`)}.` };
}

/* margin: this view's margin move, read against the twelve-month growth trend */
function insightMargin() {
  const ebm = lline('ebm'); if (!ebm || !isNum(ebm.variance) || Math.abs(ebm.variance) < 0.005) return null;
  const lp = P.lenses.LTM_py && P.lenses.LTM_py.available && S.lens !== 'LTM_py' ? P.lenses.LTM_py : null, g = id => lp ? lp.lines.find(x => x.id === id) : null;
  const gr = lp ? { rev: g('rev').variance_pct, cos: -g('cos').variance_pct, opex: -g('opex').variance_pct } : null;
  const lev = gr && [gr.rev, gr.cos, gr.opex].every(isNum) ? gr.rev > Math.max(gr.cos, gr.opex) : null;
  const why = pat('cost_growth_outpacing_revenue') ? ' as costs outran revenue' : pat('operating_leverage') ? ' as revenue outgrew costs' : '';
  const trend = gr && lev !== null ? `; over twelve months revenue grew ${pct(gr.rev)} against ${pct(gr.cos)} for cost of sales and ${pct(gr.opex)} for operating expenses` : '';
  let head, mean;
  if (ebm.variance < 0 && lev && isBud() && L().window !== 'MTD') { head = 'Margin below plan, trend intact.'; mean = 'the business is growing into its costs, but more slowly than the budget assumed, so the gap is in the plan level rather than a deterioration'; }
  else if (ebm.variance < 0) { head = lev ? 'A margin dip, not a trend.' : lev === false ? 'Margin under sustained pressure.' : 'Margin compressed.'; mean = lev ? 'operating leverage is intact, so this reads as a short-term squeeze' : lev === false ? 'costs are growing faster than revenue over the year, so the squeeze is structural and needs a cost response' : 'watch whether it repeats next month'; }
  else { head = lev === false ? 'Margin up, against the trend.' : 'Margin expanding.'; mean = lev === false ? 'costs still grow faster than revenue over the year, so this gain may not hold' : 'growth is converting into profit'; }
  return { t: tone(ebm.variance, 0.005), ref: 'line:ebm', html: `<b>${esc(head)}</b> EBITDA margin ${ebm.variance < 0 ? 'fell' : 'rose'} ${(Math.abs(ebm.variance) * 100).toFixed(1)} pt to ${esc(pct(ebm.actual))}${esc(why)}${esc(trend)}: ${esc(mean)}.` };
}

/* business mix: recurring vs non-recurring revenue moving in opposite directions */
function insightMix() {
  const r = L().drivers.find(d => d.section === 'rev' && /^recurring/i.test(d.label)), n = L().drivers.find(d => d.section === 'rev' && /^non/i.test(d.label));
  if (r && n && isNum(r.variance) && isNum(n.variance) && Math.abs(r.variance) >= MON && Math.abs(n.variance) >= MON && Math.sign(r.variance) !== Math.sign(n.variance))
    return r.variance < 0
      ? { t: 'unf', ref: 'driver:' + r.id, html: `<b>Lower-quality revenue.</b> ${esc(n.label)} (${esc(money(n.variance, { sign: true }))}) offset ${esc(r.label)} (${esc(money(r.variance))}): the top line holds, but less of it repeats next year.` }
      : { t: 'fav', ref: 'driver:' + r.id, html: `<b>Better-quality revenue.</b> ${esc(r.label)} grew (${esc(money(r.variance, { sign: true }))}) while ${esc(n.label)} fell (${esc(money(n.variance))}): more of the revenue base now repeats.` };
  const m = pat('mix_shift'); return m ? { t: 'neu', ref: 'kpi:revenue', html: `<b>Mix is shifting.</b> ${esc(clean(m.reading))}` } : null;
}

/* forecast quality: a budget that sits away from run-rate or is missed on the same side month after month */
function insightBudgetBias() {
  if (!isBud() || L().window !== 'MTD') return null;
  const hits = matDrivers().map(d => ({ d, la: leadAccount(d) })).filter(x => x.la && SIG[x.la.id].fired.some(f => f === 'budget_outside_run_rate' || f === 'persistent_gap'));
  if (!hits.length) return null;
  return { t: 'neu', ref: 'driver:' + hits[0].d.id, html: `<b>Part of the gap is the plan.</b> The budget for ${esc(labels(hits.map(x => x.d)))} sits away from recent run-rate or has been missed on the same side for months: re-basing the forecast matters as much as cost action.` };
}

/* implication for the year */
function insightYear() {
  const fy = OUT && OUT.state === 'calculated' ? OUT.lines.ebitda : null, carry = OUT && OUT.persistence_totals ? OUT.persistence_totals.proposed_carry : null; if (!fy) return null;
  const vs = isNum(fy.gap_vs_budget) ? `, ${money(Math.abs(fy.gap_vs_budget))} ${fy.gap_vs_budget < 0 ? 'short of' : 'above'} budget` : isNum(fy.gap_vs_prior_year) ? `, ${money(Math.abs(fy.gap_vs_prior_year))} ${fy.gap_vs_prior_year > 0 ? 'above' : 'below'} last year` : '';
  const c = isBud() && isNum(carry) && Math.abs(carry) >= MON ? ` Correcting the recurring gaps protects about ${money(Math.abs(carry))} of that.` : '';
  return { t: 'ink', ref: 'outlook:mechanical', html: `<b>What it means for the year.</b> Full-year EBITDA tracks about ${esc(money(fy.mechanical.value))} on run-rate${esc(vs)}${isNum(fy.gap_vs_prior_year) && fy.gap_vs_prior_year > 0 ? ', so the year is still one of growth' : ''}.${esc(c)}` };
}

/* an admitted conclusion as an insight bullet: the reviewer's heading (or one read from status and persistence),
   the observation with its registered figures, then the response */
const lowerLead = t => /^[A-Z][a-z]/.test(t) ? t[0].toLowerCase() + t.slice(1) : t;
const CONCL_HEAD = { one_off: 'Likely one-off.', recurring: 'A recurring gap.', persistent: 'A recurring gap.', seasonal: 'Seasonal; check the phasing.', timing: 'A timing effect.', coverage: 'A budget coverage gap.' };
function insightReviewed(c) {
  const head = (c.insight && c.insight.trim().replace(/[.:]?$/, '.')) || CONCL_HEAD[c.persistence] || ({ favorable: 'Supports the result.', unfavorable: 'Weighs on the result.', mixed: 'Needs confirming.' }[c.status] || 'Reviewed reading.');
  const f = findingById(c.finding_ref), did = f && ((f.scope || {}).drivers || [])[0];
  return { t: c.status === 'favorable' ? 'fav' : c.status === 'unfavorable' ? 'unf' : 'neu', rv: true, ref: did ? 'driver:' + did : 'finding:' + c.finding_ref,
    html: `<b>${esc(head)}</b> ${esc(clean(c.text).replace(/\.\s*$/, ''))}: <span class="nx-i">${esc(lowerLead(clean(c.response)).replace(/\.\s*$/, ''))}.</span>` };
}
/* 3 to 5 bullets: the net-income lead, then reviewed conclusions when a diagnosis is admitted for this view, then
   engine insights for any room left, and the full-year implication last */
function execBullets() {
  const out = [insightLead()], y = insightYear(), cap5 = y ? 4 : 5;
  const rv = (readout().conclusions || []).filter((c, i, all) => c.text && all.findIndex(x => x.text === c.text) === i).map(insightReviewed);
  rv.slice(0, cap5 - 1).forEach(x => out.push(x));
  [insightPersistence, insightConcentration, insightMargin, insightMix, insightBudgetBias].map(f => f()).filter(Boolean).slice(0, Math.max(0, cap5 - out.length)).forEach(x => out.push(x));
  if (y) out.push(y);
  return out.slice(0, 5);
}
function flowStrip() {
  const seq = [['revenue', 'Revenue', ''], ['cogs', 'Cost of sales', '−'], ['gross_profit', 'Gross profit', '='], ['opex', 'Operating expenses', '−'], ['ebitda', 'Adj. EBITDA', '='], ['nonop', 'Non-operating', '±'], ['net_income', 'Net income', '=']];
  const mg = { gross_profit: 'gpm', ebitda: 'ebm' };
  return `<div class="flow" id="kpis">${seq.map(([id, label, op], i) => { const k = lkpi(id); if (!k) return ''; const t = k.status === 'in_line' ? 'neu' : tone(k.variance), m = mg[id] ? lline(mg[id]) : null;
    return `<button class="fk${op === '=' ? ' tot' : ''}${id === 'net_income' ? ' end' : ''}" data-ref="kpi:${id}">${i ? `<span class="op">${op}</span>` : ''}<div class="kl">${esc(label)}</div><div class="kv">${esc(money(k.actual))}</div><div class="ks ${t}">${esc(pct(k.variance_pct, { sign: true }))} <span class="cmp">vs ${esc(basisWord())}</span></div>${m ? `<div class="km">${esc(pct(m.actual))} margin · ${esc(pts(m.variance))}</div>` : ''}</button>`; }).join('')}</div>`;
}
function moversItems() {
  const Lx = L(); return [...Lx.bridge.steps, ...Lx.bridge.to_net_income.steps].filter(s => isNum(s.value) && Math.abs(s.value) >= 0.5).sort((a, b) => Math.abs(b.value) - Math.abs(a.value)).slice(0, 9).map(s => ({ name: s.label, value: s.value, ref: 'driver:' + s.id }));
}
function renderSummary() {
  const Lx = L(), ebm = lline('ebm'), gpm = lline('gpm'), fy = OUT && OUT.state === 'calculated' ? OUT.lines.ebitda : null, b = basisWord();
  const dAsks = (readout().decision_asks || []).slice(0, 3).map(q => { const f = findingById(q.finding_ref) || {}, did = ((f.scope || {}).drivers || [])[0], a = (q.action_refs || []).map(r => Lx.actions.find(x => x.id === r)).find(Boolean);
    return { ref: a ? 'action:' + a.id : did ? 'driver:' + did : 'finding:' + (f.id || ''), q: clean(q.text), m: `${q.owner || (a ? a.owner.role : 'owner to name')}${a ? ' · by ' + a.date.target : ''}`, amt: a ? a.exposure.amount : null }; });
  const asks = dAsks.length ? dAsks : Lx.actions.slice(0, 3).map(a => ({ ref: 'action:' + a.id, q: askText(a), m: `${a.owner.role} · by ${a.date.target}`, amt: a.exposure.amount }));
  $('#view-summary').innerHTML = `
    <section class="sec" id="sum-exec"><div class="sh"><h2>Executive summary</h2><span class="sub">${esc(rangeLabel())} vs ${esc(b)} · click any point for the detail</span>${D() ? diagMark() : baseMark()}</div>${budgetNote()}
      <div class="exec"><ul class="bul">${execBullets().map(x => `<li class="${x.lead ? 'lead' : ''}${x.rv ? ' rv' : ''}" data-ref="${esc(x.ref)}"><span class="mk ${x.t}">${x.t === 'fav' ? '▲' : x.t === 'unf' ? '▼' : x.t === 'ink' ? '→' : '•'}</span><span class="tx">${x.html}${x.rv ? ' <i class="rvt" title="From the admitted diagnosis; not independently verified">reviewed</i>' : ''}</span><span class="go">›</span></li>`).join('')}</ul>
      <div class="side">
        <div class="ring" data-ref="line:ebm"><div class="rl">EBITDA margin</div><div class="rv">${esc(pct(ebm.actual))}</div><div class="rs ${tone(ebm.variance, 0.001)}">${esc(pts(ebm.variance))} <span class="mut">vs ${esc(b)}</span></div>${gauge(ebm.actual, ebm.comparator, cap(b))}</div>
        <div class="ring" data-ref="line:gpm"><div class="rl">Gross margin</div><div class="rv">${esc(pct(gpm.actual))}</div><div class="rs ${tone(gpm.variance, 0.001)}">${esc(pts(gpm.variance))} <span class="mut">vs ${esc(b)}</span></div>${gauge(gpm.actual, gpm.comparator, cap(b))}</div>
        ${fy ? `<div class="ring" data-ref="outlook:mechanical"><div class="rl">Full-year EBITDA (run-rate)</div><div class="rv">${esc(money(fy.mechanical.value))}</div><div class="rs mut">${isNum(fy.gap_vs_budget) ? `<span class="${tone(fy.gap_vs_budget)}">${esc(money(fy.gap_vs_budget, { sign: true }))}</span> vs full-year budget` : `<span class="${tone(fy.gap_vs_prior_year)}">${esc(money(fy.gap_vs_prior_year, { sign: true }))}</span> vs last year`}</div></div>` : ''}
      </div></div></section>
    <section class="sec"><div class="sh"><h2>P&amp;L at a glance</h2><span class="sub">in order of calculation · change vs ${esc(b)}</span></div>${flowStrip()}</section>
    <section class="sec"><div class="grid g-3-2">
      <div class="panel" id="sum-movers"><h3>What moved net income <small>by driver, vs ${esc(b)}</small></h3>${divBars(moversItems())}</div>
      <div class="panel" id="sum-asks"><h3>Decisions for management <small>${dAsks.length ? 'from the admitted diagnosis' : 'suggested owners'} · proposed, not approved</small></h3>${asks.length ? `<ol class="dec">${asks.map(a => `<li data-ref="${esc(a.ref)}"><div><div class="q">${esc(a.q)}</div><div class="m">${esc(a.m)}</div></div>${isNum(a.amt) ? `<div class="amt">${esc(money(a.amt))}<small>at stake</small></div>` : ''}</li>`).join('')}</ol>` : '<div class="empty">No decision needed: nothing reached the management threshold with a structural signal.</div>'}</div>
    </div></section>`;
  bindRefs($('#view-summary'));
}

/* ---------- DRIVERS ---------- */
function bridgeSpec() {
  const Lx = L();
  if (S.bridgeMode === 'ni') { const ni = Lx.bridge.to_net_income; return { start: ni.start, end: ni.end, steps: ni.steps.map(s => ({ label: s.label, value: s.value, kind: s.kind, ref: 'step:' + s.id })) }; }
  if (S.bridgeMode === 'layers') {
    const lay = Lx.layers, steps = [], groups = []; let idx = 1;
    const push = (label, rows, kind) => { const from = idx; let tot = 0; rows.forEach(r => { if (!isNum(r.v) || Math.abs(r.v) < 0.5) return; steps.push({ label: r.label, value: r.v, kind: kind || (r.v >= 0 ? 'fav' : 'unf'), ref: r.ref }); tot += r.v; idx++; }); if (idx > from) groups.push({ label, from, to: idx - 1, total: tot }); };
    push('Plan', lay.drivers.map(d => ({ label: DRV_BY[d.id].label, ref: 'step:' + d.id, v: d.planning })));
    push('Month', lay.drivers.map(d => ({ label: DRV_BY[d.id].label, ref: 'step:' + d.id, v: d.operational })));
    push('No budget line', lay.accounts.filter(a => isNum(a.coverage)).map(a => ({ label: acctName(a.id), ref: 'acct:' + a.id, v: a.coverage })), 'cov');
    return { start: Lx.bridge.start, end: Lx.bridge.end, steps, groups };
  }
  return { start: Lx.bridge.start, end: Lx.bridge.end, steps: Lx.bridge.steps.map(s => ({ label: s.label, value: s.value, kind: s.kind, ref: 'step:' + s.id })) };
}
function selectedDriverPanel() {
  const Lx = L(); let id = S.bridgeSel && S.bridgeSel.startsWith('step:') ? S.bridgeSel.slice(5) : null;
  if (!id || !ldrv(id)) id = (Lx.drivers.filter(d => isNum(d.variance)).sort((a, b) => Math.abs(b.variance) - Math.abs(a.variance))[0] || {}).id;
  const d = ldrv(id); if (!d) return '<div class="empty">No driver carries a variance in this view.</div>';
  const accts = d.accounts.map(a => lacct(a)).filter(a => a && isNum(a.variance)).sort((a, b) => Math.abs(b.variance) - Math.abs(a.variance));
  const ser = sumSeries(d.accounts), lo = Math.max(0, AS - 12), lbl = PER.slice(lo, AS + 1).map(shortLbl), cmp = Lx.basis === 'budget' ? ser.budget : ser.py, lead = leadAccount(d), ps = lead ? SIG[lead.id].persistence_hint : null;
  return `<h3>${esc(d.label)} <small>${esc(SECTION_LABEL[d.section])}</small></h3>
    <div class="facts" style="grid-template-columns:1fr 1fr"><div><div class="l">vs ${esc(basisWord())}</div><div class="v ${tone(d.variance)}">${esc(money(d.variance, { sign: true }))}</div></div><div><div class="l">Share of movement</div><div class="v">${esc(pct(d.share_of_abs_variance, { dec: 0 }))}</div></div></div>
    <div style="margin:10px 0 4px">${tag(tone(d.variance))}${persistTag(ps)}</div>
    <p class="small" style="margin:6px 0 12px">${esc(driverReason(d))}</p>
    ${accts.length > 1 ? `<h4 class="xs mut" style="text-transform:uppercase;letter-spacing:.08em;margin:6px 0">By account</h4>${hBars(accts.map(a => ({ name: acctName(a.id), value: a.variance, ref: 'acct:' + a.id, cls: tone(a.variance), vcls: tone(a.variance), label: money(a.variance, { sign: true }) })))}` : ''}
    <div style="margin-top:12px">${lineChart({ labels: lbl, series: [{ name: 'Actual', vals: ser.actual.slice(lo, AS + 1), cls: 'l-act' }, { name: cap(basisWord()), vals: cmp.slice(lo, AS + 1), cls: 'l-cmp' }], height: 150, W: 420, cur: AS - lo })}</div>
    ${legend([['background:var(--ink)', 'Actual'], ['background:var(--budget)', cap(basisWord())]])}
    <button class="btnl" data-ref="driver:${esc(d.id)}">Open full detail ›</button>`;
}
function dimRows(driverId) {
  const m = new Map(); L().facts.rows.filter(r => driverId === 'all' || (ACC_BY[r[0]] && ACC_BY[r[0]].driver_ref === driverId)).forEach(r => { const o = m.get(r[1]) || { name: r[1], v: 0 }; if (isNum(r[4])) o.v += r[4]; m.set(r[1], o); });
  return [...m.values()].sort((a, b) => Math.abs(b.v) - Math.abs(a.v));
}
function renderDrivers() {
  const Lx = L(), hasLayers = Lx.layers && Lx.layers.state === 'calculated';
  if (!hasLayers && S.bridgeMode === 'layers') S.bridgeMode = 'reported';
  const drivers = Lx.drivers.filter(d => isNum(d.variance)).sort((a, b) => Math.abs(b.variance) - Math.abs(a.variance));
  if (!S.dimDriver || (S.dimDriver !== 'all' && !DRV_BY[S.dimDriver])) S.dimDriver = (drivers[0] || {}).id || 'all';
  const ranged = Lx.accounts.filter(a => isNum(a.variance) && Math.abs(a.variance) >= MON && SIG[a.id].runrate.eligible).sort((a, b) => Math.abs(b.variance) - Math.abs(a.variance)).slice(0, 6);
  const sp = bridgeSpec();
  $('#view-drivers').innerHTML = `
    <section class="sec"><div class="sh"><h2>${S.bridgeMode === 'ni' ? 'From EBITDA to net income' : 'Adjusted EBITDA bridge'}</h2>
      <span class="tog" id="bridgeMode"><button data-m="reported" class="${S.bridgeMode === 'reported' ? 'on' : ''}">By driver</button><button data-m="layers" class="${S.bridgeMode === 'layers' ? 'on' : ''}" ${hasLayers ? '' : 'disabled title="Month vs budget only"'}>Plan vs month</button><button data-m="ni" class="${S.bridgeMode === 'ni' ? 'on' : ''}">To net income</button></span></div>
      ${budgetNote()}<div class="grid g-2-1">
        <div class="panel"><h3>${esc(rangeLabel())} vs ${esc(basisWord())} <small>click a bar to inspect</small></h3><div id="wfHost">${waterfall({ id: 'wf-drv', ...sp, height: 320, selected: S.bridgeSel })}</div>
          ${legend([['background:var(--dark);height:10px;width:10px', 'Start / end'], ['background:var(--fav);height:10px;width:10px', 'Favourable'], ['background:var(--adv);height:10px;width:10px', 'Unfavourable']])}
          ${S.bridgeMode === 'layers' ? `<p class="xs mut" style="margin-top:8px">Plan = how far the budget sits from run-rate. Month = how far ${esc(MONTH)} moved from run-rate. A diagnostic split, not a verified cause.</p>` : ''}</div>
        <div class="panel" id="drvSel">${selectedDriverPanel()}</div>
      </div></section>
    <section class="sec"><div class="grid g2">
      <div class="panel" id="drv-runrate"><h3>${esc(MONTH)} against each account's usual range <small>accounts above ${esc(money(MON))}</small></h3>${ranged.length ? `<div class="rb">${ranged.map(a => rangeBar(a.id)).join('')}</div>${rangeLegend()}` : '<div class="empty">No account above the monitoring threshold has a usable run-rate.</div>'}</div>
      <div class="panel"><h3>By subsidiary <select id="dimDriver" class="ctl">${drivers.map(x => `<option value="${esc(x.id)}" ${S.dimDriver === x.id ? 'selected' : ''}>${esc(x.label)}</option>`).join('')}<option value="all" ${S.dimDriver === 'all' ? 'selected' : ''}>All accounts</option></select></h3><div id="dimHost"></div></div>
    </div></section>
    ${(readout().structural_conclusions || []).length ? `<section class="sec" id="drv-reading"><div class="sh"><h2>Reviewed structural reading</h2>${diagMark()}</div><ul class="say">${readout().structural_conclusions.map(s => `<li>${esc(clean(s.text))}</li>`).join('')}</ul></section>` : ''}`;
  const dim = () => { $('#dimHost').innerHTML = divBars(dimRows(S.dimDriver).map(r => ({ name: r.name, value: r.v, ref: S.dimDriver === 'all' ? 'kpi:net_income' : 'driver:' + S.dimDriver, floor: 0.5 }))); bindRefs($('#dimHost')); };
  $('#bridgeMode').onclick = e => { const b = e.target.closest('button'); if (!b || b.disabled) return; S.bridgeMode = b.dataset.m; S.bridgeSel = null; renderDrivers(); };
  $('#dimDriver').onchange = e => { S.dimDriver = e.target.value; dim(); };
  dim(); bindRefs($('#view-drivers')); barKey($('#wfHost'));
  $('#wfHost').addEventListener('click', e => { const g = e.target.closest('.bar'); if (!g || !g.dataset.ref) return; if (g.dataset.ref.startsWith('acct:')) { openDrawer(g.dataset.ref); return; } S.bridgeSel = g.dataset.ref; $('#wfHost').innerHTML = waterfall({ id: 'wf-drv', ...bridgeSpec(), height: 320, selected: S.bridgeSel }); $('#drvSel').innerHTML = selectedDriverPanel(); bindRefs($('#drvSel')); });
}

/* ---------- OUTLOOK ---------- */
function renderOutlook() {
  const o = OUT;
  if (!o || o.state !== 'calculated') { $('#view-outlook').innerHTML = `<div class="empty">${esc((o && o.reason) || 'Outlook not calculated.')}</div>`; return; }
  const e = o.lines.ebitda, hasFY = isNum(e.fy_budget), fyIdx = PER.map((p, i) => [p, i]).filter(([p]) => p.year === o.fiscal_year).map(([, i]) => i), first = fyIdx[0], s = SS.ebitda;
  const months = Array.from({ length: o.periods_per_year }, (_, k) => first + k), lbl = months.map(i => PER[i] ? shortLbl(PER[i]) : new Date(o.fiscal_year, i - first, 1).toLocaleString('en-US', { month: 'short' }) + " '" + String(o.fiscal_year).slice(2));
  const act = months.map(i => i <= AS ? s.actual[i] : null), bud = months.map(i => i <= AS ? s.budget[i] : null), py = months.map(i => i <= AS ? s.py[i] : (isNum(s.actual[i - 12]) ? s.actual[i - 12] : null));
  const proj = months.map(i => i === AS ? s.actual[i] : (i > AS ? e.mechanical.run_rate : null));
  const sens = e.mechanical.sensitivity, tile = (ref, l, v, sub, dark) => `<button class="tile${dark ? ' dark' : ''}" data-ref="${esc(ref)}"><div class="kl">${esc(l)}</div><div class="kv">${esc(v)}</div><div class="ks">${sub}</div></button>`;
  const steps = hasFY ? [{ label: 'Year-to-date variance', value: e.ytd.variance, ref: 'outlook:ytd' }, { label: `Remaining ${e.remaining_months} months vs budget`, value: e.mechanical.remaining_effect, ref: 'outlook:mechanical' }]
    : [{ label: `Remaining ${e.remaining_months} months at run-rate`, value: isNum(e.mechanical.run_rate) ? e.mechanical.run_rate * e.remaining_months : null, kind: 'cov', ref: 'outlook:mechanical' }];
  const pv = o.persistence_view || [];
  $('#view-outlook').innerHTML = `
    <section class="sec"><div class="sh"><h2>Where the year lands</h2><span class="sub">fiscal ${esc(o.fiscal_year)} · ${e.periods_realized} of ${e.periods_total} months closed · run-rate rule, not a forecast</span></div>
      ${budgetNote(true)}<div class="grid g4">
        ${tile('outlook:ytd', 'EBITDA year to date', money(e.ytd.actual), `<span class="${tone(e.ytd.variance)}">${esc(money(e.ytd.variance, { sign: true }))}</span> vs budget`)}
        ${tile('outlook:mechanical', 'Full-year EBITDA (run-rate)', money(e.mechanical.value), `${esc(money(e.mechanical.run_rate))} a month for ${e.remaining_months} months`, true)}
        ${tile('outlook:mechanical', 'Last year full year', money(e.prior_year_full_year), `<span class="${tone(e.gap_vs_prior_year)}">${esc(money(e.gap_vs_prior_year, { sign: true }))}</span> growth on run-rate`)}
        ${tile('outlook:mechanical', 'Full-year budget', hasFY ? money(e.fy_budget) : '—', hasFY ? `<span class="${tone(e.gap_vs_budget)}">${esc(money(e.gap_vs_budget, { sign: true }))}</span> gap on run-rate` : 'not in the extract')}
      </div></section>
    <section class="sec"><div class="grid g-3-2">
      <div class="panel" id="out-trend"><h3>Monthly Adjusted EBITDA <small>actual, budget, last year and run-rate</small></h3>${lineChart({ labels: lbl, series: [{ name: 'Actual', vals: act, cls: 'l-act' }, { name: 'Run-rate', vals: proj, cls: 'l-proj' }, { name: 'Budget', vals: bud, cls: 'l-cmp' }, { name: 'Last year', vals: py, cls: 'l-py' }], height: 240, cur: AS - first })}
        ${legend([['background:var(--ink)', 'Actual'], ['background:repeating-linear-gradient(90deg,var(--ink) 0 3px,transparent 3px 6px)', 'Run-rate (remaining months)'], ['background:var(--budget)', 'Budget'], ['background:var(--ly)', 'Last year']])}</div>
      <div class="panel" id="out-scenarios"><h3>How much the rule matters <small>full-year EBITDA by run-rate rule</small></h3>${hBars(sens.map(x => ({ name: x.label, value: x.value, ref: 'scenario:' + x.rule, cls: x.rule === e.mechanical.rule ? 'hi' : '' })))}
        <p class="xs mut" style="margin-top:12px">Spread across rules: ${esc(pct(e.mechanical.sensitivity_spread_pct))}. The highlighted rule drives the headline.</p></div>
    </div></section>
    <section class="sec"><div class="grid g2">
      <div class="panel" id="wf-fy"><h3>Full-year bridge <small>Adjusted EBITDA</small></h3>${waterfall({ id: 'wf-fy-chart', start: hasFY ? { label: 'Full-year budget', value: e.fy_budget } : { label: 'Year to date', value: e.ytd.actual }, steps, end: { label: 'Full-year run-rate', value: e.mechanical.value }, height: 250, W: 560 })}</div>
      <div class="panel" id="out-treatment"><h3>If current gaps continue <small>effect over the remaining months · not in the run-rate total</small></h3>
        ${pv.length ? divBars(pv.filter(v => isNum(v.remaining_effect_if_persists)).map(v => ({ name: v.label, value: isNum(v.remaining_effect_if_persists) ? v.remaining_effect_if_persists : 0, ref: 'driver:' + v.driver }))) + `<div class="chips" style="margin-top:12px">${pv.map(v => `<span class="cp">${esc(v.label)}: ${esc((PERSIST[v.persistence_hint] || ['no pattern'])[0])}${isNum(v.remaining_effect_if_persists) ? '' : ', no carry'}</span>`).join('')}</div>` : '<div class="empty">No material driver in the month against budget.</div>'}
        <p class="xs mut" style="margin-top:10px">Proposals only: nothing enters a forecast until a named owner accepts it.</p></div>
    </div></section>
    ${(readout().forecast_assumptions || []).length ? `<section class="sec" id="out-reading"><div class="sh"><h2>Reviewed forecast assumptions</h2>${diagMark()}<span class="tag amb">proposal · not approved</span></div><ul class="say">${readout().forecast_assumptions.map(s => `<li>${esc(clean(s.text))}</li>`).join('')}</ul></section>` : ''}`;
  bindRefs($('#view-outlook')); barKey($('#wf-fy'));
}

/* ---------- DRAWER ---------- */
function keyActivatable(el) { const tg = String(el.tagName || '').toUpperCase(); if (tg === 'BUTTON') return; if (!el.hasAttribute('tabindex')) el.setAttribute('tabindex', '0'); if (!el.getAttribute('role')) el.setAttribute('role', 'button'); el.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); e.stopPropagation(); el.click(); } }); }
function bindRefs(root) { root.querySelectorAll('[data-ref]').forEach(el => { if (el.classList.contains('bar') || el.dataset.bound) return; el.dataset.bound = '1'; el.addEventListener('click', e => { e.stopPropagation(); openDrawer(el.dataset.ref, el.dataset.dtab); }); keyActivatable(el); }); }
const barKey = host => host && host.addEventListener('keydown', e => { const g = e.target.closest && e.target.closest('.bar'); if (g && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); g.dispatchEvent(new MouseEvent('click', { bubbles: true })); } });
function closeDrawer() { S.drawer = null; $('#drawer').classList.remove('open'); $('#app').classList.remove('drawer-open'); document.querySelectorAll('.fk.sel').forEach(x => x.classList.remove('sel')); const o = S.opener; S.opener = null; if (o && o.isConnected && o.focus) o.focus(); }
document.addEventListener('keydown', e => { if (e.key === 'Escape') closeDrawer(); });
function openDrawer(ref, tab) {
  if (!ref) return;
  if (S.drawer !== ref) S.drawerTab = tab || null; else if (tab) S.drawerTab = tab;
  if (!S.drawer && document.activeElement && document.activeElement !== document.body) S.opener = document.activeElement;
  const i = ref.indexOf(':'), kind = i < 0 ? ref : ref.slice(0, i), id = i < 0 ? null : ref.slice(i + 1);
  const b = { acct: acctDrawer, driver: driverDrawer, step: driverDrawer, kpi: kpiDrawer, line: lineDrawer, action: actionDrawer, finding: findingDrawer, qc: qcDrawer, outlook: outlookDrawer, scenario: scenarioDrawer }[kind];
  const spec = b ? b(id) : null; if (!spec) return;
  S.drawer = ref; $('#drawer').classList.add('open'); $('#app').classList.add('drawer-open');
  document.querySelectorAll('.fk').forEach(x => x.classList.toggle('sel', x.dataset.ref === ref));
  const names = Object.keys(spec.tabs); if (!S.drawerTab || !spec.tabs[S.drawerTab]) S.drawerTab = names[0];
  $('#dh').innerHTML = `<div class="top"><div><h2>${esc(spec.title)}</h2><div class="sub">${esc(spec.sub || '')}</div></div><button class="close" aria-label="Close" id="dclose">×</button></div><div class="badges">${(spec.tags || []).join('')}</div>${names.length > 1 ? `<div class="dtabs">${names.map(t => `<button data-t="${esc(t)}" class="${t === S.drawerTab ? 'on' : ''}">${esc(t)}</button>`).join('')}</div>` : '<div style="height:10px"></div>'}`;
  $('#dclose').onclick = closeDrawer;
  const dt = $('#dh .dtabs'); if (dt) dt.onclick = e => { const bb = e.target.closest('button'); if (bb) openDrawer(ref, bb.dataset.t); };
  $('#dbody').innerHTML = spec.tabs[S.drawerTab]();
  bindRefs($('#dbody')); $('#dbody').scrollTop = 0;
}
const facts = arr => `<div class="facts">${arr.map(f => `<div><div class="l">${esc(f[0])}</div><div class="v ${f[2] || ''}">${esc(f[1])}</div></div>`).join('')}</div>`;
const say = arr => arr.filter(Boolean).length ? `<ul class="say">${arr.filter(Boolean).map(s => `<li>${s}</li>`).join('')}</ul>` : '';
const evidence = nums => nums && nums.filter(n => n.kind !== 'literal').length ? `<details class="ev"><summary>Where the figures come from</summary><table class="mini" style="margin-top:8px"><tbody>${nums.filter(n => n.kind !== 'literal').map(n => `<tr><td>${esc(clean(n.display))}</td><td class="xs mut" style="word-break:break-all">${esc(n.source)}</td></tr>`).join('')}</tbody></table></details>` : '';
function trendBlock(actual, cmp, py, { fmt = money } = {}) {
  const lo = Math.max(0, AS - 12), lbl = PER.slice(lo, AS + 1).map(shortLbl), series = [{ name: 'Actual', vals: actual.slice(lo, AS + 1), cls: 'l-act' }];
  if (cmp) series.push({ name: 'Budget', vals: cmp.slice(lo, AS + 1), cls: 'l-cmp' }); if (py) series.push({ name: 'Last year', vals: py.slice(lo, AS + 1), cls: 'l-py' });
  return lineChart({ labels: lbl, series, height: 190, W: 440, fmt, cur: AS - lo }) + legend([['background:var(--ink)', 'Actual'], ...(cmp ? [['background:var(--budget)', 'Budget']] : []), ...(py ? [['background:var(--ly)', 'Last year']] : [])]);
}
function nextStep(a) { return a ? `<h4>Next step</h4><div class="nx" data-ref="action:${esc(a.id)}">${esc(askText(a))}<div class="m">${esc(a.owner.role)} · by ${esc(a.date.target)} · ${esc(money(a.exposure.amount))} at stake ›</div></div>` : ''; }
function acctDrawer(id) {
  const a = lacct(id); if (!a) return null; const acc = ACC_BY[id], sg = SIG[id], x = xacct(id), d = DRV_BY[a.driver_ref], act = actOf(a.driver_ref), t = tone(a.variance);
  const subs = L().facts.rows.filter(r => r[0] === id), ip = D() ? ((D().readout || {}).account_interpretations || []).find(q => q.account === id) : null;
  return { title: acc.name, sub: `${d ? d.label + ' · ' : ''}${rangeLabel()} vs ${basisWord()}`, tags: [tag(t), persistTag(sg.persistence_hint), ip ? diagMark() : ''],
    tabs: {
      Overview: () => `${facts([['Actual', money(a.actual)], [cap(basisWord()), a.budget_status === 'no_comparator' ? 'no line' : money(a.comparator)], ['Variance', `${money(a.variance, { sign: true })}`, t]])}
        <h4>What it means</h4>${say([ip ? esc(clean(ip.text)) : null, ...acctReasons(id, a.driver_ref).map(s => esc(cap(s)) + '.'), isNum(a.share_of_abs_variance) ? `${esc(pct(a.share_of_abs_variance, { dec: 0 }))} of the total movement; ${esc(pct(a.variance_pct, { sign: true }))} against ${esc(basisWord())}.` : null])}
        ${sg.runrate.eligible ? `<h4>${esc(MONTH)} against its usual range</h4>${rangeBar(id, { ref: false })}${rangeLegend()}` : ''}
        <h4>Patterns found</h4><div class="chips">${sg.tests.filter(q => q.state === 'fired').map(q => `<span class="cp on">● ${esc(q.label)}</span>`).join('') || '<span class="cp">None</span>'}<span class="cp" data-tip="Also checked, not found|${esc(sg.tests.filter(q => q.state === 'not_fired').map(q => q.label).join('|'))}">${sg.tests.filter(q => q.state === 'not_fired').length} other checks clear</span></div>
        ${nextStep(act)}
        ${evidence(x ? x.numbers : [])}`,
      Trend: () => `${trendBlock(acc.series.actual, acc.series.budget, acc.series.py)}
        <table class="mini" style="margin-top:12px"><thead><tr><th>Month</th><th class="num">Actual</th><th class="num">Budget</th><th class="num">Variance</th></tr></thead><tbody>${PER.slice(Math.max(0, AS - 5), AS + 1).map((p, k) => { const i = Math.max(0, AS - 5) + k; return `<tr class="${i === AS ? 'sel' : ''}"><td>${esc(shortLbl(p))}</td><td class="num">${esc(money(acc.series.actual[i]))}</td><td class="num">${esc(money(acc.series.budget[i]))}</td><td class="num ${tone(acc.series.variance_vs_budget[i], 0.5)}">${esc(money(acc.series.variance_vs_budget[i], { sign: true }))}</td></tr>`; }).join('')}</tbody></table>`,
      Subsidiaries: () => subs.length ? divBars(subs.map(r => ({ name: r[1], value: r[4], ref: 'acct:' + id, floor: 0.5 }))) : '<div class="empty">No subsidiary split.</div>'
    } };
}
function driverDrawer(id) {
  const d = ldrv(id); if (!d) return null; const act = actOf(id), t = tone(d.variance), lead = leadAccount(d), ser = sumSeries(d.accounts);
  const accts = d.accounts.map(a => lacct(a)).filter(a => a && isNum(a.variance)).sort((a, b) => Math.abs(b.variance) - Math.abs(a.variance));
  const fs = D() ? (D().findings || []).filter(f => ((f.scope || {}).drivers || []).includes(id)) : [];
  return { title: d.label, sub: `${SECTION_LABEL[d.section]} · ${rangeLabel()} vs ${basisWord()}`, tags: [tag(t), lead ? persistTag(SIG[lead.id].persistence_hint) : '', fs.length ? diagMark() : ''],
    tabs: {
      Overview: () => `${facts([['Actual', money(d.actual)], [cap(basisWord()), money(d.comparator)], ['Variance', money(d.variance, { sign: true }), t]])}
        <h4>What it means</h4>${say([...fs.map(f => `<span data-ref="finding:${esc(f.id)}" class="ink" style="cursor:pointer">${esc(clean(f.title))} ›</span>`), esc(driverReason(d)), `${esc(pct(d.share_of_abs_variance, { dec: 0 }))} of the total movement; ${esc(pct(d.variance_pct, { sign: true }))} against ${esc(basisWord())}.`])}
        <h4>By account</h4>${hBars(accts.map(a => ({ name: acctName(a.id), value: a.variance, ref: 'acct:' + a.id, cls: tone(a.variance), vcls: tone(a.variance), label: money(a.variance, { sign: true }) })))}
        ${lead && SIG[lead.id].runrate.eligible && L().window === 'MTD' ? `<h4>${esc(MONTH)} against its usual range</h4>${accts.slice(0, 3).map(a => rangeBar(a.id)).join('')}${rangeLegend()}` : ''}
        ${nextStep(act)}`,
      Trend: () => trendBlock(ser.actual, ser.budget, ser.py),
      Subsidiaries: () => divBars(dimRows(id).map(r => ({ name: r.name, value: r.v, ref: 'driver:' + id, floor: 0.5 })))
    } };
}
function kpiDrawer(id) {
  const k = lkpi(id); if (!k) return null; const kd = L().kpi_diagnoses.find(q => q.kpi === id) || { drivers: [], questions: [], numbers: [] }, s = SS[KPI_LINE[id]], t = k.status === 'in_line' ? 'neu' : tone(k.variance);
  return { title: k.label, sub: `${rangeLabel()} vs ${basisWord()}`, tags: [tag(t, k.status === 'ahead' ? 'Ahead' : k.status === 'behind' ? 'Behind' : 'In line')],
    tabs: {
      Overview: () => `${facts([['Actual', money(k.actual)], [cap(basisWord()), money(k.comparator)], ['Variance', `${money(k.variance, { sign: true })}`, t]].concat(isNum(k.margin_actual) ? [['Margin', pct(k.margin_actual)], ['Margin change', pts(k.margin_bps), tone(k.margin_bps, 0.001)], ['Variance %', pct(k.variance_pct, { sign: true })]] : []))}
        ${id === 'net_income' && readout().headline ? `<h4>Reviewed reading ${diagMark()}</h4>${say([esc(clean(readout().headline))])}` : ''}
        ${s ? `<h4>Last 13 months</h4>${trendBlock(s.actual, s.budget, s.py)}` : ''}
        ${kd.drivers.length ? `<h4>Largest drivers</h4>${divBars(kd.drivers.map(x => ({ name: x.label, value: x.variance, ref: 'driver:' + x.driver })))}` : ''}
        ${kd.questions.length ? `<h4>Question for management</h4>${say(kd.questions.slice(0, 2).map(q => esc(q)))}` : ''}
        ${evidence(kd.numbers)}`
    } };
}
function lineDrawer(id) {
  const ln = lline(id); if (!ln) return null;
  if (ln.kind === 'ratio') {
    const src = id === 'gpm' ? SS.gp : id === 'ebm' ? SS.ebitda : SS.ni;
    return { title: LINE_LABEL[id], sub: `${rangeLabel()} vs ${basisWord()}`, tags: [tag(tone(ln.variance, 0.001))],
      tabs: { Overview: () => `${facts([['Actual', pct(ln.actual)], [cap(basisWord()), pct(ln.comparator)], ['Change', pts(ln.variance), tone(ln.variance, 0.001)]])}<h4>Last 13 months</h4>${trendBlock(src.margin_pct, src.margin_pct_budget, src.margin_pct_py, { fmt: v => pct(v) })}
        <h4>What moved it</h4>${divBars(moversItems().slice(0, 6))}` } };
  }
  const kid = Object.keys(KPI_LINE).find(k => KPI_LINE[k] === id); return kid ? kpiDrawer(kid) : null;
}
function actionDrawer(id) {
  const a = L().actions.find(x => x.id === id); if (!a) return null;
  return { title: askText(a), sub: `${a.label} · ${a.category_label}`, tags: [persistTag(a.persistence)],
    tabs: { Overview: () => `${facts([['At stake', money(a.exposure.amount)], ['Owner (suggested)', a.owner.role], ['Target date', a.date.target]])}
      <h4>Question to answer</h4>${say([esc(a.question)])}
      <h4>Evidence needed</h4>${say(a.required_evidence.map(esc))}
      ${isNum(a.forecast.remaining_months_effect) ? `<h4>If it continues</h4><div class="nx">${esc(money(Math.abs(a.forecast.remaining_months_effect)))} over the remaining ${a.forecast.remaining_months} months<div class="m">A proposal: nothing enters a forecast until the owner accepts it.</div></div>` : ''}
      <h4>Accounts</h4><div class="chips">${a.accounts.map(x => `<span class="cp" data-ref="acct:${esc(x)}">${esc(acctName(x))} ›</span>`).join('')}</div>
      <button class="btnl" data-ref="driver:${esc(a.subject_ref)}">Open driver ›</button>` } };
}
const STATE_WORD = { observed_fact: 'Observed', analytical_inference: 'Inference', hypothesis: 'Hypothesis', management_input_required: 'Needs management input' };
function findingDrawer(id) {
  const f = findingById(id); if (!f) return null; const dids = (f.scope || {}).drivers || [];
  const hint = { one_off: 'one_off_candidate', recurring: 'recurring_level_change', timing: 'timing_reversal' }[f.persistence] || f.persistence;
  return { title: clean(f.title), sub: `Admitted finding · ${dids.map(x => (DRV_BY[x] || {}).label || x).join(', ') || rangeLabel()}`, tags: [diagMark(), persistTag(hint)],
    tabs: { Overview: () => `<h4>What the review found</h4>${say((f.statements || []).map(s => `<b class="ink">${esc(STATE_WORD[s.state] || s.state)}:</b> ${esc(clean(s.text))}`))}
      ${(f.missing_evidence || []).length ? `<h4>Still missing</h4>${say(f.missing_evidence.map(esc))}` : ''}
      ${(f.management_questions || []).length ? `<h4>Question for management</h4>${say(f.management_questions.map(q => esc(clean(q))))}` : ''}
      ${dids.map(x => `<button class="btnl" data-ref="driver:${esc(x)}">Open ${esc((DRV_BY[x] || {}).label || x)} ›</button>`).join('')}` } };
}
function qcDrawer() {
  const qc = P.qc, dot = r => r === 'PASS' ? 'fav' : r === 'FAIL' ? 'unf' : r === 'WARN' ? 'amb' : 'neu';
  return { title: 'Data quality and scope', sub: `${qc.status.toLowerCase()} · ${qc.caveats.length} note(s)`, tags: [],
    tabs: { Checks: () => `<table class="mini"><tbody>${qc.checks.map(c => `<tr><td style="width:120px">${tag(dot(c.result), c.result.toLowerCase().replace('_', ' '))}</td><td><b class="ink">${esc(cap(c.id.replace(/_/g, ' ')))}</b><div class="xs mut">${esc(clean(c.detail))}</div></td></tr>`).join('')}</tbody></table>
      <h4>Not available in this data</h4>${say(Object.entries(P.capabilities).map(([k, v]) => `<b class="ink">${esc(cap(k.replace(/_/g, ' ')))}</b>: ${esc(v.reason)}`))}` } };
}
function outlookDrawer(id) {
  const e = OUT.lines.ebitda;
  return { title: id === 'ytd' ? 'Year to date' : 'Full-year run-rate', sub: `fiscal ${OUT.fiscal_year} · Adjusted EBITDA`, tags: [tag('sky', 'Rule, not a forecast')],
    tabs: { Overview: () => `${id === 'ytd' ? facts([['Actual', money(e.ytd.actual)], ['Budget', money(e.ytd.budget)], ['Variance', money(e.ytd.variance, { sign: true }), tone(e.ytd.variance)]]) : facts([['Run-rate a month', money(e.mechanical.run_rate)], ['Months left', String(e.remaining_months)], ['Full year', money(e.mechanical.value)]])}
      <h4>All lines</h4><table class="mini"><thead><tr><th>Line</th><th class="num">Year to date</th><th class="num">Full year</th><th class="num">vs last year</th></tr></thead><tbody>${Object.values(OUT.lines).map(l => `<tr><td>${esc(LINE_LABEL[l.id] || l.id)}</td><td class="num">${esc(money(l.ytd.actual))}</td><td class="num">${esc(money(l.mechanical.value))}</td><td class="num ${tone(l.gap_vs_prior_year)}">${esc(money(l.gap_vs_prior_year, { sign: true }))}</td></tr>`).join('')}</tbody></table>
      <h4>By rule</h4>${hBars(e.mechanical.sensitivity.map(x => ({ name: x.label, value: x.value, cls: x.rule === e.mechanical.rule ? 'hi' : '' })))}
      ${OUT.note ? `<p class="xs mut" style="margin-top:12px">${esc(OUT.note)}</p>` : ''}` } };
}
function scenarioDrawer(rule) {
  const rows = Object.values(OUT.lines).map(l => ({ l, s: l.mechanical.sensitivity.find(x => x.rule === rule) })).filter(x => x.s); if (!rows.length) return null;
  return { title: rows[0].s.label, sub: 'Full-year run-rate rule', tags: [tag('sky', 'Reference only')],
    tabs: { Overview: () => `${hBars(rows.map(({ l, s }) => ({ name: LINE_LABEL[l.id] || l.id, value: s.value })))}<p class="xs mut" style="margin-top:12px">Year to date plus the remaining months at ${esc(rows[0].s.label.toLowerCase())}.</p>` } };
}

/* ---------- boot ---------- */
function renderAll() { renderHeader(); renderSummary(); renderDrivers(); renderOutlook(); renderGlossary(); }
renderAll();
const hashTab = String(location.hash || '').replace('#', '');
setTab(TABQ[hashTab] ? hashTab : S.tab);
