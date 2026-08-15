/* The page is a thin shell around finalgrade.web: it picks files, shows what
 * python says about them, and offers the results as downloads.
 *
 * Every decision about grading lives in python, so the browser and the command
 * line cannot disagree.  Nothing here uploads anything -- the only fetches in
 * this file load python itself and the wheel next to this page.
 *
 * state.yaml is the config file, and the single source of truth.  Widgets hold
 * no state of their own: each one edits that text (through python's round-trip
 * yaml, so comments and anything with no widget survive) and then the page is
 * redrawn from it.  Nothing on screen can disagree with the document that
 * grading actually reads.
 */

const PYODIDE = 'https://cdn.jsdelivr.net/pyodide/v0.28.3/full/';

// pyodide already ships these, so the only download that is ours is a 45k
// pure-python wheel
const PKG = ['pandas', 'numpy', 'ruamel-yaml', 'micropip'];

// 30 across 0-100% puts an edge every 3⅓ points
const N_BIN = 30;

const $ = (id) => document.getElementById(id);

const state = {
  py: null,
  api: null,
  seed: null,
  yaml: '',
  csv: null,
  name: null,
  configName: 'config.yaml',
  // a canvas gradebook kept aside to merge grades back into, when the file
  // being graded isn't itself one
  canvasText: null,
  canvasName: null,
  assList: [],
  studentList: [],
  catHintList: [],
  form: null,
  grades: null,
  view: 'total',
  mode: 'final',
  seq: 0,
};

/* ------------------------------------------------------------------ boot */

async function boot() {
  const msg = $('boot-msg');
  try {
    msg.textContent = 'downloading python…';
    const { loadPyodide } = await import(PYODIDE + 'pyodide.mjs');
    state.py = await loadPyodide({ indexURL: PYODIDE });

    msg.textContent = 'downloading pandas…';
    await state.py.loadPackage(PKG);

    msg.textContent = 'installing finalgrade…';
    const wheelList = await findWheels();
    await state.py.runPythonAsync(`
import micropip
await micropip.install(${JSON.stringify(wheelList)}, deps=False)
`);

    state.api = state.py.pyimport('finalgrade.web');
    state.seed = state.py.pyimport('finalgrade.seed');

    $('boot').hidden = true;
  } catch (err) {
    $('boot').innerHTML =
      '<p class="error"><strong>Could not start python.</strong> ' +
      escapeHtml(String(err && err.message ? err.message : err)) + '</p>' +
      '<p class="hint">This page needs a browser with WebAssembly, and a ' +
      'network connection the first time it loads.</p>';
  }
}

/* Wheel filenames carry versions, so they are written at build time into
 * wheel.json rather than guessed here.  'vendor' holds the pure-python
 * packages pyodide doesn't ship (openpyxl, for the banner xlsx), served from
 * this site rather than pypi so the page owes nothing to the network once
 * it has loaded. */
async function findWheels() {
  const res = await fetch('wheel.json', { cache: 'no-cache' });
  if (!res.ok) throw new Error('no wheel.json — was the site built?');
  const { wheel, vendor } = await res.json();
  return [wheel, ...(vendor || [])].map(
    (p) => new URL(p, window.location.href).href);
}

/* --------------------------------------------------------- picking files */

function readFile(file, then) {
  const reader = new FileReader();
  reader.onerror = () => showPickError('Could not read that file.');
  reader.onload = () => then(String(reader.result));
  reader.readAsText(file);
}

function takeFile(file) {
  $('pick-error').hidden = true;

  if (!state.api) {
    return showPickError('Python is still loading — try again in a moment.');
  }
  if (file.size > 40e6) {
    return showPickError('That file is over 40 MB, which is far larger than ' +
      'any gradebook — is it the right one?');
  }

  const isYaml = /\.(ya?ml)$/i.test(file.name);
  readFile(file, (text) =>
    isYaml ? useYaml(file.name, text) : useCsv(file.name, text));
}

function showPickError(text) {
  const el = $('pick-error');
  el.textContent = text;
  el.hidden = false;
}

function useCsv(name, text) {
  const info = toJs(state.api.load_csv(text, name));
  if (!info.ok) return showPickError(info.error);

  // a canvas gradebook arriving alongside a gradescope one is the file to
  // merge grades back into, not a replacement for what is being graded
  if (state.csv && info.source === 'canvas' && !state.sourceIsCanvas) {
    state.canvasText = text;
    state.canvasName = name;
    drawFiles();
    drawExport();
    return;
  }

  state.csv = text;
  state.name = name;
  state.sourceIsCanvas = info.source === 'canvas';
  state.assList = info.ass_list;
  state.studentList = info.student_list;
  state.catHintList = info.cat_hint_list;
  state.grades = null;

  if (state.sourceIsCanvas) {
    state.canvasText = text;
    state.canvasName = name;
  }

  drawRoster();
  fillAssignmentSelects();
  setYaml(state.api.seed_config(text, name));

  $('work').hidden = false;
  refresh();
}

