/* CourseTrack front end - plain JS + SVG, no build step, no libraries.
   The tree IS the plan: columns are terms, cards are courses, lines are prerequisites.
   Colour = state only:  green done · blue ready · grey locked · red broken rule. */
const SEASONS = ['fall', 'winter', 'spring', 'summer'];
const SNAME = { fall: 'Fall', winter: 'Winter', spring: 'Spring', summer: 'Summer' };
const COLW = 206, NW = 178, NH = 56, GAP = 10, HEAD = 62;
const LIMIT = { fall: [19, 19], spring: [19, 19], winter: [4, 7], summer: [8, 12] }; // [heavy, max]
const LEVELS = [[0, 'Freshman'], [30, 'Sophomore'], [60, 'Junior'], [90, 'Senior']];

const $ = s => document.querySelector(s);
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const tkey = (y, s) => y + '-' + s;
const tidx = k => { const [y, s] = k.split('-'); return (y - 1) * 4 + SEASONS.indexOf(s); };
const tlabel = k => { const [y, s] = k.split('-'); return `Y${y} ${SNAME[s]}`; };

const S = { user: null, P: null, plans: [], cur: 0, extra: false, done: {}, notes: {}, checks: {}, custom: {},
            sel: null, drawer: null, q: '', find: '', flash: {}, ai: null };
const view = { x: 16, y: 10, k: 1 };
let V = null, L = null;      // last validation, last layout

/* ───────────── server ───────────── */
async function api(path, opts = {}) {
  if (opts.json !== undefined) { opts.body = JSON.stringify(opts.json); opts.headers = { 'content-type': 'application/json' }; }
  const r = await fetch(path, opts);
  if (r.status === 401 && !path.startsWith('/api/log') && !path.startsWith('/api/sign')) { showAuth(); throw new Error('signed out'); }
  return r;
}
let saveT = null;
function store() {                       // personal state, saved to the account (debounced)
  if (!S.P) return;
  $('#stSaved').textContent = 'saving…';
  clearTimeout(saveT);
  saveT = setTimeout(flush, 500);
}
async function flush() {
  if (!S.P) return;
  clearTimeout(saveT);
  const body = { plans: S.plans.slice(1), cur: S.cur, extra: S.extra, done: S.done, notes: S.notes, checks: S.checks, custom: S.custom };
  try { const r = await api('/api/state/' + S.P.id, { method: 'PUT', json: body }); $('#stSaved').textContent = r.ok ? 'saved' : 'not saved'; }
  catch (e) { $('#stSaved').textContent = 'not saved'; }
}
const saveProgram = () => api('/api/program/' + S.P.id, { method: 'PUT', json: S.P });

/* ───────────── accounts ───────────── */
function showAuth() { $('#app').hidden = true; $('#auth').hidden = false; $('#auMsg').textContent = ''; }
async function auth(path, body) {
  const r = await fetch(path, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body || {}) });
  const d = await r.json();
  if (!r.ok) return $('#auMsg').textContent = d.error || 'Something went wrong.';
  $('#auPass').value = ''; enter(d);
}
$('#authForm').addEventListener('submit', e => { e.preventDefault(); auth('/api/login', { username: $('#auUser').value, password: $('#auPass').value }); });
$('#auSignup').addEventListener('click', () => auth('/api/signup', { username: $('#auUser').value, password: $('#auPass').value }));
$('#auGuest').addEventListener('click', () => auth('/api/guest'));
$('#btnUser').addEventListener('click', async () => {
  if (!confirm(S.user.guest ? 'Leave guest mode? Guest progress cannot be recovered.' : 'Log out?')) return;
  await flush(); await fetch('/api/logout', { method: 'POST' }); S.P = null; showAuth();
});
function enter(user) {
  S.user = user; $('#auth').hidden = true; $('#app').hidden = false;
  $('#btnUser').textContent = (user.guest ? 'guest' : user.username) + ' ⏻';
  loadPrograms(user.last_program);
}
async function boot() {
  const r = await fetch('/api/me');
  if (r.ok) enter(await r.json()); else showAuth();
}

/* ───────────── data ───────────── */
const plan = () => S.plans[S.cur];
// shared program course, else this user's own course (typed into an elective slot), else unknown
const C = id => S.P.courses[id] || (S.custom[id] && { code: id, kind: 'custom', note_text: [], ...S.custom[id] })
  || { code: id, title: '', credits: 0, kind: 'external' };
const tagOf = item => (item.split(':')[1] || '').trim();
const eff = (id, p = plan()) => p.fills[id] || id;

/* ───────────── substitutions ─────────────
   {id, replaces:[codes], with:[codes], label, source}. ALL of `with` together stand in for each course in
   `replaces`. A plan turns one on with plan.swaps[id]; plan.swapped[id] remembers what was moved so that
   turning it off puts things back. */
const SUBS = () => S.P.substitutions || [];
const subById = id => SUBS().find(x => x.id === id);
const activeSubs = (p = plan()) => SUBS().filter(x => (p.swaps || {})[x.id]);
function swappedFor(code, p = plan()) { return activeSubs(p).find(x => x.replaces.includes(code)); }
// The prerequisite graph as this plan sees it: an edge out of a replaced course is redrawn from every course
// that stands in for it (so the dependent waits for the LATEST of them, and is unlocked when ALL are done);
// edges into a replaced course go away, the stand-ins keep their own prerequisites.
function effEdges(p = plan()) {
  const rep = {}; activeSubs(p).forEach(x => x.replaces.forEach(r => rep[r] = rep[r] || x));
  const out = [];
  S.P.edges.forEach((e, oi) => {
    if (rep[e.to]) return;
    if (rep[e.from]) rep[e.from].with.forEach(w => { if (w !== e.to) out.push({ ...e, from: w, oi, via: e.from }); });
    else out.push({ ...e, oi });
  });
  return out;
}
function setSwap(sub, on) {
  const p = editable(); p.swaps = p.swaps || {}; p.swapped = p.swapped || {};
  if (!!p.swaps[sub.id] === on) return;
  if (on) {
    const v = validate(p), rec = { gone: [], added: [] }; let key = null, slotFill = null;
    for (const r of sub.replaces) {
      const a = v.at[r]; if (!a) continue;
      key = key || a.key;
      if (a.id === r) { rec.gone.push({ code: r, key: a.key }); delete p.pos[r]; }
      else { rec.gone.push({ code: r, slot: a.id }); p.fills[a.id] = slotFill = sub.with[0]; }   // the slot keeps one stand-in
    }
    if (key) sub.with.forEach(w => { if (w !== slotFill && !v.at[w]) { p.pos[w] = key; rec.added.push(w); } });
    p.swaps[sub.id] = true; p.swapped[sub.id] = rec;
    if (!key) toast(`${sub.replaces.join(', ')} is not in this plan. Add ${sub.with.join(', ')} where you want them.`);
  } else {
    const rec = p.swapped[sub.id] || { gone: [], added: [] };
    rec.added.forEach(w => delete p.pos[w]);
    rec.gone.forEach(g => { if (g.slot) { if (p.pos[g.slot]) p.fills[g.slot] = g.code; } else p.pos[g.code] = g.key; });
    delete p.swaps[sub.id]; delete p.swapped[sub.id];
  }
  refresh();
}
const isSwapAdded = (id, p = plan()) => Object.values(p.swapped || {}).some(r => r.added.includes(id));
const subLine = x => `${x.with.join(' + ')} for ${x.replaces.join(', ')}`;

