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
to it. Control points are one code path forever, and any smooth curve a
preset offers can be sampled into four or five points — nobody can
distinguish a 5-point piecewise-linear pull from a true square root in a
grade.

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
| `finalgrade/curve.py` (new) | point list, `apply`, validation, a one-line description of a curve for check and audit | ~60 |
| `policy.py` | `curve_dict` in `YAML_KEY_DICT`, the key tree, the dataclass, `_normalize`, `_validate_curve`, `average_kwargs` | ~45 |
| `gradebook.py` | `average(..., curve_dict)`, resolve names to columns once, apply per column | ~20 |
| `check.py` | the curve on `AssignmentRow`, and a line per curved assignment: the points, and the class mean before to after | ~35 |
| `audit.py` | one event per student per curved assignment that moved: "exam2 curved from 72% to 79%" | ~25 |
| `inspect.py` | the raw side of the pair for a curved assignment, and a flag so the UI can label it | ~10 |
| `edit.py` | `set_curve` (an empty mapping removes it) + `ACTION_DICT` | ~25 |
| `web.py` | `curve_list` in `form_state`; `bin_curve` and `curve_stat` for the preview (§5) | ~40 |
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

- a preset select — *none / add points / flat shift / pull toward 100%*
- one number for that preset's knob
- a readout: class mean and standard deviation, before to after, and how
  many students' letter grades moved
- a 60x60 static sparkline of the mapping, so the shape is visible. A
  polyline, ~15 lines, no interaction
- and, if wanted, a *target mean* box: bisect the preset's one knob against
  the score array the page already holds. ~20 lines, converges because each
  preset's knob moves the mean monotonically

The editor writes control points through `edit_policy('set_curve', …)` and
the page redraws from the yaml like every other widget. No SVG
interaction, no new state, nothing on screen that can disagree with the
document. The before/after histogram is the existing inspector, one view
away.

Tier 1 is the whole feature for almost every use.

### Tier 1.5 — the mean/std pair, if it is really wanted (~60 lines JS)

The sketch's editable mean *and* standard deviation belong to exactly one
preset: an affine rescale, `y = clamp(a·x + b)`. That family has two
degrees of freedom, so the two boxes are a bijection with it — they are its
editor, not the curve editor in general. Solving needs nested bisection
(bisect `b` for the mean inside a bisection on `a` for the std) because
clamping at 0 and 1 breaks the closed form, and it needs a message for the
unreachable ask ("you cannot widen the spread once a third of the class is
at 100%").

### Tier 2 — the draggable transfer-function graph (~500-700 lines JS)

This is the expensive, fiddly part, and it is where the sketch turns
unwieldy:

- pointer events, hit testing, drag with monotone clamping, add a point on
  click, remove on drag-off, keyboard equivalents for accessibility, touch.
  The most stateful code in the page by a wide margin
- a live after-histogram while dragging. It cannot be computed in
  javascript: applying a curve to scores *is* grading, and app.js's whole
  premise is that no grading decision lives there. Fixable cheaply —
  `bin_curve(value_json, name_json, point_json)` takes the score array the
  page already has and returns the binned result, so a drag costs one small
  pyodide call rather than a full re-read of the csv, debounced, with the
  real re-grade on release. Worth building either way
- **the dimensionality problem, which is the real cost.** A curve with N
  handles has N degrees of freedom. A mean box and a std box have two. Two
  editors of different dimensionality over one object cannot both be live:
  typing a mean has to rewrite the whole curve, which destroys the handles
  just dragged, and dragging a handle leaves the family the boxes describe.
  The only coherent resolutions are (a) the boxes drive a named family and
  grey out the moment a handle is touched, or (b) drop the boxes. Neither
  is what the sketch imagines, and discovering that in the middle of 600
  lines of drag code is the bad version of finding it out

## 6. The presets, concretely

Let `x` be the fraction earned. Each has one knob, and each is monotone in
its knob, which is what makes the target-mean bisection work.

- **add points**, knob `p`: points `{0: p, 1: 1}`, i.e. `y = x + p(1-x)`.
  Everyone gains, the gain tapering to nothing at the top, nothing exceeds
  100%. This is the curve people actually mean, and it is two numbers in
  the file
- **flat shift**, knob `p`: `{0: p, 1-p: 1, 1: 1}`, i.e. `y = min(x+p, 1)`.
  Everyone gains `p` except the top, which clamps
- **pull toward 100%**, knob `k` in [0, 1): `y = x^(1-k)` sampled at five
  points. The "logarithmic pull" of the sketch; `k = .5` is the square root
- **rescale** (tier 1.5 only), knobs mean and std: `y = clamp(a·x + b)`

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

Do not build the drag-handle graph, and do not put a mean box and a std box
on a free-form curve. The instinct that the sketch is unwieldy is right,
and the reason is specific: those two boxes and that graph are two editors
of different dimensionality over the same object. Because the file stores
control points, handles can be added in a later term without invalidating
a single saved policy — so there is no cost to leaving them out now, and
the fact that nobody has asked for them yet is worth learning first.