function useYaml(name, text) {
  if (!state.csv) {
    return showPickError('Load a gradebook csv first — a config on its own ' +
      'has nothing to grade.');
  }
  state.configName = name;
  setYaml(text);
  refresh();
}

function setYaml(text) {
  state.yaml = text;
}

/* One place where a change becomes everything the page shows.  Widgets are
 * redrawn from the file, then the file is checked, then -- only if it is
 * usable -- grades and the charts follow. */
function refresh() {
  drawForm();
  if (check()) runGrades();
  else clearGrades();
  drawFiles();
  drawExport();
}

function applyEdit(action, args) {
  const res = toJs(state.api.edit_config(state.yaml, action,
                                         JSON.stringify(args || {})));
  // an edit that cannot apply leaves the document exactly as it was
  if (res.ok) setYaml(res.yaml);
  refresh();
}

/* ------------------------------------------------------------- the check */

function check() {
  const seq = ++state.seq;
  const rep = toJs(state.api.check_config(state.csv, state.yaml, state.name));
  if (seq !== state.seq) return rep.ok;

  const el = $('verdict');
  if (rep.ok) {
    el.className = 'verdict ok';
    el.textContent = 'this config is usable';
  } else {
    el.className = 'verdict bad';
    el.textContent = 'grading cannot run — see below';
  }

  $('messages').innerHTML =
    msgList(rep.error_list, 'error') + msgList(rep.warn_list, 'warn');
  return rep.ok;
}

function msgList(list, kind) {
  return (list || []).map((s) =>
    `<div class="msg ${kind}"><span class="what">${kind}</span>` +
    `${escapeHtml(s)}</div>`).join('');
}

/* ----------------------------------------------------- the policy widgets

 * The markup below is built as html strings.  Everything interpolated is
 * either a number computed here or passed through escapeHtml() -- assignment
 * and category names come from the user's csv and config, so they are not
 * trusted markup. */

function drawForm() {
  const form = toJs(state.api.form_state(state.yaml));
  state.form = form;

  if (!form.ok) {
    $('cats').innerHTML =
      '<p class="empty">This config file cannot be read as yaml, so the ' +
      'controls are paused.</p>';
    ['quick', 'excl-list', 'sub-list', 'waive-list', 'thresh-list',
      'stud-card', 'weight-table'].forEach((id) => ($(id).innerHTML = ''));
    return;
  }

  drawCategories(form);
  drawQuick(form);
  drawExclude(form);
  drawSubstitute(form);
  drawThresh(form);
  drawStudent(form);
  drawWaiveList(form);
  drawRosterFilter(form);

  $('thresh-complete').value = form.complete_thresh
    ? Math.round(form.complete_thresh * 100) : '';
}

function catches(cat) {
  // exactly the substring rule python matches with
  return state.assList.map((a) => a.name).filter((n) => n.includes(cat));
}

function drawCategories(form) {
  if (!form.cat_list.length) {
    $('cats').innerHTML = '<p class="empty">No categories yet — every ' +
      'assignment counts in proportion to its own points.</p>';
    $('cats-hint').textContent = 'Add one to weight homework against exams.';
    return;
  }

  $('cats-hint').textContent =
    'Weights are normalized, so they need not sum to 100.';

  $('cats').innerHTML = form.cat_list.map((c) => {
    const late = c.late || {};
    const on = !!c.late;
    const grace = late.grace_period_minutes;

    return `<div class="cat-card" data-cat="${escapeHtml(c.name)}">
      <div class="cat-head">
        <span class="cat-name">${escapeHtml(c.name)}</span>
        <label class="f">weight
          <input type="number" data-act="weight" min="0" step="1"
            value="${escapeHtml(c.weight)}"></label>
        <span class="cat-share">${c.weight_frac === null ? ''
          : (c.weight_frac * 100).toFixed(1) + '%'}</span>
        <label class="f">drop lowest
          <input type="number" data-act="drop" min="0" step="1"
            value="${c.drop_low || 0}"></label>
        <button type="button" class="x" data-act="remove"
          title="remove ${escapeHtml(c.name)}">&times;</button>
      </div>
      <div class="cat-late">
        <label class="f"><input type="checkbox" data-act="late-on"
          ${on ? 'checked' : ''}> late penalty</label>
        ${on ? `
        <label class="f"><input type="number" data-act="late-per" min="0"
          step="1" value="${pctOf(late.penalty_per_day)}">% per day</label>
        <label class="f"><input type="number" data-act="late-excuse" min="0"
          step="1" value="${late.excuse_day || 0}"> excused days</label>
        <label class="f"><input type="number" data-act="late-grace" min="0"
          step="15" value="${grace === undefined ? 60 : grace}"> min
          grace</label>` : ''}
      </div>
      ${catches(c.name).length ? '' :
        '<div class="cat-hit"><span class="tag error">matches no ' +
        'assignment</span></div>'}
    </div>`;
  }).join('');
}