function officialPlan() {
  const pos = {}, order = {}; let n = 0;
  S.P.terms.forEach(t => t.items.forEach(id => { pos[id] = tkey(t.year, t.season); order[id] = n++; }));
  S.order = order;
  return { name: 'Official plan', locked: true, pos, fills: {}, meets: {}, swaps: {}, swapped: {} };
}

async function setProgram(P) {
  S.P = P; S.sel = null; S.drawer = null; S.q = ''; $('#q').value = '';
  let saved = {};
  try { saved = await (await api('/api/state/' + P.id)).json(); } catch (e) {}
  S.custom = saved.custom || {};
  S.plans = [officialPlan(), ...(saved.plans || []).map(p => ({ fills: {}, meets: {}, swaps: {}, swapped: {}, ...p, locked: false }))];
  S.plans.slice(1).forEach(p => Object.keys(p.pos).forEach(id => { if (!P.courses[id] && !S.custom[id]) delete p.pos[id]; }));
  S.cur = Math.min(saved.cur || 0, S.plans.length - 1);
  S.extra = !!saved.extra; S.done = saved.done || {}; S.notes = saved.notes || {}; S.checks = saved.checks || {};
  $('#empty').hidden = true; $('#stSaved').textContent = '';
  refresh(false); fit();
}

async function loadPrograms(selectId) {
  const list = await (await api('/api/programs')).json();
  $('#progSel').innerHTML = list.map(p => `<option value="${p.id}">${esc(p.name)}</option>`).join('') || '<option>no programs</option>';
  if (!list.length) { S.P = null; $('#empty').hidden = false; ['#cols', '#edges', '#nodes'].forEach(s => $(s).innerHTML = ''); $('#side').hidden = true; return; }
  const id = (list.find(p => p.id === selectId) || list[0]).id;
  $('#progSel').value = id;
  await setProgram(await (await api('/api/program/' + id)).json());
}

/* ───────────── rules engine ───────────── */
function validate(p = plan()) {
  const at = {};                               // effective course code -> {id, key, idx}
  for (const id in p.pos) at[eff(id, p)] = { id, key: p.pos[id], idx: tidx(p.pos[id]) };
  const issues = [], bad = new Set(), level = {}, load = {};
  for (const id in p.pos) load[p.pos[id]] = (load[p.pos[id]] || 0) + (C(eff(id, p)).credits || 0);
  const into = {}, E = effEdges(p);
  E.forEach((e, i) => (into[e.to] = into[e.to] || []).push({ ...e, i }));
  for (const code in at) {
    const t = at[code], ins = into[code] || [];
    const okEdge = e => { const s = at[e.from]; return s && (e.type.endsWith('coreq') ? s.idx <= t.idx : s.idx < t.idx); };
    for (const e of ins) {
      const s = at[e.from], alt = e.type.startsWith('alt_'), co = e.type.endsWith('coreq');
      if (!s) {
        if (alt || C(e.from).kind === 'external') continue;
        issues.push({ lv: 'info', id: t.id, msg: e.via ? `${code} needs ${e.from} (part of the swap for ${e.via}), which is not in this plan.`
                                                       : `${code} needs ${e.from}, which is not in this plan.` }); continue;
      }
      if (okEdge(e) || (alt && ins.some(x => x !== e && okEdge(x)))) continue;
      bad.add(e.i); level[t.id] = 'err';
      issues.push({ lv: 'err', id: t.id, fix: { tid: t.id, need: co ? s.idx : s.idx + 1 },
        msg: co ? `${code} must be taken with or after ${e.from} (${tlabel(s.key)}), but it is in ${tlabel(t.key)}.`
                : `${code} needs ${e.from} first${e.via ? ` (it stands in for ${e.via})` : ''}. ${e.from} is in ${tlabel(s.key)}, ${code} is in ${tlabel(t.key)}.` });
    }
    const c = C(code), season = t.key.split('-')[1];
    if (c.offered && !c.offered.includes(season))
      issues.push({ lv: 'info', id: t.id, msg: `${code} is listed as ${c.offered.map(s => SNAME[s]).join('/')} only. Check that a ${SNAME[season]} section exists.` });
  }
  for (const k in load) {
    const s = k.split('-')[1], [w, h] = LIMIT[s];
    if (load[k] > h) issues.push({ lv: 'err', key: k, msg: `${tlabel(k)} has ${load[k]} credits, over the usual ${h}-credit limit.` });
    else if (load[k] > w) issues.push({ lv: 'info', key: k, msg: `${tlabel(k)} has ${load[k]} credits, a heavy ${SNAME[s]} load.` });
    else if ((s === 'fall' || s === 'spring') && load[k] < 12) issues.push({ lv: 'info', key: k, msg: `${tlabel(k)} has ${load[k]} credits, below full-time (12).` });
  }
  const lastKey = Object.values(p.pos).sort((a, b) => tidx(b) - tidx(a))[0] || '1-fall';
  let doneCr = 0;
  for (const id in p.pos) if (S.done[id]) doneCr += C(eff(id, p)).credits || 0;
  return { E, issues, bad, level, load, at, total: Object.values(load).reduce((a, b) => a + b, 0), lastKey, doneCr };
}

// done / ready / locked for one card.  ready = every prerequisite that is in the plan is checked off
function status(id, v = V) {
  if (S.done[id]) return 'done';
  const code = eff(id);
  if (code === id && C(id).kind === 'slot') return 'open';      // an empty elective slot is not a course yet
  for (const e of v.E) {
    if (e.to !== code || e.type !== 'prereq') continue;
    const s = v.at[e.from];
    if (s && !S.done[s.id]) return 'locked';
  }
  return 'ready';
}
function chain(code, dir) {          // all ancestors ('up') or descendants ('down') of a course
  const out = new Set(), stack = [code];
  while (stack.length) {
    const c = stack.pop();
    for (const e of (V && V.E) || S.P.edges) {
      const [a, b] = dir === 'up' ? [e.to, e.from] : [e.from, e.to];
      if (a === c && !out.has(b)) { out.add(b); stack.push(b); }
    }
  }
  return out;
}
const level = cr => { let i = 0; LEVELS.forEach((l, n) => { if (cr >= l[0]) i = n; }); return i; };

/* ───────────── checking things off ───────────── */
function setDone(ids, val) {
  const before = new Set(Object.keys(plan().pos).filter(id => status(id) !== 'locked'));
  const lvBefore = level(V.doneCr); let gained = 0;
  ids.forEach(id => { if (!!S.done[id] !== val) { gained += C(eff(id)).credits || 0; if (val) { S.done[id] = true; S.flash[id] = 'pop'; } else delete S.done[id]; } });
  V = validate();
  const unlocked = Object.keys(plan().pos).filter(id => status(id) === 'ready' && !before.has(id));
  if (val) unlocked.forEach(id => S.flash[id] = 'unlock');
  refresh();
  if (!val || !gained) return;
  const names = unlocked.map(id => C(id).kind === 'slot' && eff(id) === id ? null : eff(id)).filter(Boolean);
  let msg = `<b>+${gained} cr</b>`;
  if (names.length) msg += ` · unlocked <u>${names.slice(0, 4).map(esc).join(', ')}${names.length > 4 ? ' +' + (names.length - 4) : ''}</u>`;
  if (level(V.doneCr) > lvBefore) msg += ` · <b>LEVEL UP: ${LEVELS[level(V.doneCr)][1]}</b>`;
  toast(msg, true);
}
const toggleDone = id => setDone([id], !S.done[id]);
function toggleTerm(key) {
  const ids = Object.keys(plan().pos).filter(id => plan().pos[id] === key);
  setDone(ids, !ids.every(id => S.done[id]));
}

