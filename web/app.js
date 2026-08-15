/* The page is a thin shell around finalgrade.web: it picks files, shows what
 * python says about them, and offers the results as downloads.
 *
 * Every decision about grading lives in python, so the browser and the command
 * line cannot disagree.  Nothing here uploads anything -- the only fetches in
 * this file load python itself and the wheel next to this page.
 *
 * state.yaml is the policy file, and the single source of truth.  Widgets hold
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
  policyName: 'policy.yaml',
  // a canvas gradebook kept aside to merge grades back into, when the file
  // being graded isn't itself one
  canvasText: null,
  canvasName: null,
  assList: [],
  studentList: [],
  catHintList: [],
  form: null,
  grades: null,
  // last mean seen per student, so an edit can show what it moved
  meanSeen: {},
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
  // which format it was read as is not cosmetic: it decides whether late
  // penalties are available at all, so it belongs next to the filename
  state.facts = `${info.source}, ${info.n_student} students, ` +
    `${info.ass_list.length} assignments`;
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
  setYaml(state.api.seed_policy(text, name));

  $('work').hidden = false;
  refresh();
}

function useYaml(name, text) {
  if (!state.csv) {
    return showPickError('Load a gradebook csv first — a policy on its own ' +
      'has nothing to grade.');
  }
  state.policyName = name;
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
  const res = toJs(state.api.edit_policy(state.yaml, action,
                                         JSON.stringify(args || {})));
  // an edit that cannot apply leaves the document exactly as it was
  if (res.ok) setYaml(res.yaml);
  refresh();
}

/* ------------------------------------------------------------- the check */

