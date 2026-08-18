# Spec: curving an individual assignment

A design note, not a feature. It exists to price the thing before building
it, and it argues for a much smaller version than the one sketched.

## 0. First: which problem is this solving?

Two different complaints get called "curving", and only one of them needs
new code.

- *"The class did worse than I intended, so grades should move up."*
  Already supported, interactively: the letter thresholds are editable and
  the distribution is drawn with the cutoff lines on it. Moving `.93: A`
  down to `.90` is the same act as curving the total, is one number instead
  of a function, and every student's grade is still traceable to a score
  they can see.
- *"Exam 2 was broken — badly written, mis-scaled, half the class ran out
  of time — and it shouldn't count as if it were fine."*
  This is the case with no answer today. It is per-assignment, it is
  occasional, and the instructor already knows roughly what they want ("add
  8 points", "give back a third of what they lost").

Everything below is for the second case only. Curving a category mean or
the final grade is out of scope: it lands on top of `grade_thresh`, which
already does it.

## 1. What the policy file stores

One new top-level section, keyed by assignment (matched by substring like
every other name in the file), whose value is the mapping itself:

```yaml
curve:
  exam2:
    0: .08
    1: 1
```

Read as points on the graph of old score to new score: a student at 0 gets
8%, a student at 100% gets 100%, and everything between is linear. Numeric
keys are already how `grade_thresh` is written, so this reads like a
section the file already has.

Rules:

- fractions, both sides. x stays within 0-1; y above 1 is how "allow above
  100%" is written (§6), and y above 2 is refused as the typo it is (`0: 8`
  is `.08` misspelled, not an 800% score) — the same error `grade_thresh`
  and `penalty_per_day` already give
- implicit anchors at (0, 0) and (1, 1), so the two-point example above is
  the whole curve and a one-point curve is legal
- strictly increasing in x, non-decreasing in y. A curve that ranks two
  students differently than their scores do is an error, not a policy
- linear between the points, `np.interp`, which is the entire
  implementation. nan (a waived assignment) passes through untouched, so
  waivers need no special case
- a curve naming no assignment is an error, and two curve entries catching
  the same assignment is an error naming both (`hw` and `hw3` together)

### Why control points rather than named curves

The alternative is `exam2: {kind: sqrt, k: .4}` — more readable in the
file, and it round-trips into a slider position perfectly. It was rejected:
every named family is another python code path, another validator and
another check message, and the list of families instructors want has no end
to it. Control points are one code path forever, and both curves in §6 are
straight lines, so nothing has to be sampled.

Sampling is worth ruling out explicitly, because it looks like it would
work. A faithful square root is expensive to approximate: five points miss
the true curve by 11 grade points at worst, and even sixteen points
weighted toward the bend still miss by 1.6. Getting under half a point
needs upward of thirty pairs, which turns the section into a wall of
numbers nobody can read or hand-edit. That is an argument against offering
a power curve at all rather than an argument for sampling one. What
instructors ask for turns out to be two straight lines (§6), which is two
pairs each.

The important consequence: because storage is the general thing, the
expensive UI (§5, tier 2) stays optional *forever*. A policy written by the
cheap UI is exactly the policy the drag-handle editor would produce, so
adding handles later invalidates nothing.

The UI should write a comment above the entry saying which option produced
it (`# percentage: 32.6% of the points lost, given back`). Comments survive
the round-trip loader (that is what `edit.py` is for), so the file stays
legible without the policy carrying a second representation of the curve.

## 2. Where in the pipeline it applies

**As an argument to `Gradebook.average`, next to `cat_drop_dict` and
`cat_late_dict`** — not as a mutation of `df_perc` in `Policy.prepare`.

That single choice buys most of the feature:

- `Policy.average_kwargs(curve_dict={})` is already the override mechanism,
  and `web._grade_twice` already averages the prepared gradebook twice to
  get the "before policy" series. Add `curve_dict=dict()` to the raw call
  and the before/after comparison works at every level of the inspector,
  including the total, with no new code and no new state
- the inspector's mode toggle currently greys out on a single assignment,
  because "an assignment has no drops or penalties of its own". A curve is
  exactly such a policy, so that toggle lights up for a curved assignment.
  The before/after histogram the sketch asks for is therefore already
  built; it needs the pair filled in (`inspect.build_view`, six lines)
- applied to `perc_cat` inside the category loop, it lands before
  `get_mean_drop_low`, so drop-lowest drops the lowest score *as it
  counts*. That is the right order and it comes for free
- the late penalty stays after it, on the category mean, so a curve cannot
  quietly refund a late penalty
- `Gradebook`'s "exactly one source of truth" docstring holds. `df_perc`
  stays the score the student earned; no parallel pre-curve frame exists to
  drift

Two consequences to accept, both already true of the two policies it sits
beside:

- the per-assignment columns of `grade_full.csv` show the score earned, not
  the curved score, so a category mean cannot be reconstructed from them by
  hand. `drop_low` and `late_penalty` already have this property
