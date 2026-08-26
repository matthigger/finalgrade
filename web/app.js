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
  // the policy as it exists in a file the reader has -- set when one is
  // loaded, and again when one is saved.  what the exit guard measures
  // against, and null until there has been a file at all
  savedYaml: null,
  // the policy as this page first wrote it, before any editing.  an untouched
  // seed is worth nothing, so it is the one unsaved document not worth
  // stopping anybody over on the way out
  seedYaml: null,
  // something the page did that the check cannot say, kept across redraws
  // until the reader has dealt with it
  notice: null,
  csv: null,
  name: null,
  // PRIVATE because it names students.  the page writes this name, so it
  // is the page's job to make handing the wrong file out hard to do by
  // accident: policy_PUBLIC.yaml is the one for the class
  policyName: 'policy_PRIVATE.yaml',
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
  // which folds the reader has opened, by data-fold key.  an edit redraws
  // the markup they live in, and a log that shuts itself the moment you
  // change the thing it explains is a log you cannot read while working.
  // the computation log starts open: how a grade was reached is the question
  // the grade provokes, so it is not something to go looking for
  fold: { audit: true },
  view: 'total',
  mode: 'final',
  // which export the panel is showing the inputs for
  exportMode: 'grades',
  seq: 0,
  // the one student this page is about, when the gradebook holds one -- a
  // student looking at their own grade rather than a course looking at
  // itself.  null for a class
  solo: null,
  // scores a student has entered, by assignment name.  the file itself is
  // never edited: it is rewritten from these every time, so an answer is
  // taken back out by deleting it rather than by undoing anything
  whatIf: {},
  // days late, by assignment name.  its own answer rather than something
  // read off a score: when a score was handed in is not something the score
  // says, and guessing would move a penalty the student never mentioned
  whatIfDay: {},
  // true when the gradebook is a sheet made from the policy rather than a
  // file anybody exported.  the page has no scores until they are typed, so
  // it must not read an empty sheet as a term of zeros
  sheet: false,
  // the csv the grades are computed from: the one that was loaded, with
  // those entries written in.  the same string when there are none
  csvGraded: null,
};

const NEED_POLICY = 'This is one student\'s row, so it is being read as ' +
  'your own grade. It needs the policy.yaml your instructor gave you as ' +
  'well — without it there is no course policy to apply, and the default ' +
  'one is not yours.';

/* What a student's sheet is called.  It is a gradebook of one student, so
 * dropping it back in is read as their own grade -- which is why it is the
 * only file the student's page offers, and why it keeps a name they will
 * recognise when they come to look for it. */
const SHEET_NAME = 'you.csv';

/* The name the package writes it under, so that the page and the command line
 * hand a reader the same filename. */
const NAME_PUBLIC = 'policy_PUBLIC.yaml';

/* ------------------------------------------------------------------ boot */

async function boot() {
  const msg = $('boot-msg');
  try {
    // before anything expensive: a stale page would download 15 MB and then
    // reload and do it again
    if (await checkFresh()) return;
    tidyUrl();
    showBuild();

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
/* Whether this page is the page that was built, and a reload if it isn't.
 *
 * app.js and style.css are fetched with a hash of themselves in the query,
 * so a new build is never taken from cache.  index.html is not: its name
 * never changes, so a browser holding yesterday's copy asks for yesterday's
 * app.js by name and gets it, cache-bust and all -- the fix ships and never
 * arrives.  That is a bug that presents as every other bug, since the code
 * running is not the code written.
 *
 * wheel.json is small, fetched already, and records what the build stamped
 * into index.html.  If the running page disagrees with it, the html is
 * stale; reloading through a url the cache has never seen gets the real
 * one.  Once only -- a reload that doesn't take must not become a loop.
 *
 * Returns:
 *   (bool) true when a reload is on its way and boot should stop
 */
const FRESH_KEY = 'finalgrade.reloaded';

async function checkFresh() {
  let want;
  try {
    const res = await fetch('wheel.json', { cache: 'no-store' });
    want = ((await res.json()).stamp || {})['app.js'];
  } catch (err) {
    // offline, or a build too old to say: carry on with what we have
    return false;
  }
  if (!want) return false;

  const el = document.querySelector('script[src^="app.js"]');
  const have = el
    && new URL(el.getAttribute('src'), location.href).searchParams.get('v');
  if (have === want) return false;

  try {
    if (sessionStorage.getItem(FRESH_KEY) === want) return false;
    sessionStorage.setItem(FRESH_KEY, want);
  } catch (err) {
    // private mode with no storage: one reload is still better than none
  }

  const url = new URL(location.href);
  url.searchParams.set('v', want);
  location.replace(url.toString());
  return true;
}

/* Which build is actually running, in the corner where a version belongs.
 * "have you got the fix yet" is otherwise unanswerable from the page, and
 * the answer has been no more than once. */
function showBuild() {
  const el = document.querySelector('script[src^="app.js"]');
  const stamp = el
    && new URL(el.getAttribute('src'), location.href).searchParams.get('v');
  $('build').textContent = `build ${stamp || 'dev'}`;
}

/* the stamp above is a cache-buster, not something to leave in the address
 * bar for the user to copy into an email */
function tidyUrl() {
  const url = new URL(location.href);
  if (!url.searchParams.has('v')) return;

  url.searchParams.delete('v');
  history.replaceState(null, '', url.toString());
}

async function findWheels() {
  const res = await fetch('wheel.json', { cache: 'no-cache' });
  if (!res.ok) throw new Error('no wheel.json — was the site built?');
  const { wheel, vendor } = await res.json();
  return [wheel, ...(vendor || [])].map(
    (p) => new URL(p, window.location.href).href);
}

/* --------------------------------------------------------- picking files */

function readText(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error('Could not read that file.'));
    reader.onload = () => resolve(String(reader.result));
    reader.readAsText(file);
  });
}

function isYamlName(name) {
  return /\.(ya?ml)$/i.test(name);
}

/* Dropping both files in one gesture is the natural thing to do, and the
 * order they arrive in belongs to the operating system rather than to the
 * reader.  A policy read before its gradebook has nothing to grade, so the
 * gradebook is applied first -- and each file is finished before the next is
 * started, because a FileReader that has merely been kicked off is a
 * gradebook that is not there yet.  Sorting the calls alone would not do it. */
async function takeFileList(fileList) {
  const list = [...fileList].sort(
    (a, b) => isYamlName(a.name) - isYamlName(b.name));

  for (const file of list) {
    if (!okToRead(file)) return;

    let text;
    try {
      text = await readText(file);
    } catch (err) {
      return showPickError(err.message);
    }

    if (isYamlName(file.name)) useYaml(file.name, text);
    else useCsv(file.name, text);
  }
}

function okToRead(file) {
  $('pick-error').hidden = true;

  if (!state.api) {
    showPickError('Python is still loading — try again in a moment.');
    return false;
  }
  if (file.size > 40e6) {
    showPickError('That file is over 40 MB, which is far larger than ' +
      'any gradebook — is it the right one?');
    return false;
  }
  return true;
}

function showPickError(text) {
  const el = $('pick-error');
  el.textContent = text;
  el.hidden = false;
}

function useCsv(name, text, opt) {
  const sheet = !!(opt && opt.sheet);
  const info = toJs(state.api.load_csv(text, name));
  if (!info.ok) return showPickError(info.error);

  // a gradebook is the answer to every complaint the picker makes, and the
  // example links reach here without having gone past one
  $('pick-error').hidden = true;

  // a canvas gradebook arriving alongside a gradescope one is the file to
  // merge grades back into, not a replacement for what is being graded
  if (!sheet && state.csv && info.source === 'canvas'
      && !state.sourceIsCanvas) {
    state.canvasText = text;
    state.canvasName = name;
    drawFiles();
    drawExport();
    return;
  }

  // re-exporting the gradebook is routine -- a regrade, a late submission,
  // one more assignment -- and seeding over the policy would throw away every
  // weight and waiver set so far, with nothing on the page to get them back.
  // the new numbers are what was asked for; the grading was not
  const keep = !sheet && !!state.yaml;

  state.csv = text;
  state.name = name;
  state.sheet = sheet;
  state.sourceIsCanvas = !sheet && info.source === 'canvas';
  // which format it was read as is not cosmetic: it decides whether late
  // penalties are available at all, so it belongs next to the filename.  a
  // sheet was exported by nobody, so it says what it is instead -- and it
  // counts the policy's assignments, having none of its own until they are
  // typed
  const nAss = (opt && opt.nAss) || 0;
  state.facts = sheet
    ? `your own scores, ${nAss} ${plural(nAss, 'assignment')} to fill in`
    : `${info.source}, ${info.n_student} ` +
      `${plural(info.n_student, 'student')}, ` +
      `${info.ass_list.length} ${plural(info.ass_list.length, 'assignment')}`;
  state.assList = info.ass_list;
  state.studentList = info.student_list;
  state.catHintList = info.cat_hint_list;
  state.grades = null;

  // one student in the file is somebody looking at their own grade.  nothing
  // else tells the two apart and nothing else has to: an instructor's export
  // is their class, and a class is more than one person
  state.solo = info.n_student === 1 ? info.student_list[0].email : null;
  state.whatIf = {};
  state.whatIfDay = {};
  document.body.classList.toggle('solo', !!state.solo);

  // set both ways round: a class loaded after a student's sheet has to take
  // the headings back, or the page keeps calling a course "your grade"
  if (state.solo) {
    $('stud-h2').firstChild.nodeValue = 'your grade';
    // what to do is said over the boxes it is about, not over the total
    $('stud-sub').textContent = '';
  } else {
    $('stud-h2').firstChild.nodeValue = 'students ';
    $('stud-sub').textContent = 'grades, waivers, accommodations';
  }

  if (state.sourceIsCanvas) {
    state.canvasText = text;
    state.canvasName = name;
  }

  drawRoster();

  if (keep && state.solo) {
    state.notice = 'Your policy was kept — these grades replaced the last ' +
      'ones, and the policy you loaded still applies to them.';
  } else if (keep) {
    state.notice = 'Your policy was kept — this gradebook replaced the last ' +
      'one, not your grading. Anything new in it is unweighted until you ' +
      'place it.';
  } else if (sheet) {
    state.notice = null;
  } else if (state.solo) {
    // a policy written for this one row would grade by whatever the points
    // happen to be, which is not the course's policy and would answer a
    // question nobody asked.  the file that says what counts has to arrive
    setYaml('');
    state.seedYaml = null;
    state.savedYaml = null;
    state.notice = null;
  } else {
    seedPolicy();
  }

  $('work').hidden = false;
  refresh();
}

