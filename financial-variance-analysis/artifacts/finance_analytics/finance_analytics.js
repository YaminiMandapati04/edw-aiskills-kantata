/* Finance diagnostic renderer 1.10.6 (contract sda.finance-analysis/1.5.0).
   Insight-led layout: a bullet summary, a P&L flow strip, charts first, text only in the drill-down. Shows the
   admitted diagnosis where one exists for the selected lens; every other lens reads as the engine baseline.
   The renderer computes nothing economic. It formats, arranges, filters and sorts values the engine emitted.
   Permitted arithmetic: chart geometry, display sign flips, sums of engine-emitted facts for a dimension lens,
   shares for display. Null renders as "—", never as zero. Negatives print in brackets; "adverse" is never shown. */
'use strict';
const P = window.__SDA_PAYLOAD__;
if (!P || P.contract_version !== 'sda.finance-analysis/1.5.0') { document.body.innerHTML = '<div style="padding:40px;font-family:sans-serif">Refused: payload contract is not sda.finance-analysis/1.3.0.</div>'; throw new Error('contract'); }
const META = P.meta, PER = META.periods, AS = META.as_of.idx, ACC = P.accounts, SIG = P.signals, OUT = P.outlook, DIAGS = P.diagnoses || (P.diagnosis && P.diagnosis.lens ? { [`${P.diagnosis.lens.window}_${P.diagnosis.lens.basis}`]: P.diagnosis } : {});
const MON = META.materiality.monitoring_abs;
const ACC_BY = Object.fromEntries(ACC.map(a => [a.id, a]));
const DRV_BY = Object.fromEntries(P.drivers.map(d => [d.id, d]));
const SS = Object.fromEntries(P.statement_series.map(s => [s.id, s]));
const SECTION_LABEL = { rev: 'Revenue', cos: 'Cost of sales', opex: 'Operating expenses', syn: 'Synergies and strategic investments', nonop: 'Non-operating income (expense)' };
const KPI_LINE = { revenue: 'rev', cogs: 'cos', gross_profit: 'gp', opex: 'opex', ebitda: 'ebitda', nonop: 'nonop', net_income: 'ni' };
const LINE_LABEL = { rev: 'Revenue', cos: 'Cost of sales', gp: 'Gross profit', gpm: 'Gross margin', opex: 'Operating expenses', ebitda: 'Adjusted EBITDA', ebm: 'Adjusted EBITDA margin', syn: 'Synergies and strategic investments', nonop: 'Non-operating income (expense)', ni: 'Net income', nim: 'Net income margin' };
const PERSIST = { one_off_candidate: ['One-off', 'amb'], persistent: ['Recurring', 'unf'], recurring_level_change: ['New level', 'unf'], seasonal: ['Seasonal', 'sky'], timing_reversal: ['Timing', 'sky'], coverage: ['No budget line', 'amb'], undetermined: null };
const MONTH = new Date(META.as_of.start + 'T00:00:00').toLocaleString('en-US', { month: 'long' });
const MONTH_YEAR = MONTH + ' ' + META.as_of.start.slice(0, 4);

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
const tone = (v, floor = MON) => !isNum(v) || Math.abs(v) < floor ? 'neu' : (v > 0 ? 'fav' : 'unf');
const toneWord = t => ({ fav: 'Favourable', unf: 'Unfavourable', neu: 'In line' })[t];
const tag = (t, word) => `<span class="tag ${t}">${esc(word || toneWord(t))}</span>`;
/* a driver's share of movement is of the bridge it sits on (engine share_scope): each bridge's shares add up to 100% */
const belowEb = d => !!d && d.share_scope === 'below_ebitda';
const shareOf = d => belowEb(d) ? 'of the movement below Adjusted EBITDA' : 'of the Adjusted EBITDA movement';
const shareLbl = d => belowEb(d) ? 'Share of below-EBITDA movement' : 'Share of EBITDA movement';
const persistTag = h => PERSIST[h] ? tag(PERSIST[h][1], PERSIST[h][0]) : '';
/* engine prose: moderate words and bracketed negatives */
const clean = t => String(t || '').replace(/adverse/g, 'unfavourable').replace(/Adverse/g, 'Unfavourable').replace(/(\d)mm\b/g, '$1mn')
  .replace(/coverage \(comparability\), not performance/g, 'a gap in the plan, not a sign of good or bad performance').replace(/comparability, not performance/g, 'a gap in the plan, not a sign of good or bad performance')
  .replace(/A projection rule, not a forecast/g, 'A straight-line projection, not a forecast').replace(/a projection rule, not a forecast/g, 'a straight-line projection, not a forecast')
  .replace(/[Mm]echanical full-year outlook/g, m => (m[0] === 'M' ? 'S' : 's') + 'traight-line full-year projection').replace(/\bmechanical\b/g, 'straight-line')
  .replace(/run-rate reference/g, 'recent run-rate').replace(/Structural signals are tested on/g, 'Patterns are checked on').replace(/\bmonitoring threshold\b/g, 'smallest amount we report')
  .replace(/\bcomparators?\b/g, m => m.endsWith('s') ? 'comparisons' : 'comparison').replace(/\bComparator\b/g, 'Comparison')
  .replace(/\(−\s?(\$?[\d.,]+(?:k|mn|%)?)\)/g, '($1)')
  .replace(/−\s?(\$?[\d.,]+(?:k|mn|%)?)( bps)?/g, (m, a, b) => '(' + a + ')' + (b || ''));
const cap = s => s ? s[0].toUpperCase() + s.slice(1) : s;
/* lower-case a label inside a sentence, keeping acronyms as written: Adjusted EBITDA -> adjusted EBITDA, Fully Loaded S&M Expense -> fully loaded S&M expense */
const lc = s => String(s == null ? '' : s).replace(/\b([A-Z])(?=[a-z])/g, c => c.toLowerCase());
const joinAnd = arr => arr.length < 2 ? (arr[0] || '') : arr.slice(0, -1).join(', ') + ' and ' + arr[arr.length - 1];
/* account name with its subsidiary, so five 'Unrealized Gain/Loss' rows stay distinguishable */
const acctName = id => { const a = ACC_BY[id]; if (!a) return id; return a.subsidiary && META.scope.subsidiaries.length > 1 ? `${a.name} (${a.subsidiary})` : a.name; };
/* month labels from the period start date: Sep '25 (the view's PERIOD text is not a month name) */
const MON3 = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const shortLbl = p => { const d = String((p && p.start) || ''); return /^\d{4}-\d{2}/.test(d) ? MON3[+d.slice(5, 7) - 1] + " '" + d.slice(2, 4) : (p && p.label) || ''; };
/* one-sided accounts: active in only one of the two periods */
const basisAdj = () => L().basis === 'budget' ? 'budget' : 'prior-year';
const BASIS_CHIP = { no_comparator: () => `New this period (no ${basisAdj()} activity)`, no_activity: () => `Not this period (${basisWord()} only)`, no_comparator_at_level: () => `No ${basisWord()} at this level` };
const basisChip = b => BASIS_CHIP[b] ? ` <span class="bchip">${esc(BASIS_CHIP[b]())}</span>` : '';
const sumSeries = ids => { const n = PER.length; const out = { actual: Array(n).fill(null), py: Array(n).fill(null), budget: Array(n).fill(null) }; ids.forEach(id => { const s = ACC_BY[id] && ACC_BY[id].series; if (!s) return; ['actual', 'py', 'budget'].forEach(k => { for (let i = 0; i < n; i++) if (isNum(s[k][i])) out[k][i] = (out[k][i] || 0) + s[k][i]; }); }); return out; };

/* ---------- state and lens access ---------- */
const S = { tab: 'summary', lens: META.primary_lens.id, drawer: null, drawerTab: null, bridgeMode: 'reported', bridgeSel: null, dimDriver: null, opener: null, rule: null, rrInfo: false, gapCat: 'ebitda' };
const L = () => P.lenses[S.lens];
const X = () => L().explanations;
const lacct = id => L().accounts.find(a => a.id === id);
const ldrv = id => L().drivers.find(d => d.id === id);
const lline = id => L().lines.find(x => x.id === id);
const lkpi = id => L().kpis.find(k => k.id === id);
const xacct = id => X().accounts.find(x => x.id === id);
const actOf = did => L().actions.find(a => a.subject_ref === did);
const D = () => DIAGS[S.lens] || null;
const readout = () => (D() && D().readout) || {};
/* the AI-review badge was retired (no "AI reviewed" badge is shown); kept as a no-op so the review headings that call it still render */
const diagMark = () => '';
const findingById = id => D() ? (D().findings || []).find(f => f.id === id) : null;
const VERIFIED = META.data_mode !== 'local' && ((P.qc.checks || []).find(c => c.id === 'governed_reconciliation') || {}).result === 'PASS';
const baseMark = () => META.data_mode === 'local' ? '<span class="tag unf">Test data</span>' : VERIFIED ? '<span class="tag fav">Data verified</span>' : '<span class="tag amb">From the data</span>';
const basisWord = () => L().basis_label;
const rangeLabel = () => L().window === 'MTD' ? MONTH_YEAR : (L().range ? L().range.label : S.lens);
/* the engine's budget reliability check: budget figures on failed lines reflect the load, not performance */
const BCHK = META.budget_check || null;
const budgetNote = (force = false) => (BCHK && !BCHK.reliable && (force || L().basis === 'budget')) ? `<div class="bnote" role="note"><b>Budget not meaningful</b><span>for ${esc(joinAnd(BCHK.failed.map(lc)))}: the budget is not in line with actuals (${esc(BCHK.rule)}). Variances against it reflect the budget load, not performance; read these lines against prior year.</span></div>` : '';
const twin = () => { const t = P.lenses[`${L().window}_${L().basis === 'budget' ? 'py' : 'budget'}`]; return t && t.available ? t : null; };

/* ---------- reasoning (selection and phrasing of engine signals only) ---------- */
function leadAccount(d) { const m = d.accounts.map(id => lacct(id)).filter(a => a && isNum(a.movement) && a.movement !== 0); return m.length ? m.sort((a, b) => Math.abs(b.movement) - Math.abs(a.movement))[0] : null; }
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
  if (d.accounts.length > 1) parts.push(`mostly ${acctName(lead.id)} at ${money(lead.movement, { sign: true })}${lead.movement_basis === 'both' ? '' : ' (' + BASIS_CHIP[lead.movement_basis]().toLowerCase() + ')'}`);
  parts.push(...acctReasons(lead.id, d.id));
  if (parts.length === (d.accounts.length > 1 ? 1 : 0) && isNum(d.share_of_abs_variance)) parts.push(`${pct(d.share_of_abs_variance, { dec: 0 })} ${shareOf(d)}`);
  return cap(parts.join('; ')) + '.';
}
const RULE_ASK = { outlier_month: 'Confirm whether the {m} spike in {l} is a one-off or a new run-rate', persistent_gap: 'Decide whether to re-plan {l} or act to close the gap', seasonal_echo: 'Check that the {l} budget phasing reflects the seasonal pattern', budget_outside_run_rate: 'Review the {l} budget assumption against recent run-rate', yoy_break: 'Explain the break in the year-on-year pace of {l}' };
const askText = a => a.ask && a.ask.text ? clean(a.ask.text) : (RULE_ASK[a.rule] || "Get the owner's explanation for the movement in {l}").replace('{m}', MONTH).replace('{l}', a.label);

/* ---------- header, tabs, footer, glossary ---------- */
function renderHeader() {
  $('#pageTitle').textContent = `Finance review · ${MONTH_YEAR}`;
  $('#scope').innerHTML = `<span class="chip">Scope <b>${esc(META.scope.label || META.scope.filtered_to || 'All subsidiaries')}</b></span><span class="chip">${esc(String(META.currency).split(' ')[0])}</span><span class="chip">${META.months_of_history} months of history</span>`;
  const curW = L().window, curB = L().basis;
  $('#lens').innerHTML = `<div class="lrow" id="rowWin"${S.tab === 'outlook' ? ' hidden' : ''}><span class="lab">Window</span><span class="seg" id="segWin">${['MTD', 'QTD', 'YTD', 'LTM'].map(w => `<button data-w="${w}" class="${w === curW ? 'on' : ''}" ${P.lenses[`${w}_${curB}`].available ? '' : 'disabled'}>${esc(META.window_labels[w])}</button>`).join('')}</span></div>
    <div class="lrow" id="rowBas"${S.tab === 'outlook' ? ' hidden' : ''}><span class="lab">Compare</span><span class="seg" id="segBas">${['py', 'budget'].map(b => `<button data-b="${b}" class="${b === curB ? 'on' : ''}">vs ${esc(META.basis_labels[b])}</button>`).join('')}</span></div>`;
  $('#segWin').onclick = e => { const b = e.target.closest('button'); if (b && !b.disabled) setLens(`${b.dataset.w}_${curB}`); };
  $('#segBas').onclick = e => { const b = e.target.closest('button'); if (b) setLens(`${curW}_${b.dataset.b}`); };
  const qc = P.qc, sb = $('#stateBadge');
  sb.className = 'state' + (qc.status === 'CLEAN' ? ' ok' : '');
  sb.innerHTML = `${VERIFIED ? '✓ Data verified' : META.data_mode === 'local' ? '! Test data' : '! Data checks'}${qc.caveats.length ? ` · ${qc.caveats.length} note${qc.caveats.length > 1 ? 's' : ''}` : ''}`;
  sb.onclick = () => openDrawer('qc');
  $('#foot').innerHTML = `<span>Source: ${esc(META.sources.join(', '))} · ${esc(META.scope.label || '')}</span><span>Generated ${esc(String(META.generated_at).slice(0, 10))}</span><span>${D() ? 'AI reviewed' : 'This view not AI reviewed'}</span>`;
}
const TABQ = { summary: 'Where do we stand, why, and what needs a decision?', drivers: 'What moved the result, and what drives it?', outlook: 'Where does the year land?' };
function setTab(t) { S.tab = t; document.querySelectorAll('nav.tabs button[data-tab]').forEach(b => b.classList.toggle('active', b.dataset.tab === t)); document.querySelectorAll('.view').forEach(v => v.classList.toggle('active', v.id === 'view-' + t)); $('#tabQ').textContent = TABQ[t]; ['#rowWin', '#rowBas'].forEach(r => { const el = $(r); if (el) el.hidden = t === 'outlook'; }); try { history.replaceState(null, '', '#' + t); } catch (e) { /* sandboxed srcdoc frame (claude.ai preview): no URL to update */ } renderGlossary(); }
$('#tabs').addEventListener('click', e => { const b = e.target.closest('button[data-tab]'); if (b) setTab(b.dataset.tab); });
function setLens(id) { if (!P.lenses[id] || !P.lenses[id].available) return; S.lens = id; S.bridgeSel = null; closeDrawer(); renderAll(); }
/* glossary: every label on the page, grouped; "This tab" shows the shared groups plus the open tab's own labels,
   "All labels" shows everything. Detail-panel labels always show, since panels open from every tab. */
