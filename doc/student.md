# Handing a student their own grade

The question a grade provokes is *how*, and the question a mid-term grade
provokes is *what would it take*. Both are arithmetic you have already
written down. This is how to hand a student the arithmetic instead of
answering it one email at a time.

One file does it: **`policy_PUBLIC.yaml`, posted once** — your policy with
every student taken out of it and the term's work written into it. It is the
same file for the whole class, so it goes on the course website and stays
there.

Your own working file is `policy_PRIVATE.yaml`: it names students, so it is
the one that must not be handed out. The names are the whole guard — you
cannot post the wrong one by accident when the wrong one says PRIVATE.

A student drops the posted file on
[matthigger.github.io/finalgrade](https://matthigger.github.io/finalgrade)
and **types their own scores in**. (The page's *see it as a student* link
loads an example of one, if you want to look at what they will see before
posting anything.) Neither gradescope nor canvas gives a
student an export of their own grades worth reading, so the scores come from
the student, and the posted policy is what says which scores there are to
type. The page then shows what they come to: what was late and what it cost,
which scores were dropped, how the categories combined, and the log of how
the number was arrived at.

Nothing is uploaded anywhere. The page runs Python in the browser tab, on
their computer, the same as it does for you.

## Writing the file

In the browser, under **export**, the **policy_PUBLIC.yaml** button.

On the command line:

```bash
finalgrade student scope.csv --policy policy_PRIVATE.yaml
```

which writes `student/policy_PUBLIC.yaml` beside the csv. `-o` puts it
somewhere else.

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
assignments, substitutions, extra credit, letter cutoffs, and the term's work.

**Left out, because it is keyed by a student:** `waive`, `waive_late`, `max`,
and `excuse_day_offset`. Also `note` (your own words about why a grade was
adjusted; it moves no grade, so an estimate has no use for it) and
`email_list` (a roster is a list of the class's email addresses).

The line is not privacy so much as arithmetic: one file is posted once, for
everybody, so it can only hold what is true of everybody. A file that is
right for one student is wrong for the other ninety nine.

**The term's work travels in `assignments/planned`.** Assignment names and
what each is out of are facts about the course, not about anybody in it, so
they go to the class — and without them a student has categories and no idea
what is in them. The section that already means *this exists, and counts for
nobody until a score arrives* is exactly the one a blank sheet wants, so the
roster needs no section of its own. An assignment you had already planned
keeps your max points; yours is the deliberate figure.

**`exclude_complete_thresh` is resolved rather than copied.** A completion
rate over a class of one is 100% or 0%, so the threshold as written would drop
every assignment that student has yet to hand in — the opposite of what it is
for. Instead your class is graded with the threshold and without it, and the
assignments it actually removed are written into `assignments/exclude` by
name. The student's file therefore excludes what your run excluded, for the
reason your run excluded it.

## Blank is not zero

The one thing a student can get wrong. An assignment with no score entered is
treated as never assigned — it weighs on nothing, exactly as a waived
assignment does. So a grade on a half-filled sheet is a grade over the work
that has been entered, which is what makes the sheet useful in week six.

It also means **leaving a missed assignment blank flatters the estimate**.
Work nobody handed in is a zero in your run; on the sheet it has to be typed
as one. The page says so where the scores are.

## The students you singled out

For everybody the policy singles out for nothing — which is nearly all of
them — a student who types in what they really got reaches exactly their
grade. Not "approximately", and not "recomputed by a second implementation":
the page grades their sheet with the posted policy using the same code that
graded your class. The test suite asserts it over the hundred students of the
example gradebook.

For the handful you did single out, the posted file is **wrong for them until
they say so**, and the tests pin that down too, so that nobody has to
discover it. They were emailed about the waiver or the extra late days, so
they know; the page gives them somewhere to put it.

Their page has the same controls yours does, doing the same things:

- **click a score** to waive that assignment, and again to count it
- **drag one score onto another** to take the best of both
- **days late**, a box per assignment they have entered a score for
- **forgive**, on one they were told was excused
- **extra late days** per category

Each writes the same yaml section your own copy would, so a policy annotated
this way is one the command line reads too.

## Keeping a term's worth of typing

Nothing is kept between visits, so the page offers a student two files and
they are not interchangeable:

- **`you.csv`** — their scores. It is a gradebook of one student, so dropping
  it back in alongside the policy is read as their own grade and their typing
  comes back with it. This is the one to save.
- **`your_grade_explained.csv`** — the breakdown behind the number: every
  category mean, what was late and what it cost, what was waived. It explains
  a grade rather than recording the scores behind one, so it cannot be read
  back in. Upload it by mistake and the page says which file was wanted.

Their adjustments live in the policy rather than the sheet, so a student who
added a waiver saves the `policy.yaml` too.

An **adjustments for you** block lists everything the estimate is assuming
about them in particular. It is worth showing even when it is empty — an
empty list is the fact that nothing special is being assumed, and a student
who expected an entry in it has just learned something worth an email.

If they would rather edit the file by hand, the header of the posted policy
shows the sections and how to write them.

## How the arithmetic stays the same arithmetic

What a student types becomes a csv, and that csv is graded by the code that
grades your course. There is no second implementation to disagree with the
first. The sheet is rebuilt from scratch on every keystroke rather than edited
in place, so clearing a box is deleting a key and not undoing an edit.

Days late are their own answer, never inferred from a score: when a score was
handed in is not something the score says, and dropping a penalty along with
it would flatter the estimate. A day entered here is a day late, so your
grace period and excused days then act on it exactly as they would on a real
submission — a category that forgives the first day still forgives it.

Clicking a box selects what is in it, so typing replaces the score rather than
appending to it; and a drag that starts inside a box is still a drag, because
the middle of a chip is where anybody dragging it takes hold.

Work you have not set yet belongs in `assignments/planned` alongside the rest.
Write the whole term's policy in one sitting and a student in week six can ask
what the final is worth to them, because you have already said.

## Should you?

The issue that asked for this ([#33](https://github.com/matthigger/finalgrade/issues/33))
also asked whether it is a good idea — whether this helps students or hands
them a tool for torturing themselves, and whether it teaches them to expect a
precision that grading does not really have.

It is worth noticing that nothing here happens unless you post the file. So
this is a thing you can do for a course where it helps, and not do for one
where it doesn't, which is roughly where a judgement call of this kind
belongs.

The page says, next to the number, that an estimate is not a grade — and that
it is only as good as what was typed.
