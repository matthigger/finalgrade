# finalgrade

Compute final grades from a Gradescope or Canvas CSV export — with category weighting, lowest-N drops, late penalties, per-student waivers, and more.

Your grading policy lives in one small file, is applied identically to every student, and is refused outright if it can't mean what you intended.

    pip install finalgrade

**No Python? Use it in your browser instead:** [matthigger.github.io/finalgrade](https://matthigger.github.io/finalgrade) runs this same package inside the page — nothing to install, and your grades are never uploaded anywhere. See [In the browser](#in-the-browser) below.

## Quick Start

1. Download grades from Gradescope (`Assignments > Download Grades > CSV`) to a file like `scope.csv`.

2. Run:

        finalgrade grade scope.csv

   This produces [grade_full.csv](doc/grade_full.csv) and creates a `policy.yaml` in the same directory. That policy is written for *your* csv: it lists your assignments by the names a policy has to use, and suggests a category split (commented out) based on them.

3. Edit `policy.yaml` to set up your grading policy (see below), then check what it will do:

        finalgrade check scope.csv

4. When the split looks right, re-run:

        finalgrade grade scope.csv --policy policy.yaml

That's it. The rest of this README covers what you can put in that policy file and the additional flags available.

### Checking a policy

Categories match assignments by substring, which is easy to get subtly wrong — and a mistake shows up as a plausible-looking grade rather than an error. `check` answers "what does this policy actually do?" without computing any grades:

    $ finalgrade check scope.csv
    grade source : scope.csv (gradescope)
    students     : 5
    assignments  : 4 graded, 0 excluded

    assignment  points  submitted  category
    ----------  ------  ---------  ------------------------------------
    hw1         1       1/5        hw
    hw2         2       2/5        hw
    hw3         3       5/5        hw
    quiz1       4       5/5        (none) <- not graded in any category

    category  weight  drop  late                assignments
    --------  ------  ----  ------------------  -------------------------------
    hw        50.0%   1     15%/day, 3 excused  hw1, hw2, hw3
    exam      50.0%   -     -                   (none) <- matches no assignment

    error: category matches no assignment: exam
    warn : assignment not in any category: quiz1

    policy has an error, grading would stop here

It exits non-zero when grading would fail, so it works in a script. Unlike grading, it reports every problem it finds at once rather than stopping at the first.

### Grading from Canvas instead

`grade` also accepts a Canvas gradebook export (`Grades > Export`), told apart from a Gradescope one by its columns:

    finalgrade grade canvas.csv --policy policy.yaml

Everything downstream is the same. Three differences are worth knowing, all of them forced by what Canvas puts in its csv:

- **Late penalties aren't available.** Canvas' export has no submission times, so a `late_penalty` in your policy is an error rather than a penalty that quietly computes to zero for everyone. (Canvas does know lateness, but only through its API.)
- **Students may be keyed by SIS ID rather than email.** Canvas has no email column; its `SIS Login ID` holds one in some courses and an ID in others. Whichever is used is logged on every run, and it's the key that `waive`, `waive_late`, `excuse_day_offset` and `email_list` must then use.
- **Excused (`EX`) becomes a waiver**, and a blank cell counts as 0 — the same meaning a blank Gradescope cell has.

Assignments worth 0 points are dropped, as always. That covers most of what this tool uploads back to Canvas (`mean_hw`, `letter`, ...) along with solution handouts, so re-importing a course you've already exported to is a no-op rather than a feedback loop.

One thing works *better* from Canvas: a policy created for a Canvas export seeds its suggested categories from your Canvas assignment groups (read off the rollup columns Canvas exports), rather than guessing from assignment names.

## Grading policy

All grading policy lives in `policy.yaml`. A default copy is created on your first run — open it up and fill in the sections that apply to your course. Tabs aren't allowed in YAML, so use spaces (2 or 4 per indent level, consistently).

### Category weights

```yaml
category:
  weight:
    hw: 50
    exam: 50
```

A category is a subset of assignments. The example above gives homework 50% and exams 50% of the final grade. Weights need not sum to 100 — they're normalized automatically — but at least one must be positive, and each category must match at least one assignment.

**How assignments map to categories:** each Gradescope assignment name is matched to categories by substring (case/space-insensitive). An assignment named "HW 3" lands in the `hw` category, "Exam - Midterm" lands in `exam`. Every assignment should match exactly one category. By default no categories are created and every assignment is weighted by its Gradescope point value.

### Drop lowest

```yaml
category:
  drop_low:
    hw: 2
```

Drops each student's 2 lowest homework scores. Any category listed here must also appear in `category/weight`. By default nothing is dropped.

### Late penalty

```yaml
category:
  late_penalty:
    hw:
      penalty_per_day: 0.15
      excuse_day: 3
      grace_period_minutes: 60
      excuse_day_offset:
        student0@uni.edu: -3
        student1@uni.edu: 4
```

- **`penalty_per_day: 0.15`** — every unexcused [late day](https://help.gradescope.com/article/ude437e7li-faq-late-submissions) costs 15% of an average HW's point value. For example, if one HW is 3 unexcused days late, the student loses 45% of the average HW points. The penalty is spread across the category mean (it won't appear on any single HW score, but shows up in the `mean_hw` column of the output).
  - **`grace_period_minutes: 60`** (optional, default 60) — minutes of grace before lateness starts counting. A submission 59 minutes late uses 0 late days; one at 24 hours 5 minutes uses 1 late day (not 2). Set to `0` to disable the grace period.
- **`excuse_day: 3`** — every student gets 3 free late days across all HWs before penalties kick in. (Helps avoid emails over deadline minutiae.)
- **`excuse_day_offset`** — adjust the excuse-day count per student, useful for DRC accommodations. Values are additive: in the example above `student0` has 0 excuse days (3 + (−3)) and `student1` has 7 (3 + 4).

By default no late penalty is applied.

### Exclude assignments

```yaml
assignments:
  exclude:
    - practice_quiz
    - quiz1_v2
```

Excludes any assignment whose name contains the given string (case/space-insensitive). By default nothing is excluded.

### Completion threshold

```yaml
assignments:
  exclude_complete_thresh: 0.6
```

Auto-excludes any assignment where fewer than 60% of students received a non-zero score (no submissions count as zero). Applied after other exclusions and substitutions. By default no threshold is applied.

### Work you haven't set yet

```yaml
assignments:
  planned:
    hw9: 10
    final_project: 100
```

Adds an assignment nobody has a score for, so that a whole term's policy can be written in one sitting. It can be weighted, categorised and dropped like any other, and counts for nobody — every student's score is empty, which every mean already skips — until the real column turns up in your export and takes its place. A completion threshold won't remove it either: 0% submitted is exactly what not-yet-assigned looks like.

### Substitute assignments

```yaml
assignments:
  substitute:
    quiz1:
      - quiz1_v2
      - quiz1_v3
  exclude:
    - quiz1_v2
    - quiz1_v3
```

Replaces each student's `quiz1` score with the maximum percentage among `quiz1`, `quiz1_v2`, and `quiz1_v3`. Useful when you have multiple Gradescope assignments for different versions of the same quiz — each needs its own rubric, but you want a single score for grading. Be sure to also exclude the alternates so they don't double-count. By default nothing is substituted.

Unlike `exclude` (which matches by substring), the names under `substitute` must match a whole assignment name — an unmatched name is reported as an error rather than silently ignored.

### Waive assignments

```yaml
waive:
  student0@uni.edu: hw1
  student1@uni.edu: hw1, hw2, hw3
```

Waives assignments for individual students. The final grade is computed as if the work was never assigned, and any associated late penalties are also waived. By default nothing is waived.

### Waive late penalties

```yaml
waive_late:
  student0@uni.edu: hw1
  student1@uni.edu: hw1, hw2, hw3
```

Waives late penalties on specific assignments for individual students (the score still counts). Applied before excused late days are consumed. By default nothing is waived.

### Grade thresholds

```yaml
grade_thresh:
  0.93: A
  0.90: A-
  0.87: B+
  0.83: B
  0.80: B-
  0.77: C+
  0.73: C
  0.70: C-
  0.67: D+
  0.63: D
  0.60: D-
  0: E
```

The lowest percentage (inclusive) to earn each letter grade. The values above are the defaults.

### Email list

```yaml
email_list:
  - name0@uni.edu
  - name1@uni.edu
```

If provided, any email not found in the Gradescope data triggers a warning, and any Gradescope student not in this list is silently dropped. Useful for filtering out students who have dropped the course.

By default every student in Gradescope is included.

### Email matching

Everywhere an email appears in the policy — `waive`, `waive_late`, `excuse_day_offset`, and `email_list` — matching is done by the **prefix** (everything before `@`). This means `student@husky.neu.edu` in the policy will correctly match `student@northeastern.edu` in Gradescope. All comparisons are case-insensitive.

## What gets checked

Grades are hard to eyeball, so a policy that can't mean what you intended is
reported as an error rather than quietly producing plausible-looking numbers:

- a `drop_low` or `late_penalty` category with no entry in `category/weight`
  (it would never be applied)
- a category that matches no assignment (usually a typo)
- category weights that are negative, or that are all zero
- `grade_thresh` outside 0–1 (writing `93: A` instead of `.93: A` used to give
  every student the lowest grade), or with no entry reaching 0
- a `substitute` naming an assignment that doesn't exist
- the same student email appearing on two rows of the Gradescope export
- a setting nothing reads, because it is misspelled or in the wrong place —
  `late_penalty123` is not a late penalty applied wrongly, it is one not
  applied at all. The error names the closest real setting
- a section given the wrong shape, such as `grade_thresh: 0.9` where a list of
  thresholds belongs. (`exclude` and `email_list` do accept a single line of
  comma-separated names, the same form `waive` takes)
- an email in `waive`, `waive_late` or `excuse_day_offset` that matches no
  student in the export — a typo there is an assignment silently *not* waived.
  The error names the closest matching students. An email that matches a
  student who is then dropped by `email_list` is fine, and says so quietly
- a csv that is neither a Gradescope nor a Canvas export

These are also handled quietly but visibly, with a warning:

- an assignment worth 0 points is excluded from grading (it can only produce
  meaningless percentages)
- an email in `email_list` that matches no student (an enrolled student who
  never submitted anything is ordinary)
- an assignment that falls into no weighted category, or into more than one

## Additional Options

All flags go on the `grade` subcommand. Run `finalgrade grade --help` for the full list.

```bash
# choose where the output CSV goes
finalgrade grade scope.csv --policy policy.yaml -o final_grades.csv

# generate a histogram of grades per category
finalgrade grade scope.csv --policy policy.yaml --plot

# export a CSV of late days per student-assignment pair
finalgrade grade scope.csv --policy policy.yaml --late_csv late_days.csv

# create per-student CSVs (handy for emailing individual breakdowns)
finalgrade grade scope.csv --policy policy.yaml --per_student

# suppress status messages
finalgrade grade scope.csv --policy policy.yaml -q

# force a fresh default policy (existing one is kept with a timestamp)
finalgrade grade scope.csv --new-policy
```

`--plot` accepts an optional filename (e.g. `--plot my_hist.html`); without one it defaults to `hist.html`.

### Histogram output

<img alt="histogram per category" src="doc/hist.png" width="800px"/>

## In the browser

[matthigger.github.io/finalgrade](https://matthigger.github.io/finalgrade) is the same tool with nothing to install: pick your csv, edit the policy, download `grade_full.csv`.

It is worth being precise about what that does and doesn't do:

- **Nothing is uploaded.** The page downloads a Python interpreter ([Pyodide](https://pyodide.org)) and a wheel of this package, then runs them in your browser. Your csv is read by JavaScript and handed to Python in the same tab. There is no server to send it to — you can disconnect from the network once the page has loaded and it still works.
- **It is the same code**, not a reimplementation. The browser and the command line call the same functions, so they cannot disagree about a grade; the test suite asserts that they don't.
- **First load fetches ~15 MB** (Python plus pandas), then caches it.
- **The policy is the same `policy.yaml`.** Download it and use it with the CLI, or drop a CLI-written one into the page.

Drop a file on the box at the top right — a gradebook csv, or a `policy.yaml` you saved earlier. Whatever you load is listed underneath as a download link, alongside the policy as it currently stands, so the policy you build is always one click from being saved. Everything recomputes on every change, so a policy edit and its effect are never more than a moment apart.

A problem that belongs to one assignment is shown against that assignment, on its row in the weights table, rather than in a list of complaints somewhere else. What's left over — a file that isn't a gradebook at all, a roster email matching nobody, a letter threshold out of range — has no row to sit on, so those stay in a message list at the top.

Every option documented above has a control:

- **Categories** — weight, drop-lowest, and late penalty (rate, excused days, grace period), above a table giving every assignment's points, its share of its category, its share of the whole grade, the mean among non-zero scores, and how many students submitted it.
- **Assignments** — exclusions picked from a list, substitutions (with a button offering the exclusion that a substitution almost always needs), and the completion threshold.
- **Students** — search by name to see every score they have, grouped by category. **Clicking a score waives it**, and clicking it again puts it back. A score that was never handed in reads *none*, a submitted zero reads *0%*, and one you haven't set yet reads *not set* — three things that are all zero points and mean entirely different things. Below that, every assignment appears again with its late days, where a click forgives the late penalty, before it is incurred as readily as after. Late days appear too: how many were used, how many were excused, how many ran over, and what the penalty cost — a category mean carries its penalty inside it, so 78% could be a 78% or an 86% with two days against it. Their whole breakdown downloads as its own csv, the same file `--per_student` writes, which is what you attach to the email asking why a grade is what it is.
- **Letter grades** — the cutoff table, editable, resettable to the defaults.
- **Roster** — paste a list to grade only those students.

**Waivers can't be typos.** The student is chosen from your csv, so the email is selected rather than typed — which is exactly the silent mistake described above, made impossible.

### Inspecting grades

The chart takes a dropdown — the final grade, any category, or any single assignment — and **hovering a bar names the students in it**. That is the question a distribution usually can't answer: not "what is the shape of the class" but "who is sitting just under the A− line?" Letter cutoffs are drawn on the overall view.

Every view toggles between **before** and **after** your policy, or both overlaid. "Before" means before drop-lowest and late penalties, so the gap between the two bars is precisely what your policy did. (Waivers and exclusions are in both — they decide what was assigned, which is a different kind of statement from an adjustment to a score.) A single assignment has no drops or penalties of its own, so there the toggle switches itself off and says why.

### Exporting

`grade_full.csv` downloads directly.

For **Canvas**, drop your Canvas gradebook export onto the box in the export section: Canvas matches students by its own SIS user id, which only that file carries, so the export merges the grades into it — scaled to 100 so Canvas doesn't round them. That is the same merge `finalgrade canvas` performs. (If the file you're grading is *itself* a Canvas export, it's already the template and the box says so.)

For **Banner**, give a term code and any CRNs and it builds the `.xlsx`, exactly as `finalgrade banner` does (the test suite checks the two produce the same ids and grades). Banner only matches a row when its CRN, term code and 9-digit student id all line up, which is why it asks for the two a gradebook can't know.

There is no Gradescope export: Gradescope is a place grades come *from*, and has no grade-import format to write.

### The policy file is still the policy file

Widgets don't hold state; they edit `policy.yaml`, and that file is what grading reads. The edit goes through a round-trip YAML writer, so it keeps comments, key order, blank lines, and any section the widgets don't cover. Download it and use it with the CLI, hand it to a TA, or drop it back in next term.

### Building the site

    python web/build.py            # writes _site/
    python -m http.server -d _site # then open localhost:8000

The build copies `web/*` and builds a wheel next to it. Pushing to `main` deploys it via `.github/workflows/pages.yml`. (Opening `index.html` off disk won't work — it loads a module over http.)

## Exporting Grades

The `grade` command produces a `grade_full.csv`. Two additional subcommands format it for upload to your LMS:

### Canvas

```bash
finalgrade canvas grade_full.csv canvas.csv --scale100
```

Download your Canvas gradebook as `canvas.csv` first. The `--scale100` flag scales grades to 0–100 to avoid Canvas's 2-decimal-place rounding ambiguity. See [doc/upload_canvas.md](doc/upload_canvas.md) for details.

### Banner (Northeastern)

```bash
finalgrade banner grade_full.csv 202310 -c 12345 -c 67890
```

Pass the term code and one or more CRNs. Produces a timestamped `.xlsx` ready for Banner import. See [doc/upload_banner.md](doc/upload_banner.md) for details.