const TAB_NAME = { summary: 'Summary', drivers: 'Drivers', outlook: 'Outlook' };
const sw = st => `<i class="sw" style="${st}"></i>`;
function glossaryRows() {
  const m = L().materiality || META.materiality, mon = money(m.monitoring_abs), sens = OUT && OUT.state === 'calculated' ? OUT.lines.ebitda.mechanical.sensitivity.map(x => x.label) : [];
  return [
    ['all', 'Direction', [
      [tag('fav'), 'Helps profit against the comparison: more revenue, or less cost.'],
      [tag('unf'), 'Hurts profit against the comparison: less revenue, or more cost.'],
      [tag('neu'), `Within ${mon} of the comparison: too small to count as a driver.`],
      [`${tag('fav', 'Ahead')}${tag('unf', 'Behind')}`, 'Used on the P&L figures: the line is better or worse than the comparison by more than that amount.']]],
    ['all', 'Will it repeat?', [
      [persistTag('one_off_candidate'), 'The latest month sits outside its usual six-month range for the first time; a second month would make it a new level.'],
      [persistTag('persistent'), 'Off budget in the same direction in most recent months: a lasting gap rather than noise.'],
      [persistTag('recurring_level_change'), 'Has stepped to a new level and held it for two months or more.'],
      [persistTag('seasonal'), 'The same month last year moved the same way against its own run-rate.'],
      [persistTag('timing_reversal'), 'This month reverses last month\'s gap: likely a timing shift between months.'],
      [persistTag('coverage'), 'Income or spending on an account with no budget line: a gap in the plan, not a sign of good or bad performance.']]],
    ['all', 'Figures', [
      ['($76k) · (420) bps', 'Brackets mark a negative figure. bps is a change in margin in basis points (100 bps = 1 percentage point).'],
      ['+$510', 'A plus sign marks a favourable change.'],
      ['$143k · $1.92mn', 'Thousands (k) and millions (mn) of US dollars, converted as stored in the marts.'],
      ['n.m. · —', 'n.m.: not meaningful (a percentage of 1,000% or more). —: not available, never zero.'],
      ['By sub-group · L5 › L6', 'The finance system\'s levels below the driver (L4): L5, then L6, then the accounts. A level that repeats its parent is left out. Each level adds up to the one above to the cent.'],
      ['Revenue by product line', 'The deepest revenue sub-groups of the finance system (the product lines), footing to revenue. Month shows the latest month alone; the other button shows the page\'s window.'],
      ['Operating expenses by sub-group', 'S&M, R&D and G&A split into their sub-groups (sales, marketing, engineering, product, finance, HR, IT and so on).'],
      ['Size thresholds', `For ${esc(META.window_labels[L().window].toLowerCase())}: large ${money(m.executive_abs)} · notable ${money(m.management_abs)} · smallest we report ${mon}. Each is a share of an average month's revenue (${esc(money(META.materiality.average_month_revenue))}) times the ${m.months} month${m.months === 1 ? '' : 's'} in the window; the Assumptions list below has every window. Smaller moves read as in line.`]]],
    ['summary', 'Summary tab', [
      ['Bold lead of a bullet', 'The conclusion. The sentence after it is the evidence and what it means; click the bullet for the detail.'],
      ['<span class="opx">−  =  ±</span>', 'In the P&L strip, the operators show the order of calculation: revenue less cost of sales gives gross profit, less opex gives Adjusted EBITDA, plus or minus non-operating items gives net income.'],
      [`${sw('background:var(--s1);width:22px;height:6px')}${sw('background:var(--budget);width:2px;height:12px')} Margin bars`, 'Margin bars: the dark bar is this view\'s margin; the gold mark is the comparison\'s margin.'],
      ['Full-year EBITDA (run-rate)', 'Year to date plus the remaining months at the run-rate rule; a projection rule, not a forecast.'],
      ['What moved net income', 'Each driver\'s variance against the comparison, from the EBITDA bridge and the steps down to net income.'],
      ['At stake · for discussion', 'The amount behind a decision. Owners are suggested teams, and dates are default targets (build date plus 10 business days).'],
      ['Excluding the … item', 'The lead backs out a named one-off (a single unusual month, or a single posting on an account with no history, at a quarter or more of the net-income movement) to show net income without it. The Assumptions list below has the test.']]],
    ['drivers', 'Drivers tab', [
      ['By driver · To net income', 'Two views of the bridge: each driver\'s step, or the steps from Adjusted EBITDA to net income.'],
      ['Bullets beside the bridge', 'What the bridge says for the window, comparison and view chosen: the result, the largest unfavourable and favourable drivers with the account that carries most of each, the split by line and how concentrated the movement is. Click a bullet, or an underlined name, to open its detail down to sub-group, account and department.'],
      ['Bridge labels at 45°', 'Category names on the bridge axis are tilted so long names never overlap.'],
      [`${sw('background:var(--s1);width:10px;height:10px')} Start / end`, 'The comparison\'s Adjusted EBITDA on the left, the actual on the right; the bars between are the steps.'],
      [`${sw('background:var(--pos);width:10px;height:10px')}${sw('background:var(--adv);width:10px;height:10px')} Green · gold steps`, 'Green steps add to profit, gold steps take away from it.'],
      ['Driver', 'An account group (L4 in the chart of accounts) or a single account; the bridge has one step per driver.'],
      ['Share of EBITDA movement', 'A driver\'s movement, ignoring its sign, as a share of all the Adjusted EBITDA bridge\'s steps ignoring their signs; the bars on the bridge add up to 100%. Drivers below EBITDA show their share of the steps to net income instead.'],
      [`${sw('background:var(--rng);width:22px;height:6px')} ${sw('background:var(--muted);width:2px;height:12px')} ${sw('background:var(--budget);width:3px;height:12px')} ${sw('background:var(--s1);width:9px;height:9px;transform:rotate(45deg)')} Range bars`, `Range bars: the band is the account's usual six-month range, the grey tick its run-rate, the gold tick its budget, the diamond ${esc(MONTH)}'s actual (red or green when it moves the result).`],
      [`Accounts above ${mon}`, 'Only accounts whose variance clears the monitoring threshold get a range bar.'],
      ['By account · By department', 'Click to expand the accounts and departments behind the selected driver; "other" rows expand to the accounts they group.'],
      ['By subsidiary', 'Against prior year only: each subsidiary\'s movement for the chosen driver. The budget is not held by subsidiary, so the panel is not shown against budget.']]],
    ['outlook', 'Outlook tab', [
      ['Where the year lands (bullets)', 'For the run-rate rule picked: where the full year lands against budget and last year, what is already banked, which drivers run ahead of or behind their remaining budget at that pace, and how much the rule choice and recurring gaps matter. They change with the rule; click a bullet or an underlined name for the detail.'],
      ['EBITDA year to date', 'Actual Adjusted EBITDA for the closed months of the fiscal year, against budget.'],
      ['Full-year EBITDA (run-rate)', 'Year to date plus the remaining months at the run-rate rule. A rule, not a forecast; nothing declared by management is included.'],
      ['Last year full year · Full-year budget', 'The comparisons for the full year. "Not available" means the budget for the rest of the year was not loaded.'],
      [`${sw('background:var(--s1);width:16px;height:3px')} ${sw('background:repeating-linear-gradient(90deg,var(--s1) 0 3px,transparent 3px 6px);width:16px;height:3px')} ${sw('background:var(--budget);width:16px;height:3px')} ${sw('background:var(--ly);width:16px;height:3px')} Chart lines`, 'Monthly chart: actual, run-rate for the remaining months (dotted: the only projected line), budget (gold), last year (grey). The lime dot is the analysis month.'],
      ['Run-rate rules', `${sens.length ? esc(sens.join(' · ')) + '. ' : ''}Different ways to project the remaining months. Pick one to update every figure, chart and detail on this tab; the Summary tab always uses the trailing three-month average. The spread shows how much the choice of rule matters.`],
      ['Full-year bridge', 'From the full-year budget (or year to date when no budget is loaded) to the full-year run-rate figure.'],
      ['If current gaps continue', 'Pick a category: each driver\'s remaining months at the chosen run-rate rule against its budget for those months, favourable to the right. The operating categories add up to the full-year bridge\'s "Remaining months vs budget" step.'],
      ['Suggestions only', 'Nothing here changes a forecast until a named owner accepts it.']]],
    ['panel', 'Detail panels (open from any tab)', [
      ['Overview · Trend · Subsidiaries', 'Panel tabs: the reading, the last 13 months, and the split by subsidiary.'],
      ['Actual · Budget · Variance', 'The figures for the selected view; Variance follows the profit sign, so (…) is unfavourable.'],
      ['What it means · Next step', 'What the patterns suggest, and the suggested next step with an owner and a target date.'],
      ['Patterns found · other checks clear', 'The patterns found in the account\'s history; hover "other checks clear" for those that did not show up.'],
      ['Where the figures come from', 'Each figure in the text, with the data field it comes from (for audit).']]],
    ['all', 'How far this page has been checked', [
      [baseMark(), META.data_mode === 'local' ? 'Made-up sample figures for testing.' : VERIFIED ? 'Every figure is calculated straight from the finance system and ties to its totals. It shows what moved, not why.' : 'Calculated straight from the finance system data. It shows what moved, not why.'],
      ['Data verified · notes', 'The data badge: click it for the checks behind the figures and what the data cannot answer.'],
      ['<span class="tag unf">Test data</span>', 'Local sample figures from a workbook; never present them as real.']]]];
}
/* the sign and colour legend, always open on every tab, above How to read this page */
const signLegend = () => `<section class="sgn" id="signLegend" aria-label="Variance legend"><h2>Variance legend: how favourable and unfavourable moves are shown</h2>
  <table class="gls-t sgn-t"><thead><tr><th>Outcome</th><th>Bar</th><th>Text colour and sign</th><th>Meaning</th></tr></thead><tbody>
  <tr data-t="fav"><td>Favourable</td><td><i class="sw fav"></i></td><td><span class="fav">Green, with a plus sign: +$92k</span></td><td>Helps profit against the comparison: more revenue, or less cost.</td></tr>
  <tr data-t="unf"><td>Unfavourable</td><td><i class="sw unf"></i></td><td><span class="unf">Red, in brackets: ($297k)</span></td><td>Hurts profit against the comparison: less revenue, or more cost.</td></tr>
  <tr data-t="neu"><td>In line</td><td><i class="sw neu"></i></td><td><span class="neu">Grey, either sign: +$4k</span></td><td>Smaller than ${esc(money(MON))}, the smallest move we report.</td></tr>
  <tr data-t="lvl"><td>Negative amount</td><td><span class="mut">—</span></td><td><span class="ink">Black, in brackets: ($4.49mn)</span></td><td>A loss or a net expense, not a judgement.</td></tr>
  </tbody></table></section>`;
function renderGlossary() {
  const host = $('#glossary'), open = !!(host.querySelector('.gls-d') || {}).open, all = !!S.glsAll, groups = glossaryRows();
  const shown = groups.filter(([sc]) => all || sc === 'all' || sc === 'panel' || sc === S.tab).sort((x, y) => all ? 0 : (y[0] === S.tab) - (x[0] === S.tab)), n = g => g.reduce((s, x) => s + x[2].length, 0);
  host.innerHTML = signLegend() + `<details class="gls-d"${open ? ' open' : ''}><summary><h2>How to read this page</h2><span class="hint">${all ? 'all tabs' : esc(TAB_NAME[S.tab] || '') + ' tab'} · ${n(shown)} labels · click to show or hide</span><span class="chev">▾</span></summary>
    <div class="gls-bar"><span class="tog" id="glsMode"><button data-m="tab" class="${all ? '' : 'on'}">This tab (${n(groups.filter(([sc]) => sc === 'all' || sc === 'panel' || sc === S.tab))})</button><button data-m="all" class="${all ? 'on' : ''}">All labels (${n(groups)})</button></span></div>
    <table class="gls-t"><thead><tr><th>Label</th><th>Meaning</th></tr></thead><tbody>${shown.map(([, grp, rows]) => `<tr class="grp"><td colspan="2">${esc(grp)}</td></tr>${rows.map(r => `<tr><td>${r[0]}</td><td>${r[1]}</td></tr>`).join('')}`).join('')}</tbody></table></details>`;
  $('#glsMode').onclick = e => { const b = e.target.closest('button'); if (!b) return; S.glsAll = b.dataset.m === 'all'; renderGlossary(); };
  renderAssumptions(host);
}
/* the Assumptions dropdown: every threshold, test and rule in use, from the engine's own objects (META.assumptions); the page formats nothing */
function renderAssumptions(host) {
  const A = META.assumptions || [], open = !!S.asmOpen, n = A.reduce((t, g) => t + g.rows.length, 0);
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
/* tilt: axis labels at 45 degrees so long category names never overlap ('auto': only when a label is wider than its slot) */
const TILT_FS = 11.5, TILT_CW = 6.4;
function waterfall({ id, start, steps, end, height = 300, selected = null, groups = null, W = 900, tilt = 'auto' }) {
  const items = [{ label: start.label, value: start.value, base: true }, ...steps, { label: end.label, value: end.value, base: true }];
  const n = items.length, maxLen = Math.max(...items.map(it => String(it.key || it.label || '').length));
  const slot0 = (W - 68) / n, tilted = tilt === true || (tilt === 'auto' && n > 6 && !steps.some(s => s.key) && maxLen * TILT_CW > slot0 * 0.95);
  const diag = maxLen * TILT_CW * Math.SQRT1_2;                  /* the vertical (and horizontal) reach of the longest tilted label */
  const padL = tilted ? Math.max(58, Math.ceil(diag - slot0 / 2 + 12)) : 58, padR = 10, padT = 26;
  const padB = tilted ? Math.ceil(diag + 22) + (groups ? 16 : 0) : (groups ? 62 : 46), H = tilted ? height + padB - 46 : height;
  const slot = (W - padL - padR) / n, bw = Math.min(slot * 0.64, 84);
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
    const dense = n > 9, words = r.it.key ? [r.it.key] : wrap(r.it.label, dense ? 11 : 18), ly = H - padB + 12;
    const axis = tilted ? `<text class="lbl tilt" x="${cx.toFixed(1)}" y="${ly}" text-anchor="end" transform="rotate(-45 ${cx.toFixed(1)} ${ly})" style="font-size:${TILT_FS}px">${esc(r.it.key || r.it.label)}</text>`
      : words.map((w, j) => `<text class="lbl" x="${cx.toFixed(1)}" y="${H - padB + 16 + j * (dense ? 11 : 13)}" text-anchor="middle" style="font-size:${dense ? 9.5 : 11}px">${esc(w)}</text>`).join('');
    bars += `<g class="bar${sel}" data-ref="${esc(r.it.ref || '')}" tabindex="0" role="button" aria-label="${esc(r.it.label)} ${esc(label)}" data-tip="${esc(r.it.label)}|${esc(r.it.base ? full(r.it.value) : full(r.it.value, { sign: true }) + ' · running ' + full(r.y1))}">
      <rect x="${x.toFixed(1)}" y="${padT}" width="${bw.toFixed(1)}" height="${H - padT - padB}" fill="transparent"/>
      <rect class="body ${cl}" rx="2" x="${x.toFixed(1)}" y="${yA.toFixed(1)}" width="${bw.toFixed(1)}" height="${h.toFixed(1)}"/>
      <text x="${cx.toFixed(1)}" y="${labY.toFixed(1)}" text-anchor="middle" style="font-size:${dense ? 10 : 11.5}px;font-weight:600">${esc(label)}</text>
      ${axis}</g>`;
    if (i < rects.length - 1) { const yc = sy(r.it.base ? r.it.value : r.y1); conns += `<line class="conn" x1="${(x + bw).toFixed(1)}" x2="${(x + slot).toFixed(1)}" y1="${yc.toFixed(1)}" y2="${yc.toFixed(1)}"/>`; }
  });
  let grp = '';
  if (groups) groups.forEach(gr => { const x0 = padL + slot * gr.from + (slot - bw) / 2, x1 = padL + slot * gr.to + (slot - bw) / 2 + bw, y = H - 8; grp += `<line x1="${x0}" x2="${x1}" y1="${y}" y2="${y}" style="stroke:var(--ink);stroke-width:1"/><text x="${(x0 + x1) / 2}" y="${y - 5}" text-anchor="middle" style="font-size:10px;font-weight:600">${esc(gr.label)} ${esc(money(gr.total, { sign: true }))}</text>`; });
  const svg = `<svg class="wf" id="${esc(id)}" viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid meet">${g}<line class="zero" x1="${padL}" x2="${W - padR}" y1="${sy(0)}" y2="${sy(0)}"/>${conns}${bars}${grp}</svg>`;
  /* keyed steps (account names): the axis carries a short key, the names sit in a key below the chart */
  const keyed = steps.filter(s => s.key);
  return keyed.length ? svg + `<div class="wfkey" id="${esc(id)}-key">${keyed.map(s => `<div class="wk"${s.ref ? ` data-ref="${esc(s.ref)}" tabindex="0" role="button"` : ''}><b class="wkb ${s.kind || ((s.value || 0) >= 0 ? 'fav' : 'unf')}">${esc(s.key)}</b><span class="wkn">${esc(s.label)}</span><span class="wkv ${tone(s.value, 0.5)}">${esc(money(s.value, { sign: true }))}</span></div>`).join('')}</div>` : svg;
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
  return `<div class="hb">${items.map(i => `<div class="hbr${i.rule ? ' pick' : ''}" ${i.ref ? `data-ref="${esc(i.ref)}"` : ''} ${i.rule ? `data-rule="${esc(i.rule)}" tabindex="0" role="button"` : ''} data-tip="${esc(i.name)}|${esc(i.label || full(i.value))}"><span class="nm">${esc(i.name)}</span><span class="tr"><i class="${i.cls || ''}" style="width:${(Math.abs(i.value || 0) / mx * 100).toFixed(1)}%"></i></span><span class="vv ${i.vcls || ''}">${esc(i.label || money(i.value))}</span></div>`).join('')}</div>`;
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
/* The bullets are built by the engine (summary.lead, summary.insights, summary.year): each carries its claim, its
   registered figures and the drill target its evidence sits at. The page orders and displays them. */
