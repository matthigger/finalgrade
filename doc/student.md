# Handing a student their own grade

The question a grade provokes is *how*, and the question a mid-term grade
provokes is *what would it take*. Both are arithmetic you have already
written down. This is how to hand a student the arithmetic instead of
answering it one email at a time.

Two files make a student's estimate:

- **`policy_PUBLIC.yaml`, posted once** — your policy with every student taken
  out of it. It is the same file for the whole class, so it goes on the
  course website and stays there.
- **their own grades csv** — one student's scores, which is the half that
  cannot be posted anywhere.

Your own working file is `policy_PRIVATE.yaml`: it names students, so it is
the one that must not be handed out. The names are the whole guard — you
cannot post the wrong one by accident when the wrong one says PRIVATE.

They drop both on
[matthigger.github.io/finalgrade](https://matthigger.github.io/finalgrade).
The page recognises a gradebook with one student in it as somebody looking at
their own grade, and swaps to showing it: every score, what was late and what
it cost, which scores were dropped, how the categories combined, and the log
of how the number was arrived at. Then they can type a score into work that
has not been graded yet and watch the grade move.

Nothing is uploaded anywhere. The page runs Python in the browser tab, on
their computer, the same as it does for you.

## Writing the files

In the browser, under **export**:

- **policy_PUBLIC.yaml** — the one file to post.
- **grades, one csv per student…** — a zip holding that same
  `policy_PUBLIC.yaml` and a `grades/` folder with one csv per student.

On the command line:

```bash
finalgrade student scope.csv --policy policy_PRIVATE.yaml
```

which writes `student/policy_PUBLIC.yaml` and
`student/grades/<last>_<first>.csv` beside the csv. `--email` writes one
student's csv, `-o` puts them somewhere else.

(`finalgrade grade` seeds and looks for `policy_PRIVATE.yaml` now. A
`policy.yaml` an earlier version wrote is still found and used, so a course
part way through a term has nothing to rename.)

Either way the class is graded first: a policy that would not grade your class
has nothing for a student's copy of it to agree with, so it is refused rather
than written.

## What the posted policy holds, and what it does not

The point of a subset rather than a second document is that a second document
can disagree. The file is rebuilt from your policy section by section, so
nothing travels that this package does not model — a comment cannot carry
what a section could not.

**Kept, because it is the same for everyone:** category weights, drop lowest,
keep highest, the late penalty rate, excused days and grace period, excluded
assignments, substitutions, extra credit, planned assignments, letter cutoffs.

**Left out, because it is keyed by a student:** `waive`, `waive_late`, `max`,
and `excuse_day_offset`. Also `note` (your own words about why a grade was
adjusted; it moves no grade, so an estimate has no use for it) and
`email_list` (a roster is a list of the class's email addresses).

The line is not privacy so much as arithmetic: one file is posted once, for
everybody, so it can only hold what is true of everybody. A file that is
right for one student is wrong for the other ninety nine.

**`exclude_complete_thresh` is resolved rather than copied.** A completion
rate over a class of one is 100% or 0%, so the threshold as written would drop
every assignment that student has yet to hand in — the opposite of what it is
for. Instead your class is graded with the threshold and without it, and the
assignments it actually removed are written into `assignments/exclude` by
name. The student's file therefore excludes what your run excluded, for the
reason your run excluded it.

## The students you singled out

For everybody the policy singles out for nothing — which is nearly all of
them — the estimate is exactly their grade. Not "approximately", and not
"recomputed by a second implementation": the page grades their row with the
posted policy using the same code that graded your class. The test suite
asserts it over the hundred students of the example gradebook.

For the handful you did single out, the posted file is **wrong for them until
they say so**, and the tests pin that down too, so that nobody has to
discover it. They were emailed about the waiver or the extra late days, so
they know; the page gives them somewhere to put it.

Their page has the same controls yours does, doing the same things:

- **click a score** to waive that assignment, and again to count it
- **drag one score onto another** to take the best of both
- **click a late chip** to forgive the penalty on it
- **extra late days** per category

Each writes the same yaml section your own copy would, keyed to the email in
their csv, so a policy annotated this way is one the command line reads too.
They can save it from the `policy.yaml` link and drop it back in next time.

An **adjustments for you** block lists everything the estimate is assuming
about them in particular. It is worth showing even when it is empty — an
empty list is the fact that nothing special is being assumed, and a student
who expected an entry in it has just learned something worth an email.

If they would rather edit the file by hand, the header of the posted policy
shows the sections and how to write them.

## What else they can change

They can type a score into any assignment — the value on each chip is a box.
That is a supposition, marked as one, and applied by rewriting their csv
rather than their policy, so there is no second way for the arithmetic to come
out. Clearing it puts the real score back, because the page rebuilds from the
file as it arrived every time rather than editing it.

Clicking a box selects what is in it, so typing replaces the score rather than
appending to it; and a drag that starts inside a box is still a drag, because
the middle of a chip is where anybody dragging it takes hold.

A supposed score does not forgive lateness: what a score would have been is a
question about the score, and quietly taking the late penalty off with it
would flatter the estimate.

Planned assignments (`assignments/planned`) are the row that matters here.
Write the whole term's policy in one sitting and a student in week six can ask
what the final is worth to them, because you have already said.

## Should you?

The issue that asked for this ([#33](https://github.com/matthigger/finalgrade/issues/33))
also asked whether it is a good idea — whether this helps students or hands
them a tool for torturing themselves, and whether it teaches them to expect a
precision that grading does not really have.

It is worth noticing that nothing here happens unless you post the file. The
page has no student mode to stumble into: it reads one student's row as one
student's grade. So this is a thing you can do for a course where it helps,
and not do for one where it doesn't, which is roughly where a judgement call
of this kind belongs.

The page says, next to the number, that an estimate is not a grade.