/* ───────────── plans ───────────── */
function editable() { if (plan().locked) fork(true); return plan(); }
function fork(auto) {
  const src = plan(), n = S.plans.filter(p => !p.locked).length + 1;
  S.plans.push({ name: 'My plan ' + n, locked: false, pos: { ...src.pos }, fills: { ...src.fills }, meets: { ...(src.meets || {}) },
    swaps: { ...(src.swaps || {}) }, swapped: JSON.parse(JSON.stringify(src.swapped || {})) });
  S.cur = S.plans.length - 1;
  if (auto) toast(`Official plan stays as printed. Your change is in "${plan().name}".`);
}
function autoFix() {
  const p = editable(); const moves = new Set(); let guard = 0;
  while (guard++ < 400) {
    const v = validate(p), is = v.issues.find(i => i.fix);
    if (!is) break;
    const c = C(eff(is.fix.tid, p));
    for (let idx = is.fix.need, n = 0; n < 40; n++, idx++) {
      const s = SEASONS[idx % 4], key = tkey(Math.floor(idx / 4) + 1, s);
      const okSeason = c.offered ? c.offered.includes(s) : (s === 'fall' || s === 'spring');
      if (okSeason && (v.load[key] || 0) + (c.credits || 0) <= LIMIT[s][1]) { p.pos[is.fix.tid] = key; break; }
    }
    moves.add(is.fix.tid);
  }
  refresh();
  toast(moves.size ? `Moved ${moves.size} course${moves.size > 1 ? 's' : ''} later. Finish: ${tlabel(V.lastKey)}.` : 'Nothing to fix.');
}

/* ───────────── layout + render ───────────── */
function layout() {
  const p = plan(), base = Math.max(...S.P.terms.map(t => t.year), 1);
  let years = Math.max(base, ...Object.values(p.pos).map(k => +k.split('-')[0]));
  if (!p.locked) years += 1;                                   // a spare year to push things into
  const has = {}; Object.values(p.pos).forEach(k => has[k] = 1);
  const cols = [];
  for (let y = 1; y <= years; y++) for (const s of SEASONS) {
    const k = tkey(y, s);
    if (s === 'fall' || s === 'spring' || S.extra || has[k]) cols.push(k);
  }
  const at = {}, per = {};
  Object.keys(p.pos).sort((a, b) => (S.order[a] ?? 999) - (S.order[b] ?? 999) || a.localeCompare(b))
    .forEach(id => { const k = p.pos[id]; (per[k] = per[k] || []).push(id); });
  cols.forEach((k, i) => (per[k] || []).forEach((id, j) => at[id] = { x: i * COLW + (COLW - NW) / 2, y: HEAD + j * (NH + GAP) }));
  const rows = Math.max(6, ...Object.values(per).map(a => a.length));
  return { cols, at, per, h: HEAD + rows * (NH + GAP) + 10, base };
}
function wrap(t, n = 27) {
  const out = [''];
  for (const x of t.split(' ')) {
    if ((out[out.length - 1] + ' ' + x).trim().length > n && out.length < 2) out.push(x);
    else out[out.length - 1] = (out[out.length - 1] + ' ' + x).trim();
  }
  return out.map(l => l.length > n + 1 ? l.slice(0, n) + '…' : l);
}
function matches(q) {                 // node ids on the map that match the search text
  q = q.trim().toLowerCase(); if (!q) return [];
  return Object.keys(plan().pos).filter(id => { const c = C(eff(id)); return (c.code + ' ' + c.title).toLowerCase().includes(q); });
}

function render() {
  const p = plan();
  V = validate(p); L = layout();
  let cum = 0;
  $('#cols').innerHTML = L.cols.map((k, i) => {
    const [y, s] = k.split('-'), ld = V.load[k] || 0, ids = L.per[k] || [];
    cum += ld;
    const extra = s === 'winter' || s === 'summer' || +y > L.base;
    const all = ids.length && ids.every(id => S.done[id]);
    return `<g class="col ${extra ? 'extra' : ''}" data-key="${k}" transform="translate(${i * COLW},0)">
      <rect class="bg" width="${COLW}" height="${L.h}"/>
      ${i ? `<line class="sep" y1="6" y2="${L.h}"/>` : ''}
      <text class="tn" x="14" y="22">Y${y} ${SNAME[s].toUpperCase()}</text>
      <text class="cr ${ld > LIMIT[s][1] ? 'bad' : ''}" x="${COLW - 14}" y="22" text-anchor="end">${ld} cr</text>
      ${ids.length ? `<text class="sum" x="14" y="42">total ${cum}</text>
      <text class="tick ${all ? 'all' : ''}" data-term="${k}" x="${COLW - 14}" y="42" text-anchor="end">${all ? '✓ term done' : 'check term'}</text>` : ''}</g>`;
  }).join('');

  let hl = new Set(), selCode = null;
  if (S.sel && (p.pos[S.sel] || V.at[S.sel])) {
    selCode = p.pos[S.sel] ? eff(S.sel) : S.sel;
    hl = new Set([...chain(selCode, 'up'), ...chain(selCode, 'down'), selCode]);
  }
  const hits = new Set(selCode ? [] : matches(S.q));

  $('#edges').innerHTML = V.E.map((e, i) => {
    const a = V.at[e.from], b = V.at[e.to];
    if (!a || !b) return '';
    const A = L.at[a.id], B = L.at[b.id]; let d;
    if (A.x === B.x) {                       // same term (co-requisite): short loop on the right edge
      const x = A.x + NW, y1 = A.y + NH / 2, y2 = B.y + NH / 2;
      d = `M${x},${y1} C${x + 20},${y1} ${x + 20},${y2} ${x + 3},${y2}`;
    } else {
      const fw = B.x > A.x, x1 = fw ? A.x + NW : A.x, x2 = fw ? B.x - 3 : B.x + NW + 3;
      const y1 = A.y + NH / 2, y2 = B.y + NH / 2, dx = Math.max(30, Math.abs(x2 - x1) * .45) * (fw ? 1 : -1);
      d = `M${x1},${y1} C${x1 + dx},${y1} ${x2 - dx},${y2} ${x2},${y2}`;
    }
    const cl = ['edge'];
    if (e.type.endsWith('coreq')) cl.push('coreq'); if (e.type.startsWith('alt_')) cl.push('alt');
    if (V.bad.has(i)) cl.push('bad'); else if (S.done[a.id]) cl.push('lit');
    if (selCode && hl.has(e.from) && hl.has(e.to)) cl.push('hl');
    return `<path class="${cl.join(' ')}" d="${d}" marker-end="url(#arr)"/>`;
  }).join('');

  $('#nodes').innerHTML = Object.keys(L.at).map(id => nodeSVG(id, L.at[id], hl, hits)).join('');
  $('#world').classList.toggle('dim', !!selCode || hits.size > 0);
  if (Object.keys(S.flash).length) setTimeout(() => { S.flash = {}; }, 50);
  applyView();
}