const drillRef = d => d && d.ids && d.ids.length ? `drill:${d.level}:${d.ids.join(',')}${d.support && d.support.length ? '|' + d.support.join(',') : ''}` : 'kpi:net_income';
/* the page shows head + the short line; the full sentence (detail) opens above the evidence when the bullet is clicked */
const engBullet = (b, lead = false) => ({ t: b.tone, lead, ref: drillRef(b.drill), claim: b.claim, html: `<b>${esc(b.head)}</b> ${esc(clean(b.short || b.text))}`, detail: `<b>${esc(b.head)}</b> ${esc(clean(b.text))}` });

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
const SUM_TONE = { favourable: 'fav', unfavourable: 'unf', neutral: 'neu', outlook: 'ink' };
/* the written summary (readout.summary in the admitted review for this view) replaces the engine's bullets; the engine's stay as the fallback */
const wRef = d => !d || !d.ids || !d.ids.length ? 'kpi:net_income' : d.level === 'action' ? 'action:' + d.ids[0] : d.level === 'account' ? 'acct:' + d.ids[0] : drillRef(d);
const written = () => (readout().summary && (readout().summary.bullets || []).length >= 3) ? readout().summary : null;
function execBullets() {
  const W = written();
  if (W) return W.bullets.slice(0, 5).map((b, i) => ({ t: SUM_TONE[b.tone] || 'neu', lead: i === 0, rv: true, ref: wRef(b.drill), claim: b.claim || null, html: `<b>${esc(b.head)}</b> ${esc(clean(b.text))}`, detail: `<b>${esc(b.head)}</b> ${esc(clean(b.detail || b.text))}` }));
  const sm = L().summary, out = [engBullet(sm.lead, true)], y = sm.year ? engBullet(sm.year) : null, cap5 = y ? 4 : 5;
  const rv = (readout().conclusions || []).filter((c, i, all) => c.text && all.findIndex(x => x.text === c.text) === i).map(insightReviewed);
  rv.slice(0, cap5 - 1).forEach(x => out.push(x));
  sm.insights.map(b => engBullet(b)).slice(0, Math.max(0, cap5 - out.length)).forEach(x => out.push(x));
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
  const W = written(), wAsks = W ? (W.decisions || []).slice(0, 3).map(d => { const a = d.drill && d.drill.level === 'action' ? Lx.actions.find(x => x.id === d.drill.ids[0]) : null;
    return { ref: wRef(d.drill), q: clean(d.text), detail: clean(d.detail || d.text), m: `${d.owner}${a ? ' · by ' + a.date.target : ''}`, amt: d.amount && isNum(d.amount.value) ? d.amount.value : (a ? a.exposure.amount : null) }; }) : [];
  /* the page shows the short question; the full question opens above the evidence (engine fallback: the action's question, then its ask) */
  const asks = wAsks.length ? wAsks : dAsks.length ? dAsks : Lx.actions.slice(0, 3).map(a => ({ ref: 'action:' + a.id, q: clean(a.question || askText(a)), detail: askText(a), m: `${a.owner.role} · by ${a.date.target}`, amt: a.exposure.amount }));
  $('#view-summary').innerHTML = `
    <section class="sec" id="sum-exec"><div class="sh"><h2>Executive summary</h2><span class="sub">${esc(rangeLabel())} vs ${esc(b)} · click any point for the detail</span>${baseMark()}</div>${budgetNote()}
      <div class="exec"><ul class="bul" id="execList">${execBullets().map((x, i) => `<li class="${x.lead ? 'lead' : ''}${x.rv ? ' rv' : ''}" data-ref="${esc(x.ref)}" data-i="${i}"${x.claim ? ` data-claim="${esc(x.claim)}"` : ''}><span class="mk ${x.t}">${x.t === 'fav' ? '▲' : x.t === 'unf' ? '▼' : x.t === 'ink' ? '→' : '•'}</span><span class="tx">${x.html}</span><span class="go">›</span></li>`).join('')}</ul>
      <div class="side">
        <div class="ring" data-ref="line:ebm"><div class="rl">EBITDA margin</div><div class="rv">${esc(pct(ebm.actual))}</div><div class="rs ${tone(ebm.variance, 0.001)}">${esc(pts(ebm.variance))} <span class="mut">vs ${esc(b)}</span></div>${gauge(ebm.actual, ebm.comparator, cap(b))}</div>
        <div class="ring" data-ref="line:gpm"><div class="rl">Gross margin</div><div class="rv">${esc(pct(gpm.actual))}</div><div class="rs ${tone(gpm.variance, 0.001)}">${esc(pts(gpm.variance))} <span class="mut">vs ${esc(b)}</span></div>${gauge(gpm.actual, gpm.comparator, cap(b))}</div>
        ${fy ? `<div class="ring" data-ref="outlook:mechanical"><div class="rl">Full-year EBITDA (run-rate)</div><div class="rv">${esc(money(fy.mechanical.value))}</div><div class="rs mut">${isNum(fy.gap_vs_budget) ? `<span class="${tone(fy.gap_vs_budget)}">${esc(money(fy.gap_vs_budget, { sign: true }))}</span> vs full-year budget` : `<span class="${tone(fy.gap_vs_prior_year)}">${esc(money(fy.gap_vs_prior_year, { sign: true }))}</span> vs last year`}</div></div>` : ''}
      </div></div></section>
    <section class="sec"><div class="sh"><h2>P&amp;L at a glance</h2><span class="sub">in order of calculation · change vs ${esc(b)}</span></div>${flowStrip()}</section>
    <section class="sec"><div class="grid g-3-2">
      <div class="panel" id="sum-movers"><h3>What moved net income <small>by driver, vs ${esc(b)}</small></h3>${divBars(moversItems())}</div>
      <div class="panel" id="sum-asks"><h3>Decisions for management <small>${wAsks.length || dAsks.length ? 'from the AI review' : 'suggested owners'} · for discussion</small></h3>${asks.length ? `<ol class="dec" id="askList">${asks.map((a, i) => `<li data-ref="${esc(a.ref)}" data-i="${i}"><div><div class="q">${esc(a.q)}</div><div class="m">${esc(a.m)}</div></div>${isNum(a.amt) ? `<div class="amt">${esc(money(a.amt))}<small>at stake</small></div>` : ''}</li>`).join('')}</ol>` : '<div class="empty">No decision needed: nothing reached the management threshold with a structural signal.</div>'}</div>
    </div></section>`;
  bindRefs($('#view-summary'));
  /* a summary bullet opens its full sentence above the evidence it drills to */
  const details = execBullets().map(x => x.detail);
  $('#execList').addEventListener('click', e => { const li = e.target.closest('li[data-i]'); S.drawerIntro = li ? details[+li.dataset.i] : null; }, true);
  const al = $('#askList'); if (al) al.addEventListener('click', e => { const li = e.target.closest('li[data-i]'); const a = li && asks[+li.dataset.i]; S.drawerIntro = a ? `<b>${esc(a.detail || a.q)}</b> <span class="mut">${esc(a.m)}</span>` : null; }, true);
}

/* ---------- DRIVERS ---------- */
function bridgeSpec() {
  const Lx = L();
  if (S.bridgeMode === 'ni') { const ni = Lx.bridge.to_net_income; return { start: ni.start, end: ni.end, steps: ni.steps.map(s => ({ label: s.label, value: s.value, kind: s.kind, ref: 'step:' + s.id })) }; }
  return { start: { label: `${cap(basisWord())} Adjusted EBITDA`, value: Lx.bridge.start.value }, end: { label: 'Actual Adjusted EBITDA', value: Lx.bridge.end.value }, steps: Lx.bridge.steps.map(s => ({ label: s.label, value: s.value, kind: s.kind, ref: 'step:' + s.id })) };
}
function selectedDriverPanel() {
  const Lx = L(); let id = S.bridgeSel && S.bridgeSel.startsWith('step:') ? S.bridgeSel.slice(5) : null;
  if (!id || !ldrv(id)) id = (Lx.drivers.filter(d => isNum(d.variance)).sort((a, b) => Math.abs(b.variance) - Math.abs(a.variance))[0] || {}).id;
  const d = ldrv(id); if (!d) return '<div class="empty">No driver carries a variance in this view.</div>';
  const ser = sumSeries(d.accounts), lo = Math.max(0, AS - 12), lbl = PER.slice(lo, AS + 1).map(shortLbl), cmp = Lx.basis === 'budget' ? ser.budget : ser.py, lead = leadAccount(d), ps = lead ? SIG[lead.id].persistence_hint : null;
  return `<h3>${esc(d.label)} <small>${esc(SECTION_LABEL[d.section])}</small></h3>
    <div class="facts" style="grid-template-columns:1fr 1fr"><div><div class="l">vs ${esc(basisWord())}</div><div class="v ${tone(d.variance)}">${esc(money(d.variance, { sign: true }))}</div></div><div><div class="l">${esc(shareLbl(d))}</div><div class="v">${esc(pct(d.share_of_abs_variance, { dec: 0 }))}</div></div></div>
    <div style="margin:10px 0 4px">${tag(tone(d.variance))}${persistTag(ps)}</div>
    <p class="small" style="margin:6px 0 12px">${esc(driverReason(d))}</p>
    ${hierOf(d.id) ? ddBlock('By sub-group', hierSummary(d.id), hierTable(d.id, { head: false })) : ''}
    ${ddBlock('By account', acctSummary(d.id), reconTable(d.id, { top: 5 }))}
    ${(() => { const t = deptTable(d.id, { head: false }); return t ? ddBlock('By department', deptSummary(d.id), t) : ''; })()}
    <div style="margin-top:12px">${lineChart({ labels: lbl, series: [{ name: 'Actual', vals: ser.actual.slice(lo, AS + 1), cls: 'l-act' }, { name: cap(basisWord()), vals: cmp.slice(lo, AS + 1), cls: 'l-cmp' }], height: 150, W: 420, cur: AS - lo })}</div>
    ${legend([['background:var(--ink)', 'Actual'], ['background:var(--budget)', cap(basisWord())]])}
    <button class="btnl" data-ref="driver:${esc(d.id)}">Open full detail ›</button>`;
}
/* ---------- drillable commentary (selection and phrasing of engine fields only; no new economics) ---------- */
/* an inline link that opens a drawer; bindRefs makes it clickable inside a bullet that drills elsewhere */
const lnk = (ref, text) => `<span class="lnk" data-ref="${esc(ref)}">${esc(text)}</span>`;
const dirWord = (v, up = 'up', down = 'down') => !isNum(v) ? '' : v >= 0 ? up : down;
/* "up $455k (19.5%) vs prior year, favourable": direction words carry the sign, so the amount reads as a magnitude */
const moveTxt = (v, vp, b) => !isNum(v) ? 'no comparison' : Math.abs(v) < 0.5 ? `in line with ${b}` : `${dirWord(v)} ${money(Math.abs(v))}${isNum(vp) && Math.abs(vp) < 10 ? ` (${pct(Math.abs(vp))})` : ''} vs ${b}, ${toneWord(tone(v, 0.5)).toLowerCase()}`;
/* a driver with the account that carries most of it: the deepest level the payload holds below L4 > L5 > L6 */
function driverWithLead(id, value) {
  /* the lead is the largest account moving the same way as the driver (a large offsetting account would mislead) */
  const d = ldrv(id), same = d ? d.accounts.map(lacct).filter(a => a && isNum(a.movement) && Math.abs(a.movement) >= 0.5 && Math.sign(a.movement) === Math.sign(value)).sort((a, b) => Math.abs(b.movement) - Math.abs(a.movement)) : [], lead = same[0];
  let s = `${lnk('driver:' + id, d ? d.label : id)} ${esc(money(value, { sign: true }))}`;
  if (lead && d.accounts.length > 1) s += ` <span class="mut">(largest ${lnk('acct:' + lead.id, acctName(lead.id))} ${esc(money(lead.movement, { sign: true }))})</span>`;
  return s;
}
const cmtList = (id, items) => `<ul class="cmt" id="${id}">${items.filter(Boolean).slice(0, 5).map(x => `<li class="${x.t || 'neu'}" data-ref="${esc(x.ref)}"><span class="mk ${x.t || 'neu'}">${x.t === 'fav' ? '▲' : x.t === 'unf' ? '▼' : x.t === 'ink' ? '→' : '•'}</span><span class="tx">${x.html}</span><span class="go">›</span></li>`).join('')}</ul>`;
/* the admitted AI review, shown inside the summary panel it belongs to (Drivers: what is lasting; Outlook: forecast assumptions) */
/* What this means, on every view: Drivers shows the admitted review's structural reading for the view when there is one,
   otherwise the engine's own pattern readings for that window and comparison; the Outlook projection is one fiscal-year
   figure whatever the view, so it shows the same reviewed assumptions on every view (the opening view's review first,
   never the selected view's), which is why the Window and Compare buttons are hidden on the Outlook tab */
const meaningDrivers = () => { const rv = readout().structural_conclusions || []; if (rv.length) return rv;
  return (L().patterns || []).filter(x => x.fired && x.reading).slice(0, 3).map(x => ({ text: x.reading })); };
const meaningOutlook = () => { const ids = [META.primary_lens.id, ...Object.keys(DIAGS)], d = ids.map(k => DIAGS[k]).find(x => x && ((x.readout || {}).forecast_assumptions || []).length);
  return d ? d.readout.forecast_assumptions : [{ text: 'A straight-line projection of the run-rate rule picked: no seasonality, pipeline or management view is included, and nothing is added to the forecast until an owner accepts it.' }]; };
