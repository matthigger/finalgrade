# Handing a student their own grade

The question a grade provokes is *how*, and the question a mid-term grade
provokes is *what would it take*. Both are arithmetic you have already
written down. This is how to hand a student the arithmetic instead of
answering it one email at a time.

Each student gets two files:

- **their own row** of the export — nobody else's grades
- **a `policy.yaml`** — your policy with everybody else taken out of it

They drop both on
[matthigger.github.io/finalgrade](https://matthigger.github.io/finalgrade),
the page recognises a gradebook with one student in it as somebody looking at
their own grade, and shows it: every score, what was late and what it cost,
which scores were dropped, how the categories combined, and the log of how the
number was arrived at. Then they can type a score into work that has not been
graded yet and watch the grade move.

Nothing is uploaded anywhere. The page runs Python in the browser tab, on
their computer, the same as it does for you.

## Writing the files

In the browser, under **export**: **files for students…** writes a zip with a
folder per student, each holding `policy.yaml` and `grades.csv`. On the
command line:

```bash
finalgrade student scope.csv --policy policy.yaml
```

which writes `student/<last>_<first>/{policy.yaml,grades.csv}` beside the csv,
one folder per student. `--email` writes one student's folder, `-o` puts them
somewhere else.

Either way the class is graded first: files that describe a policy which would
not grade your class have nothing to agree with, so they are refused rather
than written.

## What a student's policy holds, and what it does not

The point of a subset rather than a second document is that a second document
can disagree. The file is rebuilt from your policy section by section, so
nothing travels that this package does not model — a comment cannot carry
what a section could not.

**Kept, because it is the same for everyone:** category weights, drop lowest,
keep highest, the late penalty rate, excused days and grace period, excluded
assignments, substitutions, extra credit, planned assignments, letter
cutoffs.

**Kept, because it moves that one student's grade:** their own waivers, their
own forgiven late penalties, their own best-of arrangements, their own
adjustment to the excused-day count. An estimate without these would be
wrong, and they are already facts that student knows about themselves.

**Never handed over:**

| | why |
|---|---|
| anybody else's waivers, accommodations or adjustments | not their business |
| `note` | your own words about why a grade was adjusted. it moves no grade, so an estimate has no use for it |
| `email_list` | a roster is a list of the class's email addresses |
| `exclude_complete_thresh` | see below |

**`exclude_complete_thresh` is resolved rather than copied.** A completion
rate over a class of one is 100% or 0%, so the threshold as written would drop
every assignment that student has yet to hand in — the opposite of what it is
for. Instead your class is graded with the threshold and without it, and the
assignments it actually removed are written into `assignments/exclude` by
name. The student's file therefore excludes what your run excluded, for the
reason your run excluded it.

## The grade they see is the grade they have

Not "approximately", and not "recomputed by a second implementation" — the
page grades their row with their policy using the same code that graded your
class. The test suite asserts it: every one of the hundred students in the
example gradebook gets, from their own two files, the mean and the letter
your run gave them, with waivers, late-day accommodations, best-of
arrangements and dropped scores in play.

That is the whole reason to hand out a subset of your file rather than a
description of your policy. A student quoting a number back at you is
quoting your own arithmetic.

## What they can change, and what they cannot

A student's page has no controls that edit the policy. They can type a score
into an assignment — which is a supposition, marked as one, and applied by
rewriting their csv rather than their policy, so there is no second way for
the arithmetic to come out. Everything else reads.

A supposed score does not forgive lateness: what a score would have been is a
question about the score, and quietly taking the late penalty off with it
would flatter the estimate. Clearing a supposition puts the real score back,
because the page rebuilds from the file as it arrived every time rather than
editing it.

Planned assignments (`assignments/planned`) are the row that matters here.
Write the whole term's policy in one sitting and a student in week six can
ask what the final is worth to them, because you have already said.

## Should you?

The issue that asked for this ([#33](https://github.com/matthigger/finalgrade/issues/33))
also asked whether it is a good idea — whether this helps students or hands
them a tool for torturing themselves, and whether it teaches them to expect a
precision that grading does not really have.

It is worth noticing that nothing here happens unless you send the files. The
page has no student mode to stumble into: it reads one student's row as one
student's grade, and the only way a student gets one student's row is from
you. So this is a thing you can do for a course where it helps, and not do
for one where it doesn't, which is roughly where a judgement call of this
kind belongs.

The page says, next to the number, that an estimate is not a grade.