function nodeSVG(id, pt, hl, hits) {
  const p = plan(), code = eff(id), c = C(code), slot = C(id).kind === 'slot', filled = slot && code !== id;
  const cl = ['node', status(id)];
  if (slot && !filled) cl.push('slot');
  if (V.level[id]) cl.push(V.level[id]);
  if (S.sel === id) cl.push('sel'); else if (hl.has(code)) cl.push('hl');
  if (hits.has(id)) cl.push('hit');
  if (S.flash[id]) cl.push(S.flash[id]);
  const title = slot && !filled ? ['elective · choose a course', c.tag || ''] : wrap(c.title || '');
  const slotName = (c.title || '').replace(/\s*electives?$/i, '') || 'Elective';
  const moved = S.plans[0].pos[id] && S.plans[0].pos[id] !== p.pos[id];
  const tag = [filled ? 'elective' : '', isSwapAdded(id, p) ? 'swap' : '', moved ? 'moved' : '', S.notes[code] ? 'note' : ''].filter(Boolean).join(' · ');
  return `<g class="${cl.join(' ')}" data-id="${esc(id)}" transform="translate(${pt.x},${pt.y})"><g class="in">
    <rect class="card" width="${NW}" height="${NH}" rx="4"/><rect class="stripe" width="3" height="${NH}"/>
    <g class="cb"><rect x="11" y="9" width="14" height="14" rx="2"/><path d="M14 16.2l2.8 2.8 5.2-6.2"/></g>
    <text class="code" x="33" y="20.5">${esc(slot && !filled ? slotName : code)}</text>
    <text class="crd" x="${NW - 9}" y="20.5" text-anchor="end">${c.credits}${c.credits_max > c.credits ? '-' + c.credits_max : ''}</text>
    <text class="ttl" x="12" y="37">${esc(title[0] || '')}</text>
    <text class="ttl" x="12" y="49">${esc(title[1] || '')}</text>
    ${tag && !title[1] ? `<text class="tag" x="${NW - 9}" y="49" text-anchor="end">${tag}</text>` : ''}
  </g></g>`;
}

function applyView() { $('#world').setAttribute('transform', `translate(${view.x},${view.y}) scale(${view.k})`); }
function animate() { const w = $('#world'); w.classList.add('anim'); setTimeout(() => w.classList.remove('anim'), 480); }
function fit() {
  if (!L) return;
  const r = $('#stage').getBoundingClientRect(), w = L.cols.length * COLW;
  view.k = Math.max(.85, Math.min(1.15, (r.width - 24) / w, (r.height - 20) / L.h));   // stay readable; scroll for the rest
  view.x = Math.max(12, (r.width - w * view.k) / 2); view.y = 8; applyView();
}
function focusOn(id) {               // pan so a card sits in the middle of the map, then flash it
  const pt = L.at[id]; if (!pt) return;
  const r = $('#stage').getBoundingClientRect();
  if (view.k < .85) view.k = 1;
  view.x = r.width / 2 - (pt.x + NW / 2) * view.k;
  view.y = Math.min(8, r.height / 2 - (pt.y + NH / 2) * view.k);
  animate(); applyView();
  const g = document.querySelector(`.node[data-id="${CSS.escape(id)}"]`);
  if (g) { g.classList.remove('ping'); void g.getBBox(); g.classList.add('ping'); }
}

function refresh(save = true) { render(); chrome(); drawer(); if (save) store(); }

function chrome() {
  $('#planSel').innerHTML = S.plans.map((p, i) => `<option value="${i}" ${i === S.cur ? 'selected' : ''}>${esc(p.name)}</option>`).join('');
  $('#btnExtra').classList.toggle('on', S.extra);
  const errs = V.issues.filter(i => i.lv === 'err').length, lv = level(V.doneCr);
  $('#xpBar').style.width = (100 * V.doneCr / Math.max(1, V.total)) + '%';
  $('#stDone').textContent = `✓ ${V.doneCr} / ${V.total} cr`;
  $('#stLevel').textContent = `Lv ${lv + 1} ${LEVELS[lv][1]}`;
  $('#stProblems').textContent = `${errs ? '✕' : '○'} ${errs} problem${errs === 1 ? '' : 's'}`;
  $('#stProblems').classList.toggle('bad', errs > 0);
  $('#stFinish').textContent = `finish ${tlabel(V.lastKey)}`;
}

/* ───────────── drawer (closed until you ask for it) ───────────── */
function drawer() {
  const el = $('#side');
  const was = el.hidden, top = el.scrollTop;
  el.hidden = !S.drawer;
  if (S.drawer) { el.innerHTML = '<button class="x" data-act="close" title="Close (Esc)">×</button>' + (S.drawer === 'plan' ? dPlan() : dCourse()); el.scrollTop = was ? 0 : top; }
}
const sec = (title, body, open) => body ? `<details ${open ? 'open' : ''} data-sec="${esc(title)}"><summary>${esc(title)}</summary>${body}</details>` : '';
const termOptions = cur => L.cols.map(k => `<option value="${k}" ${k === cur ? 'selected' : ''}>${tlabel(k)}</option>`).join('');
function courseRow(code, right, extra) {
  return `<div class="row" data-act="go" data-id="${esc(code)}"><span class="c">${esc(code)}</span><span class="t">${esc(C(code).title)}</span><span class="s">${right || ''}</span>${extra || ''}</div>`;
}
const where = code => swappedFor(code) && !V.at[code] ? '<span class="muted">swapped</span>' : V.at[code] ? (S.done[V.at[code].id] ? '<span class="ok">✓ done</span>' : tlabel(V.at[code].key)) : 'not in plan';