const aiReview = (id, title, items, tagHtml = '') => (items || []).length ? `<div class="aird" id="${id}"><div class="airh"><span>${esc(title)}</span>${tagHtml}</div><ul class="say">${items.map(s => `<li>${esc(clean(s.text))}</li>`).join('')}</ul></div>` : '';
function bridgeCommentary() {
  const Lx = L(), b = basisWord(), out = [];
  const steps = (S.bridgeMode === 'ni' ? Lx.bridge.to_net_income.steps : Lx.bridge.steps).filter(s => isNum(s.value) && Math.abs(s.value) >= 0.5 && ldrv(s.id));
  const unf = steps.filter(s => s.value < 0).sort((x, y) => x.value - y.value).slice(0, 2), fav = steps.filter(s => s.value > 0).sort((x, y) => y.value - x.value).slice(0, 2);
  const listOf = arr => arr.map(s => driverWithLead(s.id, s.value)).join('; ');
  if (S.bridgeMode === 'ni') {
    const ni = lline('ni'), eb = lline('ebitda'), below = steps.reduce((t, s) => t + s.value, 0);
    out.push({ t: tone(ni.variance), ref: 'kpi:net_income', html: `<b>Net income ${esc(money(ni.actual))}</b> against ${esc(money(ni.comparator))} ${esc(b)}: ${esc(moveTxt(ni.variance, ni.variance_pct, b))}.` });
    out.push({ t: tone(eb.variance), ref: 'kpi:ebitda', html: `<b>Operations:</b> ${lnk('kpi:ebitda', 'Adjusted EBITDA')} moved ${esc(money(eb.variance, { sign: true }))}; items below EBITDA moved net income by ${esc(money(below, { sign: true }))}${Math.abs(eb.variance) >= Math.abs(below) ? ', so operations carry the result' : ', so the result is carried below the line'}.` });
    if (unf.length) out.push({ t: 'unf', ref: 'driver:' + unf[0].id, html: `<b>Below the line, against:</b> ${listOf(unf)}.` });
    if (fav.length) out.push({ t: 'fav', ref: 'driver:' + fav[0].id, html: `<b>Below the line, in favour:</b> ${listOf(fav)}.` });
    if (!steps.length) out.push({ t: 'neu', ref: 'kpi:net_income', html: '<b>Nothing below EBITDA moved</b> in this view; net income follows Adjusted EBITDA.' });
    return cmtList('drv-commentary-list', out);
  }
  const eb = lline('ebitda'), ebm = lline('ebm'), rev = lline('rev'), cos = lline('cos'), opx = lline('opex');
  out.push({ t: tone(eb.variance), ref: 'kpi:ebitda', html: `<b>Adjusted EBITDA ${esc(money(eb.actual))}</b> against ${esc(money(eb.comparator))} ${esc(b)}: ${esc(moveTxt(eb.variance, eb.variance_pct, b))}${ebm && isNum(ebm.actual) ? `; ${lnk('line:ebm', 'margin')} ${esc(pct(ebm.actual))}, ${esc(pts(ebm.variance))}` : ''}.` });
  if (unf.length) out.push({ t: 'unf', ref: 'driver:' + unf[0].id, html: `<b>Largest unfavourable:</b> ${listOf(unf)}.` });
  if (fav.length) out.push({ t: 'fav', ref: 'driver:' + fav[0].id, html: `<b>Largest favourable:</b> ${listOf(fav)}.` });
  const parts = [[rev, 'rev', 'revenue'], [cos, 'cos', 'cost of sales'], [opx, 'opex', 'operating expenses']].filter(([ln]) => ln && isNum(ln.variance)).map(([ln, sec, w]) => `${lnk('drill:section:' + sec, w)} ${esc(money(ln.variance, { sign: true }))}`);
  if (parts.length) out.push({ t: 'ink', ref: 'drill:section:ebitda', html: `<b>By line:</b> ${parts.join(', ')}.` });
  const top3 = steps.slice().sort((x, y) => Math.abs(y.value) - Math.abs(x.value)).slice(0, 3).map(s => ldrv(s.id)), share = top3.reduce((t, d) => t + (d.share_of_abs_variance || 0), 0);
  const hints = Lx.window === 'MTD' ? top3.map(d => { const la = leadAccount(d), h = la ? SIG[la.id].persistence_hint : null; return h && h !== 'coverage' && PERSIST[h] ? `${lnk('driver:' + d.id, d.label)} ${PERSIST[h][0].toLowerCase()}` : null; }).filter(Boolean) : [];
  if (top3.length) out.push({ t: 'neu', ref: top3.length > 1 ? 'drill:driver:' + top3.map(d => d.id).join(',') : 'driver:' + top3[0].id, html: `<b>Concentrated:</b> the top ${top3.length === 1 ? 'driver carries' : top3.length + ' drivers carry'} ${esc(pct(share, { dec: 0 }))} of the Adjusted EBITDA movement${hints.length ? `; read as ${hints.join(', ')}` : ''}.` });
  return cmtList('drv-commentary-list', out);
}
/* the latest month against each account's usual range, for the selected driver (or every account) */
function runrateHtml(did) {
  const d = did && did !== 'all' ? ldrv(did) : null, pool = d ? d.accounts.map(lacct).filter(Boolean) : L().accounts;
  const ranged = pool.filter(a => isNum(a.variance) && Math.abs(a.variance) >= MON && SIG[a.id].runrate.eligible).sort((a, b) => Math.abs(b.variance) - Math.abs(a.variance)).slice(0, 6);
  return `<h3>${esc(MONTH)} against each account's usual range <small>${d ? esc(d.label) + ' · ' : ''}accounts above ${esc(money(MON))}</small></h3>${ranged.length ? `<div class="rb">${ranged.map(a => rangeBar(a.id)).join('')}</div>${rangeLegend()}` : `<div class="empty">No account${d ? ' in ' + esc(d.label) : ''} above the monitoring threshold has a usable run-rate.</div>`}`;
}
function dimRows(driverId, { all = false } = {}) {
  const m = new Map(); L().facts.rows.filter(r => driverId === 'all' || (ACC_BY[r[0]] && ACC_BY[r[0]].driver_ref === driverId)).forEach(r => {
    /* the engine's variance, or for a one-sided row its movement (display amounts back to profit orientation) */
    const o = m.get(r[1]) || { name: r[1], v: 0 }, ds = (ACC_BY[r[0]] || {}).display_sign || 1;
    const mv = isNum(r[4]) ? r[4] : (isNum(r[2]) || isNum(r[3])) ? ((r[2] || 0) - (r[3] || 0)) * ds : null;
    if (isNum(mv)) o.v += mv; m.set(r[1], o); });
  const rows = [...m.values()].sort((a, b) => Math.abs(b.v) - Math.abs(a.v));
  return all ? rows : rows.filter(r => Math.abs(r.v) >= 0.5);
}
const dimZero = id => dimRows(id, { all: true }).length - dimRows(id).length;
function dimBars(id, ref) {
  const sp = id === 'all' ? L().by_subsidiary : (recOf(id) || {}).by_subsidiary;
  if (!sp || !sp.rows.length) return '<div class="empty">Nothing moved in this view.</div>' + (sp ? zeroNote(sp.zero_count || 0, 'subsidiary') : '');
  const rows = sp.rows.concat(sp.other ? [{ name: `${sp.other.count} other subsidiar${sp.other.count > 1 ? 'ies' : 'y'}`, movement: sp.other.movement, actual: sp.other.actual }] : []);
  const what = id === 'all' ? 'contribution to net income' : 'actual';
  if (sp.comparable) return divBars(rows.map(r => ({ name: r.name, value: r.movement, ref, floor: 0.5 }))) + zeroNote(sp.zero_count || 0, 'subsidiary');
  return `<p class="xs mut" style="margin:0 0 8px">The ${esc(basisWord())} is not held by subsidiary${id === 'all' ? ' for every account' : ' for this driver'}, so each subsidiary's ${esc(what)} is shown instead of a variance; the variance (${esc(money(id === 'all' ? lline('ni').variance : (ldrv(id) || {}).movement, { sign: true }))}) is reported for the ${id === 'all' ? 'total' : 'driver'}.</p>`
    + hBars(rows.map(r => ({ name: r.name, value: r.actual, ref, label: money(r.actual) })));
}
function renderDrivers() {
  const Lx = L(), showSub = Lx.basis !== 'budget';       /* the budget is not held by subsidiary: no By subsidiary panel against budget */
  if (S.bridgeMode !== 'ni') S.bridgeMode = 'reported';
  const drivers = Lx.drivers.filter(d => isNum(d.variance)).sort((a, b) => Math.abs(b.variance) - Math.abs(a.variance));
  const sel = S.bridgeSel && S.bridgeSel.startsWith('step:') && ldrv(S.bridgeSel.slice(5)) ? S.bridgeSel.slice(5) : null;
  S.dimDriver = sel || 'all';                              /* no bar selected: every account */
  const wf = () => waterfall({ id: 'wf-drv', ...bridgeSpec(), height: 320, selected: S.bridgeSel, tilt: true });
  /* layout: bridge | commentary; usual range | selected category; By subsidiary | selected category (continued) */
  $('#view-drivers').innerHTML = `
    <section class="sec"><div class="sh"><h2>${S.bridgeMode === 'ni' ? 'From EBITDA to net income' : 'Adjusted EBITDA bridge'}</h2>
      <span class="tog" id="bridgeMode"><button data-m="reported" class="${S.bridgeMode === 'reported' ? 'on' : ''}">By driver</button><button data-m="ni" class="${S.bridgeMode === 'ni' ? 'on' : ''}">To net income</button></span></div>
      ${budgetNote()}<div class="drv-layout${showSub ? '' : ' nosub'}">
          <div class="panel a-wf"><h3>${esc(rangeLabel())} vs ${esc(basisWord())} <small>click a bar to inspect</small></h3><div id="wfHost">${wf()}</div>
            ${legend([['background:var(--dark);height:10px;width:10px', 'Start / end'], ['background:var(--fav);height:10px;width:10px', 'Favourable'], ['background:var(--adv);height:10px;width:10px', 'Unfavourable']])}</div>
          <div class="panel a-cmt" id="drv-commentary">${bridgeCommentary()}${aiReview('drv-reading', 'What this means', meaningDrivers())}</div>
          <div class="panel a-rr" id="drv-runrate">${runrateHtml(S.dimDriver)}</div>
          ${showSub ? `<div class="panel a-sub" id="drv-sub"><h3>By subsidiary <select id="dimDriver" class="ctl"><option value="all" ${S.dimDriver === 'all' ? 'selected' : ''}>All accounts</option>${drivers.map(x => `<option value="${esc(x.id)}" ${S.dimDriver === x.id ? 'selected' : ''}>${esc(x.label)}</option>`).join('')}</select></h3><div id="dimHost"></div></div>` : ''}
          <div class="panel a-sel" id="drvSel">${selectedDriverPanel()}</div>
      </div></section>`;
  const dim = () => {
    const h = $('#dimHost'); if (h) { h.innerHTML = dimBars(S.dimDriver, S.dimDriver === 'all' ? 'kpi:net_income' : 'driver:' + S.dimDriver); bindRefs(h); }
    $('#drv-runrate').innerHTML = runrateHtml(S.dimDriver); bindRefs($('#drv-runrate'));
    const sl = $('#dimDriver'); if (sl && [...sl.options].some(o => o.value === S.dimDriver)) sl.value = S.dimDriver; };
  const redraw = () => { $('#wfHost').innerHTML = wf(); $('#drvSel').innerHTML = selectedDriverPanel(); bindRefs($('#drvSel')); };
  $('#bridgeMode').onclick = e => { const b = e.target.closest('button'); if (!b || b.disabled) return; S.bridgeMode = b.dataset.m; S.bridgeSel = null; renderDrivers(); };
  const sl = $('#dimDriver');
  if (sl) sl.onchange = e => { S.dimDriver = e.target.value; S.bridgeSel = S.dimDriver === 'all' ? null : 'step:' + S.dimDriver; if (S.bridgeMode !== 'reported') { S.bridgeMode = 'reported'; renderDrivers(); return; } redraw(); dim(); };
  dim(); bindRefs($('#view-drivers')); barKey($('#wfHost'));
  $('#wfHost').addEventListener('click', e => { const g = e.target.closest('.bar'); if (!g || !g.dataset.ref) return; if (g.dataset.ref.startsWith('acct:')) { openDrawer(g.dataset.ref); return; }
    S.bridgeSel = g.dataset.ref; redraw();
    const did = g.dataset.ref.slice(g.dataset.ref.indexOf(':') + 1); if (ldrv(did)) { S.dimDriver = did; dim(); } });
}

/* ---------- OUTLOOK ---------- */
/* the run-rate rule picked on the Outlook tab (the headline rule until one is picked) */
const ruleOf = l => l.mechanical.sensitivity.find(x => x.rule === (S.rule || l.mechanical.rule)) || l.mechanical.sensitivity[0];
function rrInfoHtml(e, r) {
  const used = r.months_used || [], span = used.length > 1 ? `${shortLbl(PER.find(p => p.label === used[0]) || { label: used[0] })} to ${shortLbl(PER.find(p => p.label === used[used.length - 1]) || { label: used[used.length - 1] })}` : used.length ? shortLbl(PER.find(p => p.label === used[0]) || { label: used[0] }) : '';
  return `<div class="rrdef" id="rrDef" ${S.rrInfo ? '' : 'hidden'}><b>What is run-rate?</b>
    <p>Run-rate is the monthly amount assumed for each of the ${e.remaining_months} month${e.remaining_months === 1 ? '' : 's'} of the fiscal year still to close. Full year = year-to-date actual + the remaining months at run-rate.</p>
    <p><b>Rule in use: ${esc(r.label)}.</b> ${esc(cap(r.how || ''))}${span ? ` (${esc(span)})` : ''}: ${r.rule === 'trend_extrapolation' ? `${esc(money(r.run_rate))} a month on average, rising or falling along the line` : `${esc(money(r.run_rate))} a month`}. ${esc(money(e.ytd.actual))} year to date + ${esc(money(r.remaining_value))} for the remaining months = ${esc(money(r.value))}.</p>
    <p class="mut">A straight-line projection, not a forecast: no seasonality, pipeline or management view is included. The Summary tab always uses the trailing three-month average.${(OUT.one_offs_excluded || []).length ? ` ${OUT.one_offs_excluded.length} flagged one-off month${OUT.one_offs_excluded.length === 1 ? ' is' : 's are'} replaced by the account's usual level before averaging (listed in the run-rate detail).` : ''}</p></div>`;
}
const GAP_CATS = [['ebitda', 'Adjusted EBITDA (all operating lines)'], ['rev', 'Revenue'], ['cos', 'Cost of sales'], ['opex', 'Operating expenses'], ['below', 'Below the line'], ['ni', 'Everything down to net income']];
function gapPanel(r) {
  const gv = OUT.gap_view;
  const head = sel => `<h3>If current gaps continue ${sel}</h3>`;
  if (!gv || !gv.available || !gv.rules[r.rule]) return head('') + `<div class="empty">${esc((gv && gv.reason) || 'Not available for this rule.')}</div>`;
  const rec = gv.rules[r.rule], cat = GAP_CATS.some(c => c[0] === S.gapCat) ? S.gapCat : 'ebitda', catLbl = GAP_CATS.find(c => c[0] === cat)[1];
  const all = rec.drivers.filter(x => cat === 'ni' || x.section === cat || x.category === cat), ds = all.filter(x => Math.abs(x.remaining_effect) >= 0.5);
  const top = ds.slice(0, 10), rest = ds.slice(10), restV = rest.reduce((t, x) => t + x.remaining_effect, 0);
  const items = top.map(x => ({ name: x.label, value: x.remaining_effect, ref: 'driver:' + x.driver, floor: 0.5 })).concat(rest.length ? [{ name: `${rest.length} other drivers`, value: restV, ref: 'outlook:mechanical', floor: 0.5 }] : []);
  const tot = rec.totals[cat], step = cat === 'ebitda' ? ' = the full-year bridge step "Remaining months vs budget"' : '';
  const pats = top.filter(x => x.persistence_hint && x.persistence_hint !== 'undetermined' && PERSIST[x.persistence_hint]);
  return head(`<select id="gapCat" class="ctl" aria-label="Category">${GAP_CATS.map(([k, l]) => `<option value="${k}" ${k === cat ? 'selected' : ''}>${esc(l)}</option>`).join('')}</select>`)
    + `<p class="xs mut" style="margin:0 0 8px">Each driver's remaining ${gv.remaining_months} month${gv.remaining_months === 1 ? '' : 's'} at the ${esc(lc(r.label))}, against its budget for those months.</p>`
    + (items.length ? divBars(items) : '<div class="empty">No driver in this category moves against its remaining budget.</div>')
    + zeroNote(all.length - ds.length, 'driver')
    + `<div class="gtot"><span>Total · ${esc(catLbl)}${esc(step)}</span><b class="${tone(tot)}">${esc(money(tot, { sign: true }))}</b></div>`
    + (pats.length ? `<div class="chips" style="margin-top:10px">${pats.map(x => `<span class="cp">${esc(x.label)}: ${esc(PERSIST[x.persistence_hint][0])}</span>`).join('')}</div>` : '')
    + `<p class="xs mut" style="margin-top:10px">Suggestions only: nothing enters a forecast until a named owner accepts it.</p>`;
}
/* Where the year lands, in 3-5 drillable bullets for the run-rate rule picked: the landing, what is banked, what runs
   ahead of and behind the remaining budget at that rule, and how much the rule choice matters. Engine fields only. */
