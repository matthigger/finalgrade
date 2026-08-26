# issue 33 — student-facing web interface: handoff

Written 2026-08-26 for whoever picks this up on another machine. Everything
below is the state of the work, the decisions behind it, and the one thing
still blocked.

Issue: <https://github.com/matthigger/finalgrade/issues/33>

## Where the work lives

- Branch **`worktree-issue-33-student-web`**, pushed to origin, **3 commits
  ahead of `origin/main`**:
  - `602d2df` a student's own page, from their row and a policy with nobody else in it
  - `1cb495c` one policy posted once, and a student who adds their own adjustments
  - `c55edd2` policy_PRIVATE.yaml and policy_PUBLIC.yaml, and one interface for both
- Written in a git worktree at `.claude/worktrees/issue-33-student-web`. That
  path is inside Dropbox, so it syncs, but the worktree registration is local
  to the old machine — on a new machine just `git fetch && git checkout
  worktree-issue-33-student-web` in the normal checkout.
- **No PR has been opened.** There is no `gh` CLI and no token in that
  environment. Compare URL:
  <https://github.com/matthigger/finalgrade/compare/main...worktree-issue-33-student-web>
- Note: local `main` is **7 commits behind `origin/main`** (pre-existing, not
  caused by this work). Worth fixing before merging anything.

Read the three commit messages first — they carry the reasoning, not just the
what. Then `doc/student.md`, which is the user-facing version of all of it.

## What the feature is

An instructor produces two files. A student drops them on the same page and
sees their own grade, with the ability to try scores on work not yet graded.

| file | who | what |
|---|---|---|
| `policy_PRIVATE.yaml` | instructor only | their working policy. names students (waivers, accommodations, notes). **must not be handed out** |
| `policy_PUBLIC.yaml` | posted once, whole class | the same policy with every student-keyed section removed |
| `grades/<last>_<first>.csv` | emailed to one student | one row of the export |

The page needs **no mode switch**: a gradebook with `n_student == 1` is read as
somebody looking at their own grade, and the UI swaps. `document.body`
gets a `solo` class; `.instructor-only` / `.solo-only` in CSS do the hiding.

Produced by:
- browser **export** panel → `policy_PUBLIC.yaml` button, and
  `grades, one csv per student…` (a zip: the policy plus `grades/*.csv`)
- `finalgrade student scope.csv --policy policy_PRIVATE.yaml`

## The decisions that took the longest to reach

These were all arrived at through back-and-forth with Matt. Don't re-litigate
them without asking.

1. **The public policy is agnostic to every student.** Earlier versions
   embedded that one student's own waivers. Matt's workflow is *posted once on
   the course website*, so the file can only hold what is true of everybody.
   The line is arithmetic, not privacy: a file right for one student is wrong
   for the other ninety-nine.

2. **Consequence, stated honestly:** for a student the policy singles out, the
   posted file is **wrong** until their line is added. `test_student.py`
   asserts both directions — exact for the 97 of 100 the example policy
   adjusts for nothing, and demonstrably wrong for the ones it does.

3. **Students add their own adjustments, with the instructor's controls.**
   Not a bespoke widget: click a score chip to waive, drag one onto another to
   take the best of both, click a late chip to forgive, plus extra late days
   per category. Same gestures, same yaml sections, same `applyEdit` actions.
   An `adjustments for you` block lists what the estimate is assuming.

4. **What-if scores rewrite the csv, not the policy.** `student.add_scores`
   returns new csv text, and the page grades *that* with the unchanged
   pipeline. So a what-if is the real code on made-up numbers, with no second
   implementation to disagree. Rebuilt from the pristine csv every time, so
   clearing an answer is deleting a key rather than undoing an edit.

5. **A supposed score does not forgive lateness.** What a score would have
   been is a question about the score; quietly dropping the late penalty with
   it would flatter the estimate. (There is a test.)

6. **`exclude_complete_thresh` is resolved, not copied.** A completion rate
   over a class of one is 100% or 0%, so as written it would drop every
   assignment the student hasn't handed in. Instead the class is graded with
   and without the threshold and the difference is written into
   `assignments/exclude` by name. Needs the gradebook; refused without it.

7. **`note` and `email_list` never travel** — a note moves no grade and the
   wording is the instructor's; a roster is a list of addresses.

8. **`SHARE_TUP` / `DROP_TUP` in `finalgrade/student.py`** must together
   account for every key in `policy.YAML_KEY_DICT`, checked *at import*. A new
   policy section therefore fails loudly rather than shipping to a class by
   default. There is also a test tying it to `Policy.iter_email()`.

9. **The public file is rebuilt from a `Policy` object**, never edited down
   from the instructor's text — so a comment in their file cannot carry what a
   section could not. (Test: a `# alice gets an extra week` comment does not
   travel.)

## Files touched

**New**
- `finalgrade/student.py` — `policy_text`, `one_row_csv`, `add_scores`,
  `resolve_thresh`, and the SHARE/DROP table
- `test/test_student.py` — 39 tests
- `doc/student.md` — the instructor-facing guide
- `memory33.md` — this file

**Changed**
- `finalgrade/web.py` — `student_policy`, `student_pack`, `what_if`,
  `_stem_dict`, `_safe_stem`
- `finalgrade/policy.py` — `NAME_PRIVATE` / `NAME_PUBLIC` / `NAME_LEGACY`,
  `resolve_policy` now seeds `policy_PRIVATE.yaml` and still reads an existing
  `policy.yaml`