function pctOf(x) {
  return Math.round((Number(x) || 0) * 100);
}

function drawQuick(form) {
  const have = new Set(form.cat_list.map((c) => c.name));
  const guess = toJs(state.seed.guess_cat_list(
    state.assList.map((a) => a.name), state.catHintList))
    .filter((c) => !have.has(c));

  const label = state.catHintList.length
    ? 'add (from your canvas groups):' : 'add:';

  $('quick').innerHTML =
    (guess.length
      ? `<span class="quick-label">${label}</span>` + guess.map((c) =>
        `<button type="button" data-cat="${escapeHtml(c)}">${escapeHtml(c)}` +
        `</button>`).join('')
      : '') +
    `<button type="button" data-cat="" class="other">+ other…</button>`;
}

/* Where every assignment's real contribution to the final grade is spelled
 * out.  It is the answer to "so what is this worth", which is otherwise two
 * multiplications away from anything on screen. */
function drawWeightTable() {
  const res = state.grades;
  if (!res || !res.row_list.length) return ($('weight-table').innerHTML = '');

  let last = null;
  const row = res.row_list.map((r) => {
    // a category spans its assignments: naming it once reads as a group
    const cat = r.category === last ? '' : (r.category || '—');
    last = r.category;

    return `<tr${cat ? ' class="grp"' : ''}>
      <td class="cat">${escapeHtml(cat)}</td>
      <td class="name">${escapeHtml(r.assignment)}</td>
      <td class="num">${fmtNum(r.points)}</td>
      <td class="num">${frac(r.weight_in_cat)}</td>
      <td class="num strong">${frac(r.weight_total)}</td>
      <td class="num">${pct(r.mean_nonzero)}</td>
      <td class="num">${r.n_complete}/${r.n_student}</td>
    </tr>`;
  }).join('');

  $('weight-table').innerHTML = `<table class="weights">
    <thead><tr>
      <th>category</th><th>assignment</th><th class="num">points</th>
      <th class="num">of category</th><th class="num">of grade</th>
      <th class="num">mean*</th><th class="num">submitted</th>
    </tr></thead><tbody>${row}</tbody></table>
    <p class="hint">* mean among non-zero scores</p>`;
}

function frac(x) {
  return x === null || x === undefined ? '–' : `${(x * 100).toFixed(1)}%`;
}

/* ------------------------------------------------------------ assignments */

function fillAssignmentSelects() {
  const opts = state.assList.map((a) =>
    `<option value="${escapeHtml(a.name)}">${escapeHtml(a.name)}</option>`
  ).join('');

  $('excl-add').innerHTML =
    '<option value="">exclude an assignment…</option>' + opts;
  $('sub-target').innerHTML = '<option value="">replace…</option>' + opts;
  $('sub-alt').innerHTML = '<option value="">…</option>' + opts;
}

function drawExclude(form) {
  if (!form.exclude_list.length) {
    return ($('excl-list').innerHTML =
      '<span class="empty">nothing excluded</span>');
  }

  $('excl-list').innerHTML = form.exclude_list.map((s) => {
    const hit = catches(s);
    const title = hit.length ? `removes ${hit.join(', ')}`
      : 'matches no assignment';
    return `<span class="chip" title="${escapeHtml(title)}">` +
      `${escapeHtml(s)}<button type="button" data-excl="${escapeHtml(s)}"
        title="stop excluding">&times;</button></span>`;
  }).join('');
}

function drawSubstitute(form) {
  if (!form.sub_list.length) {
    return ($('sub-list').innerHTML =
      '<span class="empty">no substitutions</span>');
  }

  $('sub-list').innerHTML = form.sub_list.map((s) => {
    const missing = s.ass_list.filter((a) => !catches(a).length);
    const warn = missing.length
      ? `<span class="tag error">no such assignment: ${
        escapeHtml(missing.join(', '))}</span>` : '';
    // alternates double count unless excluded too, which is the mistake this
    // section invites, so offer the fix where the mistake is made
    const open = s.ass_list.filter(
      (a) => !form.exclude_list.some((e) => a.includes(e)));
    const nag = open.length
      ? `<button type="button" class="small nag" data-excl-add="${
        escapeHtml(open.join(','))}">also exclude ${
        escapeHtml(open.join(', '))}</button>` : '';

    return `<div class="sub-row">
      <span class="name">${escapeHtml(s.target)}</span>
      <span class="arrow">← best of</span>
      <span class="name">${escapeHtml(s.ass_list.join(', '))}</span>
      <button type="button" class="x" data-sub="${escapeHtml(s.target)}"
        title="remove">&times;</button>
      ${warn}${nag}
    </div>`;
  }).join('');
}

/* ---------------------------------------------------------- letter grades */