function dCourse() {
  const p = plan();
  const nid = p.pos[S.sel] ? S.sel : (V.at[S.sel] ? V.at[S.sel].id : null);     // the card on the map, if any
  const slotC = nid && C(nid).kind === 'slot' ? C(nid) : null;
  const code = nid ? eff(nid) : S.sel, c = C(code), placed = nid && p.pos[nid];
  const moveBox = placed ? `<div class="inl"><select id="moveTerm" data-id="${esc(nid)}">${termOptions(placed)}</select>
      ${slotC && code !== nid ? `<button data-act="unpick" data-id="${esc(nid)}">Change</button>` : ''}
      ${!S.plans[0].pos[nid] ? `<button class="danger" data-act="remove" data-id="${esc(nid)}">Remove</button>` : ''}</div>` : '';

  if (slotC && code === nid) {                                  // an empty elective slot
    const pool = S.P.pools[slotC.pool], idx = tidx(placed), season = placed.split('-')[1];
    const req = S.P.requirements.find(r => r.id === slotC.req);
    let h = `<h2>${esc(slotC.title)}</h2><div class="meta">${slotC.credits}${slotC.credits_max > slotC.credits ? '–' + slotC.credits_max : ''} cr · ${tlabel(placed)}</div>`;
    const form = fillForm(nid, slotC, req);
    if (pool) {
      const taken = new Set(Object.values(p.fills)), q = S.find.trim().toLowerCase();
      h += `<input class="f" id="find" placeholder="Filter ${pool.options.length} options" value="${esc(S.find)}">` +
        pool.options.filter(o => !taken.has(o) && !V.at[o] && (!q || (o + ' ' + C(o).title).toLowerCase().includes(q))).map(o => {
          const miss = S.P.edges.filter(e => e.to === o && e.type === 'prereq' && C(e.from).kind !== 'external' && (!V.at[e.from] || V.at[e.from].idx >= idx));
          const st = miss.length ? `<span class="no">needs ${miss.map(e => e.from).join(', ')}</span>` : C(o).offered && !C(o).offered.includes(season) ? `${C(o).offered.map(s => SNAME[s]).join('/')} only` : '<span class="ok">fits</span>';
          return `<div class="row" data-act="pick" data-slot="${esc(nid)}" data-id="${esc(o)}"><span class="c">${esc(o)}</span><span class="t">${esc(C(o).title)}</span><span class="s">${st}</span></div>`;
        }).join('');
      h += sec('Something else', form) + sec('Rule', `<div class="note">${esc(pool.rule)}</div>`);
    } else {
      h += form;
      if (req) h += sec('Rule', `<div class="note">${esc(req.text)}</div>`);
    }
    h += sec('My notes', noteBox(nid), true);
    return h + sec('Move', moveBox);
  }

  const pre = S.P.edges.map((e, i) => ({ ...e, i })).filter(e => e.to === code);
  const unl = V.E.filter(e => e.from === code), allDown = chain(code, 'down');
  const st = nid ? status(nid) : null;
  let h = `<h2>${esc(code)}</h2><div class="sub">${esc(c.title)}</div>
    <div class="meta">${c.credits} cr${placed ? ' · ' + tlabel(placed) : ' · not in this plan'}${c.offered ? ' · ' + c.offered.map(s => SNAME[s]).join('/') + ' only' : ''}${st ? ` · <span class="${{ done: 'ok', ready: 'bl' }[st] || ''}">${st}</span>` : ''}</div>`;
  h += placed ? `<button class="wide ${S.done[nid] ? '' : 'go'}" data-act="done" data-id="${esc(nid)}">${S.done[nid] ? '✓ Completed · undo' : 'Mark completed'}</button>`
              : `<div class="inl" style="margin-bottom:10px"><select id="addTerm">${termOptions()}</select><button class="primary" data-act="addplan" data-id="${esc(code)}">Add to plan</button></div>`;
  h += V.issues.filter(i => i.id === nid && i.lv === 'err').map(i => `<div class="issue" style="margin-bottom:8px">${esc(i.msg)}</div>`).join('');

  h += sec(`Needs first · ${pre.length}`, pre.map(e => courseRow(e.from, (e.type.endsWith('coreq') ? 'with · ' : '') + where(e.from),
      `<span class="del" data-act="deledge" data-i="${e.i}" title="Remove this link">×</span>`)).join('') || '<div class="muted">Nothing. Take it any time.</div>', true);
  h += sec(`Unlocks · ${unl.length}${allDown.size > unl.length ? ' (' + allDown.size + ' down the line)' : ''}`, unl.map(e => courseRow(e.to, where(e.to))).join(''));
  const slotReq = slotC && S.P.requirements.find(r => r.id === slotC.req);
  if (slotReq && slotReq.items.length) h += sec('Counts toward', slotReq.items.map((it, i) => meetBox(slotReq.id + ':' + i, it, (p.meets[nid] || []).includes(slotReq.id + ':' + i), nid)).join(''), true);
  h += sec('My notes', noteBox(code), true);
  h += sec('Move', moveBox);
  const mine = SUBS().filter(x => x.replaces.includes(code)), standsIn = activeSubs(p).filter(x => x.with.includes(code));
  h += sec(`Swap this course${mine.length ? ' · ' + mine.length : ''}`, standsIn.map(x => `<div class="note">Part of the swap for ${esc(x.replaces.join(', '))}.</div>`).join('') +
    mine.map(swapRow).join('') +
    `<div class="muted" style="font-size:12px;margin-top:8px">Define a swap for ${esc(code)} (saved to the program, for everyone):</div>
    <div class="inl"><input id="swWith" placeholder="Courses, e.g. MATH 235, MATH 331"></div>
    <div class="inl" style="margin-top:6px"><input id="swLabel" placeholder="Label, e.g. Math minor path"><button data-act="addsub" data-id="${esc(code)}">Add</button></div>`);
  const info = V.issues.filter(i => i.id === nid && i.lv === 'info').map(i => `<div class="issue info">${esc(i.msg)}</div>`).join('');
  const pdf = [...(c.note_text || []), ...((nid && nid !== code && C(nid).note_text) || [])].map(n => `<div class="note">${esc(n)}</div>`).join('');
  h += sec('From the PDF', info + pdf);
  h += sec('Edit', `<div class="inl"><input id="edTitle" value="${esc(c.title)}" placeholder="Title"><input id="edCr" value="${c.credits}" style="flex:0 0 44px"><button data-act="savecourse" data-id="${esc(code)}">Save</button></div>
    ${c.kind === 'custom' ? '<div class="muted" style="font-size:12px">Your own course: only you see it.</div>' : `<div class="inl"><input id="newPre" placeholder="Add prerequisite, e.g. MATH 132"><select id="newPreType" style="flex:0 0 78px"><option value="prereq">before</option><option value="coreq">with</option></select><button data-act="addedge" data-id="${esc(code)}">Add</button></div>`}`);
  return h;
}

const swapRow = x => { const on = !!(plan().swaps || {})[x.id];
  return `<div class="row" style="cursor:default"><span class="t" style="white-space:normal"><b class="mono" style="font-size:12px">${esc(subLine(x))}</b><br>${esc(x.label || '')}</span>
    <button class="${on ? '' : 'go'}" data-act="swap" data-sub="${esc(x.id)}" data-on="${on ? 0 : 1}">${on ? 'Turn off' : 'Turn on'}</button></div>`; };