function outlookCommentary(e, r, hasFY) {
  const out = [], rl = lc(r.label), sens = e.mechanical.sensitivity.filter(x => isNum(x.value));
  const land = hasFY && isNum(r.gap_vs_budget) ? `${esc(money(Math.abs(r.gap_vs_budget)))} ${r.gap_vs_budget >= 0 ? 'ahead of' : 'short of'} the ${esc(money(e.fy_budget))} full-year budget` : '';
  const ly = isNum(r.gap_vs_prior_year) ? `${esc(money(Math.abs(r.gap_vs_prior_year)))} ${r.gap_vs_prior_year >= 0 ? 'above' : 'below'} last year's ${esc(money(e.prior_year_full_year))}` : '';
  out.push({ t: hasFY && isNum(r.gap_vs_budget) ? tone(r.gap_vs_budget) : tone(r.gap_vs_prior_year), ref: 'outlook:mechanical', html: `<b>Full year lands at ${esc(money(r.value))}</b> on the ${esc(rl)}: ${[land, ly].filter(Boolean).join(', and ') || 'no comparison loaded'}.` });
  out.push({ t: tone(e.ytd.variance), ref: 'outlook:ytd', html: `<b>Banked so far:</b> ${esc(money(e.ytd.actual))} in ${e.periods_realized} of ${e.periods_total} months${isNum(e.ytd.variance) ? ', ' + esc(moveTxt(e.ytd.variance, null, 'budget')) : ''}; the remaining ${e.remaining_months} month${e.remaining_months === 1 ? '' : 's'} add ${esc(money(r.remaining_value))} at ${esc(money(r.run_rate))} a month${r.rule === 'trend_extrapolation' ? ' on average' : ''}.` });
  const gv = OUT.gap_view, rec = gv && gv.available && gv.rules[r.rule] ? gv.rules[r.rule] : null;
  const named = arr => arr.map(x => `${lnk('driver:' + x.driver, x.label)} ${esc(money(x.remaining_effect, { sign: true }))}`).join(', ');
  if (rec) {
    const ops = rec.drivers.filter(x => ['rev', 'cos', 'opex'].includes(x.section) && isNum(x.remaining_effect) && Math.abs(x.remaining_effect) >= MON);
    const good = ops.filter(x => x.remaining_effect > 0).sort((a, b) => b.remaining_effect - a.remaining_effect).slice(0, 3), bad = ops.filter(x => x.remaining_effect < 0).sort((a, b) => a.remaining_effect - b.remaining_effect).slice(0, 3);
    if (good.length) out.push({ t: 'fav', ref: 'driver:' + good[0].driver, html: `<b>Goes well if the pace holds:</b> ${named(good)} against the remaining budget.` });
    if (bad.length) out.push({ t: 'unf', ref: 'driver:' + bad[0].driver, html: `<b>Falls short if the pace holds:</b> ${named(bad)} against the remaining budget.` });
  } else {
    /* no remaining budget: the year-to-date drivers say what has gone well and what has not */
    const yl = P.lenses.YTD_budget && P.lenses.YTD_budget.available ? P.lenses.YTD_budget : P.lenses.YTD_py, yd = yl && yl.available ? yl.drivers.filter(d => isNum(d.movement) && Math.abs(d.movement) >= 0.5 && ['rev', 'cos', 'opex'].includes(d.section)) : [];
    const good = yd.filter(d => d.movement > 0).sort((a, b) => b.movement - a.movement).slice(0, 2), bad = yd.filter(d => d.movement < 0).sort((a, b) => a.movement - b.movement).slice(0, 2), yn = arr => arr.map(d => `${lnk('driver:' + d.id, d.label)} ${esc(money(d.movement, { sign: true }))}`).join(', ');
    if (good.length) out.push({ t: 'fav', ref: 'driver:' + good[0].id, html: `<b>Going well year to date:</b> ${yn(good)} vs ${esc(yl.basis_label)}.` });
    if (bad.length) out.push({ t: 'unf', ref: 'driver:' + bad[0].id, html: `<b>Not going well year to date:</b> ${yn(bad)} vs ${esc(yl.basis_label)}.` });
  }
  const pv = (OUT.persistence_view || []).filter(x => isNum(x.remaining_effect_if_persists) && Math.abs(x.remaining_effect_if_persists) >= 0.5);
  const lo = sens.length ? sens.reduce((a, b) => b.value < a.value ? b : a) : null, hi = sens.length ? sens.reduce((a, b) => b.value > a.value ? b : a) : null;
  const rulePart = lo && hi && lo !== hi ? `the rules range from ${esc(money(lo.value))} (${esc(lc(lo.label))}) to ${esc(money(hi.value))} (${esc(lc(hi.label))}), a ${esc(pct(e.mechanical.sensitivity_spread_pct))} spread` : '';
  const pvPart = pv.length ? `recurring gaps in ${pv.slice(0, 2).map(x => lnk('driver:' + x.driver, x.label)).join(' and ')} would carry ${esc(money(OUT.persistence_totals.proposed_carry, { sign: true }))} more if they persist` : '';
  if (rulePart || pvPart) out.push({ t: 'neu', ref: 'outlook:mechanical', html: `<b>Watch:</b> ${[rulePart, pvPart].filter(Boolean).join('; ')}.` });
  return cmtList('out-commentary-list', out);
}
function renderOutlook() {
  const o = OUT;
  if (!o || o.state !== 'calculated') { $('#view-outlook').innerHTML = `<div class="empty">${esc((o && o.reason) || 'Outlook not calculated.')}</div>`; return; }
  const e = o.lines.ebitda, r = ruleOf(e), hasFY = isNum(e.fy_budget), fyIdx = PER.map((p, i) => [p, i]).filter(([p]) => p.year === o.fiscal_year).map(([, i]) => i), first = fyIdx[0], s = SS.ebitda;
  const months = Array.from({ length: o.periods_per_year }, (_, k) => first + k), lbl = months.map(i => PER[i] ? shortLbl(PER[i]) : new Date(o.fiscal_year, i - first, 1).toLocaleString('en-US', { month: 'short' }) + " '" + String(o.fiscal_year).slice(2));
  const act = months.map(i => i <= AS ? s.actual[i] : null), bud = months.map(i => i <= AS ? s.budget[i] : null), py = months.map(i => i <= AS ? s.py[i] : (isNum(s.actual[i - 12]) ? s.actual[i - 12] : null));
  const proj = months.map(i => i === AS ? s.actual[i] : (i > AS ? (r.path || [])[i - AS - 1] ?? null : null));
  const sens = e.mechanical.sensitivity, tile = (ref, l, v, sub, dark) => `<button class="tile${dark ? ' dark' : ''}" data-ref="${esc(ref)}"><div class="kl">${esc(l)}</div><div class="kv">${esc(v)}</div><div class="ks">${sub}</div></button>`;
  const steps = hasFY ? [{ label: 'Year-to-date variance', value: e.ytd.variance, ref: 'outlook:ytd' }, { label: `Remaining ${e.remaining_months} months vs budget`, value: r.remaining_effect, ref: 'outlook:mechanical' }]
    : [{ label: `Remaining ${e.remaining_months} months at run-rate`, value: r.remaining_value, kind: 'cov', ref: 'outlook:mechanical' }];
  const pv = o.persistence_view || [];
  $('#view-outlook').innerHTML = `
    <section class="sec"><div class="sh"><h2>Where the year lands</h2><span class="sub">fiscal ${esc(o.fiscal_year)} · ${e.periods_realized} of ${e.periods_total} months closed · ${esc(lc(r.label))}, not a forecast</span>
      <span class="rrctl"><label class="xs mut" for="ruleSel">Run-rate rule</label> <select id="ruleSel" class="ctl">${sens.map(x => `<option value="${esc(x.rule)}" ${x.rule === r.rule ? 'selected' : ''}>${esc(x.label)}</option>`).join('')}</select>
      <button class="info" id="rrInfo" aria-expanded="${S.rrInfo}" aria-controls="rrDef" title="What is run-rate?">i</button></span></div>
      ${rrInfoHtml(e, r)}
      ${budgetNote(true)}<div class="out-top">
      <div class="panel out-cmt" id="out-commentary">${outlookCommentary(e, r, hasFY)}${aiReview('out-reading', 'What this means', meaningOutlook(), '<span class="tag amb">for discussion</span>')}</div>
      <div class="kpi-col">
        ${tile('outlook:mechanical', 'Full-year EBITDA (run-rate)', money(r.value), `${esc(money(r.run_rate))} a month${r.rule === 'trend_extrapolation' ? ' on average' : ''} for ${e.remaining_months} months`, true)}
        ${tile('outlook:ytd', 'EBITDA year to date', money(e.ytd.actual), `<span class="${tone(e.ytd.variance)}">${esc(money(e.ytd.variance, { sign: true }))}</span> vs budget`)}
        ${tile('outlook:mechanical', 'Full-year budget', hasFY ? money(e.fy_budget) : '—', hasFY ? `<span class="${tone(r.gap_vs_budget)}">${esc(money(r.gap_vs_budget, { sign: true }))}</span> gap on run-rate` : 'not loaded')}
        ${tile('outlook:mechanical', 'Last year full year', money(e.prior_year_full_year), `<span class="${tone(r.gap_vs_prior_year)}">${esc(money(r.gap_vs_prior_year, { sign: true }))}</span> ${isNum(r.gap_vs_prior_year) && r.gap_vs_prior_year < 0 ? 'decline' : 'growth'} on run-rate`)}
      </div></div></section>
    <section class="sec"><div class="grid g2">
      <div class="panel" id="out-trend"><h3>Monthly Adjusted EBITDA <small>actual, budget, last year and run-rate</small></h3>${lineChart({ labels: lbl, series: [{ name: 'Actual', vals: act, cls: 'l-act' }, { name: 'Run-rate', vals: proj, cls: 'l-proj' }, { name: 'Budget', vals: bud, cls: 'l-cmp' }, { name: 'Last year', vals: py, cls: 'l-py' }], height: 240, cur: AS - first })}
        ${legend([['background:var(--ink)', 'Actual'], ['background:repeating-linear-gradient(90deg,var(--ink) 0 3px,transparent 3px 6px)', 'Run-rate (remaining months)'], ['background:var(--budget)', 'Budget'], ['background:var(--ly)', 'Last year']])}</div>
      <div class="panel" id="out-scenarios"><h3>How much the rule matters <small>full-year EBITDA by run-rate rule</small></h3>${hBars(sens.map(x => ({ name: x.label, value: x.value, cls: x.rule === r.rule ? 'hi' : '' })))}
        <p class="xs mut" style="margin-top:12px">Spread across rules: ${esc(pct(e.mechanical.sensitivity_spread_pct))}. The highlighted rule drives every figure on this tab; click a rule to switch.</p></div>
    </div></section>
    <section class="sec"><div class="grid g2">
      <div class="panel" id="wf-fy"><h3>Full-year bridge <small>Adjusted EBITDA</small></h3>${waterfall({ id: 'wf-fy-chart', start: hasFY ? { label: 'Full-year budget', value: e.fy_budget } : { label: 'Year to date', value: e.ytd.actual }, steps, end: { label: 'Full-year run-rate', value: r.value }, height: 250, W: 560 })}</div>
      <div class="panel" id="out-treatment">${gapPanel(r)}</div>
    </div></section>`;
  bindRefs($('#view-outlook')); barKey($('#wf-fy'));
  const pick = rule => { S.rule = rule; renderOutlook(); };
  $('#ruleSel').onchange = ev => pick(ev.target.value);
  const bindGap = () => { const g = $('#gapCat'); if (g) g.onchange = ev => { S.gapCat = ev.target.value; $('#out-treatment').innerHTML = gapPanel(r); bindRefs($('#out-treatment')); bindGap(); }; };
  bindGap();
  document.querySelectorAll('#out-scenarios .hbr').forEach((el, k) => { el.dataset.rule = sens[k].rule; el.classList.add('pick'); el.setAttribute('aria-pressed', sens[k].rule === r.rule); el.onclick = () => pick(sens[k].rule); keyActivatable(el); });
  $('#rrInfo').onclick = () => { S.rrInfo = !S.rrInfo; $('#rrDef').hidden = !S.rrInfo; $('#rrInfo').setAttribute('aria-expanded', S.rrInfo); };
}

/* ---------- DRILL TABLES (engine reconciliation blocks; the page only lays them out) ---------- */
const recOf = did => (L().reconciliation || {})[did] || null;
const zeroNote = (n, what = 'account') => n > 0 ? `<p class="xs mut zn">${n} ${what}${n > 1 ? 's' : ''} with no movement in this view ${n > 1 ? 'are' : 'is'} not shown.</p>` : '';
const mvWord = () => L().basis === 'budget' ? 'variance' : 'movement';
let TGL = 0;
/* a collapsible block (closed by default): the heading carries the count and the total */
const ddBlock = (title, meta, body) => `<details class="dd"><summary><span class="ddt">${esc(title)}</span><span class="ddm">${meta}</span></summary><div class="ddb">${body}</div></details>`;
function acctSummary(did) { const rc = recOf(did); if (!rc) return ''; const n = rc.items.length + (rc.other ? rc.other.count : 0); return `${n} account${n === 1 ? '' : 's'} · <b class="${tone(rc.total, 0.5)}">${esc(money(rc.total, { sign: true }))}</b>`; }
function deptSummary(did) { const dep = (recOf(did) || {}).by_department; if (!dep) return ''; const n = dep.rows.length + (dep.other ? dep.other.count : 0), k = dep.comparable ? 'movement' : 'actual';
  return `${n} department${n === 1 ? '' : 's'} · ${dep.comparable ? `<b class="${tone(dep.total.movement, 0.5)}">${esc(money(dep.total.movement, { sign: true }))}</b>` : `actual ${esc(money(dep.total[k]))}`}`; }
/* an "N other …" row that expands to the members it groups; cents-level members are counted, not listed */
function othRows(label, total, members, { sign = true, sub = false } = {}) {
  const id = 'g' + (++TGL), big = members.filter(m => !isNum(m.value) || Math.abs(m.value) >= 0.5), tiny = members.length - big.length;
  if (!big.length) return `<tr class="oth${sub ? ' sub' : ''}"><td>${esc(label)}</td><td class="num">${esc(money(total, { sign }))}</td></tr>`;
  return `<tr class="oth tgl${sub ? ' sub' : ''}" data-tgl="${id}" tabindex="0" role="button" aria-expanded="false"><td><span class="car">▸</span>${esc(label)}</td><td class="num">${esc(money(total, { sign }))}</td></tr>`
    + big.map(m => `<tr class="sub hid xm" data-grp="${id}" ${m.ref ? `data-ref="${esc(m.ref)}"` : ''}><td>${esc(m.name)}${m.chip || ''}</td><td class="num ${sign ? tone(m.value, 0.5) : ''}">${esc(money(m.value, { sign }))}</td></tr>`).join('')
    + (tiny ? `<tr class="sub hid xm" data-grp="${id}"><td class="mut">${tiny} more with moves under $1</td><td class="num"></td></tr>` : '');
}
/* levels below L4: L5 > L6 > account, each level footing to the one above (payload hierarchy; the page lays it out) */
const hierOf = did => (L().hierarchy || {})[did] || null;
function hierSummary(did) { const h = hierOf(did); if (!h) return ''; const n5 = h.nodes.length, n6 = h.nodes.reduce((t, n) => t + n.children.length, 0);
  return `${n5} L5 group${n5 === 1 ? '' : 's'}${n6 ? ` · ${n6} L6` : ''} · <b class="${tone(h.total.movement, 0.5)}">${esc(money(h.total.movement, { sign: true }))}</b>`; }