/* A policy that knows this course's assignments, and the one document the
 * page is allowed to write without being asked.  Recorded as the seed so the
 * exit guard can tell it apart from work: nobody has lost anything yet. */
function seedPolicy() {
  setYaml(state.api.seed_policy(state.csv, state.name));
  state.seedYaml = state.yaml;
  state.savedYaml = null;
  state.notice = null;
}

function useYaml(name, text) {
  // a policy with no gradebook beside it is a student's.  the file their
  // instructor posted is the whole of what they were given -- neither
  // gradescope nor canvas hands them an export worth reading -- so the
  // sheet to fill in is made from the policy itself
  if (!state.csv) return useStudentYaml(name, text);

  state.policyName = name;
  setYaml(text);
  // it came from a file, so that file is what unsaved is measured against
  state.savedYaml = text;
  state.notice = null;
  refresh();
}

/* The student's way in: their policy, and a sheet of the term's work with
 * nothing entered against any of it. */
function useStudentYaml(name, text) {
  const res = toJs(state.api.student_sheet(text));
  if (!res.ok) return showPickError(res.error);

  $('pick-error').hidden = true;
  state.policyName = name;
  // the policy is in place before the sheet, because useCsv reads the policy
  // it finds to decide whether it is replacing one
  setYaml(text);
  state.savedYaml = text;
  state.seedYaml = null;
  useCsv(SHEET_NAME, res.csv, { sheet: true, nAss: res.n_ass });
}

function setYaml(text) {
  state.yaml = text;
}

/* One place where a change becomes everything the page shows.  Widgets are
 * redrawn from the file, then the file is checked, then -- only if it is
 * usable -- grades and the charts follow. */
function refresh() {
  if (state.solo && !state.yaml) return askForPolicy();

  const error = gradeSource();
  drawForm();
  if (check()) runGrades();
  else clearGrades();
  if (error) $('messages').innerHTML += msgList([error], 'error');
  if (state.solo) {
    $('messages').innerHTML += msgList(emptyCatWarnList(), 'warn');
  }
  drawFiles();
  drawExport();
}

/* A category nothing has been entered into weighs on nothing, so a grade that
 * looks finished is a grade over part of the course.  The instructor's page
 * warns when a category matches no assignment; this is the same hole seen
 * from the other side, where the assignments exist and the scores do not. */
function emptyCatWarnList() {
  const graded = soloGraded();
  if (!graded) return [];

  const scored = {};
  for (const a of graded.ass_list || []) {
    if (a.category && a.perc !== null && a.perc !== undefined) {
      scored[a.category] = true;
    }
  }

  // a sheet nobody has started is every category at once, which is not news
  // to whoever just opened it.  the warning is for the category missed while
  // filling the others in
  if (!Object.keys(scored).length) return [];

  return Object.keys(graded.cat_dict || {}).sort()
    .filter((cat) => !scored[cat])
    .map((cat) => `no scores entered for ${cat}, so it is not counted at `
      + 'all — your grade so far is over the rest of the course');
}

/* the one student's graded row, when there is one */
function soloGraded() {
  if (!state.solo || !state.grades) return null;
  return (state.grades.student_list || [])
    .find((s) => s.email === state.solo) || null;
}

/* Half of what a student needs, and the page saying which half is missing.
 * Grading them by the default policy would produce a number, which is worse
 * than producing none: it would be wrong and look right. */
function askForPolicy() {
  clearGrades();
  state.form = null;
  $('stud-card').innerHTML = '';
  $('messages').innerHTML = msgList([NEED_POLICY], 'note');
  drawFiles();
  drawExport();
}

/* The csv the grades are computed from.  Rebuilt from the file as it arrived
 * every time, rather than edited in place, so that a supposition is undone by
 * deleting it and nothing accumulates. */
function gradeSource() {
  state.csvGraded = state.csv;
  if (!state.solo || !(Object.keys(state.whatIf).length
                       || Object.keys(state.whatIfDay).length)) return null;

  const res = toJs(state.api.what_if(state.csv, state.yaml,
                                     JSON.stringify(state.whatIf),
                                     JSON.stringify(state.whatIfDay)));
  if (res.ok) {
    state.csvGraded = res.csv;
    return null;
  }
  return res.error;
}

/* the csv to grade: the same string as the one loaded, unless a student has
 * supposed something */
function gradedCsv() {
  return state.csvGraded || state.csv;
}

function applyEdit(action, args) {
  const res = toJs(state.api.edit_policy(state.yaml, action,
                                         JSON.stringify(args || {})));
  // an edit that cannot apply leaves the document exactly as it was
  if (res.ok) {
    setYaml(res.yaml);
    // editing the kept policy is deciding to keep it, so the offer to
    // replace it has been answered and should stop taking up room
    state.notice = null;
  }
  refresh();
}

/* ------------------------------------------------------------- the check */

function check() {
  const seq = ++state.seq;
  const rep = toJs(state.api.check_policy(gradedCsv(), state.yaml,
                                          state.name));
  if (seq !== state.seq) return rep.ok;

  state.report = rep;

  // whatever belongs to one assignment is shown on that assignment; what is
  // left is about the file, the roster or the letters, and has nowhere else
  // to go
  $('messages').innerHTML = noticeHtml() +
    msgList(rep.error_list, 'error') + msgList(rep.warn_list, 'warn');
  return rep.ok;
}

/* The check's messages are redrawn from the document on every edit.  This one
 * is not about the document -- it reports what the page did with a file, and
 * carries the only way back from it, so it outlives the redraw. */
function noticeHtml() {
  if (!state.notice) return '';
  return '<div class="msg note"><span class="what">note</span>' +
    escapeHtml(state.notice) +
    '<button type="button" id="reseed" class="link">start a fresh policy' +
    '</button></div>';
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
      ['quick', 'waive-list', 'thresh-list', 'stud-card',
      'weight-table'].forEach((id) => ($(id).innerHTML = ''));
    return;
  }

  drawCategories(form);
  drawQuick(form);
  drawThresh(form);
  drawStudent(form);
  drawWaiveList(form);
  drawRosterFilter(form);

}

function catches(cat) {
  // exactly the substring rule python matches with
  return state.assList.map((a) => a.name).filter((n) => n.includes(cat));
}

function drawCategories(form) {
  if (!form.cat_list.length) {
    // the one thing not visible from the controls: what happens with none
    $('cats').innerHTML = '<p class="empty">No categories yet — every ' +
      'assignment counts in proportion to its own points.</p>';
    return;
  }

  $('cats').innerHTML = form.cat_list.map((c) => {
    const late = c.late || {};
    const on = !!c.late;
    const grace = late.grace_period_minutes;
    // one control for the two exclusive rules: which one, and how many
    const rule = ruleOf(c);
    const n = rule === 'keep' ? c.keep_high : c.drop_low;
    const nAss = catches(c.name).length;

    return `<div class="cat-card" data-cat="${escapeHtml(c.name)}">
      <div class="cat-head">
        <span class="cat-name">${escapeHtml(c.name)}</span>
        <label class="f">weight
          <input type="number" data-act="weight" min="0" step="1"
            value="${escapeHtml(c.weight)}"></label>
        <span class="cat-share">${c.weight_frac === null ? ''
          : (c.weight_frac * 100).toFixed(1) + '%'}</span>
        <span class="f"><select data-act="rule" aria-label="score rule">
          ${ruleOptions(rule)}</select>${rule ? `
          <select data-act="rule-n" aria-label="how many">
            ${countOptions(rule, n, nAss)}</select>` : ''}</span>
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
      ${catches(c.name).length ? ruleHint(c, catches(c.name).length) :
        '<div class="cat-hit"><span class="tag error">matches no ' +
        'assignment</span></div>'}
    </div>`;
  }).join('');
}

/* the two exclusive rules and the absence of either, so that every state
 * the file can be in is one the control can show */
function ruleOptions(rule) {
  return [['', 'no rule'], ['drop', 'drop lowest'],
          ['keep', 'keep highest']].map(
    ([v, label]) => `<option value="${v}"${v === rule ? ' selected' : ''}>`
      + `${label}</option>`).join('');
}

/* how many, as a list rather than a number box: 0 is the interesting value
 * and it does not read as one.  "all" and "none" say what it does, and the
 * choices stop at the assignments the category actually has.
 *
 * Whatever the file says is always among them, even out of range -- an
 * option list that omitted the current value would show the first one
 * instead, and the next click would write it. */
function countOptions(rule, n, nAss) {
  const max = rule === 'keep' ? nAss : Math.max(nAss - 1, 0);
  const valList = [0];
  for (let i = 1; i <= max; i++) valList.push(i);
  if (!valList.includes(n)) valList.push(n);

  return valList.map((v) => {
    const label = v === 0 ? (rule === 'keep' ? 'all' : 'none') : String(v);
    return `<option value="${escapeHtml(v)}"${v === n ? ' selected' : ''}>`
      + `${escapeHtml(label)}</option>`;
  }).join('');
}