const noteBox = key => `<textarea id="note" data-code="${esc(key)}" placeholder="Professor, section, what to review, who to ask…">${esc(S.notes[key] || '')}</textarea>`;
const meetBox = (key, label, on, slot) => `<label class="chk"><input type="checkbox" name="meet" value="${esc(key)}" ${slot ? `data-meet="${esc(slot)}"` : ''} ${on ? 'checked' : ''}><span>${esc(label)}</span></label>`;
function fillForm(slot, slotC, req) {            // "What are you taking?" - any course, even one the PDF never listed
  return `<form id="fillForm" data-slot="${esc(slot)}" autocomplete="off">
    <div class="muted" style="font-size:12px;margin-bottom:6px">What are you taking?</div>
    <div class="inl"><input name="ccode" placeholder="Course code, e.g. HISTORY 101" required><input name="ccr" value="${slotC.credits}" title="Credits" style="flex:0 0 44px"></div>
    <input class="f" name="ctitle" placeholder="Title (optional)" style="margin-top:6px">
    ${req && req.items.length ? `<div class="muted" style="font-size:12px;margin-top:8px">Which of these does it satisfy?</div>` + req.items.map((it, i) => meetBox(req.id + ':' + i, it)).join('') : ''}
    <button class="primary wide" type="submit" style="margin-top:8px">Fill this slot</button></form>`;
}
function fillSlot(slot, code, meets) {
  const q = editable(); q.fills[slot] = code; q.meets = q.meets || {};
  if (meets && meets.length) q.meets[slot] = meets; else delete q.meets[slot];
  if (S.notes[slot]) { S.notes[code] = S.notes[code] ? S.notes[code] + '\n' + S.notes[slot] : S.notes[slot]; delete S.notes[slot]; }
  S.sel = slot; S.find = ''; refresh();
}
const chk = (key, label) => `<label class="chk"><input type="checkbox" data-chk="${esc(key)}" ${S.checks[key] ? 'checked' : ''}><span>${esc(label)}</span></label>`;
function dPlan() {
  const p = plan(), off = S.plans[0], vo = validate(off);
  const moved = Object.keys(p.pos).filter(id => off.pos[id] && off.pos[id] !== p.pos[id]), added = Object.keys(p.pos).filter(id => !off.pos[id]);
  const delta = tidx(V.lastKey) - tidx(vo.lastKey), errs = V.issues.filter(i => i.lv === 'err'), infos = V.issues.filter(i => i.lv === 'info');
  let h = `<h2>${esc(p.name)}</h2><div class="meta">${p.locked ? 'as printed in the PDF · drag a course to branch a copy' : 'compared with the official plan'}</div>
    <div class="stat">
      <div><b class="ok">${V.doneCr}</b><span>credits completed</span></div>
      <div><b>${V.total - V.doneCr}</b><span>credits to go</span></div>
      <div><b class="${errs.length ? 'no' : ''}">${errs.length}</b><span>problems</span></div>
      <div><b>${tlabel(V.lastKey)}</b><span>finish${delta ? ` · ${delta > 0 ? 'later' : 'earlier'} than official` : ''}</span></div>
    </div><div class="btns">
      ${errs.some(e => e.fix) ? '<button class="primary" data-act="autofix">Fix by pushing courses later</button>' : ''}
      ${p.locked ? '' : '<button data-act="rename">Rename</button><button data-act="reset">Reset</button><button class="danger" data-act="delplan">Delete</button>'}
    </div>`;
  h += sec(`Problems · ${errs.length}`, errs.map(i => `<div class="issue" data-act="go" data-id="${esc(i.id || '')}">${esc(i.msg)}</div>`).join('') || '<div class="muted">None. Every prerequisite is in order.</div>', true);
  h += sec(`Changes from official · ${moved.length + added.length}`, moved.map(id => `<div class="row" data-act="go" data-id="${esc(id)}"><span class="c">${esc(C(id).kind === 'slot' ? C(id).title : id)}</span><span class="t"></span><span class="s">${tlabel(off.pos[id])} → ${tlabel(p.pos[id])}</span></div>`).join('') +
    added.map(id => courseRow(id, '+ ' + tlabel(p.pos[id]))).join(''));
  let cum = 0;
  h += sec('Credits by term', L.cols.filter(k => V.load[k]).map(k => { cum += V.load[k]; return `<div class="row" style="cursor:default"><span class="c">${tlabel(k)}</span><span class="t"></span><span class="s">${V.load[k]} cr · total ${cum}</span></div>`; }).join(''));
  for (const pool of Object.values(S.P.pools)) {
    const slots = Object.keys(p.pos).filter(id => C(id).pool === pool.id), chosen = slots.filter(id => p.fills[id]);
    const hi = chosen.filter(id => /\s[5-9]\d\d/.test(p.fills[id])).length;
    h += sec(`${pool.label} · ${chosen.length}/${slots.length}`, `<div class="bar"><i style="width:${100 * chosen.length / Math.max(1, slots.length)}%"></i></div>
      ${/500-level/.test(pool.rule) ? `<div class="muted" style="font-size:12px">${hi} at 500-level or above</div>` : ''}` +
      slots.map(id => p.fills[id] ? courseRow(p.fills[id], tlabel(p.pos[id])) : `<div class="row" data-act="go" data-id="${esc(id)}"><span class="c muted">empty slot</span><span class="t"></span><span class="s">${tlabel(p.pos[id])}</span></div>`).join('') + `<div class="note">${esc(pool.rule)}</div>`);
  }
  const via = {};                                  // checklist key -> courses in this plan that meet it
  for (const id in p.meets || {}) if (p.pos[id] && p.fills[id]) p.meets[id].forEach(k => (via[k] = via[k] || []).push(p.fills[id]));
  for (const r of S.P.requirements) h += sec(r.label, r.items.map((it, i) => { const k = r.id + ':' + i;
    return via[k] ? `<label class="chk"><input type="checkbox" checked disabled><span>${esc(it)} <span class="muted">· ${esc(via[k].join(', '))}</span></span></label>` : chk(k, it); }).join('') + `<div class="note">${esc(r.text)}</div>`);
  if ((S.P.rules || []).length) h += sec('Rules found by AI', S.P.rules.map((r, i) => chk('rule:' + i, r)).join(''));
  h += sec(`Swaps · ${activeSubs(p).length}/${SUBS().length}`, SUBS().map(swapRow).join('') || '<div class="muted">None in this program. Open a course to define one.</div>');
  h += sec('Heads-up · ' + infos.length, infos.map(i => `<div class="issue info" data-act="go" data-id="${esc(i.id || '')}">${esc(i.msg)}</div>`).join(''));
  h += sec('Program', `<pre class="log">${esc((S.P.log || []).join('\n'))}</pre>
    ${S.ai && S.ai.msg ? `<div class="note">${esc(S.ai.msg)}</div>` : ''}
    <div class="inl" style="margin-top:8px"><input id="ncCode" placeholder="Add course, e.g. MATH 233"><input id="ncCr" placeholder="cr" style="flex:0 0 44px"><button data-act="newcourse">Add</button></div>
    <div class="btns" style="margin-top:8px"><button data-act="renameprog">Rename program</button><button class="danger" data-act="delprog">Delete program</button></div>`);
  return h;
}

/* ───────────── actions ───────────── */
function select(id, pan) {
  S.sel = id || null; S.find = '';
  S.drawer = id ? 'course' : (S.drawer === 'plan' ? 'plan' : null);
  render(); drawer();
  if (pan && id) focusOn(plan().pos[id] ? id : (V.at[id] || {}).id);
}
function go(code) {                  // jump to a course wherever it is: pan + highlight, or offer to add it
  const nid = plan().pos[code] ? code : (V.at[code] || {}).id;
  S.q = ''; $('#q').value = ''; $('#qList').hidden = true;
  select(nid || code, true);
}
function toast(m, html) { const t = $('#toast'); t[html ? 'innerHTML' : 'textContent'] = m; t.classList.add('on'); clearTimeout(toast.t); toast.t = setTimeout(() => t.classList.remove('on'), 3600); }
function moveTo(id, key) {
  const p = editable(); if (p.pos[id] === key) return; p.pos[id] = key; refresh();
  const n = V.issues.filter(i => i.lv === 'err').length;
  if (n) toast(`${n} problem${n > 1 ? 's' : ''}. Click the red count at the bottom to see or fix.`);
}
const normCode = s => { const m = s.toUpperCase().trim().match(/^([A-Z&\-]+)\s*(H?\d{3}[A-Z]{0,3})$/); return m ? m[1] + ' ' + m[2] : null; };