- `finalgrade/__main__.py` — the `student` subcommand
- `web/app.js`, `web/index.html`, `web/style.css` — solo mode, what-if boxes,
  adjustments block, PUBLIC/PRIVATE labels, agnostic intro
- `README.md`, `doc/policy.md`, `test/test_web.py`, `test/test_main.py`,
  `test/test_seed.py`

**597 tests pass** (530 before this work). New python is flake8-clean; the
repo has ~20 pre-existing flake8 complaints (star imports, two `E741`) which
are not mine.

## Blocked: the student-side export

Matt wants the student's csv to be **their own download from Gradescope or
Canvas**, not a row sliced out of the instructor's export. He couldn't produce
one himself and **asked TAs to send copies — he will update when they arrive.**

Today `student.one_row_csv` slices one row from the instructor export, so the
file is in *instructor export* format with a single data row. A real
student-side download is probably a different shape (likely one row per
assignment rather than one row with four columns per assignment), in which case
neither reader parses it and the `n_student == 1` detection never fires.

When a sample arrives: add a reader beside `read_scope` and
`canvas/read.py:read_canvas`, dispatch on shape in `Gradebook.from_file`, and
the rest of the student page needs no change — it is independent of where the
csv came from. Do **not** guess the columns; this package's posture is that a
plausible-looking wrong answer is worse than an error.

## Running it

Deps are not installed anywhere convenient. The repo's `.venv` is broken (no
pip). Make a fresh one:

```bash
python3 -m venv /tmp/fgvenv
/tmp/fgvenv/bin/pip install "ruamel.yaml>=0.18.10,<0.19.0" pandas numpy \
    openpyxl pytest hypothesis build flake8
```

Then:

```bash
/tmp/fgvenv/bin/python -m pytest -q              # 597 pass, ~8s
/tmp/fgvenv/bin/python web/build.py --out _site  # needs `build` installed
/tmp/fgvenv/bin/python -m http.server 8080 -d _site --bind 127.0.0.1
```

Opening `index.html` off disk does **not** work — `app.js` does a dynamic
`import()` and fetches `wheel.json`. First page load takes ~20-25s to fetch
Pyodide and pandas, then caches.

### Sample files to drive the UI

Generated into `tmp_student/` (gitignored by the `/tmp*` rule, but Dropbox
syncs it). Each folder holds `policy_PUBLIC.yaml` plus a couple of one-student
csvs:

- `tmp_student/gradescope/late_larry.csv` — **best one to test with**, late on
  everything, so the late row and forgive control have something to act on
- `tmp_student/gradescope/doesnt-do-hw_dan.csv` — hands nothing in, so every
  what-if box is empty; 52% E → 88% B+ when filled in
- `tmp_student/canvas/…` — the canvas path

Select **both** files (policy + csv) in the file dialog; the picker takes
several now. Regenerate them with the throwaway scripts in the old job's tmp
dir if needed — they are just `web.student_pack` unzipped.

Instructor side: open the page and click *try an example from gradescope*.

## Testing in a browser

Playwright MCP works well here. Two gotchas found the hard way:

- The `beforeunload` guard fires when the student has unsaved policy edits, so
  `browser_navigate` times out — answer it with `browser_handle_dialog`.
- Playwright can only read files under the repo root, so copy fixtures into
  `.playwright-mcp/` first.
- `.chip-k` / `.chip-v` have `pointer-events: none`, so target the chip
  itself (`[data-score='hw5']`), not its children.

## Repo conventions worth matching

- **Commit messages:** `type: lowercase sentence naming the behaviour change`,
  then a body explaining *why* in prose. Look at `git log` — the voice is
  distinctive and deliberate. Not bullet lists of files.
- **Comments explain the reasoning**, especially the near-miss that motivated
  the code. Match the density; it is high and intentional.
- **`filterwarnings = ["error"]`** in pytest — warnings are part of this
  package's interface. Also means class-scoped pytest fixtures defined as
  instance methods now hard-fail; use module-level fixtures.
- **The project refuses to guess.** A policy that cannot mean what was
  intended is an error naming the nearest real setting, never plausible
  numbers.
- Browser/CLI parity is the central claim: `test_web.py` asserts the page's
  answer equals the command line's.

## Open questions / things I'd look at next

1. **The student export** (above) — the real blocker.
2. **Keyboard waiving on the student page.** The score box is the only tab
   stop per chip, deliberately, so that typing a term's worth of scores is one
   Tab each. Waiving is therefore mouse-only there; a keyboard user has to
   edit the yaml. Stated in a comment, not solved.
3. **A score above max is accepted** (e.g. 109/10, which I hit by accident
   before adding focus-select). Not clamped on purpose — real gradebooks do
   have bonus points above max — but there is no sanity ceiling either.
4. **The pedagogy question in the issue itself** is unresolved and Matt has
   not asked for it to be. Issue 33 asks whether this helps students or hands
   them a tool for self-torture. `doc/student.md` ends with that question
   rather than answering it. The design's answer is that nothing happens
   unless the instructor posts the file.
5. `web/app.js` is ~2600 lines of flat functions over one mutable `state`.
   The invariant to preserve: **`state.yaml` is the single source of truth**,
   every edit round-trips through python, and the page redraws from the file.
   `state.whatIf` and `state.csvGraded` follow the same shape.
