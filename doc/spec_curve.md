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
  8 points", "square-root it").

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

- values are fractions, both sides, and outside 0-1 is an error naming the
  fix (`8` where `.08` was meant) — the same error `grade_thresh` and
  `penalty_per_day` already give
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
to it. Control points are one code path forever, and every preset in §6 is
piecewise-linear by construction, so nothing has to be sampled.

Sampling is worth ruling out explicitly, because it looks like it would
work. A faithful square root is expensive to approximate: five points miss
the true curve by 11 grade points at worst, and even sixteen points
weighted toward the bend still miss by 1.6. Getting under half a point
needs upward of thirty pairs, which turns the section into a wall of
numbers nobody can read or hand-edit. That is an argument against offering
a power curve at all rather than an argument for sampling one — the shape
instructors want from it is "concave, lifts the middle", and §6 gets that
from three pairs.

The important consequence: because storage is the general thing, the
expensive UI (§5, tier 2) stays optional *forever*. A policy written by the
cheap UI is exactly the policy the drag-handle editor would produce, so
adding handles later invalidates nothing.

The UI should write a comment above the entry saying which preset produced
it (`# +8 points, tapering to nothing at 100%`). Comments survive the
round-trip loader (that is what `edit.py` is for), so the file stays
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
| `finalgrade/curve.py` (new) | point list, `apply`, validation, a one-line description of a curve for check and audit, the three presets of §6 and the target-mean solve | ~100 |
| `policy.py` | `curve_dict` in `YAML_KEY_DICT`, the key tree, the dataclass, `_normalize`, `_validate_curve`, `average_kwargs` | ~45 |
| `gradebook.py` | `average(..., curve_dict)`, resolve names to columns once, apply per column | ~20 |
| `check.py` | the curve on `AssignmentRow`, and a line per curved assignment: the points, and the class mean before to after | ~35 |
| `audit.py` | one event per student per curved assignment that moved: "exam2 curved from 72% to 79%" | ~25 |
| `inspect.py` | the raw side of the pair for a curved assignment, and a flag so the UI can label it | ~10 |
| `edit.py` | `set_curve` (an empty mapping removes it) + `ACTION_DICT` | ~25 |
| `web.py` | `curve_list` in `form_state`; `curve_preset` (a preset name and a knob, or a target mean, in — control points and before/after stats out); `bin_curve` for the preview (§5) | ~50 |
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

### Tier 1 — presets in the weight table (~180 lines JS, ~60 CSS)

A `curve` cell on the assignment's row in the weight table: `—`, or the
shorthand (`+8 pts`). Clicking opens a small inline editor, the same shape
as the other row editors:

- a preset select — *none / flat shift / taper to 100% / peak at the
  median* (§6), which is where the kink sits
- one number for that preset's knob, capped where the curve would stop
  being monotone
- a readout: class mean and standard deviation before to after, how many
  students' letters moved, and how many end at exactly 100%
- a 60x60 static sparkline of the mapping, so the shape is visible. A
  polyline, ~15 lines, no interaction
- a *target mean* box, solved by bisection on the preset's one knob

The browser holds none of that arithmetic. Choosing a knob from a target
mean reads the class's scores, and the median-peak preset needs the class
median, so both are grading decisions and both live in `curve.py` behind
`web.curve_preset` — the page sends a preset name and a number and receives
control points. The command line gets the same presets for free, and there
is no second implementation to disagree with the first.

The editor then writes those points through `edit_policy('set_curve', …)`
and the page redraws from the yaml like every other widget. No SVG
interaction, no new state, nothing on screen that can disagree with the
document. The before/after histogram is the existing inspector, one view
away.

Tier 1 is the whole feature for almost every use.

### Why the standard deviation is a readout, not a box

Not a cost argument — an arithmetic one. A curve that only lifts scores,
into a range capped at 100%, must compress the spread as it raises the
mean. There is no shape that avoids it.

Measured on the shipped example (`Exam1`, mean 80.7%, sd 15.7%): asking for
a mean of 87% pins the resulting sd into roughly 12.4-15.3% no matter where
the kink goes. Typing 16% is unreachable, and so is 10%. So a std box would
spend most of its life refusing what was typed and explaining why — which
is a worse widget than a readout that simply says what the spread became.

If both are genuinely wanted later, they belong to one two-parameter
family, `y = clamp(a·x + b)`, whose two knobs *are* the two boxes; solving
needs nested bisection because the clamp breaks the closed form, and the
"closest reachable" message becomes the main feature rather than an edge
case. ~60 lines, and worth it only if the readout turns out to be the thing
people argue with.

### Tier 2 — handles on the graph

Two very different versions hide behind "make the curve draggable".

**One draggable kink** (~120 lines JS). The presets of §6 are one shape
with the pivot in three places, so exposing the pivot as a single handle is
the presets with the constraint removed. Two degrees of freedom, no add or
remove, no monotone bookkeeping beyond clamping the point inside the
triangle its neighbours make, and the sparkline becomes the editor. If any
graph gets built, it is this one — and note it can reach mean/sd pairs that
the presets cannot, which is the honest use for it.

**N handles** (~500-700 lines JS). Pointer events, hit testing, add on
click, remove on drag-off, keyboard equivalents for accessibility, touch;
the most stateful code in the page by a wide margin. And the dimensionality
problem: a curve with N handles has N degrees of freedom, a mean box and a
std box have two, and two editors of different dimensionality over one
object cannot both be live — typing a mean rewrites the whole curve and
destroys the handles just dragged, while dragging a handle leaves the
family the boxes describe. There is no known grading need for a shape with
more than one kink.