function hierTable(did, { head = true } = {}) {
  const h = hierOf(did), d = ldrv(did); if (!h || !d) return '';
  const row = (n, depth, grp, anc) => {
    const kids = n.children.length ? n.children : null, accs = !kids ? n.accounts.map(a => lacct(a)).filter(a => a && isNum(a.movement) && Math.abs(a.movement) >= 0.5).sort((a, b) => Math.abs(b.movement) - Math.abs(a.movement)) : [];
    const id = 'h' + (++TGL), open = kids || accs.length;
    let html = `<tr class="${depth ? 'sub' : ''}${open ? ' tgl' : ''}${grp ? ' hid' : ''}" ${open ? `data-tgl="${id}" tabindex="0" role="button" aria-expanded="false"` : ''} ${grp ? `data-grp="${grp}"` : ''} ${anc ? `data-anc="${anc}"` : ''} data-node="${esc(n.id)}"><td style="padding-left:${8 + depth * 14}px">${open ? '<span class="car">▸</span>' : ''}${esc(n.name)} <span class="xs mut">${n.level}</span>${basisChip(n.movement_basis)}</td><td class="num ${tone(n.movement, 0.5)}">${esc(money(n.movement, { sign: true }))}</td></tr>`;
    if (kids) html += kids.map(k => row(k, depth + 1, id, anc || grp || null)).join('');
    else html += accs.map(a => `<tr class="sub hid xm" data-grp="${id}" ${anc || grp ? `data-anc="${anc || grp}"` : ''} data-ref="acct:${esc(a.id)}"><td style="padding-left:${22 + depth * 14}px">${esc(acctName(a.id))}${basisChip(a.movement_basis)}</td><td class="num ${tone(a.movement, 0.5)}">${esc(money(a.movement, { sign: true }))}</td></tr>`).join('');
    return html;
  };
  return `<table class="mini recon hier"><thead><tr><th>${head ? esc(d.label) + ' · ' : ''}sub-group (${esc(h.levels.join(' › '))} › account)</th><th class="num">${esc(cap(mvWord()))}</th></tr></thead><tbody>
    ${h.nodes.map(n => row(n, 0, null, null)).join('')}
    <tr class="tot"><td>Total = ${esc(d.label)} ${esc(mvWord())}</td><td class="num ${tone(h.total.movement, 0.5)}">${esc(money(h.total.movement, { sign: true }))}</td></tr></tbody></table>${h.unsplit_accounts.length ? `<p class="xs mut">${h.unsplit_accounts.length} account${h.unsplit_accounts.length > 1 ? 's' : ''} with no sub-group below L4 ${h.unsplit_accounts.length > 1 ? 'are' : 'is'} in the total.</p>` : ''}`;
}
/* one sub-group: its figures, its accounts, where it sits */
function nodeDrawer(id) {
  const Lx = L(); let found = null, par = null, did = null;
  for (const [k, h] of Object.entries(Lx.hierarchy || {})) for (const n of h.nodes) { if (n.id === id) { found = n; did = k; } for (const c of n.children) if (c.id === id) { found = c; par = n; did = k; } }
  if (!found) { const pl = (Lx.product_lines || { items: [] }).items.find(x => x.id === id); if (!pl) return null; found = pl; did = pl.driver; }
  const d = ldrv(did), accs = (found.accounts || []).map(a => lacct(a)).filter(a => a && isNum(a.movement) && Math.abs(a.movement) >= 0.5).sort((a, b) => Math.abs(b.movement) - Math.abs(a.movement));
  return { title: found.name, sub: `${d ? d.label + ' › ' : ''}${par ? par.name + ' › ' : ''}${found.level} · ${rangeLabel()} vs ${basisWord()}`, tags: [tag(tone(found.movement, 0.5))],
    tabs: { Overview: () => `${facts([['Actual', money(found.actual)], [cap(basisWord()), money(found.comparator)], [cap(mvWord()), money(found.movement, { sign: true }), tone(found.movement, 0.5)]])}
      ${accs.length ? `<h4>Accounts</h4><table class="mini recon"><thead><tr><th>Account</th><th class="num">${esc(cap(mvWord()))}</th></tr></thead><tbody>${accs.map(a => `<tr data-ref="acct:${esc(a.id)}"><td>${esc(acctName(a.id))}${basisChip(a.movement_basis)}</td><td class="num ${tone(a.movement, 0.5)}">${esc(money(a.movement, { sign: true }))}</td></tr>`).join('')}</tbody></table>` : '<div class="empty">No account moved in this view.</div>'}
      ${d ? `<button class="btnl" data-ref="driver:${esc(d.id)}">Open ${esc(d.label)} ›</button>` : ''}` } };
}
/* accounts behind a driver: top N, the remainder, and the total that equals the driver's movement */
function reconTable(did, { top = 8 } = {}) {
  const rc = recOf(did); if (!rc || !rc.items.length) return '<div class="empty">No account moved in this view.</div>';
  const shown = rc.items.slice(0, top), more = rc.items.slice(top);
  const oth = rc.other || more.length ? { count: (rc.other ? rc.other.count : 0) + more.length, movement: (rc.other ? rc.other.movement : 0) + more.reduce((t, i) => t + i.movement, 0) } : null;
  return `<table class="mini recon"><thead><tr><th>Account</th><th class="num">${esc(cap(mvWord()))}</th></tr></thead><tbody>
    ${shown.map(i => `<tr data-ref="acct:${esc(i.account)}"><td>${esc(acctName(i.account))}${basisChip(i.movement_basis)}</td><td class="num ${tone(i.movement, 0.5)}">${esc(money(i.movement, { sign: true }))}</td></tr>`).join('')}
    ${oth ? othRows(`${oth.count} other account${oth.count > 1 ? 's' : ''}`, oth.movement, more.concat((rc.other || {}).items || []).map(i => ({ name: acctName(i.account), value: i.movement, ref: 'acct:' + i.account, chip: basisChip(i.movement_basis) }))) : ''}
    <tr class="tot"><td>Total = ${esc(DRV_BY[did] ? DRV_BY[did].label : 'driver')} ${esc(mvWord())}</td><td class="num ${tone(rc.total, 0.5)}">${esc(money(rc.total, { sign: true }))}</td></tr></tbody></table>${zeroNote(rc.zero_count)}`;
}
/* comparator to actual for one driver: the top three accounts as numbered steps, the rest as one "Other" step; names in the key below */
function reconWaterfall(did) {
  const rc = recOf(did), d = ldrv(did); if (!rc || !d || !isNum(d.comparator) || !isNum(d.actual) || rc.items.length < 2) return '';
  const ds = d.display_sign, top = rc.items.slice(0, 3), rest = rc.items.slice(3), n = rest.length + (rc.other ? rc.other.count : 0), oth = (rc.other ? rc.other.movement : 0) + rest.reduce((t, i) => t + i.movement, 0);
  const steps = top.map((i, k) => ({ key: String(k + 1), label: acctName(i.account), value: i.movement * ds, kind: i.movement >= 0 ? 'fav' : 'unf', ref: 'acct:' + i.account }));
  if (Math.abs(oth) >= 0.5) steps.push({ key: 'Other', label: `Other accounts (${n})`, value: oth * ds, kind: oth >= 0 ? 'fav' : 'unf' });
  return waterfall({ id: 'wf-rc-' + did.replace(/[^a-z0-9]/gi, ''), start: { label: cap(basisWord()), value: d.comparator }, steps, end: { label: 'Actual', value: d.actual }, height: 230, W: 460 });
}
/* top-down: the driver by department, each department with the accounts that carry it */
function deptTable(did, { head = true } = {}) {
  const dep = (recOf(did) || {}).by_department; if (!dep || dep.rows.length < 2) return '';
  const key = dep.comparable ? 'movement' : 'actual';
  const sub = r => {
    const cmp = dep.comparable && r.accounts_comparable !== false, k = cmp ? 'movement' : 'actual';       /* rows follow the table: actuals when the department split is on actuals */
    return (r.accounts || []).map(a => `<tr class="sub" data-ref="acct:${esc(a.name)}"><td>${esc(acctName(a.name))}${cmp ? basisChip(a.movement_basis) : ''}</td><td class="num">${esc(money(a[k], { sign: cmp }))}</td></tr>`).join('')
      + (r.accounts_other ? othRows(`${r.accounts_other.count} other account${r.accounts_other.count > 1 ? 's' : ''}`, r.accounts_other[k], (r.accounts_other.items || []).map(x => ({ name: acctName(x.name), value: x[k], ref: 'acct:' + x.name })), { sign: cmp, sub: true }) : '');
  };
  return `${head ? '<h4>By department</h4>' : ''}${dep.comparable ? '' : `<p class="xs mut">The ${esc(basisWord())} is not held by department, so the split shows actuals; the ${esc(mvWord())} is reported at the driver.</p>`}
    <table class="mini recon dept"><thead><tr><th>Department › account</th><th class="num">${dep.comparable ? esc(cap(mvWord())) : 'Actual'}</th></tr></thead><tbody>
    ${dep.rows.map(r => `<tr class="dep"><td><b>${esc(r.name)}</b>${dep.comparable ? basisChip(r.movement_basis) : ''}</td><td class="num ${dep.comparable ? tone(r[key], 0.5) : ''}">${esc(money(r[key], { sign: dep.comparable }))}</td></tr>${sub(r)}`).join('')}
    ${dep.other ? othRows(`${dep.other.count} other department${dep.other.count > 1 ? 's' : ''}`, dep.other[key], (dep.other.items || []).map(x => ({ name: x.name, value: x[key] })), { sign: dep.comparable }) : ''}
    <tr class="tot"><td>Total</td><td class="num">${esc(money(dep.total[key], { sign: dep.comparable }))}</td></tr></tbody></table>${zeroNote(dep.zero_count || 0, 'department')}`;
}
/* one account's subsidiary, class or department split */
function splitTable(t, dim) {
  return `${t.comparable ? '' : `<p class="xs mut">No ${esc(basisWord())} at ${esc(dim)} level: actuals shown; the ${esc(mvWord())} is reported for the account.</p>`}
    <table class="mini recon"><thead><tr><th>${esc(cap(dim))}</th><th class="num">Actual</th><th class="num">${esc(cap(basisWord()))}</th>${t.comparable ? `<th class="num">${esc(cap(mvWord()))}</th>` : ''}</tr></thead><tbody>
    ${t.rows.map(r => `<tr><td>${esc(r.name)}${t.comparable ? basisChip(r.movement_basis) : ''}</td><td class="num">${esc(money(r.actual))}</td><td class="num">${esc(money(r.comparator))}</td>${t.comparable ? `<td class="num ${tone(r.movement, 0.5)}">${esc(money(r.movement, { sign: true }))}</td>` : ''}</tr>`).join('')}
    ${t.other ? `<tr class="oth"><td>${t.other.count} other</td><td class="num">${esc(money(t.other.actual))}</td><td></td>${t.comparable ? `<td class="num">${esc(money(t.other.movement, { sign: true }))}</td>` : ''}</tr>` : ''}
    <tr class="tot"><td>Total</td><td class="num">${esc(money(t.total.actual))}</td><td class="num">${esc(money(t.total.comparator))}</td>${t.comparable ? `<td class="num">${esc(money(t.total.movement, { sign: true }))}</td>` : ''}</tr></tbody></table>${zeroNote(t.zero_count || 0, dim === 'class' ? 'class' : dim)}`;
}
/* summary bullets open evidence at the level of their claim */
function drillDrawer(key) {
  const [level, rest] = [key.slice(0, key.indexOf(':')), key.slice(key.indexOf(':') + 1)];
  const [idsS, supS] = rest.split('|'), ids = idsS.split(',').filter(Boolean), sup = (supS || '').split(',').filter(Boolean);
  if (level === 'line') return lineDrawer(ids[0]);
  if (level === 'outlook') return outlookDrawer(ids[0]);
  if (level === 'driver') return ids.length === 1 ? driverDrawer(ids[0]) : driversDrawer(ids);
  if (level === 'section') return sectionDrawer(ids, sup);
  return null;
}
const SEC_LINE = { rev: 'rev', cos: 'cos', opex: 'opex', syn: 'syn', nonop: 'nonop', ebitda: 'ebitda' };
/* a P&L section, then its L4 drivers (they foot to the line), each opening its accounts */
function sectionBlock(sec) {
  const ln = lline(SEC_LINE[sec]); if (!ln) return '';
  const inSec = d => sec === 'ebitda' ? ['rev', 'cos', 'opex'].includes(d.section) : d.section === sec;   /* Adjusted EBITDA is a line: its drivers are the operating sections' */
  const ds = L().drivers.filter(d => inSec(d) && isNum(d.movement) && Math.abs(d.movement) >= 0.5).sort((a, b) => Math.abs(b.movement) - Math.abs(a.movement));
  return `<h4>${esc(LINE_LABEL[SEC_LINE[sec]] || SECTION_LABEL[sec])} · ${esc(money(ln.actual))} vs ${esc(money(ln.comparator))}</h4>
    ${ds.length ? `<table class="mini recon"><thead><tr><th>Driver (L4)</th><th class="num">${esc(cap(mvWord()))}</th></tr></thead><tbody>
    ${ds.map(d => `<tr data-ref="driver:${esc(d.id)}"><td>${esc(d.label)}${basisChip(d.movement_basis)} ›</td><td class="num ${tone(d.movement, 0.5)}">${esc(money(d.movement, { sign: true }))}</td></tr>`).join('')}
    <tr class="tot"><td>Total = ${esc(LINE_LABEL[SEC_LINE[sec]] || sec)} ${esc(mvWord())}</td><td class="num ${tone(ln.variance, 0.5)}">${esc(money(ln.variance, { sign: true }))}</td></tr></tbody></table>${zeroNote(L().drivers.filter(inSec).length - ds.length, 'driver')}` : '<div class="empty">Nothing moved.</div>'}`;
}
function sectionDrawer(ids, sup) {
  const moved = ids.filter(i => { const ln = lline(SEC_LINE[i]); return ln && (Math.abs(ln.variance || 0) >= 0.5 || L().drivers.some(d => d.section === i && Math.abs(d.movement || 0) >= 0.5)); });
  if (moved.length) ids = moved;                                  /* an empty section (e.g. synergies) adds nothing */
  const lbl = ids.map(i => lc(LINE_LABEL[SEC_LINE[i]] || i));
  return { title: cap(joinAnd(lbl)), sub: `${rangeLabel()} vs ${basisWord()} · the evidence behind the summary`, tags: [],
    tabs: { Overview: () => `${ids.map(sectionBlock).join('')}
      ${sup.length ? `<h4>Alongside</h4><table class="mini"><tbody>${sup.map(i => { const ln = lline(SEC_LINE[i]); return ln ? `<tr data-ref="drill:section:${esc(i)}"><td>${esc(LINE_LABEL[SEC_LINE[i]] || i)} ›</td><td class="num">${esc(money(ln.actual))}</td><td class="num ${tone(ln.variance)}">${esc(money(ln.variance, { sign: true }))} vs ${esc(basisWord())}</td></tr>` : ''; }).join('')}</tbody></table>` : ''}` } };
}
function driversDrawer(ids) {
  const ds = ids.map(ldrv).filter(Boolean); if (!ds.length) return null;
  return { title: joinAnd(ds.map(d => d.label)), sub: `${rangeLabel()} vs ${basisWord()} · the drivers behind the summary point`, tags: [],
    tabs: { Overview: () => ds.map(d => `<h4 data-ref="driver:${esc(d.id)}" style="cursor:pointer">${esc(d.label)} · ${esc(money(d.movement, { sign: true }))} ›</h4>${reconTable(d.id, { top: 3 })}`).join('') } };
}

