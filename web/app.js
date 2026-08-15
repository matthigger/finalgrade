/* The page is a thin shell around gradescope_mean.web: it picks a file,
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

    msg.textContent = 'installing gradescope-mean…';
    const wheel = await findWheel();
    await state.py.runPythonAsync(`
import micropip
await micropip.install(${JSON.stringify(wheel)}, deps=False)
`);

    state.api = state.py.pyimport('gradescope_mean.web');
    state.seed = state.py.pyimport('gradescope_mean.seed');

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

  $('file-name').textContent = name;
  $('file-facts').textContent =
    `${info.source} export · ${info.n_student} students · ` +
    `${info.ass_list.length} assignments`;

  $('yaml').value = state.api.seed_config(text, name);
  drawQuick(info);

  $('pick').hidden = true;
  $('work').hidden = false;

  resetGrades();
  check();
}

/* ------------------------------------------------- the live mapping view */

let timer = null;

function checkSoon() {
  clearTimeout(timer);
  busy();
  timer = setTimeout(check, 250);
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

/* ------------------------------------------------ quick add for categories */

function drawQuick(info) {
  const guess = toJs(state.seed.guess_cat_list(
    info.ass_list.map((a) => a.name), info.cat_hint_list));

  if (!guess.length) return ($('quick').innerHTML = '');

  const label = info.cat_hint_list.length
    ? 'add a category (from your canvas groups):'
    : 'add a category:';

  $('quick').innerHTML = `<span class="quick-label">${label}</span>` +
    guess.map((c) =>
      `<button type="button" data-cat="${escapeHtml(c)}">${escapeHtml(c)}` +
      `</button>`).join('');
}

/* Writing yaml by string surgery is crude, but it keeps the textarea the
 * single source of truth: a structured editor would have to round-trip every
 * section, including the ones it doesn't understand.  The textarea is still
 * editable, so a config this can't express is always one keystroke away. */

// '    hw: 50   # hw1, hw2' -> key, value and any trailing comment
const RE_WEIGHT = /^(\s{4}[^:#]+:)([^#]*)(#.*)?$/;

function addCategory(cat) {
  const el = $('yaml');
  const lines = el.value.split('\n');

  let at = lines.findIndex((l) => /^\s{2}weight:/.test(l));
  if (at < 0) {
    lines.unshift('category:', '  weight:');
    at = 1;
  } else if (/^\s{2}weight:\s*null\s*$/.test(lines[at])) {
    // the placeholder the packaged config ships with
    lines[at] = '  weight:';
  }

  let end = at + 1;
  while (end < lines.length && RE_WEIGHT.test(lines[end])) end++;

  if (lines.slice(at + 1, end).some((l) => l.trim().startsWith(`${cat}:`))) {
    return;  // already there
  }

  lines.splice(end, 0, `    ${cat}: 0`);
  end++;

  // equal shares, so clicking two chips reads as 50/50 rather than 100/50.
  // weights are normalized anyway, but a number nobody chose is confusing
  const share = Math.round(100 / (end - at - 1));
  for (let i = at + 1; i < end; i++) {
    const [, key, , comment] = lines[i].match(RE_WEIGHT);
    const head = `${key} ${share}`;
    lines[i] = comment ? head.padEnd(24) + comment : head;
  }

  el.value = lines.join('\n');
  checkSoon();
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
  if (cat) addCategory(cat);
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
  check();
});

boot();