/* which rule the file gives this category, or '' for neither.  a 0 is a
 * rule: the user picked it and has not said how many yet, and a control that
 * throws that away reads as a page which is not responding */
function ruleOf(c) {
  if (c.keep_high !== null && c.keep_high !== undefined) return 'keep';
  if (c.drop_low !== null && c.drop_low !== undefined) return 'drop';
  return '';
}

/* what the chosen rule does to this category, spelled out.  keep highest is
 * the one that needs saying: a student short of the number is averaged over
 * zeros, which is not what dropping the lowest few would have done */
function ruleHint(c, nAss) {
  const rule = ruleOf(c);
  if (rule && !(rule === 'keep' ? c.keep_high : c.drop_low)) {
    // legible, but still an entry that does nothing -- "no rule" removes it
    return `<div class="cat-rule">${rule === 'keep'
      ? 'every score counts, the same as no rule at all'
      : 'nothing is dropped, the same as no rule at all'}</div>`;
  }
  if (c.keep_high) {
    const short = c.keep_high > nAss
      ? `<span class="tag warn">only ${nAss} to count, so every one
         does</span>` : '';
    return `<div class="cat-rule">best ${c.keep_high} of ${nAss} count;
      anyone with fewer than ${c.keep_high} scores is averaged over zeros
      to make up the number ${short}</div>`;
  }
  if (c.drop_low) {
    return `<div class="cat-rule">the ${c.drop_low} lowest of ${nAss} are
      dropped, whatever they are for each student</div>`;
  }
  return '';
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

/* The weights table is also the assignments editor.  There is only one list
 * of assignments in a course, so there is one list of them on screen: what an
 * assignment is worth, what the class did on it, and what you have decided
 * about it, all on its own row.
 *
 * Click an assignment name to waive it, drag onto another to take the best of
 * both, and the last row adds work that has not happened yet.
 */

const SORT_TUP = [
  { key: 'category', label: 'category', num: false },
  { key: 'assignment', label: 'assignment', num: false },
  { key: 'points', label: 'points', num: true },
  { key: 'extra', label: 'extra credit', num: true },
  { key: 'weight_in_cat', label: 'of category', num: true },
  { key: 'weight_total', label: 'of grade', num: true },
  { key: 'mean_nonzero', label: 'mean*', num: true },
  { key: 'complete_frac', label: 'submitted', num: true },
  { key: 'max', label: 'substitute', num: false },
];

/* Fixed, in the order SORT_TUP declares.  The substitute column grows a chip
 * the moment one assignment is dropped onto another, and a table sized by
 * its contents would re-lay every other column out from under the cursor. */
const COL_WIDTH_TUP = ['8%', '17%', '6%', '12%', '11%', '9%', '8%', '9%',
                       '20%'];

function sortRows(rowList) {
  const sort = state.sort;
  if (!sort) return rowList;

  const col = SORT_TUP.find((c) => c.key === sort.key);
  const dir = sort.dir === 'down' ? -1 : 1;

  return [...rowList].sort((a, b) => {
    const x = sortValue(a, sort.key);
    const y = sortValue(b, sort.key);
    // an assignment with no value sorts last whichever way the column goes
    if (x === null) return 1;
    if (y === null) return -1;
    if (col && col.num) return (x - y) * dir;
    return String(x).localeCompare(String(y)) * dir;
  });
}

function sortValue(row, key) {
  if (key === 'complete_frac') {
    return row.n_student ? row.n_complete / row.n_student : null;
  }
  if (key === 'max') {
    return (maxOf(row.assignment) || []).join(', ') || null;
  }
  if (key === 'extra') return isExtra(row.assignment) ? 1 : 0;
  const v = row[key];
  return v === undefined ? null : v;
}

function maxOf(ass) {
  const hit = ((state.form || {}).sub_list || [])
    .find((s) => s.target === ass);
  return hit ? hit.ass_list : null;
}

/* Names in the policy are matched the way python matches them: as fragments,
 * so `extra_credit: [bonus]` catches every bonus without naming each. */
function isExtra(ass) {
  return ((state.form || {}).extra_list || []).some((e) => ass.includes(e));
}

function drawWeightTable() {
  const res = state.grades;
  if (!res) return ($('weight-table').innerHTML = '');

  const problem = ((state.report || {}).ass_problem_dict) || {};
  const excluded = ((state.report || {}).excluded_list || []);
  const exclSet = new Set(excluded.map((a) => a.name));

  // every assignment in one list, graded or not: a table that omits the
  // excluded ones agrees they never existed, and they are the ones you are
  // most likely to want back
  const rowList = sortRows([
    ...res.row_list,
    ...excluded.map((a) => ({
      category: null, assignment: a.name, points: a.points,
      weight_in_cat: null, weight_total: null, mean_nonzero: null,
      n_complete: a.n_complete, n_student: a.n_student,
      excluded_by: a.excluded_by,
    })),
  ]);

  // grouping only reads as grouping while the rows are in category order
  const grouped = !state.sort;
  let last = null;

  if (grouped) stableOrder(rowList);

  const row = rowList.map((r) => {
    const shown = r.category
      || ((state.form || {}).cat_list || [])
        .map((c) => c.name).find((c) => r.assignment.includes(c))
      || '—';
    const cat = !grouped ? shown : (shown === last ? '' : shown);
    if (grouped) last = shown;

    const note = (problem[r.assignment] || []).map((s) =>
      `<div class="row-warn">${escapeHtml(s)}</div>`).join('');

    const off = exclSet.has(r.assignment);
    const cls = [grouped && cat ? 'grp' : '', note ? 'flag-none' : '',
                 off ? 'dropped' : ''].filter(Boolean);

    return `<tr${cls.length ? ` class="${cls.join(' ')}"` : ''}>
      <td class="cat">${escapeHtml(cat)}</td>
      <td class="name">${assChip(r, off)}${note}${whyNote(r)}</td>
      <td class="num">${r.points === null ? '–' : fmtNum(r.points)}</td>
      <td class="num">${extraCell(r)}</td>
      <td class="num">${frac(r.weight_in_cat)}</td>
      <td class="num strong">${frac(r.weight_total)}</td>
      <td class="num">${pct(r.mean_nonzero)}</td>
      <td class="num">${r.n_complete === null ? '–'
        : `${r.n_complete}/${r.n_student}`}</td>
      <td>${maxCell(r)}</td>
    </tr>`;
  }).join('');

  $('weight-table').innerHTML = `<table class="weights">
    <colgroup>${COL_WIDTH_TUP.map((w) => `<col style="width:${w}">`)
    .join('')}</colgroup>
    <thead><tr>${SORT_TUP.map(headCell).join('')}</tr></thead>
    <tbody>${row}${addRow()}</tbody></table>
    <p class="hint">* mean among non-zero scores</p>`;
}

/* Leaving an assignment out must not move it.  Excluded assignments arrive
 * from a different list than graded ones, so appending them sends a row to
 * the bottom the moment it is switched off -- and the row you just clicked
 * is the one you are still looking at.  Position comes from the assignment,
 * never from what has been decided about it. */
function stableOrder(rowList) {
  const order = ((state.form || {}).cat_list || []).map((c) => c.name);

  const key = (r) => {
    const cat = r.category
      || order.find((c) => r.assignment.includes(c));
    const idx = cat === undefined || cat === null ? order.length
      : order.indexOf(cat);
    return [idx < 0 ? order.length : idx, r.assignment];
  };

  rowList.sort((a, b) => {
    const x = key(a);
    const y = key(b);
    return x[0] - y[0] || String(x[1]).localeCompare(String(y[1]));
  });
}

function headCell(col) {
  const on = state.sort && state.sort.key === col.key;
  const arrow = on ? (state.sort.dir === 'down' ? ' ▼' : ' ▲') : '';
  return `<th class="${col.num ? 'num ' : ''}sortable" data-sort="${col.key}"
    title="sort by ${escapeHtml(col.label)}">${escapeHtml(col.label)}${
    arrow}</th>`;
}

function assChip(r, off) {
  const why = off ? 'waived for everyone — click to put it back'
    : 'click to waive this assignment, or drag it onto another to take '
      + 'the best of both';

  return `<span class="chip ass ${off ? 'is-off' : ''}" data-ass="${
    escapeHtml(r.assignment)}" role="button" tabindex="0"
    title="${escapeHtml(why)}"><span class="chip-k">${
    escapeHtml(r.assignment)}</span>${r.planned
      ? '<span class="chip-v">not set</span>' : ''}</span>`
    + (r.planned ? `<button type="button" class="x" data-unplan="${
      escapeHtml(r.assignment)}" title="remove this assignment"
      >&times;</button>` : '');
}

/* Extra credit counts towards what a student earned and not towards what
 * was available, so it can only raise a grade -- and skipping it costs
 * nothing, which is the difference between extra credit and an assignment. */
function extraCell(r) {
  const on = isExtra(r.assignment);
  return `<input type="checkbox" data-extra="${escapeHtml(r.assignment)}"${
    on ? ' checked' : ''} title="${on
    ? 'extra credit: its points are not part of the grade it is a share of'
    : 'make this extra credit: it can raise a grade but never lower one'}">`;
}

function whyNote(r) {
  return r.excluded_by
    ? `<div class="row-warn">${escapeHtml(r.excluded_by)}</div>` : '';
}

function maxCell(r) {
  const from = maxOf(r.assignment);
  if (!from) return '';

  // the alternates count twice unless they are excluded as well, which is
  // the mistake this invites, so the offer to fix it sits on the row
  const open = from.filter((a) => !((state.form || {}).exclude_list || [])
    .some((e) => a.includes(e)));

  return `<span class="chip is-max">
      <span class="chip-v">${escapeHtml(r.assignment)} = max(${
    escapeHtml([r.assignment, ...from].join(', '))})</span>
      <button type="button" data-unsub="${escapeHtml(r.assignment)}"
        title="undo this">&times;</button>
    </span>` + (open.length
    ? `<button type="button" class="small nag" data-excl-add="${
      escapeHtml(open.join(','))}">also leave out ${
      escapeHtml(open.join(', '))}</button>` : '');
}

function addRow() {
  return `<tr class="add-row">
    <td><button type="button" id="plan-go" class="plus"
      title="add an assignment">+</button></td>
    <td><input type="text" id="plan-name" placeholder="assignment"></td>
    <td class="num"><input type="number" id="plan-points" min="1" step="1"
      placeholder="pts" class="pct"></td>
    <td colspan="6"></td>
  </tr>`;
}

function frac(x) {
  return x === null || x === undefined ? '–' : `${(x * 100).toFixed(1)}%`;
}

/* ------------------------------------------------------------ assignments */

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
  // a page about one student is always about that student: there is nobody
  // to pick, and no picker to pick them with
  const email = state.solo || $('stud').value.trim();
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
          id="stud-csv">${escapeHtml(
    state.solo ? SHEET_NAME : studentFile(stud))}</button>` : ''}
        ${graded
          ? `<span class="stud-grade">${delta(stud, graded)}${pct(graded.mean)}
              <span class="stud-letter">${escapeHtml(graded.letter)}</span>
             </span>`
          : '<span class="empty">no grade yet</span>'}
      </div>
      ${graded ? catRow(graded) : ''}
      ${graded ? scoreBlock(graded, stud) : ''}
      ${graded ? lateGrid(graded) : ''}
      ${excuseRow(form, stud)}
      ${state.solo ? adjustBlock(form, stud) : ''}
      ${state.solo ? '' : noteBox(form, stud)}
      ${graded ? auditLog(graded) : ''}
      ${state.solo && graded ? threshRow(graded) : ''}
    </div>`;
}