function drawThresh(form) {
  const list = form.thresh_list;
  $('letters-sub').textContent = (list.length && list[0].is_default)
    ? 'the defaults' : `${list.length} letters`;

  $('thresh-list').innerHTML = '<table class="thresh"><tbody>' +
    list.map((t, i) => `<tr>
      <td><input type="number" data-thresh="${i}" data-k="perc" min="0"
        max="100" step="1" class="pct" value="${
        Math.round(t.perc * 1000) / 10}"></td>
      <td class="unit">% and up earns</td>
      <td><input type="text" data-thresh="${i}" data-k="letter" class="ltr"
        value="${escapeHtml(t.letter)}"></td>
      <td><button type="button" class="x" data-thresh-drop="${i}"
        title="remove">&times;</button></td>
    </tr>`).join('') + '</tbody></table>';
}

function threshFromForm() {
  return [...document.querySelectorAll('#thresh-list tr')].map((tr) => ({
    perc: Number(tr.querySelector('[data-k="perc"]').value) / 100,
    letter: tr.querySelector('[data-k="letter"]').value.trim(),
  })).filter((t) => t.letter);
}

/* ---------------------------------------------------------------- students */

function drawRoster() {
  $('roster').innerHTML = state.studentList.map((s) => {
    const name = [s.first, s.last].filter(Boolean).join(' ');
    return `<option value="${escapeHtml(s.email)}">${escapeHtml(name)}` +
      `</option>`;
  }).join('');
}

function pickedStudent() {
  const email = $('stud').value.trim();
  return state.studentList.find((s) => s.email === email) || null;
}

function waiveOf(form, kind) {
  return kind === 'waive_late' ? form.waive_late_list : form.waive_list;
}

function drawStudent(form) {
  if (!form || !form.ok) return;
  const stud = pickedStudent();
  $('stud-clear').hidden = !$('stud').value.trim();

  if (!stud) {
    $('stud-card').innerHTML = $('stud').value.trim()
      ? '<p class="empty">No student with that email. Pick one from the ' +
        'list — the roster comes from your csv, so a student chosen here ' +
        'can never be a typo.</p>'
      : '<p class="empty">Pick a student to see their grade, waive an ' +
        'assignment, or give them extra late days.</p>';
    return;
  }

  const graded = ((state.grades || {}).student_list || [])
    .find((s) => s.email === stud.email);

  $('stud-card').innerHTML = `
    <div class="stud-card">
      <div class="stud-head">
        <span class="stud-name">${escapeHtml(
          [stud.first, stud.last].filter(Boolean).join(' ') || stud.email)
        }</span>
        <span class="stud-email">${escapeHtml(stud.email)}</span>
        ${graded
          ? `<span class="stud-grade">${pct(graded.mean)}<span
              class="stud-letter">${escapeHtml(graded.letter)}</span></span>`
          : '<span class="empty">no grade yet</span>'}
      </div>
      ${graded ? studGrades(graded) : ''}
      ${waiveChecks(form, stud)}
      ${excuseRow(form, stud)}
    </div>`;
}

function studGrades(graded) {
  const cell = ([k, v]) =>
    `<span class="mini"><span class="mini-k">${escapeHtml(k)}</span>` +
    `<span class="mini-v">${pct(v)}</span></span>`;

  const cat = Object.entries(graded.cat_dict).map(cell).join('');
  const ass = Object.entries(graded.ass_dict).map(cell).join('');

  return `<div class="stud-rows">
    ${cat ? `<div class="mini-row">${cat}</div>` : ''}
    <div class="mini-row dim">${ass}</div>
  </div>`;
}

function waiveChecks(form, stud) {
  const row = (kind, label) => {
    const cur = waiveOf(form, kind).find((w) => w.email === stud.email);
    const have = new Set(cur ? cur.ass_list : []);
    return `<div class="waive-row">
      <span class="field-k">${label}</span>
      <div class="checks">${state.assList.map((a) => `<label class="f">
        <input type="checkbox" data-waive="${escapeHtml(a.name)}"
          data-kind="${kind}" ${have.has(a.name) ? 'checked' : ''}>
        ${escapeHtml(a.name)}</label>`).join('')}</div>
    </div>`;
  };

  return row('waive', 'waive assignment') +
         row('waive_late', 'waive late penalty');
}

function excuseRow(form, stud) {
  const late = form.cat_list.filter((c) => c.late);
  if (!late.length) return '';

  return `<div class="waive-row">
    <span class="field-k">extra late days</span>
    <div class="checks">${late.map((c) => {
      const off = ((c.late || {}).excuse_day_offset || {})[stud.email] || 0;
      return `<label class="f">${escapeHtml(c.name)}
        <input type="number" data-excuse="${escapeHtml(c.name)}" step="1"
          value="${off}"></label>`;
    }).join('')}</div>
  </div>`;
}

