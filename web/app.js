/* The page is a thin shell around finalgrade.web: it picks a file,
 * shows what python says about it, and offers the result as a download.
 *
 * Every decision about grading lives in python, so the browser and the
 * command line cannot disagree.  Nothing here uploads anything -- there is
 * no fetch in this file except the two that load python itself.
 */

const PYODIDE = 'https://cdn.jsdelivr.net/pyodide/v0.28.3/full/';

// pyodide already ships these, so the only download that is ours is a 45k
// pure-python wheel
const PKG = ['pandas', 'numpy', 'ruamel-yaml', 'micropip'];

const $ = (id) => document.getElementById(id);

const state = {
  py: null,
  api: null,
  csv: null,
  name: null,
  gradeCsv: null,
  seq: 0,
  assList: [],
  studentList: [],
  catHintList: [],
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
    const wheel = await findWheel();
    await state.py.runPythonAsync(`
import micropip
await micropip.install(${JSON.stringify(wheel)}, deps=False)
`);

    state.api = state.py.pyimport('finalgrade.web');
    state.seed = state.py.pyimport('finalgrade.seed');

    $('boot').hidden = true;
    $('pick').hidden = false;
  } catch (err) {
    $('boot').innerHTML =
      '<p class="error"><strong>Could not start python.</strong> ' +
      escapeHtml(String(err && err.message ? err.message : err)) + '</p>' +
      '<p class="hint">This page needs a browser with WebAssembly, and a ' +
      'network connection the first time it loads.</p>';
  }
}

/* The wheel's filename carries a version, so it is written at build time
 * into wheel.json rather than guessed here. */
async function findWheel() {
  const res = await fetch('wheel.json', { cache: 'no-cache' });
  if (!res.ok) throw new Error('no wheel.json — was the site built?');
  const { wheel } = await res.json();
  return new URL(wheel, window.location.href).href;
}

/* ------------------------------------------------------- reading a file */

function readCsv(file) {
  $('pick-error').hidden = true;

  if (file.size > 40e6) {
    return showPickError('That file is over 40 MB, which is far larger than ' +
      'any gradebook — is it the right one?');
  }

  const reader = new FileReader();
  reader.onerror = () => showPickError('Could not read that file.');
  reader.onload = () => useCsv(file.name, String(reader.result));
  reader.readAsText(file);
}

function showPickError(text) {
  const el = $('pick-error');
  el.textContent = text;
  el.hidden = false;
}

function useCsv(name, text) {
  const info = toJs(state.api.load_csv(text, name));

  if (!info.ok) {
    return showPickError(info.error);
  }

  state.csv = text;
  state.name = name;
  state.assList = info.ass_list;
  state.studentList = info.student_list;
  state.catHintList = info.cat_hint_list;

  $('file-name').textContent = name;
  $('file-facts').textContent =
    `${info.source} export · ${info.n_student} students · ` +
    `${info.ass_list.length} assignments`;

  drawRoster();
  $('yaml').value = state.api.seed_config(text, name);

  $('pick').hidden = true;
  $('work').hidden = false;

  resetGrades();
  refresh();
}

/* One place where a change becomes everything the page shows: the widgets,
 * the report, and the fact that any computed grades are now stale. */
function refresh() {
  drawForm();
  check();
}

/* ------------------------------------------------- the live mapping view */

let timer = null;

function checkSoon() {
  clearTimeout(timer);
  busy();
  timer = setTimeout(refresh, 250);
}

function busy() {
  const el = $('verdict');
  el.className = 'verdict busy';
  el.textContent = 'checking…';
}

function check() {
  const seq = ++state.seq;
  const rep = toJs(state.api.check_config(state.csv, $('yaml').value,
                                          state.name));
  // a slower earlier keystroke must not overwrite a newer answer
  if (seq !== state.seq) return;

  drawVerdict(rep);
  drawReport(rep);
  resetGrades();
}

function drawVerdict(rep) {
  const el = $('verdict');
  if (rep.ok) {
    el.className = 'verdict ok';
    el.textContent = 'config looks usable — every category matches something';
  } else {
    el.className = 'verdict bad';
    el.textContent = 'grading would stop here';
  }
}