/* Why this student's grade was adjusted, in the instructor's own words.  It
 * is kept in the policy next to the adjustment it explains, so that the
 * reason outlives the email thread that produced it -- and so that the
 * person asking in May is answered by the file rather than by memory. */
function noteBox(form, stud) {
  const note = (form.note_dict || {})[stud.email] || '';
  const hint = 'note to self — why this grade was adjusted? '
    + 'store a note in the YAML for future reference';

  return `<div class="stud-note"><textarea id="stud-note" rows="3"
    placeholder="${escapeHtml(hint)}">${
  escapeHtml(note)}</textarea></div>`;
}

function catRow(graded) {
  const cell = ([k, v]) =>
    `<span class="mini"><span class="mini-k">${escapeHtml(k)}</span>` +
    `<span class="mini-v">${pct(v)}</span></span>`;

  const cat = Object.entries(graded.cat_dict).map(cell).join('');
  return cat ? `<div class="mini-row cat-means">${cat}</div>` : '';
}

/* The same scores, as a control for whoever is reading them: an instructor
 * waives one, a student supposes one. */
function scoreBlock(graded, stud) {
  return state.solo ? whatIfGrid(graded, stud) : scoreGrid(graded, stud);
}

/* Scores grouped by the categories the policy already defines, because
 * fifteen chips in one row is a list and four rows of four is a gradebook. */
function scoreRows(graded, chipOf) {
  const group = new Map();
  for (const a of graded.ass_list) {
    const key = a.category || 'other';
    if (!group.has(key)) group.set(key, []);
    group.get(key).push(a);
  }

  return [...group.entries()].map(([cat, list]) => `
    <div class="grid-group">
      <span class="grid-k">${escapeHtml(cat)}</span>
      <div class="chips">${list.map(chipOf).join('')}</div>
    </div>`).join('');
}

/* Clicking one waives it: the thing an instructor came here to do. */
function scoreGrid(graded, stud) {
  const block = scoreRows(graded, scoreChip);

  return `<div class="waive-row block">
    <span class="field-k">scores <span class="sub">click to waive, drag
      one onto another to take the best of both</span></span>
    <div class="grid">${block}${maxGroup(stud)}</div>
  </div>`;
}

/* Every score, as a box holding what it is -- so that a student can put
 * something else in it and watch the grade follow.  What has not been graded
 * yet is the row that matters: a whole term's policy is already written down,
 * so the arithmetic on "what do I need on the final" is sitting right here.
 *
 * A box left as it was is not an answer, and nothing is written into the file
 * for it.  Only what was typed is supposed. */
function whatIfGrid(graded, stud) {
  const block = scoreRows(graded, whatIfBox);
  const n = Object.keys(state.whatIf).length
    + Object.keys(state.whatIfDay).length;

  // the em dash is the placeholder in an empty box, so the sentence names
  // what a reader is actually looking at
  const clear = n
    ? ` — <button type="button" class="link" id="whatif-clear">clear all ${
      n} you have entered</button>`
    : '';

  return `<div class="waive-row block">
    <span class="field-k">your scores <span class="sub">Enter your scores to
      compute your final grade. Scores marked as "—" are
      ignored.${clear}</span></span>
    <div class="grid">${block}${maxGroup(stud)}</div>
  </div>`;
}

/* One score: the chip an instructor sees, with the value as a box.
 *
 * data-score is on it, so the click and the drag do here exactly what they do
 * on an instructor's copy -- waive this, or take the best of it and another.
 * A span rather than a label: a label would hand a click on the assignment
 * name to the input, and that click means "waive".
 *
 * The input is the only tab stop on it, because typing a term's worth of
 * scores is the frequent thing and a second stop per chip would double the
 * tabbing.  Waiving by keyboard is the gap that leaves; the file's own header
 * says how to write a waiver by hand. */
function whatIfBox(a) {
  const supposed = Object.prototype.hasOwnProperty.call(state.whatIf, a.name);

  // waived is the same fact for either reader, and the same chip: nothing to
  // suppose about work that was never assigned, and clicking counts it again
  if (a.waived) return scoreChip(a);

  const points = a.points === null || a.points === undefined ? '' : a.points;
  const earned = a.perc === null || a.perc === undefined || !a.submitted
    ? '' : Math.round(a.perc * points * 100) / 100;
  const value = supposed ? state.whatIf[a.name] : earned;

  const said = a.planned ? 'not assigned yet — suppose a score'
    : !a.submitted ? 'nothing handed in, so it counts as zero'
      : 'what you were given';
  const why = `${said}. click to waive it, drag onto another to take the `
    + 'best of both, or type a different score';

  return `<span class="chip score whatif${supposed ? ' is-supposed' : ''}${
    a.planned ? ' is-planned' : ''}${
    !supposed && !a.submitted ? ' is-missing' : ''}"
    data-score="${escapeHtml(a.name)}" title="${escapeHtml(why)}">
    <span class="chip-k">${escapeHtml(a.name)}</span>
    <span class="chip-v"><input type="number" step="any" min="0"
      data-whatif="${escapeHtml(a.name)}" value="${value}"
      placeholder="—" aria-label="${escapeHtml(a.name)} score">
      <span class="of">/ ${escapeHtml(String(points))}</span></span>
  </span>`;
}

/* Everything this estimate is assuming about the reader in particular.
 *
 * The policy they were given is the class's, so it holds none of it -- and a
 * student who was emailed about a waiver has to say so here or read a number
 * that is not theirs.  Which makes this list the answer to "what is this
 * working from", and that is worth showing even when it is empty: an empty
 * list is the fact that nothing special is being assumed, and a student who
 * expected an entry in it has just learned something.
 *
 * Everything here writes the same yaml sections an instructor's copy would,
 * so a policy annotated this way is one the command line reads too. */
function adjustBlock(form, stud) {
  const waived = waiveList(form, 'waive');
  const forgiven = waiveList(form, 'waive_late');
  const offList = excuseOffsets(form, stud);

  const row = [
    ...waived.map((ass) => adjustChip('waive', ass, 'waived')),
    ...forgiven.map((ass) =>
      adjustChip('waive_late', ass, 'late penalty forgiven')),
    // a best-of-both is an assumption like any other, and this list saying
    // "nothing" while one was in force would be the list being wrong
    ...maxTargets(stud).map(([target, fromList]) => adjustChip(
      'max', target, `best of ${[target, ...fromList].join(', ')}`)),
    ...offList.map((c) => adjustChip(
      'excuse', c.name, `${c.days > 0 ? '+' : ''}${c.days} late `
      + `${plural(Math.abs(c.days), 'day')}`)),
  ].join('');

  return `<div class="waive-row block adjust">
    <span class="field-k">adjustments</span>
    <div class="grid">
      <div class="chips">${row
    || '<span class="empty">nothing — you are being graded by the class '
      + 'policy exactly as written</span>'}</div>
    </div>
  </div>`;
}

/* every assignment named in one of the two waive sections, for this reader */
function waiveList(form, kind) {
  const cur = (waiveOf(form, kind) || [])
    .find((w) => w.email === (state.solo || ''))
    || (waiveOf(form, kind) || [])[0];
  return (cur || {}).ass_list || [];
}

function maxTargets(stud) {
  const cur = ((state.form || {}).max_list || [])
    .find((s) => s.email === stud.email);
  return Object.entries((cur || {}).target_dict || {});
}


function excuseOffsets(form, stud) {
  return (form.cat_list || []).filter((c) => c.late).map((c) => ({
    name: c.name,
    days: ((c.late || {}).excuse_day_offset || {})[stud.email] || 0,
  })).filter((c) => c.days);
}

function adjustChip(kind, ass, said) {
  return `<span class="chip is-adjust">
    <span class="chip-k">${escapeHtml(ass)}</span>
    <span class="chip-v">${escapeHtml(said)}</span>
    <button type="button" data-unadjust="${escapeHtml(kind)}"
      data-ass="${escapeHtml(ass)}" title="take this back out">&times;</button>
  </span>`;
}

