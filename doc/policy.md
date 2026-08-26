# The policy file

Every grading decision lives in one `policy.yaml`. The browser at
[matthigger.github.io/finalgrade](https://matthigger.github.io/finalgrade)
writes this file for you with a control for each setting below, and the
command line reads the same file — this page is the reference for what can
go in it.

A policy seeded for your csv already lists your assignments by the names a
policy has to use, so most of this is reading rather than typing.

## Writing it by hand

A default copy is created on your first run — open it up and fill in the sections that apply to your course. Tabs aren't allowed in YAML, so use spaces (2 or 4 per indent level, consistently).

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

An assignment nobody handed in reads as a 0 in a Gradescope or Canvas export, so it is a low score like any other and is the first thing dropped. Only a waived or Canvas-excused assignment is skipped instead of dropped: it was never assigned, so it is neither.

### Keep highest

```yaml
category:
  weight:
    puzzle: 20
  keep_high:
    puzzle: 2
```

Only each student's 2 highest puzzle scores count, however many they attempted. Written for a set of interchangeable assignments — six puzzles, pick any two — where students stop as soon as they have enough good ones, so `drop_low` can't express it: the number to drop would be different for every student.

**A student short of the number is averaged over zeros.** The count is what is required: one puzzle at 90% and nothing else is 45%, not 90%. Mostly this needs no thought, because an assignment nobody handed in already reads as a 0 in your export. It holds for the slots that don't, too — a waived, Canvas-excused or not-yet-graded assignment is counted as a zero where a student has nothing else to make the number up with.

`drop_low` and `keep_high` are mutually exclusive — a category takes one rule or the other, and a policy that sets both on one category is refused. Which of a student's scores count is one question with one answer.

Four things follow:

- **`waive` cannot lower the number required.** A student excused from one puzzle still needs their best 2, out of the five left. (Which is usually what you want: being let off one of six changes nothing when only two count.)
- **A late puzzle that isn't counted costs nothing**, which is the point of attempting freely — but a late day on one of the 2 that *are* counted is charged over those 2, so it costs more here than the same rate would in a category of six.
- **Mid-term grades are deflated**, the same way an ungraded assignment deflates any average — if only one puzzle has been released and 2 count, nobody can be above 50% yet.
- **Watch `exclude_complete_thresh`.** A puzzle a third of the class attempted is exactly what that threshold is built to throw out, and here it is the expected submission rate rather than a sign of a broken assignment. Keep the threshold below the rate you expect, or drop it and `exclude` by name instead.

If the category holds fewer assignments than the number to keep, all of them count and a warning says so. By default every score counts.

Writing `keep_high: 0` (or `drop_low: 0`) is allowed and grades as no rule at all — every score counts, nothing is dropped — but it is warned about, because a rule set to nothing reads like a decision and acts like an omission. The browser writes it the moment you pick a rule, before you have said how many, so that the choice sticks; it shows that 0 as **all** (for keep highest) or **none** (for drop lowest) rather than as a number. Pick "no rule" to take the setting back out of the file.

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

- **`penalty_per_day: 0.15`** — every unexcused [late day](https://help.gradescope.com/article/ude437e7li-faq-late-submissions) costs 15% of an average HW's point value. Write it as a fraction: `15` would be a hundredfold penalty, so anything outside 0–1 is refused rather than graded. For example, if one HW is 3 unexcused days late, the student loses 45% of the average HW points. The penalty is spread across the category mean (it won't appear on any single HW score, but shows up in the `mean_hw` column of the output).
  - **Only the scores that count are involved**, on both sides of that. An assignment a student was waived from, or that `drop_low` discarded, or that `keep_high` didn't count, charges no late days — and is not one of the HWs the penalty is an average over. Being late on work that isn't in your grade costs nothing, because there is nothing for it to cost. So with 4 HWs where the lowest is dropped, a late day costs 15% ÷ 3, and if the dropped HW was the late one it costs nothing at all.
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

### Extra credit

```yaml
assignments:
  extra_credit:
    - hw9
    - bonus
```

Marks assignments whose points count towards what a student earned but not towards what was available. A 10 point bonus in a 100 point homework category is scored out of 100, not 110: doing it raises the category mean, skipping it leaves the same grade as if it had never been offered, and a category can pass 100%.

Names are matched by substring, like `exclude`. Extra credit is never chosen by `drop_low` — dropping it would take away the credit rather than the damage.

Put extra credit in the category it should lift. An assignment that is alone in its own category has no mean to raise, so the points land nowhere; that case is reported as a warning rather than left to be discovered from the grades.

### Completion threshold

```yaml
assignments:
  exclude_complete_thresh: 0.6
```

Auto-excludes any assignment where fewer than 60% of students received a non-zero score (no submissions count as zero). Applied after other exclusions and substitutions. By default no threshold is applied.

### Max, for one student

```yaml
max:
  alice@uni.edu:
    exam2a: exam2b
  bob@uni.edu:
    quiz1: quiz1_makeup, quiz1_v3
```

Reads as `exam2a = max(exam2a, exam2b)`: Alice's exam2a becomes the better of the two, and can only go up. The same rule `assignments/substitute` applies to everyone, applied to one student — for the makeup one person sat, where a policy-wide rule would be inventing a policy to describe a single arrangement.

Emails are matched by prefix and refused if they name nobody, like every other student setting. In the browser, dragging one score onto another writes exactly this.

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

Waives assignments for individual students. The final grade is computed as if the work was never assigned: it charges no late days, and it is not counted among the assignments a late penalty is an average over, so a student waived from one of three HWs has each late day charged over the two that are left. By default nothing is waived.

### Waive late penalties

```yaml
waive_late:
  student0@uni.edu: hw1
  student1@uni.edu: hw1, hw2, hw3
```

Waives late penalties on specific assignments for individual students (the score still counts). Applied before excused late days are consumed. By default nothing is waived.

### Notes

```yaml
note:
  student0@uni.edu: extension agreed with the dean's office, 2026-03-04
  student1@uni.edu: missed exam2 for the away game, sat the makeup
```

Free text about one student. It changes no grade — it is the reason the other settings were changed, kept in the file that changed them, so that the answer to "why does this student have a waiver?" outlives the email thread that produced it.

Emails are matched and checked like every other student setting: a note on an address nobody has is a note filed under nobody, and is refused.

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

## The copy a class may have

Everything above is your file. A subset of it can be posted once for the
whole class, and a student who has that file and their own grades csv can
work their own grade out on the same page with the same code -- including
trying a score on work you have not graded yet.

What crosses over is every course-wide setting on this page. What does not is
every section keyed by a student -- `waive`, `waive_late`, `max`,
`excuse_day_offset` -- because one file posted once can only hold what is
true of everybody. Nor `note` (it moves no grade) or `email_list` (a roster).
`exclude_complete_thresh` is resolved into the exclusions it actually came
to, because a completion rate over a class of one is 100% or 0%.

A student you singled out adds their own line: on the page, where their own
waivers and late days are controls, or by hand -- the posted file's header
shows the three sections and how to write them.

See [student.md](student.md) for how to write those files and what is in
them.

## What gets checked

Grades are hard to eyeball, so a policy that can't mean what you intended is
reported as an error rather than quietly producing plausible-looking numbers:

- a `drop_low`, `keep_high` or `late_penalty` category with no entry in
  `category/weight` (it would never be applied)
- both `drop_low` and `keep_high` on one category, which are two answers to
  the one question of which of a student's scores count
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
- a `keep_high` larger than the number of assignments in its category, which
  leaves nothing to make the number up with, so every one of them counts
- a `drop_low` or `keep_high` of 0, which reads as a rule and grades as none