$('#side').addEventListener('click', async e => {
  const el = e.target.closest('[data-act]'); if (!el) return;
  const a = el.dataset.act, id = el.dataset.id, p = plan();
  if (a === 'close') { S.drawer = null; S.sel = null; render(); drawer(); }
  else if (a === 'go') { if (id) go(id); }
  else if (a === 'done') toggleDone(id);
  else if (a === 'pick') fillSlot(el.dataset.slot, id);
  else if (a === 'unpick') { const q = editable(); delete q.fills[id]; delete (q.meets || {})[id]; refresh(); }
  else if (a === 'remove') { const q = editable(); delete q.pos[id]; delete q.fills[id]; delete S.done[id]; S.sel = null; S.drawer = null; refresh(); }
  else if (a === 'addplan') { const k = $('#addTerm').value; editable().pos[id] = k; S.sel = id; refresh(); focusOn(id); }
  else if (a === 'autofix') autoFix();
  else if (a === 'swap') setSwap(subById(el.dataset.sub), el.dataset.on === '1');
  else if (a === 'addsub') {
    const w = $('#swWith').value.split(',').map(x => x.trim()).filter(Boolean), codes = w.map(normCode);
    if (!codes.length || codes.includes(null)) return toast('List course codes separated by commas, e.g. MATH 235, MATH 331.');
    if (codes.includes(id)) return toast(`${id} cannot stand in for itself.`);
    const sub = { id: 'sub-u' + Date.now().toString(36), replaces: [id], with: [...new Set(codes)], label: $('#swLabel').value.trim(), source: 'user' };
    sub.with.forEach(c => { if (!S.P.courses[c]) S.P.courses[c] = { code: c, title: (S.custom[c] || {}).title || '', credits: (S.custom[c] || {}).credits || 3, kind: 'alternate', note_text: [] }; });
    S.P.substitutions = [...SUBS(), sub]; await saveProgram(); refresh(false); toast('Swap saved to the program. Turn it on to try it.');
  }
  else if (a === 'reset') { p.pos = { ...S.plans[0].pos }; p.fills = {}; p.meets = {}; p.swaps = {}; p.swapped = {}; refresh(); }
  else if (a === 'rename') { const n = prompt('Plan name', p.name); if (n) { p.name = n; refresh(); } }
  else if (a === 'delplan') { S.plans.splice(S.cur, 1); S.cur = 0; refresh(); }
  else if (a === 'deledge') { e.stopPropagation(); S.P.edges.splice(+el.dataset.i, 1); await saveProgram(); refresh(false); }
  else if (a === 'addedge') {
    const from = normCode($('#newPre').value); if (!from) return toast('Type a course code like MATH 132.');
    if (!S.P.courses[from]) S.P.courses[from] = { code: from, title: '', credits: 3, kind: 'external', note_text: [] };
    S.P.edges.push({ from, to: id, type: $('#newPreType').value, source: 'user' }); await saveProgram(); refresh(false);
  }
  else if (a === 'savecourse' && !S.P.courses[id] && S.custom[id]) { Object.assign(S.custom[id], { title: $('#edTitle').value, credits: +$('#edCr').value || S.custom[id].credits }); refresh(); toast('Saved to your account.'); }
  else if (a === 'savecourse') { const c = S.P.courses[id]; c.title = $('#edTitle').value; c.credits = +$('#edCr').value || c.credits; await saveProgram(); refresh(false); toast('Saved.'); }
  else if (a === 'newcourse') {
    const code = normCode($('#ncCode').value); if (!code) return toast('Type a course code like MATH 233.');
    S.P.courses[code] = S.P.courses[code] || { code, title: '', credits: +$('#ncCr').value || 3, kind: 'elective', note_text: [] };
    await saveProgram(); select(code);
  }
  else if (a === 'renameprog') { const n = prompt('Program name', S.P.name); if (n) { S.P.name = n; await saveProgram(); loadPrograms(S.P.id); } }
  else if (a === 'delprog') { if (confirm('Delete this program for everyone?')) { const r = await api('/api/program/' + S.P.id, { method: 'DELETE' }); if (r.ok) loadPrograms(); else toast((await r.json()).error); } }
});
$('#side').addEventListener('submit', e => {
  e.preventDefault();
  const f = e.target, v = n => f.elements.namedItem(n).value.trim();
  if (f.id === 'fillForm') {
    const code = normCode(v('ccode')), slot = f.dataset.slot;
    if (!code) return toast('Type a course code like HISTORY 101.');
    if (V.at[code]) return toast(`${code} is already in this plan (${tlabel(V.at[code].key)}).`);
    const meets = [...f.querySelectorAll('input[name=meet]:checked')].map(x => x.value);
    if (!S.P.courses[code]) S.custom[code] = { title: v('ctitle'), credits: +v('ccr') || C(slot).credits,
      tags: meets.map(k => { const [r, i] = k.split(':'); return tagOf(S.P.requirements.find(x => x.id === r).items[i]); }).filter(Boolean) };
    fillSlot(slot, code, meets);
  }
});
$('#side').addEventListener('change', e => {
  if (e.target.id === 'moveTerm') moveTo(e.target.dataset.id, e.target.value);
  if (e.target.dataset.meet) {                        // re-tag which checklist item a filled slot satisfies
    const q = editable(), slot = e.target.dataset.meet, set = new Set(q.meets[slot] || []);
    e.target.checked ? set.add(e.target.value) : set.delete(e.target.value);
    if (set.size) q.meets[slot] = [...set]; else delete q.meets[slot];
    refresh();
  }
  if (e.target.dataset.chk) { S.checks[e.target.dataset.chk] = e.target.checked; store(); }
});
$('#side').addEventListener('input', e => {
  if (e.target.id === 'note') {                       // notes save as you type
    const k = e.target.dataset.code, v = e.target.value;
    if (v.trim()) S.notes[k] = v.slice(0, 4000); else delete S.notes[k];
    store();
  }
  if (e.target.id === 'find') { S.find = e.target.value; const pos = e.target.selectionStart; drawer(); const f = $('#find'); f.focus(); f.setSelectionRange(pos, pos); }
});
$('#planSel').addEventListener('change', e => { S.cur = +e.target.value; refresh(); });
$('#btnFork').addEventListener('click', () => { fork(); refresh(); toast(`"${plan().name}" created. Drag courses to try a different path.`); });
$('#btnExtra').addEventListener('click', () => { S.extra = !S.extra; refresh(); });
$('#progSel').addEventListener('change', async e => { await flush(); loadPrograms(e.target.value); });
$('#btnUpload').addEventListener('click', () => openUpload());
$('#stProblems').addEventListener('click', () => { S.drawer = 'plan'; drawer(); });
$('#stDone').addEventListener('click', () => { S.drawer = 'plan'; drawer(); });
$('#status').addEventListener('click', e => {
  const z = e.target.dataset.z; if (!z) return;
  if (z === 'fit') return fit();
  const r = $('#stage').getBoundingClientRect(); zoomAt(r.width / 2, r.height / 2, z === 'in' ? 1.2 : 1 / 1.2);
});