/* The tables below build html strings.  Everything interpolated into them is
 * either a number computed here or passed through escapeHtml() -- assignment
 * and category names come from the user's csv and config, so they are not
 * trusted markup. */
function drawReport(rep) {
  const out = [];

  out.push(msgList(rep.error_list, 'error'));
  out.push(msgList(rep.warn_list, 'warn'));

  out.push(assignmentTable(rep));
  if (rep.excluded_list.length) out.push(excludedTable(rep));
  out.push(categoryTable(rep));

  $('report').innerHTML = out.join('');
}

function msgList(list, kind) {
  return (list || []).map((s) =>
    `<div class="msg ${kind}"><span class="what">${kind}</span>` +
    `${escapeHtml(s)}</div>`).join('');
}

function assignmentTable(rep) {
  if (!rep.ass_list.length) {
    return '<p class="empty">No assignment is left to grade.</p>';
  }

  const row = rep.ass_list.map((a) => {
    let cat, flag = '';
    if (rep.weight_by_point) {
      cat = '<span class="empty">by points</span>';
    } else if (!a.cat_list.length) {
      cat = '<span class="empty">none</span>' +
            '<span class="tag none">not counted</span>';
      flag = ' class="flag-none"';
    } else if (a.cat_list.length > 1) {
      cat = escapeHtml(a.cat_list.join(', ')) +
            '<span class="tag many">counted twice</span>';
      flag = ' class="flag-many"';
    } else {
      cat = escapeHtml(a.cat_list[0]);
    }

    return `<tr${flag}><td class="name">${escapeHtml(a.name)}</td>` +
      `<td class="num">${fmtNum(a.points)}</td>` +
      `<td class="num">${a.n_complete}/${a.n_student}</td>` +
      `<td class="cat">${cat}</td></tr>`;
  }).join('');

  return `<table><caption>assignments being graded</caption><thead><tr>
    <th>assignment</th><th class="num">points</th>
    <th class="num">submitted</th><th>category</th>
    </tr></thead><tbody>${row}</tbody></table>`;
}

function excludedTable(rep) {
  const row = rep.excluded_list.map((a) =>
    `<tr><td class="name">${escapeHtml(a.name)}</td>` +
    `<td class="num">${a.points === null ? '–' : fmtNum(a.points)}</td>` +
    `<td>${escapeHtml(a.excluded_by)}</td></tr>`).join('');

  return `<table><caption>not graded</caption><thead><tr>
    <th>assignment</th><th class="num">points</th><th>why</th>
    </tr></thead><tbody>${row}</tbody></table>`;
}

function categoryTable(rep) {
  if (rep.weight_by_point) {
    return '<p class="empty">No category is weighted, so every assignment ' +
      'counts in proportion to its own points. Add a <code>category: ' +
      'weight:</code> block to weight by category instead.</p>';
  }

  const row = rep.cat_list.map((c) => {
    const empty = !c.ass_list.length;
    const caught = empty
      ? '<span class="empty">nothing</span>' +
        '<span class="tag error">no match</span>'
      : escapeHtml(c.ass_list.join(', '));

    return `<tr${empty ? ' class="flag-error"' : ''}>` +
      `<td class="name">${escapeHtml(c.name)}</td>` +
      `<td class="num">${(c.weight_frac * 100).toFixed(1)}%</td>` +
      `<td class="num">${c.drop_low || '–'}</td>` +
      `<td>${fmtLate(c.late)}</td>` +
      `<td class="cat">${caught}</td></tr>`;
  }).join('');

  return `<table><caption>categories</caption><thead><tr>
    <th>category</th><th class="num">weight</th><th class="num">drop</th>
    <th>late</th><th>catches</th>
    </tr></thead><tbody>${row}</tbody></table>`;
}

function fmtLate(late) {
  if (!late) return '–';
  const part = [`${(late.penalty_per_day || 0) * 100}%/day`];
  if (late.excuse_day) part.push(`${late.excuse_day} excused`);
  return escapeHtml(part.join(', '));
}

/* ---------------------------------------------- the policy widgets

 * The widgets and the textarea are one document, not two: an edit goes
 * through python's round-trip yaml, so a form control can change one line
 * and leave every comment (and every section that has no widget) alone.
 */