Both versions need the same live preview, which is worth building either
way: the after-histogram cannot be computed in javascript, because applying
a curve to scores *is* grading and app.js's whole premise is that no
grading decision lives there. `bin_curve(value_json, name_json,
point_json)` takes the score array the page already holds and returns the
binned result, so a drag costs one small pyodide call rather than a re-read
of the csv — debounced, with the real re-grade on release.

## 6. The presets, concretely

The three presets are **one shape with the kink in a different place**: a
line from the bottom of the range to a single interior point, and a line
from there to (1, 1). One implementation, three sensible defaults, and a
sparkline that makes the difference obvious without reading anything.

Each has one knob, and each moves the class mean monotonically in that
knob, which is what lets a target mean be solved by bisection.

The worked numbers below are the shipped example, `web/ex_gradescope.csv`,
whose `Exam1` has 98 scores, a mean of 80.7%, a standard deviation of
15.7%, a median of 81.6% and 9 students at exactly 100%. Every preset is
set to land the class mean on **87%**, so the columns are comparable: the
same mean, bought three different ways.

**Flat shift** — the kink is at the top. Everyone gains the same `p`, and
the top of the class runs into the ceiling.

```yaml
curve:
  exam1:
    0: .075
    .925: 1
```

`y = min(x + p, 1)`. Knob: points added to everybody, 7.5 here.

**Taper to 100%** — the kink is at the bottom, which is to say there is no
kink: one straight line from `(0, p)` to `(1, 1)`. The gain shrinks
steadily to nothing at the top.

```yaml
curve:
  exam1:
    0: .326
    1: 1
```

`y = x + p(1 - x)`. Knob: points added at zero — 32.6 here, which is why
the box needs the median gain (+6.0) printed beside it. Nobody reads "add
32 points" and means "the typical student gains 6".

**Peak at the median** — the kink sits on the class median, so the ends
are pinned and the middle is lifted.

```yaml
curve:
  exam1:
    0: 0
    .816: .916
    1: 1
```

Knob: points added to the median student, 10.0 here, capped at `1 - median`
(18.4 points) because the median cannot be lifted past 100%.

### What the same +6.3 to the mean costs, three ways

| | flat shift | taper to 100% | peak at median |
|---|---|---|---|
| a blank exam, 0 | **33** | 8 | **0** |
| 10th percentile, 61 | 69 | 74 | 69 |
| median, 82 | 89 | 88 | **92** |
| 90th percentile, 98 | **100** | 99 | 99 |
| already at 100 | 100 | 100 | 100 |
| standard deviation, from 15.7 | 14.4 | **10.6** | 14.4 |
| students at exactly 100% | **26** | 9 | 9 |

The three differ in exactly three things a reader can be shown: what a
blank exam earns, whether the top of the class ties up, and how much spread
survives. Flat shift moves 17 more students onto 100%, erasing the order
among the best work. Taper hands 33 points to someone who wrote nothing and
compresses the spread by a third. Peak-at-the-median does neither, and its
knob is the only one that reads as what an instructor means.

**So: peak at the median is the default preset.** The others exist because
sometimes the flat "+8 for everybody, I announced it in class" is the
policy, and sometimes the bottom of the class really is who the broken exam
hurt.

## 7. Decisions still open

- **cap at 100%?** Recommended yes: a control point above 1 is refused,
  matching every other fraction in the file. Costs one comparison to
  reverse if "everyone gets 5 points, the top student gets 105%" turns out
  to be wanted
- **scores already above 100%** (a gradescope score over max points). With
  the implicit (1, 1) anchor, `np.interp` leaves them at 1, which *lowers*
  them. Either extend the curve beyond 1 in parallel (`f(1) + (x-1)`) or
  refuse to curve an assignment where any score exceeds its max points.
  Parallel extension is three lines and never lowers anybody
- **extra credit**: a curve on an extra-credit column is just a column, so
  it works. Probably fine unremarked
- **"before policy" changes meaning.** It currently means before drops and
  late penalties; it would come to mean before curves too. That is the
  right definition, but `inspect.py`'s module docstring and the page's
  `MODE_HINT` text both state the old one and must be updated

## 8. Recommendation

Build tier 0 and tier 1. Show the curve as a static sparkline, let the
presets be the editor, make the target mean editable and the standard
deviation a readout. That is roughly 250 lines of python, 150 of test and
200 of browser, all of it in the shape the codebase already has.

Do not build the many-handle graph, and do not put a std box on a free-form
curve. The instinct that the sketch is unwieldy is right, and there are two
separate reasons. The std box is refused by arithmetic: a lift into a capped
range compresses the spread, so once the mean is set the spread is nearly
determined and the box would mostly reject what was typed. The many-handle
graph is refused by dimensionality: N handles and two boxes are two editors
of different sizes over one object, and they cannot both be live.

What is left open, cheaply, is the single draggable kink — the presets with
the pivot free, two degrees of freedom, ~120 lines. Because the file stores
control points, it can be added in a later term without invalidating a
single saved policy. There is no cost to leaving it out now, and whether
the three presets are already enough is worth learning from a term of use
rather than guessing at.