/* Where the letters fall, because the question a grade provokes is how far
 * away the next one is.  Read from the policy that produced the letter, so
 * the answer cannot be a different set of cutoffs than the one applied. */
function threshRow(graded) {
  const list = (state.grades || {}).thresh_list || [];
  if (!list.length) return '';

  const cell = (item) => `<span class="mini${
    item.letter === graded.letter ? ' is-mine' : ''}">
    <span class="mini-k">${escapeHtml(item.letter)}</span>
    <span class="mini-v">${pct(item.perc)}</span></span>`;

  return `<details class="audit" data-fold="thresh"${foldOpen('thresh')}>
    <summary>letter grades <span class="sub">what each one takes</span>
    </summary>
    <div class="mini-row">${list.map(cell).join('')}</div>
  </details>`;
}

/* The maxes standing for this student, as one more row of the same grid --
 * they are a kind of score, arrived at differently.  Each says its whole
 * arithmetic, because a drag is easy to make by accident and otherwise
 * leaves no mark on the score it changed. */
function maxGroup(stud) {
  const cur = ((state.form || {}).max_list || [])
    .find((s) => s.email === stud.email);
  const entries = Object.entries((cur || {}).target_dict || {});
  if (!entries.length) return '';

  const chip = entries.map(([target, fromList]) =>
    `<span class="chip is-max">
      <span class="chip-v">${escapeHtml(target)} = max(${
        escapeHtml([target, ...fromList].join(', '))})</span>
      <button type="button" data-unmax="${escapeHtml(target)}"
        title="undo this">&times;</button>
    </span>`).join('');

  return `<div class="grid-group">
    <span class="grid-k">max</span>
    <div class="chips">${chip}</div>
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
      : !a.submitted
        ? 'nothing submitted, counts as zero — click to waive, '
          + 'drag to another assignment to copy'
        : 'click to waive, drag to another assignment to copy';

  // a span rather than a button, dragged by pointer events rather than the
  // draggable attribute: see the pointerdown handler for why
  return `<span class="chip ${cls}" data-score="${escapeHtml(a.name)}"
    role="button" tabindex="0"
    title="${escapeHtml(why)}">` +
    `<span class="chip-k">${escapeHtml(a.name)}</span>` +
    `<span class="chip-v">${text}</span></span>`;
}

/* Dragging one score onto another gives that student the better of the two,
 * for the makeup only they sat.  The same rule as a policy-wide substitution,
 * without inventing a policy-wide rule to describe one arrangement. */
function dropSubstitute(fromName, toName) {
  const stud = pickedStudent();
  if (!stud || fromName === toName) return;

  applyEdit('set_max', {
    email: stud.email,
    target: toName,
    ass_list: [...new Set([...studMaxOf(toName), fromName])],
  });
}

/* Every assignment a late penalty could act on -- not only the late ones, so
 * a penalty can be forgiven before it is incurred as readily as after, and
 * not the ones in categories with no penalty, where lateness is trivia. */
function lateGrid(graded) {
  const list = graded.ass_list.filter(
    (a) => a.late_counts && (a.submitted || a.late_days));
  if (!list.length) return '';

  if (state.solo) return lateBoxGrid(graded, list);

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
    <span class="field-k">late <span class="sub">what it was, and what it
      cost — click to forgive one you were told was excused</span></span>
    <div class="grid">
      ${summary ? `<div class="mini-row">${summary}</div>` : ''}
      <div class="chips">${list.map(lateChip).join('')}</div>
    </div>
  </div>`;
}

/* The same row, for the reader whose lateness it is.  An instructor reads
 * days late off the export; a student has to say, so each one is a box.
 *
 * Only work with a score in it appears, which is the filter lateGrid already
 * applies: there is nothing to be late on until something was handed in. */
function lateBoxGrid(graded, list) {
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
    <span class="field-k">days late <span class="sub">Be sure to put in late
      days for accurate computation too</span></span>
    <div class="grid">
      ${summary ? `<div class="mini-row">${summary}</div>` : ''}
      <div class="chips">${list.map(lateBox).join('')}</div>
    </div>
  </div>`;
}

function lateBox(a) {
  // waiving an assignment nulls its lateness as well, so there is no longer
  // a question here to answer
  if (a.waived) {
    return `<span class="chip late-c is-waived" title="${escapeHtml(
      a.name)} is waived, so its lateness is not counted either">` +
      `<span class="chip-k">${escapeHtml(a.name)}</span>` +
      `<span class="chip-v">forgiven</span></span>`;
  }

  if (a.late_waived) {
    return `<button type="button" class="chip late-c is-waived" data-late="${
      escapeHtml(a.name)}" title="late penalty forgiven — click to count it ` +
      `again"><span class="chip-k">${escapeHtml(a.name)}</span>` +
      `<span class="chip-v">forgiven</span></button>`;
  }

  const entered = Object.prototype.hasOwnProperty.call(state.whatIfDay,
                                                       a.name);
  // falling back on the days already being charged, not on empty: a sheet
  // saved and dropped back in carries its own lateness, and a box reading
  // blank beside a penalty being applied would be the page contradicting
  // itself
  const value = entered ? state.whatIfDay[a.name] : (a.late_days || '');

  // the forgive control only where there is a penalty to forgive: an
  // assignment nobody has said was late has nothing to take off it
  const forgive = a.late_days
    ? `<button type="button" class="chip-forgive" data-late="${
      escapeHtml(a.name)}" title="forgive the late penalty on ${escapeHtml(
      a.name)} — for one you were told was excused">forgive</button>`
    : '';

  return `<span class="chip late-c whatif${entered ? ' is-supposed' : ''}${
    a.late_days ? ' is-late' : ''}">
    <span class="chip-k">${escapeHtml(a.name)}</span>
    <span class="chip-v"><input type="number" step="1" min="0"
      data-whatif-day="${escapeHtml(a.name)}" value="${value}"
      placeholder="0" aria-label="${escapeHtml(a.name)} days late">
      <span class="of">d</span></span>${forgive}
  </span>`;
}

function lateChip(a) {
  // waiving an assignment nulls its lateness as well -- the penalty follows
  // the waiver -- so "on time" would be describing a fact that no longer
  // applies to a grade
  if (a.waived) {
    return `<span class="chip late-c is-waived" title="${escapeHtml(
      a.name)} is waived, so its lateness is not counted either">` +
      `<span class="chip-k">${escapeHtml(a.name)}</span>` +
      `<span class="chip-v">forgiven</span></span>`;
  }

  const cls = a.late_waived ? 'late-c is-waived'
    : a.late_days ? 'late-c is-late' : 'late-c';

  // days are what the penalty counts, but "2d" hides whether that was two
  // minutes past a deadline or two whole days
  const exact = a.late_minutes ? ` = ${hhmm(a.late_minutes)}` : '';
  const value = a.late_waived ? 'forgiven'
    : a.late_days ? `${a.late_days}d${exact}`
      : a.late_minutes ? `0d${exact}` : 'on time';

  const inGrace = a.late_minutes && !a.late_days;

  const why = a.late_waived
    ? 'late penalty forgiven — click to count it again'
    : inGrace ? `${hhmm(a.late_minutes)} late, inside the grace period`
      : 'click to forgive any late penalty on this';

  return `<button type="button" class="chip ${cls}" data-late="${
    escapeHtml(a.name)}" title="${escapeHtml(why)}">` +
    `<span class="chip-k">${escapeHtml(a.name)}</span>` +
    `<span class="chip-v">${escapeHtml(value)}</span></button>`;
}

/* Whether a fold was open last time it was drawn.  toggle doesn't bubble,
 * so the listener that records this captures instead. */
function foldOpen(key) {
  return state.fold[key] ? ' open' : '';
}

document.addEventListener('toggle', (e) => {
  const key = e.target.getAttribute && e.target.getAttribute('data-fold');
  if (key !== null && key !== undefined) state.fold[key] = e.target.open;
}, true);

/* Every step that moved this number, in order.  The question after a final
 * grade is always how it was arrived at, and a list of decisions answers it
 * where a number cannot. */
function auditLog(graded) {
  const list = graded.log_list || [];
  if (!list.length) return '';

  return `<details class="audit" data-fold="audit"${foldOpen('audit')}>
    <summary>computation log <span class="sub">${list.length} steps</span>
    </summary>
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

/* For an instructor, the same file --per_student writes: everything behind
 * one grade, which is what you attach to the email asking why it is what it
 * is.
 *
 * For the student whose grade it is, that file explains what is already on
 * the screen in front of them.  What they have and the page does not is their
 * own typing, so theirs is the sheet -- the one file that brings it back. */
function downloadStudentCsv() {
  const stud = pickedStudent();
  if (!stud) return;

  if (state.solo) return download(gradedCsv(), SHEET_NAME, 'text/csv');

  const res = toJs(state.api.student_csv(gradedCsv(), state.yaml, stud.email,
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
    <span class="field-k">extra late days${state.solo
    ? ' <span class="sub">Just for you, above and beyond the late days given '
      + 'to all students</span>' : ''}</span>
    <div class="checks">${late.map((c) => {
      const off = ((c.late || {}).excuse_day_offset || {})[stud.email] || 0;
      return `<label class="f">${escapeHtml(c.name)}
        <input type="number" data-excuse="${escapeHtml(c.name)}" step="1"
          value="${off}"></label>`;
    }).join('')}</div>
  </div>`;
}