- `substitute` and `max` compare raw scores (they run in `prepare`, before
  any curve). Worth one line in the docs; "best of two" across two
  differently-curved assignments is not a thing anyone has asked for

The rejected alternative — curving inside `prepare`, the way `substitute`
and `take_max` rewrite `df_perc` and log what they did — needs a stashed
pre-curve frame for the inspector, and makes the curve invisible to the
before/after comparison that already exists.

## 3. What each module gains

| file | what | lines |
|------|------|-------|
| `finalgrade/curve.py` (new) | point list, `apply`, validation, a one-line description of a curve for check and audit, the two curves of §6 and the mean conversion | ~100 |
| `policy.py` | `curve_dict` in `YAML_KEY_DICT`, the key tree, the dataclass, `_normalize`, `_validate_curve`, `average_kwargs` | ~45 |
| `gradebook.py` | `average(..., curve_dict)`, resolve names to columns once, apply per column | ~20 |
| `check.py` | the curve on `AssignmentRow`, and a line per curved assignment: the points, and the class mean before to after | ~35 |
| `audit.py` | one event per student per curved assignment that moved: "exam2 curved from 72% to 79%" | ~25 |
| `inspect.py` | the raw side of the pair for a curved assignment, and a flag so the UI can label it | ~10 |
| `edit.py` | `set_curve` (an empty mapping removes it) + `ACTION_DICT` | ~25 |
| `web.py` | `curve_list` in `form_state`; `curve_points` (an option, a parameter or a target mean, and the ceiling toggle in — control points and stats out); `bin_curve` for the preview (§5) | ~50 |
| `policy.yaml`, `doc/policy.md`, `README.md` | an example block, a reference section, a bullet | ~40 |
| `test/test_curve.py` | interp math, nan passthrough, each refusal, the drop-lowest interaction, the raw override, an `edit` round trip, one end-to-end | ~150 |

Around 350 lines of code and 150 of test — the same size as `max` or extra
credit. None of it is hard. This half is not the reason to hesitate.

## 4. What it has to say out loud

Non-negotiable in this package: a policy that silently did nothing, or
silently did something surprising, is the failure mode the whole design is
against.

`check` reports, per curved assignment: the control points, how many
students moved, the class mean before and after, and the largest single
move. It refuses a curve that names no assignment, that isn't monotone,
that is written `8` instead of `.08`, or that collides with another curve.
It warns on a curve that lowers any score, and on a curve that moved
nobody.

`audit` (and so the per-student csv, and the student card in the page)
gains one line per curved assignment whose score actually moved. Without
it, a student reading their breakdown sees a category mean that their
listed scores cannot produce.

## 5. The UI, in tiers, priced

### Tier 0 — no UI (~250 lines, python only)

The section is typed into the yaml textarea, which is a first-class way to
use the page. `check` explains it, the inspector already draws before and
after, the command line has the feature. This tier alone is defensible to
ship.

### Tier 1 — the curve editor in the weight table (~180 lines JS, ~60 CSS)

A `curve` cell on the assignment's row in the weight table: `—`, or the
shorthand (`+8 pts`). Clicking opens a small inline editor, the same shape
as the other row editors:

- a choice of two curves, *percentage* or *flat* (§6)
- **two number boxes that are the same setting seen twice**: the curve's
  own parameter, and the class mean it produces. Typing in either fills in
  the other, so an instructor who thinks "give back a third of what they
  lost" and one who thinks "this exam should have averaged 87" both get to
  say it the way they think it
- an *allow above 100%* toggle
- a readout: standard deviation before and after, how many students' letters
  moved, and how many end at exactly 100%
- a 60x60 static sparkline of the mapping, so the shape is visible. A
  polyline, ~15 lines, no interaction

The browser holds none of that arithmetic. Turning a target mean into a
parameter reads the class's scores, so it is a grading decision and it
lives in `curve.py` behind `web.curve_points` — the page sends an option, a
number and the toggle, and receives control points plus the stats. The
command line gets the same two curves for free, and there is no second
implementation to disagree with the first.

The editor then writes those points through `edit_policy('set_curve', …)`
and the page redraws from the yaml like every other widget. No SVG
interaction, no new state, nothing on screen that can disagree with the
document. The before/after histogram is the existing inspector, one view
away.

Tier 1 is the whole feature for almost every use.

### Why the standard deviation is a readout, not a box

Not a cost argument — an arithmetic one. Two boxes already say everything
there is to say: pick an option and a mean, and the spread is no longer
free, it is whatever that option implies. On the shipped example, landing
`Exam1` (mean 80.7%, sd 15.7%) on a mean of 87% gives sd 10.6 by
percentage, 14.4 by flat, and 15.7 by flat with the ceiling off. Nothing is
left to type.

A third box would therefore have to change the *shape* of the curve to
honour it, and most of what could be typed is unreachable anyway: a lift
into a range capped at 100% cannot widen a spread. A readout that says what
the spread became is the whole of what a std box could honestly offer.