function drawWaiveList(form) {
  const rows = [
    ...form.waive_list.map((w) => ({ ...w, kind: 'waive' })),
    ...form.waive_late_list.map((w) => ({ ...w, kind: 'waive_late' })),
  ];

  if (!rows.length) return ($('waive-list').innerHTML = '');

  $('waive-list').innerHTML =
    '<table class="waive-table"><caption>waivers in this config</caption>' +
    '<tbody>' + rows.map((w) => `<tr>
      <td><button type="button" class="link" data-goto="${
        escapeHtml(w.email)}">${escapeHtml(w.email)}</button></td>
      <td>${escapeHtml(w.ass_list.join(', '))}</td>
      <td>${w.kind === 'waive_late'
        ? '<span class="tag late">late only</span>' : ''}</td>
      <td><button type="button" class="x" data-drop="${escapeHtml(w.email)}"
        data-kind="${w.kind}" title="remove">&times;</button></td>
    </tr>`).join('') + '</tbody></table>';
}

function drawRosterFilter(form) {
  const n = form.email_list.length;
  $('roster-count').textContent = n ? `${n} students`
    : 'everyone in the csv';
  if (document.activeElement !== $('email-list')) {
    $('email-list').value = form.email_list.join('\n');
  }
}

/* ------------------------------------------------------------------ grades */

function clearGrades() {
  state.grades = null;
  $('inspect-panel').hidden = true;
  $('weight-table').innerHTML = '';
}

function runGrades() {
  const res = toJs(state.api.grade(state.csv, state.yaml, state.name));

  if (!res.ok) {
    state.grades = null;
    $('inspect-panel').hidden = true;
    $('weight-table').innerHTML = '';
    $('messages').innerHTML += msgList([res.error], 'error');
    return;
  }

  state.grades = res;
  $('messages').innerHTML += msgList(res.warn_list, 'warn');
  drawWeightTable();
  drawInspector();
  if (pickedStudent()) drawStudent(state.form);
}

/* --------------------------------------------------------- the inspector */

const MODE_HINT = {
  final: 'The grade as it stands, with drops and late penalties applied.',
  raw: 'The same grade before drop-lowest and late penalties — what the ' +
       'scores alone would give.',
  both: 'Before and after the policy, overlaid. The gap between them is ' +
        'what your drops and late penalties did.',
};

function drawInspector() {
  const res = state.grades;
  if (!res) return;

  $('inspect-panel').hidden = false;
  drawStats(res);

  if (!res.view_list.some((v) => v.key === state.view)) state.view = 'total';

  $('view').innerHTML = optGroup(res.view_list, 'total', 'overall') +
    optGroup(res.view_list, 'category', 'categories') +
    optGroup(res.view_list, 'assignment', 'assignments');
  $('view').value = state.view;

  const pair = res.value_dict[state.view] || { final: [], raw: null };
  const hasRaw = !!pair.raw;
  const mode = hasRaw ? state.mode : 'final';

  // an assignment has no policy of its own, so the toggle would be a lie
  [...$('mode').children].forEach((b) => {
    const m = b.getAttribute('data-mode');
    b.disabled = !hasRaw && m !== 'final';
    b.classList.toggle('on', m === mode);
  });

  $('mode-hint').textContent = hasRaw ? MODE_HINT[mode]
    : 'A single assignment has no drops or late penalties of its own — ' +
      'those apply across a category, so there is nothing to compare here.';

  drawChart(pair, mode);
}

function drawStats(res) {
  const letters = res.letter_list.map((l) =>
    `<span class="ltr-chip"><b>${escapeHtml(l.letter)}</b> ${l.n}</span>`
  ).join('');

  $('stats').innerHTML = `<div class="stats">
    <div class="stat"><span class="k">students</span>
      <span class="v">${res.n_student}</span></div>
    <div class="stat"><span class="k">mean</span>
      <span class="v">${pct(res.mean_avg)}</span></div>
    <div class="stat"><span class="k">median</span>
      <span class="v">${pct(res.mean_median)}</span></div>
    <div class="stat wide"><span class="k">letters</span>
      <span class="ltr-row">${letters}</span></div>
  </div>`;
}

function optGroup(viewList, kind, label) {
  const list = viewList.filter((v) => v.kind === kind);
  if (!list.length) return '';
  return `<optgroup label="${label}">` + list.map((v) =>
    `<option value="${escapeHtml(v.key)}">${escapeHtml(v.label)}</option>`
  ).join('') + '</optgroup>';
}

function studentNames() {
  return ((state.grades || {}).student_list || []).map((s) =>
    [s.first, s.last].filter(Boolean).join(' ') || s.email);
}

function bin(values) {
  return toJs(state.api.bin_values(JSON.stringify(values),
                                   JSON.stringify(studentNames()), N_BIN));
}

const COLOR = { final: '#1f5fa9', raw: '#c98b2e' };

