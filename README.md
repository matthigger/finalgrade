# Gradescope Mean

Compute final grades from a Gradescope CSV export — with category weighting, lowest-N drops, late penalties, per-student waivers, and more.

    pip install gradescope-mean

## Quick Start

1. Download grades from Gradescope (`Assignments > Download Grades > CSV`) to a file like `scope.csv`.

2. Run:

        gradescope-mean grade scope.csv

   This produces [grade_full.csv](doc/grade_full.csv) and creates a `config.yaml` in the same directory.

3. Edit `config.yaml` to set up your grading policy (see below), then re-run:

        gradescope-mean grade scope.csv --config config.yaml

That's it. The rest of this README covers what you can put in that config file and the additional flags available.

## Configuration

All grading policy lives in `config.yaml`. A default copy is created on your first run — open it up and fill in the sections that apply to your course. Tabs aren't allowed in YAML, so use spaces (2 or 4 per indent level, consistently).

Anywhere a list of names is expected (`exclude`, `email_list`, `waive`), a single name may be written on its own, with or without the leading `-`, and several may be comma separated:

```yaml
assignments:
  exclude: practice_quiz            # same as a one item list
email_list: alice@uni.edu, bob@uni.edu
```

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

Everywhere an email appears in the config — `waive`, `waive_late`, `excuse_day_offset`, and `email_list` — matching is done by the **prefix** (everything before `@`). This means `student@husky.neu.edu` in the config will correctly match `student@northeastern.edu` in Gradescope. All comparisons are case-insensitive.

## What gets checked

Grades are hard to eyeball, so a config that can't mean what you intended is
reported as an error rather than quietly producing plausible-looking numbers:

- a key this tool doesn't recognize, such as `catagory` or `category/weights`.
  The nearest real key is suggested. An ignored key is a grading policy
  silently not applied, so a misspelling is never assumed harmless
- a section given something other than the shape it needs (`category: 50`)
- a `drop_low` or `late_penalty` category with no entry in `category/weight`
  (it would never be applied)
- a category that matches no assignment (usually a typo)
- category weights that are negative, or that are all zero
- `grade_thresh` outside 0–1 (writing `93: A` instead of `.93: A` used to give
  every student the lowest grade), or with no entry reaching 0
- `penalty_per_day` outside 0–1 — it is a fraction, so `15` rather than `.15`
  is a hundredfold penalty
- a `late_penalty` block with no `penalty_per_day`, or with a negative
  `excuse_day` / `grace_period_minutes`
- a `substitute` naming an assignment that doesn't exist
- the same student email appearing on two rows of the Gradescope export

These are also handled quietly but visibly, with a warning:

- an assignment worth 0 points is excluded from grading (it can only produce
  meaningless percentages)
- an email in `waive`, `waive_late`, `excuse_day_offset` or `email_list` that
  matches no student
- an assignment that falls into no weighted category, or into more than one

## Additional Options

All flags go on the `grade` subcommand. Run `gradescope-mean grade --help` for the full list.

```bash
# choose where the output CSV goes
gradescope-mean grade scope.csv --config config.yaml -o final_grades.csv

# generate a histogram of grades per category
gradescope-mean grade scope.csv --config config.yaml --plot

# export a CSV of late days per student-assignment pair
gradescope-mean grade scope.csv --config config.yaml --late_csv late_days.csv

# create per-student CSVs (handy for emailing individual breakdowns)
gradescope-mean grade scope.csv --config config.yaml --per_student

# suppress status messages
gradescope-mean grade scope.csv --config config.yaml -q

# force a fresh default config (existing one is kept with a timestamp)
gradescope-mean grade scope.csv --new-config
```

`--plot` accepts an optional filename (e.g. `--plot my_hist.html`); without one it defaults to `hist.html`.

### Histogram output

<img alt="histogram per category" src="doc/hist.png" width="800px"/>

## Exporting Grades

The `grade` command produces a `grade_full.csv`. Two additional subcommands format it for upload to your LMS:

### Canvas

```bash
gradescope-mean canvas grade_full.csv canvas.csv --scale100
```

Download your Canvas gradebook as `canvas.csv` first. The `--scale100` flag scales grades to 0–100 to avoid Canvas's 2-decimal-place rounding ambiguity. See [doc/upload_canvas.md](doc/upload_canvas.md) for details.

### Banner (Northeastern)

```bash
gradescope-mean banner grade_full.csv 202310 -c 12345 -c 67890
```

Pass the term code and one or more CRNs. Produces a timestamped `.xlsx` ready for Banner import. See [doc/upload_banner.md](doc/upload_banner.md) for details.