function applyEdit(action, args) {
  const res = toJs(state.api.edit_config($('yaml').value, action,
                                         JSON.stringify(args || {})));
  if (!res.ok) {
    // an edit that can't apply means the file no longer parses; the report
    // will say so, and the user's own text is left exactly as they typed it
    return check();
  }
  $('yaml').value = res.yaml;
  refresh();
}

function drawForm() {
  const form = toJs(state.api.form_state($('yaml').value));
  if (!form.ok) {
    $('cats').innerHTML =
      '<p class="empty">The file below cannot be read as yaml, so these ' +
      'controls are paused. Fix it there and they come back.</p>';
    $('quick').innerHTML = '';
    $('waive-list').innerHTML = '';
    return;
  }

  drawCategories(form);
  drawQuick(form);
  drawWaivers(form);
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

  $('cats-hint').textContent = 'Weights are normalized, so they need not ' +
    'sum to 100.';

  $('cats').innerHTML = form.cat_list.map((c) => {
    const hit = catches(c.name);
    const late = c.late || {};
    const on = !!c.late;

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
          step="1" value="${late.excuse_day || 0}"> excused days</label>` : ''}
      </div>
      <div class="cat-hit">${hit.length
        ? 'catches ' + escapeHtml(hit.join(', '))
        : '<span class="tag error">matches no assignment</span>'}</div>
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

/* ------------------------------------------------------ waivers by roster */

function drawRoster() {
  $('roster').innerHTML = state.studentList.map((s) => {
    const name = [s.first, s.last].filter(Boolean).join(' ');
    return `<option value="${escapeHtml(s.email)}">${escapeHtml(name)}` +
      `</option>`;
  }).join('');
}

function waiveOf(form, kind) {
  return kind === 'waive_late' ? form.waive_late_list : form.waive_list;
}

function drawWaivers(form) {
  state.form = form;
  drawWaiveChecks(form);

  const rows = [
    ...form.waive_list.map((w) => ({ ...w, kind: 'waive' })),
    ...form.waive_late_list.map((w) => ({ ...w, kind: 'waive_late' })),
  ];

  if (!rows.length) {
    $('waive-list').innerHTML = '<p class="empty">No waivers yet.</p>';
    return;
  }

  $('waive-list').innerHTML = `<table class="waive-table"><tbody>` +
    rows.map((w) => `<tr>
      <td class="name">${escapeHtml(w.email)}</td>
      <td>${escapeHtml(w.ass_list.join(', '))}</td>
      <td>${w.kind === 'waive_late'
        ? '<span class="tag late">late only</span>' : ''}</td>
      <td><button type="button" class="x" data-drop="${escapeHtml(w.email)}"
        data-kind="${w.kind}" title="remove">&times;</button></td>
    </tr>`).join('') + '</tbody></table>';
}

function drawWaiveChecks(form) {
  const email = $('stud').value.trim();
  const kind = $('waive-kind').value;

  if (!email) {
    $('waive-pick-ass').innerHTML = '';
    return;
  }

  const known = state.studentList.some((s) => s.email === email);
  if (!known) {
    $('waive-pick-ass').innerHTML =
      '<p class="empty">Pick a student from the list — the roster comes ' +
      'from your csv, so a name here is never a typo.</p>';
    return;
  }

  const cur = waiveOf(form, kind).find((w) => w.email === email);
  const have = new Set(cur ? cur.ass_list : []);

  $('waive-pick-ass').innerHTML = '<div class="checks">' +
    state.assList.map((a) => `<label class="f">
      <input type="checkbox" data-waive="${escapeHtml(a.name)}"
        ${have.has(a.name) ? 'checked' : ''}> ${escapeHtml(a.name)}
    </label>`).join('') + '</div>';
}

function setWaive(ass, on) {
  const email = $('stud').value.trim();
  const kind = $('waive-kind').value;
  const cur = waiveOf(state.form, kind).find((w) => w.email === email);

  const set = new Set(cur ? cur.ass_list : []);
  if (on) set.add(ass); else set.delete(ass);

  applyEdit('set_waive', {
    email, ass_list: [...set], field: kind,
  });
}

/* ------------------------------------------------------------- grading */

function resetGrades() {
  state.gradeCsv = null;
  $('dl-grades').hidden = true;
  $('grades').innerHTML = '';
}

function runGrades() {
  const res = toJs(state.api.grade(state.csv, $('yaml').value, state.name));

  if (!res.ok) {
    $('grades').innerHTML = `<div class="msg error">` +
      `<span class="what">error</span>${escapeHtml(res.error)}</div>`;
    return;
  }

  state.gradeCsv = res.csv;
  $('dl-grades').hidden = false;

  const max = Math.max(...res.letter_list.map((l) => l.n), 1);
  const bars = res.letter_list.map((l) => `
    <div class="bar-wrap" title="${l.n} students">
      <span class="bar-n">${l.n}</span>
      <div class="bar" style="height:${(l.n / max) * 100}%"></div>
      <span class="bar-k">${escapeHtml(l.letter)}</span>
    </div>`).join('');

  $('grades').innerHTML =
    msgList(res.warn_list, 'warn') +
    `<div class="stats">
      <div class="stat"><span class="k">students</span>
        <span class="v">${res.n_student}</span></div>
      <div class="stat"><span class="k">mean</span>
        <span class="v">${pct(res.mean_avg)}</span></div>
      <div class="stat"><span class="k">median</span>
        <span class="v">${pct(res.mean_median)}</span></div>
    </div>
    <div class="dist">${bars}</div>`;
}

/* ---------------------------------------------------------------- utils */

function toJs(proxy) {
  const out = proxy.toJs({ dict_converter: Object.fromEntries });
  proxy.destroy();
  return out;
}

function download(text, name, type) {
  const url = URL.createObjectURL(new Blob([text], { type }));
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

/* ---------------------------------------------------------------- wiring */

$('browse').addEventListener('click', () => $('file').click());
$('file').addEventListener('change', (e) => {
  if (e.target.files[0]) readCsv(e.target.files[0]);
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
  if (e.dataTransfer.files[0]) readCsv(e.dataTransfer.files[0]);
});

$('demo').addEventListener('click', async () => {
  const res = await fetch('example.csv');
  useCsv('example.csv', await res.text());
});

$('yaml').addEventListener('input', checkSoon);

$('quick').addEventListener('click', (e) => {
  const cat = e.target.getAttribute('data-cat');
  if (cat === null) return;

  const name = cat || (prompt('Category name — it matches any assignment ' +
    'whose name contains it:') || '').trim().replace(/\s+/g, '').toLowerCase();
  if (name) applyEdit('add_category', { cat: name });
});

/* number inputs commit on change (blur or enter), not on every keystroke:
 * re-rendering mid-keystroke would take the caret with it */
$('cats').addEventListener('change', (e) => {
  const act = e.target.getAttribute('data-act');
  const cat = e.target.closest('.cat-card').getAttribute('data-cat');
  if (!act) return;

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
  }
});

$('cats').addEventListener('click', (e) => {
  if (e.target.getAttribute('data-act') !== 'remove') return;
  const cat = e.target.closest('.cat-card').getAttribute('data-cat');
  applyEdit('remove_category', { cat });
});

$('stud').addEventListener('input', () => drawWaiveChecks(state.form));
$('waive-kind').addEventListener('change', () => drawWaiveChecks(state.form));

$('waive-pick-ass').addEventListener('change', (e) => {
  const ass = e.target.getAttribute('data-waive');
  if (ass) setWaive(ass, e.target.checked);
});

$('waive-list').addEventListener('click', (e) => {
  const email = e.target.getAttribute('data-drop');
  if (!email) return;
  applyEdit('set_waive', {
    email, ass_list: [], field: e.target.getAttribute('data-kind'),
  });
});

$('dl-config').addEventListener('click', () =>
  download($('yaml').value, 'config.yaml', 'text/yaml'));

$('dl-grades').addEventListener('click', () => {
  if (state.gradeCsv) download(state.gradeCsv, 'grade_full.csv', 'text/csv');
});

$('run').addEventListener('click', runGrades);

$('change').addEventListener('click', () => {
  $('work').hidden = true;
  $('pick').hidden = false;
});

$('reset').addEventListener('click', () => {
  $('yaml').value = state.api.seed_config(state.csv, state.name);
  refresh();
});

boot();