function check() {
  const seq = ++state.seq;
  const rep = toJs(state.api.check_policy(state.csv, state.yaml, state.name));
  if (seq !== state.seq) return rep.ok;

  state.report = rep;

  // whatever belongs to one assignment is shown on that assignment; what is
  // left is about the file, the roster or the letters, and has nowhere else
  // to go
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
 * and category names come from the user's csv and policy, so they are not
 * trusted markup. */

function drawForm() {
  const form = toJs(state.api.form_state(state.yaml));
  state.form = form;

  if (!form.ok) {
    $('cats').innerHTML =
      '<p class="empty">This policy file cannot be read as yaml, so the ' +
      'controls are paused.</p>';
    ['quick', 'excl-list', 'sub-list', 'waive-list', 'thresh-list',
      'stud-card', 'weight-table'].forEach((id) => ($(id).innerHTML = ''));
    return;
  }

  drawCategories(form);
  drawQuick(form);
  drawExclude(form);
  drawPlanned(form);
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

  const problem = ((state.report || {}).ass_problem_dict) || {};

  let last = null;
  const row = res.row_list.map((r) => {
    // a category spans its assignments: naming it once reads as a group
    const cat = r.category === last ? '' : (r.category || '—');
    last = r.category;

    // a complaint about an assignment belongs on that assignment's row,
    // where whoever is reading the weights is already looking
    const note = (problem[r.assignment] || []).map((s) =>
      `<div class="row-warn">${escapeHtml(s)}</div>`).join('');

    const cls = [cat ? 'grp' : '', note ? 'flag-none' : ''].filter(Boolean);

    return `<tr${cls.length ? ` class="${cls.join(' ')}"` : ''}>
      <td class="cat">${escapeHtml(cat)}</td>
      <td class="name">${escapeHtml(r.assignment)}${note}</td>
      <td class="num">${fmtNum(r.points)}</td>
      <td class="num">${frac(r.weight_in_cat)}</td>
      <td class="num strong">${frac(r.weight_total)}</td>
      <td class="num">${pct(r.mean_nonzero)}</td>
      <td class="num">${r.n_complete}/${r.n_student}</td>
    </tr>`;
  }).join('');

  // an assignment that is not being graded still has to appear, or the table
  // quietly agrees that it never existed
  const gone = ((state.report || {}).excluded_list || []).map((a) => `
    <tr class="dropped">
      <td class="cat">—</td>
      <td class="name">${escapeHtml(a.name)}
        <div class="row-warn">not graded: ${escapeHtml(a.excluded_by)}</div>
      </td>
      <td class="num">${a.points === null ? '–' : fmtNum(a.points)}</td>
      <td class="num">–</td><td class="num">–</td><td class="num">–</td>
      <td class="num">${a.n_complete === null ? '–'
        : `${a.n_complete}/${a.n_student}`}</td>
    </tr>`).join('');

  $('weight-table').innerHTML = `<table class="weights">
    <thead><tr>
      <th>category</th><th>assignment</th><th class="num">points</th>
      <th class="num">of category</th><th class="num">of grade</th>
      <th class="num">mean*</th><th class="num">submitted</th>
    </tr></thead><tbody>${row}${gone}</tbody></table>
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

function drawPlanned(form) {
  if (!form.plan_list.length) {
    return ($('plan-list').innerHTML =
      '<span class="empty">nothing planned</span>');
  }

  $('plan-list').innerHTML = form.plan_list.map((p) =>
    `<span class="chip" title="not set yet, worth ${p.points} points">` +
    `${escapeHtml(p.name)} <span class="dim">${escapeHtml(p.points)}pt</span>` +
    `<button type="button" data-plan="${escapeHtml(p.name)}"
      title="remove">&times;</button></span>`).join('');
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
        ${graded ? `<button type="button" class="link stud-file"
          id="stud-csv">${escapeHtml(studentFile(stud))}</button>` : ''}
        ${graded
          ? `<span class="stud-grade">${delta(stud, graded)}${pct(graded.mean)}
              <span class="stud-letter">${escapeHtml(graded.letter)}</span>
             </span>`
          : '<span class="empty">no grade yet</span>'}
      </div>
      ${graded ? catRow(graded) : ''}
      ${graded ? scoreGrid(graded) : ''}
      ${graded ? lateGrid(graded) : ''}
      ${excuseRow(form, stud)}
      ${graded ? auditLog(graded) : ''}
    </div>`;
}

function catRow(graded) {
  const cell = ([k, v]) =>
    `<span class="mini"><span class="mini-k">${escapeHtml(k)}</span>` +
    `<span class="mini-v">${pct(v)}</span></span>`;

  const cat = Object.entries(graded.cat_dict).map(cell).join('');
  return cat ? `<div class="mini-row cat-means">${cat}</div>` : '';
}

/* Every score, grouped by the categories the policy already defines, because
 * fifteen chips in one row is a list and four rows of four is a gradebook.
 * Clicking one waives it: the thing an instructor came here to do. */
function scoreGrid(graded) {
  const group = new Map();
  for (const a of graded.ass_list) {
    const key = a.category || 'other';
    if (!group.has(key)) group.set(key, []);
    group.get(key).push(a);
  }

  const block = [...group.entries()].map(([cat, list]) => `
    <div class="grid-group">
      <span class="grid-k">${escapeHtml(cat)}</span>
      <div class="chips">${list.map(scoreChip).join('')}</div>
    </div>`).join('');

  return `<div class="waive-row block">
    <span class="field-k">scores <span class="sub">click to waive</span></span>
    <div class="grid">${block}</div>
  </div>`;
}

function scoreChip(a) {
  let cls = 'score';
  let text;

  if (a.waived) {
    cls += ' is-waived';
    text = 'waived';
  } else if (a.planned) {
    cls += ' is-planned';
    text = 'not set';
  } else if (!a.submitted) {
    // a blank and a zero are both 0 points and mean different things
    cls += ' is-missing';
    text = 'none';
  } else if (a.perc === null) {
    cls += ' is-waived';
    text = '—';
  } else {
    if (a.perc === 0) cls += ' is-zero';
    text = `${Math.round(a.perc * 100)}%`;
  }

  const why = a.waived ? 'waived — click to count it again'
    : a.planned ? 'not assigned yet'
      : !a.submitted ? 'nothing submitted, counts as zero — click to waive'
        : 'click to waive · drag onto another to let this stand in for it';

  return `<button type="button" class="chip ${cls}" data-score="${
    escapeHtml(a.name)}" draggable="true" title="${escapeHtml(why)}">` +
    `<span class="chip-k">${escapeHtml(a.name)}</span>` +
    `<span class="chip-v">${text}</span></button>`;
}

/* Dragging one score onto another gives that student the better of the two,
 * for the makeup only they sat.  The same rule as a policy-wide substitution,
 * without inventing a policy-wide rule to describe one arrangement. */
function dropSubstitute(fromName, toName) {
  const stud = pickedStudent();
  if (!stud || fromName === toName) return;

  const cur = (state.form.stud_sub_list || [])
    .find((s) => s.email === stud.email);
  const target = ((cur || {}).target_dict || {})[toName] || [];

  applyEdit('set_student_sub', {
    email: stud.email,
    target: toName,
    ass_list: [...new Set([...target, fromName])],
  });
}

/* Every assignment a late penalty could act on -- not only the late ones, so
 * a penalty can be forgiven before it is incurred as readily as after, and
 * not the ones in categories with no penalty, where lateness is trivia. */
function lateGrid(graded) {
  const list = graded.ass_list.filter(
    (a) => a.late_counts && (a.submitted || a.late_days));
  if (!list.length) return '';

  const late = graded.late_dict || {};
  const summary = Object.entries(late)
    .filter(([, v]) => v && (v.days_used || v.penalty))
    .map(([name, v]) => `<span class="mini late-mini">
      <span class="mini-k">${escapeHtml(name)}</span>
      <span class="mini-v">${v.days_used} used · ${v.days_excused} excused${
        v.days_unexcused ? ` · <b>${v.days_unexcused} over</b>` : ''}</span>
      ${v.penalty ? `<span class="late-hit">${pct(v.penalty)}</span>` : ''}
    </span>`).join('');

  return `<div class="waive-row block">
    <span class="field-k">late <span class="sub">click to forgive</span></span>
    <div class="grid">
      ${summary ? `<div class="mini-row">${summary}</div>` : ''}
      <div class="chips">${list.map(lateChip).join('')}</div>
    </div>
  </div>`;
}

function lateChip(a) {
  const cls = a.late_waived ? 'late-c is-waived'
    : a.late_days ? 'late-c is-late' : 'late-c';

  // days are what the penalty counts, but "2d" hides whether that was two
  // minutes past a deadline or two whole days
  const exact = a.late_minutes ? ` = ${hhmm(a.late_minutes)}` : '';
  const value = a.late_waived ? 'forgiven'
    : a.late_days ? `${a.late_days}d${exact}`
      : a.late_minutes ? `0d${exact}` : 'on time';

  const why = a.late_waived
    ? 'late penalty forgiven — click to count it again'
    : a.late_minutes && !a.late_days
      ? `${hhmm(a.late_minutes)} late, inside the grace period`
      : 'click to forgive any late penalty on this';

  return `<button type="button" class="chip ${cls}" data-late="${
    escapeHtml(a.name)}" title="${escapeHtml(why)}">` +
    `<span class="chip-k">${escapeHtml(a.name)}</span>` +
    `<span class="chip-v">${escapeHtml(value)}</span></button>`;
}

/* Every step that moved this number, in order.  The question after a final
 * grade is always how it was arrived at, and a list of decisions answers it
 * where a number cannot. */
function auditLog(graded) {
  const list = graded.log_list || [];
  if (!list.length) return '';

  return `<details class="audit">
    <summary>how this grade was computed <span class="sub">${list.length}
      steps</span></summary>
    <ol class="audit-list">${list.map((e) =>
      `<li class="ev ev-${escapeHtml(e.kind)}">` +
      `<span class="ev-k">${escapeHtml(e.kind)}</span>` +
      `${escapeHtml(e.text)}</li>`).join('')}</ol>
  </details>`;
}

/* the same wording python's audit log uses */
function hhmm(minutes) {
  const day = Math.floor(minutes / 1440);
  const hour = Math.floor((minutes % 1440) / 60);
  const min = minutes % 60;

  const part = [];
  if (day) part.push(`${day}d`);
  if (hour) part.push(`${hour}h`);
  if (min || !part.length) part.push(`${min}m`);
  return part.join('');
}

/* A category mean carries its late penalty inside it, so 78% could be a 78%
 * or an 86% with days against it.  This says which. */
function lateRow(graded) {
  const entries = Object.entries(graded.late_dict || {})
    .filter(([, v]) => v && (v.days_used || v.penalty));
  const dayList = Object.entries(graded.late_day_dict || {});

  if (!entries.length && !dayList.length) return '';

  const cat = entries.map(([name, v]) => `
    <span class="mini late-mini">
      <span class="mini-k">${escapeHtml(name)}</span>
      <span class="mini-v">${v.days_used} late ${plural(v.days_used, 'day')}
        · ${v.days_excused} excused${v.days_unexcused
          ? ` · <b>${v.days_unexcused} over</b>` : ''}</span>
      ${v.penalty ? `<span class="late-hit">${pct(v.penalty)}</span>` : ''}
    </span>`).join('');

  const each = dayList.map(([ass, d]) =>
    `<span class="mini"><span class="mini-k">${escapeHtml(ass)}</span>` +
    `<span class="mini-v">${d}d</span></span>`).join('');

  return `<div class="waive-row">
    <span class="field-k">late</span>
    <div class="stud-rows">
      ${cat ? `<div class="mini-row">${cat}</div>` : ''}
      ${each ? `<div class="mini-row dim">${each}</div>` : ''}
    </div>
  </div>`;
}

function plural(n, word) {
  return Number(n) === 1 ? word : `${word}s`;
}

/* The name the download will carry, worked out here so the link can say it
 * without grading the whole class to find out.  Python writes the file and
 * names it the same way; a test holds the two together. */
function studentFile(stud) {
  const safe = (text) => (String(text || '').replace(/[^a-zA-Z0-9-_]/g, '_')
    .replace(/^_+|_+$/g, '') || 'unknown');

  const last = safe(stud.last);
  const first = safe(stud.first);
  if (last === 'unknown' && first === 'unknown') {
    return `${safe(stud.email.split('@')[0])}.csv`;
  }
  return `${last}_${first}.csv`;
}

/* The same file --per_student writes: everything behind one grade, which is
 * what you attach to the email asking why it is what it is. */
function downloadStudentCsv() {
  const stud = pickedStudent();
  if (!stud) return;

  const res = toJs(state.api.student_csv(state.csv, state.yaml, stud.email,
                                         state.name));
  if (!res.ok) return;
  download(res.csv, res.filename, 'text/csv');
}

/* How much the last edit moved this student.  Waiving one homework out of
 * fifteen shifts a grade by about a point, which reads as nothing happening
 * unless the page says what happened. */
function delta(stud, graded) {
  const seen = state.meanSeen[stud.email];
  state.meanSeen[stud.email] = graded.mean;

  if (seen === undefined || graded.mean === null
      || Math.abs(graded.mean - seen) < 1e-9) {
    return '';
  }

  const move = (graded.mean - seen) * 100;
  return `<span class="delta ${move > 0 ? 'up' : 'down'}">` +
    `${move > 0 ? '▲' : '▼'} ${Math.abs(move).toFixed(1)}</span>`;
}

function studGrades(graded, form, stud) {
  const waived = new Set(
    ((form.waive_list || []).find((w) => w.email === stud.email) || {})
      .ass_list || []);

  const cell = ([k, v]) =>
    `<span class="mini"><span class="mini-k">${escapeHtml(k)}</span>` +
    `<span class="mini-v">${waived.has(k) ? 'waived' : pct(v)}</span></span>`;

  const cat = Object.entries(graded.cat_dict).map(cell).join('');
  const ass = Object.entries(graded.ass_dict).map(([k, v]) =>
    waived.has(k)
      ? `<span class="mini waived"><span class="mini-k">${escapeHtml(k)}` +
        `</span><span class="mini-v">waived</span></span>`
      : cell([k, v])).join('');

  return `<div class="stud-rows">
    ${cat ? `<div class="mini-row">${cat}</div>` : ''}
    <div class="mini-row dim">${ass}</div>
  </div>`;
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

  $('waive-all').hidden = !rows.length;
  $('waive-count').textContent = rows.length === 1
    ? '1 student' : `${rows.length} students`;

  if (!rows.length) return ($('waive-list').innerHTML = '');

  $('waive-list').innerHTML =
    '<table class="waive-table"><tbody>' + rows.map((w) => `<tr>
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
  $('stats').innerHTML = `<div class="stats">
    <div class="stat"><span class="k">students</span>
      <span class="v">${res.n_student}</span></div>
    <div class="stat"><span class="k">mean</span>
      <span class="v">${pct(res.mean_avg)}</span></div>
    <div class="stat"><span class="k">median</span>
      <span class="v">${pct(res.mean_median)}</span></div>
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

/* These are links, but the file behind one is made when it is clicked rather
 * than held on the element.  A long-lived blob url has to be revoked when the
 * page redraws -- which happens on every edit -- and a link clicked against a
 * revoked url downloads as a uuid with no extension, which is worse than not
 * offering it.  The content is always current for the same reason. */
function fileLink(key, name, note) {
  return `<a href="#" data-file="${key}" download="${escapeHtml(name)}">` +
    `${escapeHtml(name)}</a>` +
    (note ? `<span class="file-note">${escapeHtml(note)}</span>` : '');
}

function fileOf(key) {
  if (key === 'csv') {
    return [state.csv, state.name, 'text/csv'];
  }
  if (key === 'yaml') {
    return [state.yaml, state.policyName, 'text/yaml'];
  }
  if (key === 'canvas') {
    return [state.canvasText, state.canvasName, 'text/csv'];
  }
  return null;
}

function drawFiles() {
  if (!state.csv) return ($('files').innerHTML = '');

  const part = [
    '<span class="file-k">files</span>',
    fileLink('csv', state.name, state.facts),
    fileLink('yaml', state.policyName, 'your whole grading policy'),
  ];

  if (state.canvasText && !state.sourceIsCanvas) {
    part.push(fileLink('canvas', state.canvasName, 'canvas template'));
  }

  $('files').innerHTML = part.join('<span class="file-sep">·</span>');
}

/* The canvas template is the gradebook canvas exported: grades are merged
 * back into it by SIS user id, which is the only thing the two files share.
 * When the file being graded is itself a canvas export, it is already the
 * template and the box says so rather than asking again. */
function drawCanvasDrop() {
  const box = $('canvas-drop');
  const set = !!state.canvasText;

  box.classList.toggle('is-set', set);

  if (!set) {
    $('canvas-drop-msg').textContent = 'Drop your canvas gradebook here';
    $('canvas-drop-sub').innerHTML =
      'Grades &rsaquo; Export — canvas matches students by its own SIS user ' +
      'id, which only that file carries. ' +
      '<button type="button" id="canvas-browse" class="link">choose a ' +
      'file</button>';
    return;
  }

  $('canvas-drop-msg').innerHTML =
    `<span class="tick">&check;</span> canvas template set`;
  $('canvas-drop-sub').innerHTML =
    `<code>${escapeHtml(state.canvasName)}</code>` +
    (state.sourceIsCanvas
      ? ' — the file you are grading is a canvas export, so it is the '
        + 'template too. '
      : ' ') +
    '<button type="button" id="canvas-browse" class="link">use a different ' +
    'file</button>';
}

function setCanvasTemplate(name, text) {
  const info = toJs(state.api.load_csv(text, name));
  if (!info.ok || info.source !== 'canvas') {
    $('export-hint').textContent = info.ok
      ? `${name} is not a canvas gradebook export — it has no SIS user id ` +
        'column to match students by.'
      : info.error;
    return;
  }
  state.canvasText = text;
  state.canvasName = name;
  drawCanvasDrop();
  drawFiles();
  drawExport();
}

function drawExport() {
  drawCanvasDrop();

  if (!state.grades) {
    $('export-row').innerHTML = '';
    $('export-hint').textContent =
      'Exports appear once the policy grades cleanly.';
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
    : 'Set a canvas template below to enable the canvas export.';

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

/* The anchor goes into the document and the url is released later on
 * purpose.  A detached anchor is ignored by some browsers, and revoking the
 * url in the same tick as the click can beat the download to the blob --
 * which saves a file named for the url with no extension and nothing in it. */
function saveBlob(blob, name) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = name;
  a.rel = 'noopener';
  a.style.display = 'none';
  document.body.appendChild(a);
  a.click();
  setTimeout(() => {
    a.remove();
    URL.revokeObjectURL(url);
  }, 30000);
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

$('plan-go').addEventListener('click', () => {
  const name = $('plan-name').value.trim().replace(/\s+/g, '').toLowerCase();
  const points = Number($('plan-points').value) || 0;
  if (!name || points <= 0) return;
  $('plan-name').value = '';
  $('plan-points').value = '';
  applyEdit('set_planned', { ass: name, points });
});

$('plan-list').addEventListener('click', (e) => {
  const name = e.target.getAttribute('data-plan');
  if (name !== null) applyEdit('set_planned', { ass: name, points: 0 });
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
  const cat = e.target.getAttribute('data-excuse');
  if (stud && cat !== null) {
    applyEdit('set_excuse_offset',
              { cat, email: stud.email, days: Number(e.target.value) });
  }
});

let dragFrom = null;

$('stud-card').addEventListener('dragstart', (e) => {
  const chip = e.target.closest('[data-score]');
  if (!chip) return;
  dragFrom = chip.getAttribute('data-score');
  e.dataTransfer.effectAllowed = 'link';
  e.dataTransfer.setData('text/plain', dragFrom);
  chip.classList.add('dragging');
});

$('stud-card').addEventListener('dragend', (e) => {
  document.querySelectorAll('.dragging, .drop-target').forEach(
    (el) => el.classList.remove('dragging', 'drop-target'));
  dragFrom = null;
});

$('stud-card').addEventListener('dragover', (e) => {
  const chip = e.target.closest('[data-score]');
  if (!chip || !dragFrom || chip.getAttribute('data-score') === dragFrom) {
    return;
  }
  e.preventDefault();
  e.dataTransfer.dropEffect = 'link';
  chip.classList.add('drop-target');
});

$('stud-card').addEventListener('dragleave', (e) => {
  const chip = e.target.closest('[data-score]');
  if (chip) chip.classList.remove('drop-target');
});

$('stud-card').addEventListener('drop', (e) => {
  const chip = e.target.closest('[data-score]');
  if (!chip) return;
  e.preventDefault();
  const from = dragFrom || e.dataTransfer.getData('text/plain');
  dragFrom = null;
  dropSubstitute(from, chip.getAttribute('data-score'));
});

/* one click, one waiver: the chip is the control */
$('stud-card').addEventListener('click', (e) => {
  const stud = pickedStudent();
  if (!stud) return;

  const chip = e.target.closest('[data-score], [data-late]');
  if (!chip) return;

  const late = chip.hasAttribute('data-late');
  const ass = chip.getAttribute(late ? 'data-late' : 'data-score');
  const field = late ? 'waive_late' : 'waive';

  const cur = waiveOf(state.form, field).find((w) => w.email === stud.email);
  const set = new Set(cur ? cur.ass_list : []);
  if (set.has(ass)) set.delete(ass); else set.add(ass);

  applyEdit('set_waive',
            { email: stud.email, ass_list: [...set], field });
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

$('stud-card').addEventListener('click', (e) => {
  if (e.target.id === 'stud-csv') downloadStudentCsv();
});

$('files').addEventListener('click', (e) => {
  const key = e.target.getAttribute('data-file');
  if (key === null) return;
  e.preventDefault();
  const part = fileOf(key);
  if (part) download(part[0], part[1], part[2]);
});

/* the export box takes one kind of file and means one thing by it, so a csv
 * dropped here is always the template, never a new gradebook to grade */
const canvasDrop = $('canvas-drop');
['dragenter', 'dragover'].forEach((ev) =>
  canvasDrop.addEventListener(ev, (e) => {
    e.preventDefault();
    canvasDrop.classList.add('over');
  }));
['dragleave', 'drop'].forEach((ev) =>
  canvasDrop.addEventListener(ev, (e) => {
    e.preventDefault();
    canvasDrop.classList.remove('over');
  }));
canvasDrop.addEventListener('drop', (e) => {
  const file = e.dataTransfer.files[0];
  if (file) readFile(file, (text) => setCanvasTemplate(file.name, text));
});
canvasDrop.addEventListener('click', (e) => {
  if (e.target.id === 'canvas-browse') $('canvas-file').click();
});
$('canvas-file').addEventListener('change', (e) => {
  const file = e.target.files[0];
  if (file) readFile(file, (text) => setCanvasTemplate(file.name, text));
  e.target.value = '';
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