function drawChart(pair, mode) {
  if (!window.Plotly) {
    $('chart').innerHTML =
      '<p class="empty">The chart library is still loading…</p>';
    return void setTimeout(() => drawChart(pair, mode), 400);
  }

  const traceList = [];
  if (mode === 'final' || mode === 'both') {
    traceList.push(trace(bin(pair.final), 'after policy', COLOR.final));
  }
  if ((mode === 'raw' || mode === 'both') && pair.raw) {
    traceList.push(trace(bin(pair.raw), 'before policy', COLOR.raw));
  }

  const dark = window.matchMedia('(prefers-color-scheme: dark)').matches;
  const ink = dark ? '#e8eaed' : '#1a1d21';
  const line = dark ? '#333940' : '#dfe3e8';

  const shapes = [];
  const annotations = [];
  if (state.view === 'total') {
    for (const t of (state.grades.thresh_list || [])) {
      if (t.perc <= 0 || t.perc > 1) continue;
      shapes.push({
        type: 'line', x0: t.perc, x1: t.perc, yref: 'paper', y0: 0, y1: 1,
        line: { color: line, width: 1, dash: 'dot' },
      });
      annotations.push({
        x: t.perc, y: 1, yref: 'paper', text: t.letter, showarrow: false,
        yanchor: 'bottom', font: { size: 10, color: ink }, opacity: .75,
      });
    }
  }

  Plotly.react($('chart'), traceList, {
    barmode: 'overlay',
    bargap: .06,
    margin: { l: 46, r: 14, t: 24, b: 42 },
    height: 340,
    paper_bgcolor: 'rgba(0,0,0,0)',
    plot_bgcolor: 'rgba(0,0,0,0)',
    font: { color: ink, size: 12 },
    xaxis: { title: { text: 'grade' }, tickformat: '.0%',
             gridcolor: line, zerolinecolor: line },
    yaxis: { title: { text: 'students' }, gridcolor: line,
             zerolinecolor: line, rangemode: 'tozero' },
    showlegend: mode === 'both',
    legend: { orientation: 'h', y: 1.12, x: 0 },
    shapes,
    annotations,
    hovermode: 'closest',
  }, { displayModeBar: false, responsive: true });
}

function trace(hist, name, color) {
  const x = [];
  const y = [];
  const custom = [];

  for (let i = 0; i < hist.count_list.length; i++) {
    const lo = hist.edge_list[i];
    const hi = hist.edge_list[i + 1];
    x.push((lo + hi) / 2);
    y.push(hist.count_list[i]);

    // the names are the reason this is binned in python at all
    const list = hist.who_list[i];
    custom.push([
      `${(lo * 100).toFixed(1)}–${(hi * 100).toFixed(1)}%`,
      list.length > 12
        ? list.slice(0, 12).join('<br>') + `<br>…and ${list.length - 12} more`
        : list.join('<br>'),
    ]);
  }

  return {
    type: 'bar', x, y, name,
    width: (hist.edge_list[1] - hist.edge_list[0]) || .05,
    marker: { color, line: { width: 0 } },
    opacity: .8,
    customdata: custom,
    hovertemplate: '<b>%{customdata[0]}</b> · %{y} students' +
      '<br>%{customdata[1]}<extra></extra>',
  };
}

/* --------------------------------------------------------- files & export */

const blobUrl = {};

function fileLink(key, name, text, type) {
  if (blobUrl[key]) URL.revokeObjectURL(blobUrl[key]);
  blobUrl[key] = URL.createObjectURL(new Blob([text], { type }));
  return `<a href="${blobUrl[key]}" download="${escapeHtml(name)}">` +
    `${escapeHtml(name)}</a>`;
}

function drawFiles() {
  if (!state.csv) return ($('files').innerHTML = '');

  const part = [
    '<span class="file-k">files</span>',
    fileLink('csv', state.name, state.csv, 'text/csv'),
    fileLink('yaml', state.configName, state.yaml, 'text/yaml'),
  ];

  if (state.canvasText && !state.sourceIsCanvas) {
    part.push(fileLink('canvas', state.canvasName, state.canvasText,
                       'text/csv') + '<span class="file-note">for canvas ' +
              'export</span>');
  }

  $('files').innerHTML = part.join('<span class="file-sep">·</span>');
}