function drawWaiveList(form) {
  const row = [];

  for (const w of form.waive_list) {
    row.push({ email: w.email, kind: 'waived',
               what: w.ass_list.join(', '),
               undo: `waive:${w.email}` });
  }
  for (const w of form.waive_late_list) {
    row.push({ email: w.email, kind: 'late forgiven',
               what: w.ass_list.join(', '),
               undo: `waive_late:${w.email}` });
  }
  for (const s of (form.max_list || [])) {
    for (const [target, from] of Object.entries(s.target_dict || {})) {
      row.push({ email: s.email, kind: 'maximum',
                 what: `${target} = max(${[target, ...from].join(', ')})`,
                 undo: `max:${s.email}:${target}` });
    }
  }
  // an accommodation is an adjustment for one student like any other, and
  // was the one this list used to leave out
  for (const c of form.cat_list) {
    const offset = (c.late || {}).excuse_day_offset || {};
    for (const [email, days] of Object.entries(offset)) {
      row.push({ email, kind: 'extra late days',
                 what: `${days > 0 ? '+' : ''}${days} on ${c.name}`,
                 undo: `excuse:${email}:${c.name}` });
    }
  }

  // a note changes no grade, but it is the record of why one was changed,
  // and this list is where you go to find out what was done for whom
  for (const [email, note] of Object.entries(form.note_dict || {})) {
    row.push({ email, kind: 'note', what: note, undo: `note:${email}` });
  }

  // always present, so that "is there anything set for anyone?" is answered
  // by opening it rather than by noticing whether it exists
  $('waive-count').textContent = row.length === 1
    ? '1 adjustment' : `${row.length} adjustments`;

  if (!row.length) {
    return ($('waive-list').innerHTML =
      '<p class="empty">Nothing is set for any individual student.</p>');
  }

  $('waive-list').innerHTML =
    '<table class="waive-table"><tbody>' + row.map((w) => `<tr>
      <td><button type="button" class="link" data-goto="${
        escapeHtml(w.email)}">${escapeHtml(w.email)}</button></td>
      <td><span class="adj-k">${escapeHtml(w.kind)}</span></td>
      <td class="name">${escapeHtml(w.what)}</td>
      <td><button type="button" class="x" data-undo="${escapeHtml(w.undo)}"
        title="remove">&times;</button></td>
    </tr>`).join('') + '</tbody></table>';
}

/* one undo for every kind of adjustment, keyed by what it is */
function undoAdjustment(token) {
  const part = token.split(':');
  const kind = part[0];
  const email = part[1];

  if (kind === 'waive' || kind === 'waive_late') {
    return applyEdit('set_waive', { email, ass_list: [], field: kind });
  }
  if (kind === 'max') {
    return applyEdit('set_max', { email, target: part[2], ass_list: [] });
  }
  if (kind === 'excuse') {
    return applyEdit('set_excuse_offset',
                     { cat: part[2], email, days: 0 });
  }
  if (kind === 'note') {
    return applyEdit('set_note', { email, note: '' });
  }
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
  const res = toJs(state.api.grade(gradedCsv(), state.yaml, state.name));

  if (!res.ok) {
    state.grades = null;
    $('inspect-panel').hidden = true;
    $('weight-table').innerHTML = '';
    $('messages').innerHTML += msgList([res.error], 'error');
    return;
  }

  state.grades = res;
  // the check already showed whatever the report said, and the report exists
  // to say what grading would -- so the overlap is by design, and showing it
  // twice reads as two problems
  const shownSet = new Set(((state.report || {}).warn_list) || []);
  $('messages').innerHTML += msgList(
    (res.warn_list || []).filter((s) => !shownSet.has(s)), 'warn');
  drawWeightTable();
  drawInspector();
  if (pickedStudent()) drawStudent(state.form);
}

/* --------------------------------------------------------- the inspector */