/* ───────────── search: type, see matches light up, Enter to fly there ───────────── */
let qi = 0, qHits = [];
function qRender() {
  const q = S.q.trim().toLowerCase(), box = $('#qList');
  qHits = !q ? [] : [...Object.values(S.P.courses), ...Object.keys(S.custom).filter(k => !S.P.courses[k]).map(C)].filter(c => c.kind !== 'slot' && (c.code + ' ' + c.title).toLowerCase().includes(q))
    .sort((a, b) => (V.at[b.code] ? 1 : 0) - (V.at[a.code] ? 1 : 0) || a.code.localeCompare(b.code)).slice(0, 9);
  qi = Math.min(qi, Math.max(0, qHits.length - 1));
  box.hidden = !q;
  box.innerHTML = qHits.map((c, i) => `<div class="${i === qi ? 'on' : ''}" data-code="${esc(c.code)}"><b>${esc(c.code)}</b><span>${esc(c.title)}</span><em>${V.at[c.code] ? tlabel(V.at[c.code].key) : 'not in plan'}</em></div>`).join('') || '<div><span>No course matches.</span></div>';
}
$('#q').addEventListener('input', e => { S.q = e.target.value; qi = 0; if (S.sel) { S.sel = null; if (S.drawer === 'course') S.drawer = null; drawer(); } render(); qRender(); });
$('#q').addEventListener('keydown', e => {
  if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { e.preventDefault(); qi = (qi + (e.key === 'ArrowDown' ? 1 : -1) + qHits.length) % Math.max(1, qHits.length); qRender(); }
  else if (e.key === 'Enter' && qHits[qi]) { go(qHits[qi].code); e.target.blur(); }
  else if (e.key === 'Escape') { S.q = ''; e.target.value = ''; $('#qList').hidden = true; render(); e.target.blur(); }
});
$('#qList').addEventListener('mousedown', e => { const d = e.target.closest('[data-code]'); if (d) { e.preventDefault(); go(d.dataset.code); } });
$('#q').addEventListener('blur', () => setTimeout(() => $('#qList').hidden = true, 120));
$('#q').addEventListener('focus', () => { if (S.q) qRender(); });

/* ───────────── pan / zoom / drag ───────────── */
function zoomAt(cx, cy, f) {
  const k = Math.max(.35, Math.min(2.2, view.k * f));
  view.x = cx - (cx - view.x) * (k / view.k); view.y = cy - (cy - view.y) * (k / view.k); view.k = k; applyView();
}
const svg = $('#svg');
svg.addEventListener('wheel', e => {
  e.preventDefault();
  const r = svg.getBoundingClientRect();
  if (e.ctrlKey || e.metaKey) zoomAt(e.clientX - r.left, e.clientY - r.top, Math.exp(-e.deltaY * .0022));
  else { view.x -= e.shiftKey ? e.deltaY : e.deltaX; view.y -= e.shiftKey ? 0 : e.deltaY; applyView(); }
}, { passive: false });

let drag = null;
svg.addEventListener('pointerdown', e => {
  if (!S.P || e.button) return;
  const n = e.target.closest('.node'), tick = e.target.closest('.tick');
  drag = { sx: e.clientX, sy: e.clientY, vx: view.x, vy: view.y, id: n ? n.dataset.id : null, moved: false,
           cb: !!e.target.closest('.cb'), term: tick ? tick.dataset.term : null };
  svg.setPointerCapture(e.pointerId);
});
svg.addEventListener('pointermove', e => {
  if (!drag) return;
  const dx = e.clientX - drag.sx, dy = e.clientY - drag.sy;
  if (!drag.moved && Math.hypot(dx, dy) < 5) return;
  drag.moved = true;
  if (!drag.id) { svg.classList.add('panning'); view.x = drag.vx + dx; view.y = drag.vy + dy; return applyView(); }
  if (!drag.ghost) {
    const g = document.querySelector(`.node[data-id="${CSS.escape(drag.id)}"]`);
    drag.ghost = g.cloneNode(true); drag.ghost.classList.add('ghost'); g.style.opacity = .25;
    $('#nodes').appendChild(drag.ghost); drag.o = L.at[drag.id];
  }
  const x = drag.o.x + dx / view.k, y = drag.o.y + dy / view.k;
  drag.ghost.setAttribute('transform', `translate(${x},${y})`);
  drag.key = L.cols[Math.max(0, Math.min(L.cols.length - 1, Math.floor((x + NW / 2) / COLW)))];
  document.querySelectorAll('.col').forEach(c => c.classList.toggle('drop', c.dataset.key === drag.key));
});
svg.addEventListener('pointerup', () => {
  if (!drag) return;
  const d = drag; drag = null; svg.classList.remove('panning');
  if (!d.moved) {                                // a click
    if (d.term) return toggleTerm(d.term);
    if (d.id && d.cb) return toggleDone(d.id);
    return select(d.id);                         // card = open it, background = close
  }
  if (d.id && d.key) { if (d.key !== plan().pos[d.id]) { S.sel = d.id; S.drawer = 'course'; moveTo(d.id, d.key); } else render(); }
});
window.addEventListener('keydown', e => {
  const typing = /INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName);
  if (e.key === 'Escape' && !typing) { if (!$('#modal').hidden) closeUpload(); else { S.drawer = null; S.sel = null; render(); drawer(); } }
  if ((e.key === '/' && !typing) || ((e.ctrlKey || e.metaKey) && e.key === 'k')) { e.preventDefault(); $('#q').focus(); $('#q').select(); }
  if ((e.ctrlKey || e.metaKey) && e.key === 's') { e.preventDefault(); flush().then(() => toast('Saved to your account.')); }
});
window.addEventListener('beforeunload', () => { if (saveT) flush(); });

/* ───────────── upload ───────────── */
let picked = [];
function openUpload() { $('#modal').hidden = false; $('#upMsg').textContent = ''; }
function closeUpload() { $('#modal').hidden = true; }
const drop = $('#drop'), file = $('#file');
function setPicked(fs) { picked = [...fs].filter(f => /\.pdf$/i.test(f.name)); $('#dropTxt').innerHTML = picked.length ? picked.map(f => esc(f.name)).join('<br>') : '<b>Drop PDFs here</b> or click to choose'; }
drop.addEventListener('click', () => file.click());
file.addEventListener('change', () => setPicked(file.files));
drop.addEventListener('dragover', e => { e.preventDefault(); drop.classList.add('over'); });
drop.addEventListener('dragleave', () => drop.classList.remove('over'));
drop.addEventListener('drop', e => { e.preventDefault(); drop.classList.remove('over'); setPicked(e.dataTransfer.files); });
window.addEventListener('dragover', e => { if (S.user && e.dataTransfer && [...e.dataTransfer.types].includes('Files')) { e.preventDefault(); openUpload(); } });
window.addEventListener('drop', e => e.preventDefault());

async function built(res) {
  const d = await res.json();
  if (!res.ok) { $('#upMsg').textContent = d.error || 'Something went wrong.'; return; }
  closeUpload(); picked = []; setPicked([]); $('#progName').value = '';
  await loadPrograms(d.program.id); S.ai = d.ai;
  toast(`Built ${Object.values(d.program.courses).filter(c => c.kind !== 'slot').length} courses and ${d.program.edges.length} links.`);
  if (d.ai.status === 'running') pollAI(d.program.id);
}
$('#goUpload').addEventListener('click', async () => {
  if (!picked.length) return $('#upMsg').textContent = 'Choose at least one PDF first.';
  const fd = new FormData(); picked.forEach(f => fd.append('files', f)); fd.append('name', $('#progName').value);
  $('#upMsg').textContent = 'Reading the PDF…';
  built(await api('/api/upload', { method: 'POST', body: fd }));
});
$('#goTyped').addEventListener('click', async () => built(await api('/api/typed', { method: 'POST', json: { text: $('#typed').value, name: $('#progName').value } })));
function pollAI(id) {
  const t = setInterval(async () => {
    const a = await (await api('/api/ai/' + id)).json();
    if (a.status === 'running') return;
    clearInterval(t);
    if (a.status === 'done' && S.P && S.P.id === id) { await flush(); await loadPrograms(id); toast('AI pass merged extra rules into your tree.'); }
    S.ai = a; drawer();
  }, 2500);
}

boot();