function drawExport() {
  if (!state.grades) {
    $('export-row').innerHTML = '';
    $('export-hint').textContent =
      'Exports appear once the config grades cleanly.';
    $('banner-form').hidden = true;
    return;
  }

  const canCanvas = !!state.canvasText;
  $('export-row').innerHTML =
    '<button type="button" id="dl-grades">download grade_full.csv</button>' +
    `<button type="button" id="dl-canvas" class="${canCanvas ? '' : 'secondary'}"
      ${canCanvas ? '' : 'disabled'}>export for canvas</button>` +
    '<button type="button" id="dl-banner">export for banner…</button>';

  $('export-hint').textContent = canCanvas
    ? 'The canvas export merges these grades into your canvas gradebook by ' +
      'SIS user id, scaled to 100 so canvas does not round them.'
    : 'To export for canvas, drop your canvas gradebook export ' +
      '(Grades › Export) onto the box above — canvas matches students by its ' +
      'own SIS user id, which only that file carries.';

  $('dl-grades').addEventListener('click', () =>
    download(state.grades.csv, 'grade_full.csv', 'text/csv'));

  if (canCanvas) {
    $('dl-canvas').addEventListener('click', () => {
      const res = toJs(state.api.canvas_export(
        state.csv, state.yaml, state.canvasText, state.name, true));
      if (!res.ok) return ($('export-hint').textContent = res.error);
      download(res.csv, stamped('canvas_upload', 'csv'), 'text/csv');
    });
  }

  $('dl-banner').addEventListener('click', () => {
    const form = $('banner-form');
    form.hidden = !form.hidden;
    if (!form.hidden) $('term-code').focus();
  });
}

/* Banner will only match a row when its CRN, term code and student id all
 * line up, so it needs the two that a gradebook cannot know. */
function runBanner() {
  const term = $('term-code').value.trim();
  const crnList = $('crn-list').value.split(/[\s,]+/).filter(Boolean);

  const res = toJs(state.api.banner_export(
    state.csv, state.yaml, term, JSON.stringify(crnList), state.name));

  const note = $('banner-note');
  if (!res.ok) {
    note.className = 'error';
    note.textContent = res.error;
    return;
  }

  note.className = 'hint';
  note.textContent = `${res.n_row} rows written.`;
  downloadBytes(res.xlsx_b64, stamped('banner', 'xlsx'),
                'application/vnd.openxmlformats-officedocument.' +
                'spreadsheetml.sheet');
}

function stamped(stem, ext) {
  return `${stem}_${new Date().toISOString().slice(0, 10)}.${ext}`;
}

/* ------------------------------------------------------------------ utils */

function toJs(proxy) {
  const out = proxy.toJs({ dict_converter: Object.fromEntries });
  proxy.destroy();
  return out;
}

function download(text, name, type) {
  saveBlob(new Blob([text], { type }), name);
}

/* a workbook is bytes, which is the one thing that does not cross out of
 * python cleanly, so it arrives base64 encoded */
function downloadBytes(b64, name, type) {
  const bin = atob(b64);
  const buf = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) buf[i] = bin.charCodeAt(i);
  saveBlob(new Blob([buf], { type }), name);
}

function saveBlob(blob, name) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = name;
  a.click();
  URL.revokeObjectURL(url);
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[c]));
}

function fmtNum(x) {
  return Number.isInteger(x) ? String(x) : String(Math.round(x * 100) / 100);
}

function pct(x) {
  return x === null || x === undefined ? '–' : `${(x * 100).toFixed(1)}%`;
}

/* ----------------------------------------------------------------- wiring */

$('browse').addEventListener('click', () => $('file').click());
$('file').addEventListener('change', (e) => {
  if (e.target.files[0]) takeFile(e.target.files[0]);
  e.target.value = '';
});

const drop = $('drop');
['dragenter', 'dragover'].forEach((ev) =>
  drop.addEventListener(ev, (e) => {
    e.preventDefault();
    drop.classList.add('over');
  }));
['dragleave', 'drop'].forEach((ev) =>
  drop.addEventListener(ev, (e) => {
    e.preventDefault();
    drop.classList.remove('over');
  }));
drop.addEventListener('drop', (e) => {
  for (const file of e.dataTransfer.files) takeFile(file);
});

$('demo').addEventListener('click', async () => {
  const res = await fetch('example.csv');
  useCsv('example.csv', await res.text());
});

$('quick').addEventListener('click', (e) => {
  const cat = e.target.getAttribute('data-cat');
  if (cat === null) return;
  const name = cat || (prompt('Category name — it matches any assignment ' +
    'whose name contains it:') || '').trim().replace(/\s+/g, '').toLowerCase();
  if (name) applyEdit('add_category', { cat: name });
});

/* number inputs commit on change (blur or enter), not on every keystroke:
 * redrawing mid-keystroke would take the caret with it */
$('cats').addEventListener('change', (e) => {
  const act = e.target.getAttribute('data-act');
  if (!act) return;
  const cat = e.target.closest('.cat-card').getAttribute('data-cat');
  const num = Number(e.target.value);

  if (act === 'weight') applyEdit('set_weight', { cat, weight: num });
  else if (act === 'drop') applyEdit('set_drop_low', { cat, n: num });
  else if (act === 'late-on') {
    applyEdit('set_late', e.target.checked
      ? { cat, late_dict: { penalty_per_day: 0.1, excuse_day: 0 } }
      : { cat, late_dict: null });
  } else if (act === 'late-per') {
    applyEdit('set_late', { cat, late_dict: { penalty_per_day: num / 100 } });
  } else if (act === 'late-excuse') {
    applyEdit('set_late', { cat, late_dict: { excuse_day: num } });
  } else if (act === 'late-grace') {
    applyEdit('set_late', { cat, late_dict: { grace_period_minutes: num } });
  }
});