const MODE_HINT = {
  final: 'The grade as it stands, with the score rules and late penalties ' +
         'applied.',
  raw: 'The same grade before drop-lowest / keep-highest and late ' +
       'penalties — what every score, weighted by its points, would give.',
  both: 'Before and after the policy, overlaid. The gap between them is ' +
        'what your score rules and late penalties did.',
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

/* Whether there is work in the page that exists nowhere else.
 *
 * The files line says nothing about this any more -- whether a reader has put
 * a copy somewhere is between them and their filesystem, and a page keeping
 * score of it was answering a question nobody asked.  Two things still want
 * the answer: the exit guard, and the student example, which is the one
 * button that replaces the file being edited.
 *
 * A saved document is not at risk, and a seed the page wrote by itself and
 * nobody has touched is not work -- warning about either is how a guard
 * teaches people to click through it. */
function isDirty() {
  // nothing written is nothing to lose: a student waiting on the policy file
  // their instructor sent has no work in the page to be warned about
  if (!state.yaml) return false;
  if (state.yaml === state.savedYaml) return false;
  if (state.savedYaml === null && state.yaml === state.seedYaml) return false;
  return true;
}

/* An anchor download reports nothing back: not that it succeeded, and not
 * that the reader cancelled a save dialog.  So this is the page believing it
 * did what it was told, which is the better bet -- browsers save without
 * asking by default, and a guard that can never be satisfied is one nobody
 * gets past twice. */
function markSaved(text) {
  state.savedYaml = text;
}

function fileOf(key) {
  if (key === 'csv') {
    // a student's scores live in this file and nowhere else -- their policy
    // holds the adjustments they claimed, not the marks they got -- so what
    // is offered is the sheet with what they typed in it.  dropped back next
    // time alongside the policy it is a gradebook of one, which is read as
    // their own grade, so saving it is how a term's typing survives
    return [state.solo ? gradedCsv() : state.csv, state.name, 'text/csv'];
  }
  if (key === 'yaml') {
    return [state.yaml, state.policyName, 'text/yaml'];
  }
  // built on the spot rather than held: it is a view of the policy above it,
  // and a stale copy of that would be worse than none.  A policy that will
  // not grade the class has nothing for the class's copy to agree with, which
  // is the whole of what it is for, so it is refused rather than written
  if (key === 'public') {
    const res = toJs(state.api.student_policy(state.csv, state.yaml,
                                              state.name));
    if (!res.ok) {
      showPickError(res.error);
      return null;
    }
    return [res.yaml, res.filename, 'text/yaml'];
  }
  if (key === 'canvas') {
    return [state.canvasText, state.canvasName, 'text/csv'];
  }
  return null;
}

/* Every file the page is holding, one per line, each saying what saving it
 * would be for.  On one line they read as a breadcrumb trail; the point of
 * them is that they are the save buttons, and nothing is kept between
 * visits. */
function drawFiles() {
  if (!state.csv) return ($('files').innerHTML = '');

  const part = [
    '<span class="file-k">your files</span>',
    // a student's scores live in this csv and nowhere else, so what it is
    // good for is worth saying rather than left to be inferred from a name
    fileRow('csv', state.name, state.solo
      ? 'your scores — save this to pick up where you left off'
      : state.facts),
  ];

  // no row for a file that does not exist yet: a student who has dropped
  // their scores in and is waiting on the policy has nothing here to link
  if (state.yaml) {
    part.push(fileRow('yaml', state.policyName, state.solo
      ? 'the policy you were given, and any adjustments you added'
      : 'Contains the whole grading policy'));
  }

  // the same policy with every student taken out of it.  offered beside the
  // file it is made from rather than among the exports, because the choice a
  // reader makes here is which of the two to hand out -- and built when asked
  // for, since a copy kept around would go stale against the one above it
  if (state.grades && !state.solo) {
    part.push(fileRow('public', NAME_PUBLIC,
                      'Contains the grading policy without any individual '
                      + 'student adjustments, ready to share with '
                      + 'everyone.'));
  }

  if (state.canvasText && !state.sourceIsCanvas) {
    part.push(fileRow('canvas', state.canvasName,
                      'your canvas gradebook, to merge grades back into'));
  }

  $('files').innerHTML = part.join('');
}

function fileRow(key, name, note) {
  return `<span class="file-row">${fileLink(key, name, note)}</span>`;
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

/* this box has its own error line, which is where its own trouble belongs */
function takeCanvasFile(file) {
  readText(file)
    .then((text) => setCanvasTemplate(file.name, text))
    .catch((err) => ($('canvas-hint').textContent = err.message));
}

function setCanvasTemplate(name, text) {
  const info = toJs(state.api.load_csv(text, name));
  if (!info.ok || info.source !== 'canvas') {
    $('canvas-hint').textContent = info.ok
      ? `${name} is not a canvas gradebook export — it has no SIS user id `
        + 'column to match students by.'
      : info.error;
    return;
  }
  state.canvasText = text;
  state.canvasName = name;
  drawCanvasDrop();
  drawFiles();
  drawExport();
}

/* Each export wants different things of you -- a canvas gradebook to merge
 * into, a term code and CRNs, or nothing at all -- and three sets of inputs
 * on screen at once left it unclear which belonged to which.  So: pick the
 * one you are doing, and see only what it asks for. */
const EXPORT_MODE_TUP = ['grades', 'canvas', 'banner'];

function drawExport() {
  drawCanvasDrop();

  const ready = !!state.grades;
  $('export-mode').hidden = !ready;
  EXPORT_MODE_TUP.forEach((mode) =>
    ($(`export-pane-${mode}`).hidden = true));

  if (!ready) {
    $('export-hint').hidden = false;
    $('export-hint').textContent =
      'Exports appear once the policy grades cleanly.';
    return;
  }
  $('export-hint').hidden = true;

  Array.from($('export-mode').children).forEach((el) =>
    el.classList.toggle('on', el.dataset.mode === state.exportMode));
  $(`export-pane-${state.exportMode}`).hidden = false;

  // the canvas tab stays reachable with no template set -- the drop zone
  // that sets one lives inside it.  the export button is what waits
  const canCanvas = !!state.canvasText;
  $('dl-canvas').disabled = !canCanvas;
  $('dl-canvas').classList.toggle('secondary', !canCanvas);
  $('canvas-hint').textContent = canCanvas
    ? 'The canvas export merges these grades into your canvas gradebook by '
      + 'SIS user id, scaled to 100 so canvas does not round them.'
    : 'Drop the gradebook canvas exported to enable this.';
}

function setExportMode(mode) {
  state.exportMode = mode;
  drawExport();
  if (mode === 'banner') $('term-code').focus();
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
  if (e.target.files.length) takeFileList(e.target.files);
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
  takeFileList(e.dataTransfer.files);
});

/* the same hundred students, exported by each platform.  the pair is worth
 * having on the page: what canvas leaves out (submission times, and so every
 * late penalty) is easier to see than to explain */
async function useExample(name) {
  const res = await fetch(name);
  useCsv(name, await res.text());
}

/* The other half of the same course: what its instructor would post for it,
 * which is all a student is given.  Loading it is the student's way in, so it
 * goes through the same door a dropped file does.
 *
 * The gradebook is cleared first, because the button promises the student's
 * page and a policy dropped onto a class is a different act entirely.  That
 * makes this the one example that replaces the file being edited, so unsaved
 * work is refused rather than carried off. */
async function useExamplePolicy(name) {
  if (isDirty()) {
    return showPickError('Your policy has unsaved changes, and the student '
      + 'example would replace it — save it from the files line first.');
  }

  const res = await fetch(name);
  state.csv = null;
  state.canvasText = null;
  useYaml(name, await res.text());
}

$('demo').addEventListener('click', () => useExample('ex_gradescope.csv'));
$('demo-canvas').addEventListener('click', () => useExample('ex_canvas.csv'));
$('demo-student').addEventListener('click',
                                   () => useExamplePolicy(
                                     'ex_policy_public.yaml'));

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
  else if (act === 'rule' || act === 'rule-n') {
    // the select and the number are one setting: read both, whichever moved
    const card = e.target.closest('.cat-card');
    const rule = card.querySelector('[data-act="rule"]').value;
    const box = card.querySelector('[data-act="rule-n"]');
    // picking a rule where there was none has no number yet, and writing the
    // 0 is what makes the choice stick and the warning appear
    if (!rule) applyEdit('clear_rule', { cat });
    else applyEdit(rule === 'keep' ? 'set_keep_high' : 'set_drop_low',
                   { cat, n: box ? Number(box.value) : 0 });
  } else if (act === 'late-on') {
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

/* The weights table: sorting, excluding, un-planning, and dragging one
 * assignment onto another.  Class-wide, where the student card's identical
 * gestures are for one person. */

$('weight-table').addEventListener('change', (e) => {
  const extra = e.target.getAttribute('data-extra');
  if (extra !== null) toggleExtra(extra);
});

$('weight-table').addEventListener('click', (e) => {
  if (e.target.getAttribute('data-extra') !== null) return;

  const sort = e.target.closest('[data-sort]');
  if (sort) {
    const key = sort.getAttribute('data-sort');
    state.sort = (state.sort && state.sort.key === key)
      ? (state.sort.dir === 'up' ? { key, dir: 'down' } : null)
      : { key, dir: 'up' };
    return drawWeightTable();
  }

  const unplan = e.target.getAttribute('data-unplan');
  if (unplan !== null) {
    return applyEdit('set_planned', { ass: unplan, points: 0 });
  }

  const unsub = e.target.getAttribute('data-unsub');
  if (unsub !== null) {
    return applyEdit('set_substitute', { target: unsub, ass_list: [] });
  }

  const add = e.target.getAttribute('data-excl-add');
  if (add !== null) {
    return applyEdit('set_exclude', {
      ass_list: [...state.form.exclude_list, ...add.split(',')],
    });
  }

  if (e.target.id === 'plan-go') return addPlanned();

  if (assDragMoved) return;
  const chip = e.target.closest('[data-ass]');
  if (chip) toggleExclude(chip.getAttribute('data-ass'));
});

$('weight-table').addEventListener('keydown', (e) => {
  if (e.key !== 'Enter') return;
  if (e.target.id === 'plan-name' || e.target.id === 'plan-points') {
    e.preventDefault();
    return addPlanned();
  }
  const chip = e.target.closest('[data-ass]');
  if (chip) {
    e.preventDefault();
    toggleExclude(chip.getAttribute('data-ass'));
  }
});

function addPlanned() {
  const name = $('plan-name').value.trim().replace(/\s+/g, '').toLowerCase();
  const points = Number($('plan-points').value) || 0;
  if (!name || points <= 0) return;
  applyEdit('set_planned', { ass: name, points });
}

/* An assignment is excluded by name, and the name is what the chip says, so
 * removing it again is removing that name rather than anything cleverer. */
function toggleExclude(ass) {
  applyEdit('set_exclude', {
    ass_list: without((state.form || {}).exclude_list, ass),
  });
}

function toggleExtra(ass) {
  applyEdit('set_extra', {
    ass_list: without((state.form || {}).extra_list, ass),
  });
}

/* An assignment is named by the chip, and the name in the policy may be a
 * fragment of it, so switching a setting off removes whatever named it
 * rather than looking for the full name and finding nothing. */
function without(cur, ass) {
  const list = cur || [];
  const hit = list.filter((s) => ass.includes(s));
  return hit.length ? list.filter((s) => !hit.includes(s)) : [...list, ass];
}

/* the same pointer drag as the student card, on the class-wide table */
let assDrag = null;
let assDragMoved = false;

$('weight-table').addEventListener('pointerdown', (e) => {
  if (e.button !== 0) return;
  const chip = e.target.closest('[data-ass]');
  if (!chip) return;

  assDrag = { from: chip.getAttribute('data-ass'), chip,
              x: e.clientX, y: e.clientY, moved: false };
  try {
    chip.setPointerCapture(e.pointerId);
  } catch (err) { /* an optimisation only */ }
});

$('weight-table').addEventListener('pointermove', (e) => {
  if (!assDrag) return;

  if (!assDrag.moved) {
    if (Math.hypot(e.clientX - assDrag.x, e.clientY - assDrag.y) < 5) return;
    assDrag.moved = true;
    assDrag.chip.classList.add('dragging');
    const ghost = document.createElement('div');
    ghost.id = 'drag-ghost';
    document.body.appendChild(ghost);
  }

  const over = chipAtSel(e.clientX, e.clientY, '#weight-table [data-ass]');
  markDrag(over, assDrag.from, e.clientX, e.clientY);
});

$('weight-table').addEventListener('pointerup', (e) => {
  if (!assDrag) return;

  const from = assDrag.from;
  const moved = assDrag.moved;
  const over = moved
    ? chipAtSel(e.clientX, e.clientY, '#weight-table [data-ass]') : null;
  assDrag = null;
  clearDragMarks();

  if (!moved) return;
  assDragMoved = true;
  setTimeout(() => { assDragMoved = false; }, 0);

  const to = over && over.getAttribute('data-ass');
  if (!to || to === from) return;

  const cur = maxOf(to) || [];
  applyEdit('set_substitute', {
    target: to, ass_list: [...new Set([...cur, from])],
  });
});

$('weight-table').addEventListener('pointercancel', () => {
  assDrag = null;
  clearDragMarks();
});

$('stud').addEventListener('input', () => drawStudent(state.form));
$('stud-clear').addEventListener('click', () => {
  $('stud').value = '';
  drawStudent(state.form);
});

$('stud-card').addEventListener('change', (e) => {
  const stud = pickedStudent();

  // a score a student has entered.  it goes nowhere near the policy: the
  // file says what counts, and this says what they got
  const what = e.target.getAttribute('data-whatif');
  if (what !== null) {
    const text = e.target.value.trim();
    if (text === '') delete state.whatIf[what];
    else state.whatIf[what] = Number(text);
    refresh();
    return keepFocus(what);
  }

  // how late one of them was.  a separate answer from the score, because
  // when it was handed in is not something the score says
  const day = e.target.getAttribute('data-whatif-day');
  if (day !== null) {
    const text = e.target.value.trim();
    if (text === '' || Number(text) === 0) delete state.whatIfDay[day];
    else state.whatIfDay[day] = Math.max(0, Math.round(Number(text)));
    refresh();
    return keepFocus(day, 'data-whatif-day');
  }

  if (e.target.id === 'stud-note') {
    if (!stud) return;
    return applyEdit('set_note',
                     { email: stud.email, note: e.target.value });
  }

  // a student adding what they were told applies to them.  the same edit
  // an instructor would make, in the same section, because it is the same
  // file -- theirs is just the copy that was posted for the class
  const adjust = e.target.getAttribute('data-adjust');
  if (stud && adjust !== null) {
    const ass = e.target.value;
    if (!ass) return;
    return addAdjust(stud, adjust, ass);
  }

  const cat = e.target.getAttribute('data-excuse');
  if (stud && cat !== null) {
    applyEdit('set_excuse_offset',
              { cat, email: stud.email, days: Number(e.target.value) });
  }
});

/* One assignment into one of the two waive sections, keeping whatever is
 * already there.  set_waive replaces the list, so it is read first. */
function addAdjust(stud, field, ass) {
  const set = new Set(waiveList(state.form, field));
  set.add(ass);
  applyEdit('set_waive',
            { email: stud.email, ass_list: [...set], field });
}

/* Clicking a score box selects what is in it, so that typing replaces the
 * score rather than appending to it.  The gesture is "what if this were
 * something else", and the something else is almost never the old number
 * with a digit stuck on the front of it. */
$('stud-card').addEventListener('focusin', (e) => {
  if (e.target.matches
      && e.target.matches('[data-whatif], [data-whatif-day]')) {
    e.target.select();
  }
});

/* A redraw builds the card again from scratch, which throws away the element
 * the keyboard was about to move to -- so tab out of a score and focus lands
 * on the document, where the next tab starts again from the top of the page.
 * Filling in a term's worth of suppositions is the whole gesture here, so it
 * has to survive doing it twice.
 *
 * Only when focus fell to nothing: if something that still exists has taken
 * it, that was deliberate and taking it back would be worse. */
function keepFocus(name, attr = 'data-whatif') {
  if (document.activeElement && document.activeElement !== document.body) {
    return;
  }
  const box = $('stud-card').querySelector(
    `[${attr}="${CSS.escape(name)}"]`);
  if (box) box.focus();
}

/* Dragging a score onto another, on pointer events rather than html5 drag
 * and drop.  That api refuses to begin a drag for reasons the page cannot
 * see -- a child that isn't draggable, a browser that won't drag a form
 * control, a text selection starting instead -- and when it declines, no
 * event fires at all.  Pointer events always fire, so this either works or
 * leaves a trace of where it stopped.
 */
let drag = null;
let suppressClick = false;

function chipAt(x, y) {
  return chipAtSel(x, y, '#stud-card [data-score]');
}

function chipAtSel(x, y, sel) {
  const el = document.elementFromPoint(x, y);
  return el ? el.closest(sel) : null;
}

/* The label under the cursor says what the drop would do, not merely what is
 * being dragged: over nothing it is the assignment, over a target it is the
 * whole operation, so the result is readable before it is committed. */
function markDrag(over, from, x, y) {
  const ghost = $('drag-ghost');
  if (ghost) {
    // kept inside the window: a label hanging off the right edge gives the
    // page a horizontal scrollbar, which narrows the table underneath it
    // and moves the very column the drop is aimed at
    const wide = ghost.offsetWidth || 0;
    ghost.style.left = `${Math.max(
      2, Math.min(x + 14, window.innerWidth - wide - 8))}px`;
    ghost.style.top = `${y + 14}px`;
  }

  document.querySelectorAll('.drop-target').forEach(
    (el) => el.classList.remove('drop-target'));

  // a score belongs to the student on screen, an assignment to the class
  const score = over && over.getAttribute('data-score');
  const to = score || (over && over.getAttribute('data-ass'));

  if (to && to !== from) {
    over.classList.add('drop-target');
    if (ghost) ghost.textContent = maxLabel(to, from, Boolean(score));
    if (ghost) ghost.classList.add('is-over');
  } else if (ghost) {
    ghost.textContent = from;
    ghost.classList.remove('is-over');
  }
}

/* A drop onto a target that already takes a maximum adds to that operation
 * rather than replacing it, so the label has to name everything already in
 * it -- otherwise dragging hw0 onto hw2 = max(hw2, hw3) promises something
 * narrower than what it does. */
function maxLabel(to, from, perStudent) {
  const cur = perStudent ? studMaxOf(to) : (maxOf(to) || []);
  return `${to} = max(${[...new Set([to, ...cur, from])].join(', ')})`;
}

function studMaxOf(ass) {
  const stud = pickedStudent();
  if (!stud) return [];

  const cur = ((state.form || {}).max_list || [])
    .find((s) => s.email === stud.email);
  return ((cur || {}).target_dict || {})[ass] || [];
}

function clearDragMarks() {
  document.querySelectorAll('.dragging, .drop-target').forEach(
    (el) => el.classList.remove('dragging', 'drop-target'));
  const ghost = $('drag-ghost');
  if (ghost) ghost.remove();
}

$('stud-card').addEventListener('pointerdown', (e) => {
  if (e.button !== 0) return;
  const chip = e.target.closest('[data-score]');
  if (!chip) return;

  // The middle of a student's chip is the box its score is typed into, which
  // is also where anybody dragging it will take hold.  So a press there is
  // both things at once, and which one it was is not known until the pointer
  // either moves or doesn't: the box keeps the press, and the drag stays a
  // candidate until the slop is passed.
  const inBox = !!e.target.closest('input');

  drag = { from: chip.getAttribute('data-score'), chip,
           x: e.clientX, y: e.clientY, moved: false, inBox };

  // capture, so a pointer that outruns the chip still reports back to it.
  // it is an optimisation, not a requirement -- the drop is worked out from
  // the coordinates -- so a browser that refuses must not stop the drag.
  // not taken over a box, where it would cost the caret the press was for
  if (inBox) return;
  try {
    chip.setPointerCapture(e.pointerId);
  } catch (err) { /* carry on without it */ }
});

$('stud-card').addEventListener('pointermove', (e) => {
  if (!drag) return;

  if (!drag.moved) {
    // a few pixels of slop, so a click with a shaky hand stays a click
    if (Math.hypot(e.clientX - drag.x, e.clientY - drag.y) < 5) return;
    drag.moved = true;

    // it was a drag after all: hand the press back from the score box, or
    // the gesture drags a selection of digits around instead of a chip
    if (drag.inBox) {
      if (document.activeElement) document.activeElement.blur();
      const sel = window.getSelection();
      if (sel) sel.removeAllRanges();
    }

    drag.chip.classList.add('dragging');

    const ghost = document.createElement('div');
    ghost.id = 'drag-ghost';
    ghost.textContent = drag.from;
    document.body.appendChild(ghost);
  }

  markDrag(chipAt(e.clientX, e.clientY), drag.from, e.clientX, e.clientY);
});

$('stud-card').addEventListener('pointerup', (e) => {
  if (!drag) return;

  const from = drag.from;
  const moved = drag.moved;
  const over = moved ? chipAt(e.clientX, e.clientY) : null;
  drag = null;
  clearDragMarks();

  if (!moved) return;

  // a pointerup is followed by a click, and the chip's click waives; a drag
  // is not a waiver
  suppressClick = true;
  setTimeout(() => { suppressClick = false; }, 0);

  if (over && over.getAttribute('data-score') !== from) {
    dropSubstitute(from, over.getAttribute('data-score'));
  }
});

$('stud-card').addEventListener('pointercancel', () => {
  drag = null;
  clearDragMarks();
});

/* one click, one waiver: the chip is the control */
$('stud-card').addEventListener('keydown', (e) => {
  if (e.key !== 'Enter' && e.key !== ' ') return;
  // a student's chip holds a score box: those keys belong to whoever is
  // typing in it, not to the chip around it
  if (e.target.closest('input')) return;
  const chip = e.target.closest('[data-score]');
  if (!chip) return;
  e.preventDefault();
  chip.click();
});

$('stud-card').addEventListener('click', (e) => {
  if (suppressClick) return;
  const stud = pickedStudent();
  if (!stud) return;

  if (e.target.id === 'whatif-clear') {
    state.whatIf = {};
    state.whatIfDay = {};
    return refresh();
  }

  // an adjustment the reader is taking back out of their own copy
  const unadjust = e.target.getAttribute('data-unadjust');
  if (unadjust !== null) {
    const ass = e.target.getAttribute('data-ass');
    if (unadjust === 'excuse') {
      return applyEdit('set_excuse_offset',
                       { cat: ass, email: stud.email, days: 0 });
    }
    if (unadjust === 'max') {
      return applyEdit('set_max',
                       { email: stud.email, target: ass, ass_list: [] });
    }
    const set = new Set(waiveList(state.form, unadjust));
    set.delete(ass);
    return applyEdit('set_waive',
                     { email: stud.email, ass_list: [...set],
                       field: unadjust });
  }

  // a click that landed in a score box is somebody about to type, not
  // somebody waiving the assignment they are typing into
  if (e.target.closest('input')) return;

  const undo = e.target.getAttribute('data-unmax');
  if (undo !== null) {
    return applyEdit('set_max',
                     { email: stud.email, target: undo, ass_list: [] });
  }

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
  const undo = e.target.getAttribute('data-undo');
  if (undo !== null) undoAdjustment(undo);
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
  if (!part) return;
  download(part[0], part[1], part[2]);

  // the text that went out, not whatever the document says by the time this
  // is read: those are the same right now, and an edit mid-download would
  // make marking the live document a lie
  if (key === 'yaml') markSaved(part[0]);
});

$('messages').addEventListener('click', (e) => {
  if (e.target.id !== 'reseed') return;
  seedPolicy();
  refresh();
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
  if (file) takeCanvasFile(file);
});
canvasDrop.addEventListener('click', (e) => {
  if (e.target.id === 'canvas-browse') $('canvas-file').click();
});
$('canvas-file').addEventListener('change', (e) => {
  const file = e.target.files[0];
  if (file) takeCanvasFile(file);
  e.target.value = '';
});

/* the panes are in the page rather than rendered into it, so each of these
 * is wired once -- and a CRN typed into one survives every redraw */
$('export-mode').addEventListener('click', (e) => {
  const mode = e.target.dataset && e.target.dataset.mode;
  if (mode) setExportMode(mode);
});

$('dl-grades').addEventListener('click', () =>
  download(state.grades.csv, 'grade_full.csv', 'text/csv'));

$('dl-canvas').addEventListener('click', () => {
  const res = toJs(state.api.canvas_export(
    state.csv, state.yaml, state.canvasText, state.name, true));
  if (!res.ok) return ($('canvas-hint').textContent = res.error);
  download(res.csv, stamped('canvas_upload', 'csv'), 'text/csv');
});

$('banner-go').addEventListener('click', runBanner);
$('export-pane-banner').addEventListener('keydown', (e) => {
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

/* This tab is the only place the policy exists until it is downloaded, and a
 * closed tab takes it with it -- an afternoon of weights and waivers, gone to
 * a stray ctrl-w.  Only unsaved editing is worth stopping anybody over: a
 * saved document is not at risk, and a seed nobody has touched is not work.
 *
 * The browser picks the wording; nothing said here is shown. */
window.addEventListener('beforeunload', (e) => {
  if (!state.csv || !isDirty()) return;
  e.preventDefault();
  // older browsers want the property set, and one of the two always lands
  e.returnValue = '';
});

boot();