/* ---------- DRAWER ---------- */
function keyActivatable(el) { const tg = String(el.tagName || '').toUpperCase(); if (tg === 'BUTTON') return; if (!el.hasAttribute('tabindex')) el.setAttribute('tabindex', '0'); if (!el.getAttribute('role')) el.setAttribute('role', 'button'); el.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); e.stopPropagation(); el.click(); } }); }
function bindRefs(root) { root.querySelectorAll('[data-ref]').forEach(el => { if (el.classList.contains('bar') || el.dataset.bound) return; el.dataset.bound = '1'; el.addEventListener('click', e => { e.stopPropagation(); openDrawer(el.dataset.ref, el.dataset.dtab); }); keyActivatable(el); }); }
const barKey = host => host && host.addEventListener('keydown', e => { const g = e.target.closest && e.target.closest('.bar'); if (g && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); g.dispatchEvent(new MouseEvent('click', { bubbles: true })); } });
function closeDrawer() { S.drawer = null; S.drawerIntro = null; $('#drawer').classList.remove('open'); $('#app').classList.remove('drawer-open'); document.querySelectorAll('.fk.sel').forEach(x => x.classList.remove('sel')); const o = S.opener; S.opener = null; if (o && o.isConnected && o.focus) o.focus(); }
document.addEventListener('keydown', e => { if (e.key === 'Escape') closeDrawer(); });
function openDrawer(ref, tab) {
  if (!ref) return;
  if (S.drawer !== ref) S.drawerTab = tab || null; else if (tab) S.drawerTab = tab;
  if (!S.drawer && document.activeElement && document.activeElement !== document.body) S.opener = document.activeElement;
  const i = ref.indexOf(':'), kind = i < 0 ? ref : ref.slice(0, i), id = i < 0 ? null : ref.slice(i + 1);
  const b = { drill: drillDrawer, acct: acctDrawer, driver: driverDrawer, step: driverDrawer, kpi: kpiDrawer, line: lineDrawer, action: actionDrawer, finding: findingDrawer, qc: qcDrawer, outlook: outlookDrawer, scenario: scenarioDrawer, node: nodeDrawer }[kind];
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
  const a = lacct(id); if (!a) return null; const acc = ACC_BY[id], sg = SIG[id], x = xacct(id), d = DRV_BY[a.driver_ref], act = actOf(a.driver_ref), t = tone(a.movement);
  const sp = (L().splits || {})[id] || {};
  const subs = L().facts.rows.filter(r => r[0] === id), ip = D() ? ((D().readout || {}).account_interpretations || []).find(q => q.account === id) : null;
  return { title: acctName(id), sub: `${d ? d.label + ' · ' : ''}${acc.budget_grain === 'account' ? 'compared across subsidiaries (budget held at ' + (acc.budget_held_at || []).join(', ') + ') · ' : ''}${rangeLabel()} vs ${basisWord()}`, tags: [tag(t), persistTag(sg.persistence_hint), ip ? diagMark() : ''],
    tabs: {
      Overview: () => `${facts([['Actual', money(a.actual)], [cap(basisWord()), isNum(a.comparator) ? money(a.comparator) : 'none'], [isNum(a.variance) ? 'Variance' : 'Movement', money(isNum(a.variance) ? a.variance : a.movement, { sign: true }), tone(a.movement)]])}
        ${a.movement_basis && a.movement_basis !== 'both' ? `<div style="margin:6px 0">${basisChip(a.movement_basis)}</div>` : ''}
        <h4>What it means</h4>${say([ip ? esc(clean(ip.text)) : null, ...acctReasons(id, a.driver_ref).map(s => esc(cap(s)) + '.'), isNum(a.share_of_abs_variance) ? `${esc(pct(a.share_of_abs_variance, { dec: 0 }))} of the total movement; ${esc(pct(a.variance_pct, { sign: true }))} against ${esc(basisWord())}.` : null])}
        ${sg.runrate.eligible ? `<h4>${esc(MONTH)} against its usual range</h4>${rangeBar(id, { ref: false })}${rangeLegend()}` : ''}
        <h4>Patterns found</h4><div class="chips">${sg.tests.filter(q => q.state === 'fired').map(q => `<span class="cp on">● ${esc(q.label)}</span>`).join('') || '<span class="cp">None</span>'}<span class="cp" data-tip="Also checked, not found|${esc(sg.tests.filter(q => q.state === 'not_fired').map(q => q.label).join('|'))}">${sg.tests.filter(q => q.state === 'not_fired').length} other checks clear</span></div>
        ${nextStep(act)}
        ${evidence(x ? x.numbers : [])}`,
      Trend: () => `${trendBlock(acc.series.actual, acc.series.budget, acc.series.py)}
        <table class="mini" style="margin-top:12px"><thead><tr><th>Month</th><th class="num">Actual</th><th class="num">Budget</th><th class="num">Variance</th></tr></thead><tbody>${PER.slice(Math.max(0, AS - 5), AS + 1).map((p, k) => { const i = Math.max(0, AS - 5) + k; return `<tr class="${i === AS ? 'sel' : ''}"><td>${esc(shortLbl(p))}</td><td class="num">${esc(money(acc.series.actual[i]))}</td><td class="num">${esc(money(acc.series.budget[i]))}</td><td class="num ${tone(acc.series.variance_vs_budget[i], 0.5)}">${esc(money(acc.series.variance_vs_budget[i], { sign: true }))}</td></tr>`; }).join('')}</tbody></table>`,
      Split: () => ['subsidiary', 'class', 'department'].filter(k => sp[k]).map(k => `<h4>By ${esc(k)}</h4>${splitTable(sp[k], k)}`).join('') || (subs.length ? divBars(subs.map(r => ({ name: r[1], value: r[4], ref: 'acct:' + id, floor: 0.5 }))) : '<div class="empty">One subsidiary, class and department: no split.</div>')
    } };
}
function driverDrawer(id) {
  const d = ldrv(id); if (!d) return null; const act = actOf(id), t = tone(d.variance), lead = leadAccount(d), ser = sumSeries(d.accounts);
  const accts = d.accounts.map(a => lacct(a)).filter(a => a && isNum(a.movement) && a.movement !== 0).sort((a, b) => Math.abs(b.movement) - Math.abs(a.movement));
  const fs = D() ? (D().findings || []).filter(f => ((f.scope || {}).drivers || []).includes(id)) : [];
  return { title: d.label, sub: `${SECTION_LABEL[d.section]} · ${rangeLabel()} vs ${basisWord()}`, tags: [tag(t), lead ? persistTag(SIG[lead.id].persistence_hint) : ''],
    tabs: {
      Overview: () => `${facts([['Actual', money(d.actual)], [cap(basisWord()), money(d.comparator)], [isNum(d.variance) ? 'Variance' : 'Movement', money(isNum(d.variance) ? d.variance : d.movement, { sign: true }), t]])}
        <h4>What it means</h4>${say([...fs.map(f => `<span data-ref="finding:${esc(f.id)}" class="ink" style="cursor:pointer">${esc(clean(f.title))} ›</span>`), esc(driverReason(d)), `${esc(pct(d.share_of_abs_variance, { dec: 0 }))} ${esc(shareOf(d))}; ${esc(pct(d.variance_pct, { sign: true }))} against ${esc(basisWord())}.`])}
        ${hierOf(id) ? `<h4>By sub-group (${esc(hierOf(id).levels.join(' › '))} › account)</h4>${hierTable(id, { head: false })}` : ''}
        <h4>How the accounts add up to ${esc(money(d.movement, { sign: true }))}</h4>${reconWaterfall(id)}${reconTable(id)}
        ${deptTable(id)}
        ${lead && SIG[lead.id].runrate.eligible && L().window === 'MTD' ? `<h4>${esc(MONTH)} against its usual range</h4>${accts.slice(0, 3).map(a => rangeBar(a.id)).join('')}${rangeLegend()}` : ''}
        ${nextStep(act)}`,
      Trend: () => trendBlock(ser.actual, ser.budget, ser.py),
      Subsidiaries: () => dimBars(id, 'driver:' + id)
    } };
}
function kpiDrawer(id) {
  const k = lkpi(id); if (!k) return null; const kd = L().kpi_diagnoses.find(q => q.kpi === id) || { drivers: [], questions: [], numbers: [] }, s = SS[KPI_LINE[id]], t = k.status === 'in_line' ? 'neu' : tone(k.variance);
  return { title: k.label, sub: `${rangeLabel()} vs ${basisWord()}`, tags: [tag(t, k.status === 'ahead' ? 'Ahead' : k.status === 'behind' ? 'Behind' : 'In line')],
    tabs: {
      Overview: () => `${facts([['Actual', money(k.actual)], [cap(basisWord()), money(k.comparator)], ['Variance', `${money(k.variance, { sign: true })}`, t]].concat(isNum(k.margin_actual) ? [['Margin', pct(k.margin_actual)], ['Margin change', pts(k.margin_bps), tone(k.margin_bps, 0.001)], ['Variance %', pct(k.variance_pct, { sign: true })]] : []))}
        ${id === 'net_income' && readout().headline ? `<h4>AI review ${diagMark()}</h4>${say([esc(clean(readout().headline))])}` : ''}
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
      <h4>Accounts</h4>${(() => { const mv = a.accounts.filter(x => { const q = lacct(x); return q && isNum(q.movement) && Math.abs(q.movement) >= 0.5; }).sort((x, y) => Math.abs(lacct(y).movement) - Math.abs(lacct(x).movement));
        return `<div class="chips">${mv.map(x => `<span class="cp" data-ref="acct:${esc(x)}">${esc(acctName(x))} ${esc(money(lacct(x).movement, { sign: true }))} ›</span>`).join('')}</div>${zeroNote(a.accounts.length - mv.length)}`; })()}
      <button class="btnl" data-ref="driver:${esc(a.subject_ref)}">Open driver ›</button>` } };
}
const STATE_WORD = { observed_fact: 'What the data shows', analytical_inference: 'What it suggests', hypothesis: 'Possible explanation', management_input_required: 'Needs an answer from the owner' };
function findingDrawer(id) {
  const f = findingById(id); if (!f) return null; const dids = (f.scope || {}).drivers || [];
  const hint = { one_off: 'one_off_candidate', recurring: 'recurring_level_change', timing: 'timing_reversal' }[f.persistence] || f.persistence;
  return { title: clean(f.title), sub: `AI review · ${dids.map(x => (DRV_BY[x] || {}).label || x).join(', ') || rangeLabel()}`, tags: [persistTag(hint)],
    tabs: { Overview: () => `<h4>What the review found</h4>${say((f.statements || []).map(s => `<b class="ink">${esc(STATE_WORD[s.state] || s.state)}:</b> ${esc(clean(s.text))}`))}
      ${(f.missing_evidence || []).length ? `<h4>Still missing</h4>${say(f.missing_evidence.map(esc))}` : ''}
      ${(f.management_questions || []).length ? `<h4>Question for management</h4>${say(f.management_questions.map(q => esc(clean(q))))}` : ''}
      ${dids.map(x => `<button class="btnl" data-ref="driver:${esc(x)}">Open ${esc((DRV_BY[x] || {}).label || x)} ›</button>`).join('')}` } };
}
const QC_NAME = { governed_reconciliation: 'Ties to the finance system totals', adjustments_included: 'Group adjustments included', fiscal_calendar: 'Fiscal calendar', scope_exclusions: 'Subsidiaries left out', open_months: 'Months still open',
  sign_convention: 'How costs are signed', sign_mismatch: 'Budget signed differently from actuals', budget_reliability: 'Budget usable for comparison', unmapped_accounts: 'Accounts outside the P&L lines',
  history: 'Months of history', prior_year_coverage: 'Prior year available', budget_coverage: 'Accounts with a budget', fiscal_year_budget: 'Full-year budget available', data_freshness: 'How recent the data is', window_tie_out: 'Quarter, year and twelve-month figures tie to the finance system',
  completeness: 'Nothing cut off', data_mode: 'Data source', scope: 'Scope' };
function qcDrawer() {
  const qc = P.qc, dot = r => r === 'PASS' ? 'fav' : r === 'FAIL' ? 'unf' : r === 'WARN' ? 'amb' : 'neu', word = r => ({ PASS: 'OK', WARN: 'Note', FAIL: 'Failed', NOT_RUN: 'Not run' })[r] || r;
  return { title: 'Data checks and scope', sub: `${VERIFIED ? 'data verified' : 'data checks'} · ${qc.caveats.length} note${qc.caveats.length === 1 ? '' : 's'}`, tags: [],
    tabs: { Checks: () => `<table class="mini"><tbody>${qc.checks.map(c => `<tr><td style="width:120px">${tag(dot(c.result), word(c.result))}</td><td><b class="ink">${esc(QC_NAME[c.id] || cap(c.id.replace(/_/g, ' ')))}</b><div class="xs mut">${esc(clean(c.detail))}</div>${(c.items || []).length ? `<table class="mini" style="margin-top:6px"><thead><tr><th>Window</th><th>Line</th><th>Subsidiary</th><th class="num">From the months</th><th class="num">In the view</th><th class="num">Difference</th></tr></thead><tbody>${c.items.slice(0, 12).map(x => `<tr><td>${esc(META.window_labels[x.window] || x.window)}</td><td>${esc({ REVENUE: 'Revenue', ADJUSTED_EBITDA: 'Adjusted EBITDA', NET_INCOME: 'Net income' }[x.metric] || x.metric)}</td><td>${esc(x.subsidiary)}</td><td class="num">${esc(money(x.extract))}</td><td class="num">${esc(money(x.governed))}</td><td class="num ${x.result === 'PASS' ? '' : x.result === 'WARN' ? 'amb' : 'unf'}">${esc(money(x.difference, { sign: true }))}${x.pct === null || x.pct === undefined ? '' : ' (' + esc(pct(x.pct, { sign: true })) + ')'}</td></tr>`).join('')}</tbody></table>` : ''}</td></tr>`).join('')}</tbody></table>
      <h4>What this data cannot answer</h4>${say(Object.entries(P.capabilities).map(([k, v]) => `<b class="ink">${esc(cap(k.replace(/_/g, ' ')))}</b>: ${esc(v.reason)}`))}` } };
}
function outlookDrawer(id) {
  const e = OUT.lines.ebitda, r = ruleOf(e);
  return { title: id === 'ytd' ? 'Year to date' : 'Full-year run-rate', sub: `fiscal ${OUT.fiscal_year} · Adjusted EBITDA · ${lc(r.label)}`, tags: [tag('sky', 'Rule, not a forecast')],
    tabs: { Overview: () => `${id === 'ytd' ? facts([['Actual', money(e.ytd.actual)], ['Budget', money(e.ytd.budget)], ['Variance', money(e.ytd.variance, { sign: true }), tone(e.ytd.variance)]]) : facts([[r.rule === 'trend_extrapolation' ? 'Run-rate a month (average)' : 'Run-rate a month', money(r.run_rate)], ['Months left', String(e.remaining_months)], ['Full year', money(r.value)]])}
      <h4>All lines · ${esc(lc(r.label))}</h4><table class="mini"><thead><tr><th>Line</th><th class="num">Year to date</th><th class="num">Full year</th><th class="num">vs budget</th><th class="num">vs last year</th></tr></thead><tbody>${Object.values(OUT.lines).map(l => { const lr = ruleOf(l); return `<tr><td>${esc(LINE_LABEL[l.id] || l.id)}</td><td class="num">${esc(money(l.ytd.actual))}</td><td class="num">${esc(money(lr.value))}</td><td class="num ${tone(lr.gap_vs_budget)}">${esc(money(lr.gap_vs_budget, { sign: true }))}</td><td class="num ${tone(lr.gap_vs_prior_year)}">${esc(money(lr.gap_vs_prior_year, { sign: true }))}</td></tr>`; }).join('')}</tbody></table>
      <h4>By rule · click to switch</h4>${hBars(e.mechanical.sensitivity.map(x => ({ name: x.label, value: x.value, cls: x.rule === r.rule ? 'hi' : '', rule: x.rule })))}
      ${(OUT.one_offs_excluded || []).length ? `<h4>One-off months taken out of the run-rate</h4><table class="mini"><thead><tr><th>Account</th><th>Month</th><th class="num">Amount</th></tr></thead><tbody>${OUT.one_offs_excluded.slice(0, 12).map(x => `<tr><td>${esc(x.name)}</td><td>${esc(shortLbl(PER.find(p => p.label === x.month) || { label: x.month }))}</td><td class="num ${tone(x.amount)}">${esc(money(x.amount, { sign: true }))}</td></tr>`).join('')}</tbody></table>${OUT.one_offs_excluded.length > 12 ? `<p class="xs mut">and ${OUT.one_offs_excluded.length - 12} smaller</p>` : ''}<p class="xs mut">${esc(OUT.one_offs_rule || '')}</p>` : ''}
      ${OUT.note ? `<p class="xs mut" style="margin-top:12px">${esc(OUT.note)}</p>` : ''}` } };
}
function scenarioDrawer(rule) {
  const rows = Object.values(OUT.lines).map(l => ({ l, s: l.mechanical.sensitivity.find(x => x.rule === rule) })).filter(x => x.s); if (!rows.length) return null;
  return { title: rows[0].s.label, sub: 'Full-year run-rate rule', tags: [tag('sky', 'Reference only')],
    tabs: { Overview: () => `${hBars(rows.map(({ l, s }) => ({ name: LINE_LABEL[l.id] || l.id, value: s.value })))}<p class="xs mut" style="margin-top:12px">Year to date plus the remaining months at ${esc(lc(rows[0].s.label))}.</p>` } };
}

