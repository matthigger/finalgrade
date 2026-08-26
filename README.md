# finalgrade

Final grades from a Gradescope or Canvas csv export — category weights,
dropped lowests, best-n-of-m, late penalties, per-student waivers.

## → [matthigger.github.io/finalgrade](https://matthigger.github.io/finalgrade)

**Build your grading policy in the browser.** Drop in your gradebook, click
through the policy, watch every grade move as you change it, and download the
results. Nothing to install.

**Your grades never leave your computer.** The page downloads a Python
interpreter and runs this package inside the tab — there is no server to send
anything to. Once it has loaded you can disconnect from the network and it
keeps working.

The policy you build downloads as a `policy.yaml`. Keep it: drop it back in
next time to pick up where you left off, hand it to a TA, or run it from the
command line. Nothing is stored between visits, so that file is the thing to
save.

## What it does

- **Category weights** — homework 50%, exams 50%. Assignments match categories
  by substring, so `hw1`…`hw9` land in `hw` without listing them.
- **Drop lowest** — the *n* worst scores in a category, never the extra credit.
- **Keep highest** — only the *n* best count, however many were attempted: six
  puzzles where any two count, and a student short of two averaged over zeros.
  One rule or the other per category, never both.
- **Late penalties** — a rate per day, a bank of excused days per student, and
  a grace period so nobody emails you about 90 seconds. Per-student
  adjustments for DRC accommodations. Only the scores that count charge late
  days — work that isn't in the grade can't be late.
- **Waivers** — click a score to waive the assignment, click a late submission
  to forgive just the penalty. Computed as if the work was never assigned.
- **Extra credit** — points that count towards what a student earned but not
  towards what was available.
- **Makeups and retakes** — drag one score onto another to take the better of
  the two, for the makeup only one student sat, without inventing a
  course-wide rule for it.
- **Work you haven't set yet** — write a whole term's policy in one sitting;
  planned assignments count for nobody until the real column arrives.
- **Letter grades** — editable cutoffs, sensible defaults.
- **Per-student breakdowns** — a csv per student that ends with *how* the
  grade was reached: what was waived, which scores counted and which didn't,
  what was late and what that cost, how the categories combined. It's the
  attachment for the email asking why a grade is what it is.
- **Notes** — free text on a student, stored beside the waiver it explains, so
  the reason outlives the email thread.
- **A student's own copy** — post one `policy_PUBLIC.yaml` for the class, with
  every student taken out of it and the term's work written in. A student drops
  it on the same page and types their own scores; same code, same answer as
  your run, plus what a score on work you haven't graded yet would do to it.
  Work left blank counts for nobody, so the sheet is useful in week six. Your
  own file is `policy_PRIVATE.yaml`, because it names students. A student you
  singled out sets their own waiver, days late or extra late days with the
  same controls you use. See [doc/student.md](doc/student.md).
- **Inspect** — the distribution of any category or assignment, before and
  after your policy, where hovering a bar names the students in it. Not "what
  is the shape of the class" but "who is sitting just under the A− line?"
- **Exports** — `grade_full.csv`, a Canvas upload merged by SIS id, and a
  Banner `.xlsx`.

**It refuses to guess.** Grades are hard to eyeball, so a policy that can't
mean what you intended is an error rather than plausible-looking numbers: a
category matching no assignment, a misspelled setting nothing reads, a
threshold written `93` where `.93` was meant, a waiver on an email nobody has.
The error names the closest real setting or student.

## Command line

The same code, same policy file, same results.

    pip install finalgrade

```bash
finalgrade grade scope.csv                        # grades, seeds a policy
$EDITOR policy_PRIVATE.yaml                       # weights, score rules, late
finalgrade check scope.csv --policy policy_PRIVATE.yaml   # what will it do?
finalgrade grade scope.csv --policy policy_PRIVATE.yaml   # grade with it
```

The seeded `policy_PRIVATE.yaml` lists your assignments by the names a policy
has to use and suggests a category split, commented out. PRIVATE because it
names students — `finalgrade student` writes the public half of it, for the
class. An existing `policy.yaml` from an earlier version is still found and
used. Editing it is the middle
step — until you do, every assignment counts in proportion to its own points.

`check` answers "what will this do?" without computing any grades, reports
every problem at once, and exits non-zero when grading would fail — so it
works in a script. It wants the policy named outright and will not write one
for you: a report on a file finalgrade just seeded tells you only what
finalgrade guessed.

    $ finalgrade check scope.csv --policy policy.yaml
    grade source : scope.csv (gradescope)
    students     : 5
    assignments  : 4 graded, 0 excluded

    assignment  points  submitted  category
    ----------  ------  ---------  ------------------------------------
    hw1         1       1/5        hw
    hw2         2       2/5        hw
    hw3         3       5/5        hw
    quiz1       4       5/5        (none) <- not graded in any category

    category  weight  drop/keep  late                assignments
    --------  ------  ---------  ------------------  -------------------------------
    hw        50.0%   drop 1     15%/day, 3 excused  hw1, hw2, hw3
    exam      50.0%   -          -                   (none) <- matches no assignment

    error: category matches no assignment: exam (assignments are: hw1, hw2, hw3, quiz1)

    policy has an error, grading would stop here

Other flags: `-o` output path, `--late_csv` late days per student-assignment,
`--per_student` a csv each, `--new-policy` a fresh one, `-q` quiet. Run
`finalgrade grade --help` for the full list.

`student` writes the one file students need to work their own grade out on the
page — `policy_PUBLIC.yaml`, to post once for the class:

    finalgrade student scope.csv --policy policy_PRIVATE.yaml

beside the csv. See [doc/student.md](doc/student.md).

### Grading from Canvas

`grade` also takes a Canvas export (`Grades > Export`), told apart by its
columns. Two differences are forced by what Canvas puts in the file: there are
no submission times, so late penalties are refused rather than silently
computing to zero; and students may be keyed by SIS ID rather than email.
Excused (`EX`) becomes a waiver. In exchange, a policy seeded from a Canvas
export takes its suggested categories from your Canvas assignment groups
rather than guessing from names.

### Uploading grades

```bash
finalgrade canvas grade_full.csv canvas.csv --scale100
finalgrade banner grade_full.csv 202310 -c 12345 -c 67890
```

See [doc/upload_canvas.md][canvas] and [doc/upload_banner.md][banner].

## Policy reference

**[doc/policy.md][policy]** — every setting a `policy.yaml` can hold, and
everything that gets checked.

[canvas]: https://github.com/matthigger/finalgrade/blob/main/doc/upload_canvas.md
[banner]: https://github.com/matthigger/finalgrade/blob/main/doc/upload_banner.md
[policy]: https://github.com/matthigger/finalgrade/blob/main/doc/policy.md