$('cats').addEventListener('click', (e) => {
  if (e.target.getAttribute('data-act') !== 'remove') return;
  applyEdit('remove_category',
            { cat: e.target.closest('.cat-card').getAttribute('data-cat') });
});

$('excl-add').addEventListener('change', (e) => {
  const name = e.target.value;
  e.target.value = '';
  if (name) {
    applyEdit('set_exclude', { ass_list: [...state.form.exclude_list, name] });
  }
});

$('excl-list').addEventListener('click', (e) => {
  const name = e.target.getAttribute('data-excl');
  if (name === null) return;
  applyEdit('set_exclude',
            { ass_list: state.form.exclude_list.filter((s) => s !== name) });
});

$('sub-go').addEventListener('click', () => {
  const target = $('sub-target').value;
  const alt = $('sub-alt').value;
  if (!target || !alt || target === alt) return;

  const cur = state.form.sub_list.find((s) => s.target === target);
  const list = new Set(cur ? cur.ass_list : []);
  list.add(alt);
  applyEdit('set_substitute', { target, ass_list: [...list] });
});

$('sub-list').addEventListener('click', (e) => {
  const target = e.target.getAttribute('data-sub');
  if (target !== null) {
    return applyEdit('set_substitute', { target, ass_list: [] });
  }
  const add = e.target.getAttribute('data-excl-add');
  if (add !== null) {
    applyEdit('set_exclude',
              { ass_list: [...state.form.exclude_list, ...add.split(',')] });
  }
});

$('thresh-complete').addEventListener('change', (e) =>
  applyEdit('set_complete_thresh', { thresh: Number(e.target.value) / 100 }));

$('thresh-list').addEventListener('change', () =>
  applyEdit('set_grade_thresh', { thresh_list: threshFromForm() }));

$('thresh-list').addEventListener('click', (e) => {
  const i = e.target.getAttribute('data-thresh-drop');
  if (i === null) return;
  const list = threshFromForm();
  list.splice(Number(i), 1);
  applyEdit('set_grade_thresh', { thresh_list: list });
});

$('thresh-add').addEventListener('click', () => {
  const list = threshFromForm();
  const low = list.length ? Math.min(...list.map((t) => t.perc)) : 1;
  list.push({ perc: Math.max(0, low - 0.05), letter: 'new' });
  applyEdit('set_grade_thresh', { thresh_list: list });
});

$('thresh-reset').addEventListener('click', () =>
  applyEdit('set_grade_thresh', { thresh_list: [] }));

$('stud').addEventListener('input', () => drawStudent(state.form));
$('stud-clear').addEventListener('click', () => {
  $('stud').value = '';
  drawStudent(state.form);
});

$('stud-card').addEventListener('change', (e) => {
  const stud = pickedStudent();
  if (!stud) return;

  const ass = e.target.getAttribute('data-waive');
  if (ass !== null) {
    const kind = e.target.getAttribute('data-kind');
    const cur = waiveOf(state.form, kind).find((w) => w.email === stud.email);
    const set = new Set(cur ? cur.ass_list : []);
    if (e.target.checked) set.add(ass); else set.delete(ass);
    return applyEdit('set_waive',
                     { email: stud.email, ass_list: [...set], field: kind });
  }

  const cat = e.target.getAttribute('data-excuse');
  if (cat !== null) {
    applyEdit('set_excuse_offset',
              { cat, email: stud.email, days: Number(e.target.value) });
  }
});

$('waive-list').addEventListener('click', (e) => {
  const goto = e.target.getAttribute('data-goto');
  if (goto !== null) {
    $('stud').value = goto;
    drawStudent(state.form);
    $('stud').scrollIntoView({ block: 'center' });
    return;
  }
  const email = e.target.getAttribute('data-drop');
  if (email !== null) {
    applyEdit('set_waive', {
      email, ass_list: [], field: e.target.getAttribute('data-kind'),
    });
  }
});

$('email-save').addEventListener('click', () =>
  applyEdit('set_email_list', {
    email_list: $('email-list').value.split(/[\n,]/)
      .map((s) => s.trim()).filter(Boolean),
  }));

$('email-clear').addEventListener('click', () => {
  $('email-list').value = '';
  applyEdit('set_email_list', { email_list: [] });
});

$('banner-go').addEventListener('click', runBanner);
$('banner-form').addEventListener('keydown', (e) => {
  if (e.key === 'Enter') runBanner();
});

$('view').addEventListener('change', (e) => {
  state.view = e.target.value;
  drawInspector();
});

$('mode').addEventListener('click', (e) => {
  const mode = e.target.getAttribute('data-mode');
  if (!mode || e.target.disabled) return;
  state.mode = mode;
  drawInspector();
});

boot();