### Tier 2 — handles on the graph

Both options in §6 are straight lines, so a graph would be dragging the
line's two ends: two degrees of freedom, the same two the boxes already
have, and a nicer way to feel the trade-off. ~120 lines, and additive
whenever it is wanted.

The many-handle version is the one to refuse. Pointer events, hit testing,
add on click, remove on drag-off, keyboard equivalents, touch — the most
stateful code in the page by a wide margin — and a curve with N handles has
N degrees of freedom against two boxes, so typing a mean rewrites the shape
just dragged. No grading question has yet needed a curve that bends more
than once.

Either way the live preview is the same, and worth building: the
after-histogram cannot be computed in javascript, because applying a curve
to scores *is* grading and app.js's whole premise is that no grading
decision lives there. `bin_curve(value_json, name_json, point_json)` takes
the score array the page already holds and returns the binned result, so a
drag costs one small pyodide call rather than a re-read of the csv —
debounced, with the real re-grade on release.

## 6. The two curves

Both are straight lines. **Percentage** gives back a share of the points
each student lost; **flat** gives every student the same points. That is
the entire vocabulary.

The numbers below are the shipped example, `web/ex_gradescope.csv`, whose
`Exam1` has 98 scores, a mean of 80.7%, a standard deviation of 15.7% and 9
students already at 100%. Both curves are set to land the class mean on
**87%**, so the columns are comparable: the same mean, bought two ways.

### Percentage (the default)

Hand back `p` of what each student missed: `y = x + p(1 - x)`. A student at
60% missed 40 points; at `p` = a third, they get 13 of them back.

```yaml
curve:
  exam1:
    0: .326
    1: 1
```

Nobody can pass 100%, because a student at 100% lost nothing to give back —
so the ceiling toggle does not arise. The parameter and the mean convert
with one line of algebra each way:

    mean_after = mean + p(1 - mean)      p = (target - mean) / (1 - mean)

### Flat

Give everybody the same `p`: `y = x + p`.

```yaml
curve:
  exam1:
    0: .075
    .925: 1
```

That is the capped form — the second point is where the line reaches 100%,
and it stays there. With *allow above 100%* on, the ceiling is gone and the
line simply continues:

```yaml
curve:
  exam1:
    0: .063
    1: 1.063
```

Uncapped, `p` *is* the change in the mean, so the two boxes are the same
number. Capped, the clamp eats part of it and the conversion needs a
bisection — about ten lines, and the only place in the feature that isn't
closed-form algebra.

### The same +6.3 to the mean, three ways

| | percentage | flat | flat, above 100% |
|---|---|---|---|
| parameter | 32.6% of points lost | +7.5 | +6.3 |
| a blank exam, 0 | **33** | 7.5 | 6.3 |
| 10th percentile, 61 | 74 | 69 | 68 |
| median, 82 | 88 | 89 | 88 |
| 90th percentile, 98 | 99 | **100** | **105** |
| standard deviation, from 15.7 | 10.6 | 14.4 | 15.7 |
| students at exactly 100% | 9 | **26** | 9 |
| students above 100% | 0 | 0 | **22** |

What a reader should take from it: percentage helps the bottom of the class
most and squeezes the spread; flat treats everyone alike but pins 17 more
students onto exactly 100%, erasing the order among the best work; allowing
above 100% removes that ceiling and leaves the spread untouched, at the
cost of scores that read oddly on a transcript.

Percentage is the default because "here is some of what you lost back" is
the thing most instructors mean, and because it cannot produce either
oddity by construction.

## 7. Decisions still open

- **scores already above 100%** (a gradescope score over max points). With
  the implicit (1, 1) anchor, `np.interp` would leave them at 1, which
  *lowers* them. Decided: continue the curve past 1 in parallel, three
  lines, which never lowers anybody. Under percentage that means a student
  above 100% is left where they are, which is right — they lost nothing to
  give back
- **extra credit**: a curve on an extra-credit column is just a column, so
  it works. Probably fine unremarked
- **"before policy" changes meaning.** It currently means before drops and
  late penalties; it would come to mean before curves too. That is the
  right definition, but `inspect.py`'s module docstring and the page's
  `MODE_HINT` text both state the old one and must be updated

## 8. Recommendation

Build tier 0 and tier 1: two curves, two linked boxes, a ceiling toggle, a
static sparkline, and the before/after histogram that already exists.
Roughly 250 lines of python, 150 of test and 200 of browser, all of it in
the shape the codebase already has.

Leave out the many-handle graph and the third box for the spread. Neither
is a cost dodge: the spread stops being free the moment the option and the
mean are chosen, and N handles against two boxes are two editors of
different sizes over one object, which cannot both be live.

Dragging the line's two ends stays available whenever it is wanted, ~120
lines, and because the file stores control points it invalidates no saved
policy. Whether the two curves are already enough is worth learning from a
term of use rather than guessing at.