/* ---------- boot ---------- */
function renderAll() { renderHeader(); renderSummary(); renderDrivers(); renderOutlook(); renderGlossary(); }
function toggleRows(t) { const on = t.getAttribute('aria-expanded') !== 'true'; t.setAttribute('aria-expanded', String(on)); const root = t.closest('table') || document;
  root.querySelectorAll(`tr[data-grp="${t.dataset.tgl}"]`).forEach(r => r.classList.toggle('hid', !on));
  if (!on) root.querySelectorAll(`tr[data-anc="${t.dataset.tgl}"]`).forEach(r => { r.classList.add('hid'); if (r.dataset.tgl) r.setAttribute('aria-expanded', 'false'); }); }
document.addEventListener('click', e => { const t = e.target.closest('[data-tgl]'); if (t) { e.stopPropagation(); toggleRows(t); } });
/* a rule picked in the run-rate drawer drives the Outlook tab too */
const drawerRule = t => { S.rule = t.dataset.rule; renderOutlook(); openDrawer('outlook:mechanical'); };
document.addEventListener('click', e => { const t = e.target.closest('#dbody .hbr[data-rule]'); if (t) { e.stopPropagation(); drawerRule(t); } });
document.addEventListener('keydown', e => { const t = e.target.closest && e.target.closest('#dbody .hbr[data-rule]'); if (t && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); drawerRule(t); } });
document.addEventListener('keydown', e => { const t = e.target.closest && e.target.closest('[data-tgl]'); if (t && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); toggleRows(t); } });
renderAll();
const hashTab = String(location.hash || '').replace('#', '');
setTab(TABQ[hashTab] ? hashTab : S.tab);
/* headless self-test (#selftest): overlapping chart labels on every tab, month-label format, the Drivers and Outlook
   controls, and where the lead bullet's drill lands. Inert otherwise. */
if (/selftest/.test(String(location.hash) + String(location.search))) {
  const res = { errors: [], overlaps: [], bad_labels: [], lead: null, drill_title: null };
  try {
    const overl = where => document.querySelectorAll(where + ' svg').forEach(svg => {
      const ts = [...svg.querySelectorAll('text:not(.tilt)')].map(t => ({ t: t.textContent, r: t.getBoundingClientRect() })).filter(x => x.r.width > 0 && x.t.trim());
      for (let i = 0; i < ts.length; i++) for (let j = i + 1; j < ts.length; j++) { const a = ts[i].r, b = ts[j].r;
        if (a.left < b.right - 1 && b.left < a.right - 1 && a.top < b.bottom - 1 && b.top < a.bottom - 1) res.overlaps.push(`${svg.id || svg.className.baseVal}: "${ts[i].t}" / "${ts[j].t}"`); } });
    ['summary', 'drivers', 'outlook'].forEach(t => { setTab(t); overl('#view-' + t); });
    /* tilted axis labels: parallel at 45 degrees, so they clear each other when the bar spacing times sin 45 exceeds the line height */
    res.tilt = [...document.querySelectorAll('svg.wf')].filter(svg => svg.querySelector('text.tilt')).map(svg => { const xs = [...svg.querySelectorAll('text.tilt')].map(t => +t.getAttribute('x')); const gap = Math.min(...xs.slice(1).map((x, i) => x - xs[i])); return { id: svg.id, n: xs.length, clear: gap * Math.SQRT1_2 > TILT_FS * 1.2 }; });
    /* drillable commentary: 3-5 bullets on the bridge (both views) and on the Outlook */
    setTab('drivers'); const cn = () => document.querySelectorAll('#drv-commentary .cmt li').length; res.commentary = { driver: cn() };
    S.bridgeMode = 'ni'; renderDrivers(); res.commentary.ni = cn(); res.commentary.ni_head = (($('#drv-commentary .cmt li b') || {}).textContent || ''); S.bridgeMode = 'reported'; renderDrivers();
    const l0 = document.querySelector('#drv-commentary .lnk'); if (l0) { l0.click(); res.commentary.link_opens = !!$('#drawer.open'); closeDrawer(); }
    setTab('outlook'); res.commentary.outlook = document.querySelectorAll('#out-commentary .cmt li').length; setTab('drivers');
    /* What this means stays on every view (Drivers and Outlook) */
    const keep = S.lens; res.meaning_missing = [];
    Object.keys(P.lenses).filter(k => P.lenses[k].available).forEach(k => { S.lens = k; renderAll(); if (!$('#drv-reading')) res.meaning_missing.push('drivers:' + k); if (OUT && OUT.state === 'calculated' && !$('#out-reading')) res.meaning_missing.push('outlook:' + k); });
    S.lens = keep; renderAll(); setTab('drivers');
    res.bad_labels = (document.body.innerText.match(/\b20\d '\d\d\b/g) || []).slice(0, 5);
    if (P.lenses.MTD_budget && P.lenses.MTD_budget.available) { S.lens = 'MTD_budget'; renderAll(); setTab('drivers'); res.sub_on_budget = !!$('#drv-sub'); res.plan_vs_month = /Plan vs month/.test($('#view-drivers').innerText); }
    /* the selected run-rate rule drives the Outlook tiles, chart and drawer */
    if (OUT && OUT.state === 'calculated') { setTab('outlook'); const tv = () => (($('#view-outlook .tile.dark .kv') || {}).textContent || ''); const wft = () => [...document.querySelectorAll('#wf-fy text')].map(t => t.textContent).join('|'); const gpt = () => (($('#out-treatment .gtot b') || {}).textContent || ''); const before = tv(), wf0 = wft(), gp0 = gpt(); const other = OUT.lines.ebitda.mechanical.sensitivity.find(x => x.rule !== OUT.lines.ebitda.mechanical.rule && isNum(x.value));
      if (other) { const el = document.querySelector(`#out-scenarios .hbr[data-rule="${other.rule}"]`); if (el) el.click(); res.rule_switch = { rule: other.rule, before, after: tv(), want: money(other.value), select: ($('#ruleSel') || {}).value, bridge_changed: wft() !== wf0, gap_before: gp0, gap_after: gpt(), gap_want: OUT.gap_view && OUT.gap_view.available ? money(OUT.gap_view.rules[other.rule].totals.ebitda, { sign: true }) : null };
        const gc = $('#gapCat'); if (gc) { gc.value = 'rev'; gc.dispatchEvent(new Event('change')); res.gap_cat = { total: gpt(), want: money(OUT.gap_view.rules[other.rule].totals.rev, { sign: true }) }; S.gapCat = 'ebitda'; }
        openDrawer('outlook:mechanical'); const db = document.querySelector('#dbody .hbr[data-rule="period_flat"]'); if (db) { db.click(); res.drawer_rule = { rule: S.rule, tile: tv(), sub: ($('#dh') || {}).textContent.includes('latest month held flat') }; } closeDrawer(); overl('#view-outlook'); S.rule = null; }
      $('#rrInfo').click(); res.rr_info = !$('#rrDef').hidden; $('#rrInfo').click(); }
    S.lens = META.primary_lens.id; renderAll(); setTab('drivers');
    /* a bridge bar re-targets the usual-range and By-subsidiary panels */
    res.default_panel = ($('#dimDriver') || {}).value || null;
    const bars = [...document.querySelectorAll('#wfHost .bar')].filter(g => (g.dataset.ref || '').startsWith('step:'));
    if (bars.length > 1) { const g = bars[1], did = g.dataset.ref.slice(5); g.dispatchEvent(new MouseEvent('click', { bubbles: true }));
      res.bridge_sync = { driver: did, select: ($('#dimDriver') || {}).value, runrate: (($('#drv-runrate small') || {}).textContent || '').startsWith(ldrv(did).label) }; }
    /* drill tables stay inside their panel, and no drill row shows a zero movement */
    const over = [], zeros = [];
    const scan = root => root.querySelectorAll('table.recon').forEach(t => { const host = t.closest('.panel, #dbody'); if (host && t.getBoundingClientRect().right > host.getBoundingClientRect().right + 1) over.push((host.id || 'panel') + ': ' + t.rows[0].textContent.slice(0, 40));
      t.querySelectorAll('tr[data-ref] td.num').forEach(td => { if (/^\+?\$0$/.test(td.textContent.trim())) zeros.push(td.parentNode.textContent.trim().slice(0, 50)); }); });
    scan($('#view-drivers'));
    res.side_collapsed = [...document.querySelectorAll('#drvSel details.dd')].map(x => x.open);
    /* L4 > L5 > L6 > account: open a driver with sub-groups, expand the first L5, then its first L6 (or accounts), then an account */
    const hd = Object.keys(L().hierarchy || {})[0];
    if (hd) { openDrawer('driver:' + hd); const t5 = document.querySelector('#dbody table.hier tr[data-tgl]'); const chain = [];
      if (t5) { t5.click(); chain.push('L5'); const g5 = [...document.querySelectorAll(`#dbody table.hier tr[data-grp="${t5.dataset.tgl}"]`)]; const t6 = g5.find(r => r.dataset.tgl);
        if (t6) { t6.click(); chain.push('L6'); const g6 = [...document.querySelectorAll(`#dbody table.hier tr[data-grp="${t6.dataset.tgl}"]`)]; if (g6.some(r => (r.dataset.ref || '').startsWith('acct:') && !r.classList.contains('hid'))) chain.push('account'); }
        else if (g5.some(r => (r.dataset.ref || '').startsWith('acct:') && !r.classList.contains('hid'))) chain.push('account');
        t5.click(); res.hier_collapse_hides_all = [...document.querySelectorAll(`#dbody table.hier tr[data-grp], #dbody table.hier tr[data-anc]`)].every(r => r.classList.contains('hid')); }
      res.hier_chain = chain; closeDrawer(); }
    /* the product-line and opex sub-group panels are off the Drivers tab; a sub-group still opens its drawer */
    res.removed_panels = !$('#drv-pl') && !$('#drv-opex');
    const nid = Object.values(L().hierarchy || {}).flatMap(h => h.nodes.map(n => n.id))[0]; if (nid) { openDrawer('node:' + nid); res.node_drawer = !!document.querySelector('#dbody .facts'); closeDrawer(); }
    /* the account waterfall: at most three named steps plus Other, names in the key, never on the axis */
    const dw = L().drivers.filter(d => recOf(d.id) && recOf(d.id).items.length >= 2).sort((a, b) => Math.abs(b.movement) - Math.abs(a.movement))[0];
    if (dw) { openDrawer('driver:' + dw.id); const svg = document.querySelector('#dbody svg.wf'), key = document.querySelector('#dbody .wfkey');
      const ax = svg ? [...svg.querySelectorAll('text.lbl')].map(t => t.textContent) : [];
      res.acct_waterfall = { key_rows: key ? key.querySelectorAll('.wk').length : 0, named: key ? key.querySelectorAll('.wk[data-ref]').length : 0, axis: ax, names_on_axis: ax.some(t => !['1', '2', '3', 'Other', 'Actual', cap(basisWord())].includes(t)) }; closeDrawer(); }
    const tg = document.querySelector('#drvSel tr[data-tgl], #view-drivers tr[data-tgl]');
    if (tg) { const grp = () => [...tg.closest('table').querySelectorAll(`tr[data-grp="${tg.dataset.tgl}"]`)]; const hidden0 = grp().every(r => r.classList.contains('hid')); tg.click(); res.other_expand = { hidden0, shown: grp().every(r => !r.classList.contains('hid')), rows: grp().length }; tg.click(); }
    const d0 = L().drivers.filter(d => isNum(d.movement)).sort((a, b) => Math.abs(b.movement) - Math.abs(a.movement))[0]; if (d0) { openDrawer('driver:' + d0.id); scan($('#dbody')); closeDrawer(); }
    res.overflow = over; res.zero_rows = zeros;
    setTab('summary');
    res.assumptions = { present: !!$('#assumptions'), rows: document.querySelectorAll('#assumptions tbody tr:not(.grp)').length, after_glossary: !!($('#assumptions') && $('#assumptions').previousElementSibling && $('#assumptions').previousElementSibling.classList.contains('gls-d')) };
    res.age_chip = !!$('#ageChip'); res.reviewed_views = Object.keys(DIAGS);   /* the age note lives in the data checks and the Assumptions list, not the header */
    res.written_summary = written() ? { bullets: document.querySelectorAll('#sum-exec li.rv').length, first_is_lead: !!document.querySelector('#sum-exec li.lead.rv'), decisions: document.querySelectorAll('#sum-asks ol.dec li').length, heads: [...document.querySelectorAll('#sum-exec li b')].map(b => b.textContent) } : null;
    const li = document.querySelector('#sum-exec li.lead'); res.lead = li ? { claim: li.dataset.claim || null, ref: li.dataset.ref } : null;
    res.bullet_words = [...document.querySelectorAll('#sum-exec li .tx')].map(t => t.textContent.trim().split(/\s+/).length);
    res.ask_words = [...document.querySelectorAll('#askList li .q')].map(t => t.textContent.trim().split(/\s+/).length);
    const ask0 = document.querySelector('#askList li'); if (ask0) { ask0.click(); res.ask_intro = !!document.querySelector('#dbody .intro'); res.ask_title = ($('#dh h2') || {}).textContent || null; closeDrawer(); }
    /* EBITDA keeps its capitals in every drawer title: the section drill, alone and with its lines */
    res.ebitda_titles = ['drill:section:ebitda', 'drill:section:rev,cos,opex'].map(r => { try { openDrawer(r); const t = ($('#dh').textContent || ''); closeDrawer(); return t; } catch (e) { return 'error: ' + e.message; } });
    if (li) { li.click(); res.drill_title = ($('#dh h2') || {}).textContent || null; res.drill_has_table = !!document.querySelector('#dbody table.recon'); res.drill_intro = !!document.querySelector('#dbody .intro'); closeDrawer(); }
  } catch (e) { res.errors.push(String(e && e.stack || e)); }
  const pre = document.createElement('pre'); pre.id = 'selftest'; pre.textContent = JSON.stringify(res); document.body.appendChild(pre);
}
