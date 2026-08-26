#!/usr/bin/env python3
""" writes the example gradebooks the page's "try an example" loads

A demo gradebook is only worth anything if it exercises the awkward cases,
so this one is built around students who each break something: nobody who
submitted nothing, somebody who stopped halfway, a retake sitting in a second
column, a whole category never attempted.  They are named after what they do,
so the histogram and the student panel can be read without a key.

Two files, one class: ex_gradescope.csv and ex_canvas.csv hold the same
hundred students with the same scores, written the way each platform writes
them.  The pair is the point -- canvas' export carries no submission times,
so a late penalty has nothing to act on there, and having both on hand makes
that a thing you can see rather than a paragraph of documentation.

A third, ex_policy_public.yaml, is what an instructor of this class would post
for it: the same policy with the three students it singles out taken back out
again, and the term's work written in.  It is what the page's student example
loads, and it is built by the package so that it cannot drift from either the
gradebook or the code that writes the real ones.

    python web/make_example.py

Deterministic: the same files every time, so a rebuild is not a diff.
"""
import pathlib
import random

ROOT = pathlib.Path(__file__).resolve().parents[1]
F_SCOPE = ROOT / 'web' / 'ex_gradescope.csv'
F_CANVAS = ROOT / 'web' / 'ex_canvas.csv'
F_PUBLIC = ROOT / 'web' / 'ex_policy_public.yaml'

# a plausible policy over the class above, written the way an instructor's own
# file looks: it singles three of the hundred out, which is the whole reason
# the posted copy has to be built rather than handed over.  the emails are
# filled in from the cast below, so that dropping them is visible rather than
# asserted
YAML_INSTRUCTOR = """
category:
  weight:
    hw: 40
    quiz: 25
    exam: 35
  drop_low:
    hw: 1
  late_penalty:
    hw:
      penalty_per_day: .1
      excuse_day: 2
      grace_period_minutes: 60
      excuse_day_offset:
        {drc}: 5
assignments:
  substitute:
    exam2a:
      - exam2b
  exclude:
    - exam2b
waive:
  {waived}: hw3
waive_late:
  {forgiven}: hw1
note:
  {drc}: DRC accommodation, agreed in week two
grade_thresh:
  .93: A
  .90: A-
  .87: B+
  .83: B
  .80: B-
  .77: C+
  .73: C
  .70: C-
  .67: D+
  .63: D
  .60: D-
  0: E
"""

# canvas names an assignment group per assignment; these are the groups an
# instructor would have set up, and canvas writes a rollup column for each
GROUP_DICT = {'HW': 'Homework', 'Quiz': 'Quizzes', 'Exam': 'Exams'}

N_STUDENT = 100
SEED = 20260815

# gradescope writes four columns per assignment, in this order
SUFFIX_TUP = ('', ' - Max Points', ' - Submission Time', ' - Lateness (H:M:S)')

SUB_TIME = '2026-04-21 23:14:07 -0400'

# name -> max points.  exam2a and exam2b are two versions of one exam: most
# of the class sits a, a few sit the makeup, and a policy substitutes one for
# the other (and excludes b, or it would count twice)
ASSIGN_DICT = {
    **{f'HW{i}': 10 for i in range(1, 9)},
    **{f'Quiz{i}': 20 for i in range(1, 5)},
    'Exam1': 100,
    'Exam2a': 100,
    'Exam2b': 100,
}

HW_TUP = tuple(f'HW{i}' for i in range(1, 9))
QUIZ_TUP = tuple(f'Quiz{i}' for i in range(1, 5))

# hand-built students, each one a case worth seeing on the page.  scores are
# fractions of the assignment's points; None means nothing was submitted
CAST_TUP = (
    ('Dan', 'Doesnt-Do-Hw',
     'every homework missed, and otherwise perfectly capable',
     dict(hw=None, quiz=.88, exam=.91)),
    ('Nadia', 'No-Show',
     'enrolled and never submitted anything at all',
     dict(hw=None, quiz=None, exam=None)),
    ('Absent', 'Abernathy',
     'the second student with nothing: one is easy to call a glitch',
     dict(hw=None, quiz=None, exam=None)),
    ('Started-Late', 'Stevens',
     'joined in week three, so the first assignments are simply missing',
     dict(hw=.86, quiz=.83, exam=.8, skip_before=3)),
    ('Dropped-Out', 'Duncan',
     'stopped after the fourth homework, mid-term',
     dict(hw=.78, quiz=.74, exam=.7, stop_after=4)),
    ('Quit', 'Quigley',
     'stopped later, after the sixth',
     dict(hw=.83, quiz=.8, exam=.76, stop_after=6)),
    ('Late', 'Larry',
     'always submits, always a day or two past the deadline',
     dict(hw=.9, quiz=.85, exam=.87, late_days=2)),
    ('Tardy', 'Tran',
     'late just often enough to matter once excused days run out',
     dict(hw=.84, quiz=.8, exam=.82, late_days=1, late_n=3)),
    ('Perfect', 'Park',
     'full marks on everything, on time',
     dict(hw=1., quiz=1., exam=1., exact=True)),
    ('Median', 'Morales',
     'the middle of the class, for a sanity check',
     dict(hw=.82, quiz=.79, exam=.8)),
    ('Clutch', 'Chen',
     'a bad start and a strong finish, so drop-lowest flatters them',
     dict(hw=.55, quiz=.72, exam=.94, ramp=.45)),
    ('Quiz-Flunking', 'Quinn',
     'homework is fine, quizzes are not',
     dict(hw=.93, quiz=.41, exam=.7)),
    ('Exam-Ace', 'Ellis',
     'the reverse: exams carry them',
     dict(hw=.62, quiz=.7, exam=.98)),
    ('Borderline', 'Bailey',
     'sits within a point of a letter cutoff, wherever you put it',
     dict(hw=.9, quiz=.9, exam=.9, exact=True)),
    ('Retake', 'Reyes',
     'sat the makeup exam, so exam2a is blank and exam2b is not',
     dict(hw=.8, quiz=.77, exam=.75, retake=.84)),
    ('Makeup', 'Mbeki',
     'the same, with a better makeup score',
     dict(hw=.85, quiz=.82, exam=.79, retake=.92)),
    ('Waived', 'Walsh',
     'one homework missing for a reason a waiver would record',
     dict(hw=.88, quiz=.86, exam=.85, miss=('HW6',))),
    ('Zero', 'Zheng',
     'submitted a blank exam: a real zero, not an absence',
     dict(hw=.8, quiz=.78, exam=.81, flunk=('Exam1',))),
)

FIRST_TUP = (
    'Ava', 'Ben', 'Cora', 'Dev', 'Elena', 'Finn', 'Grace', 'Hugo', 'Iris',
    'Jonah', 'Kira', 'Liam', 'Maya', 'Noor', 'Omar', 'Priya', 'Quinn',
    'Rosa', 'Sam', 'Tess', 'Uma', 'Vik', 'Wren', 'Xime', 'Yara', 'Zane',
)
LAST_TUP = (
    'Abbott', 'Baker', 'Cruz', 'Diaz', 'Evans', 'Foster', 'Gupta', 'Hayes',
    'Ibrahim', 'Jensen', 'Kaur', 'Lopez', 'Moreau', 'Nakamura', "O'Brien",
    'Patel', 'Quan', 'Rossi', 'Silva', 'Torres', 'Ueda', 'Vargas', 'Weber',
    'Xu', 'Young', 'Zhao',
)


def clamp(x):
    return max(0., min(1., x))


def score_dict(rng, spec):
    """ one student's fraction earned per assignment, None where nothing was

    Args:
        rng (random.Random): so the file is the same on every run
        spec (dict): the shape of this student (see CAST_TUP)

    Returns:
        out (dict): assignment -> fraction, or None
    """
    out = {}
    stop_after = spec.get('stop_after')
    skip_before = spec.get('skip_before')
    ramp = spec.get('ramp', 0.)
    miss_set = set(spec.get('miss', ()))
    flunk_set = set(spec.get('flunk', ()))

    def base(kind, idx, n):
        level = spec.get(kind)
        if level is None:
            return None
        if spec.get('exact'):
            # a student whose whole point is a number (full marks, or a hair
            # from a cutoff) can't have that number jittered away
            return clamp(level)
        # ramp carries a student from below their level to above it
        drift = ramp * ((idx / max(n - 1, 1)) - .5) * 2
        return clamp(rng.gauss(level + drift, .06))

    for idx, ass in enumerate(HW_TUP):
        n = idx + 1
        if ass in flunk_set:
            out[ass] = 0.
        elif ass in miss_set or (stop_after and n > stop_after) \
                or (skip_before and n < skip_before):
            out[ass] = None
        else:
            out[ass] = base('hw', idx, len(HW_TUP))

    for idx, ass in enumerate(QUIZ_TUP):
        n = idx + 1
        if ass in flunk_set:
            out[ass] = 0.
        elif (stop_after and n > stop_after / 2) \
                or (skip_before and n < skip_before / 2):
            out[ass] = None
        else:
            out[ass] = base('quiz', idx, len(QUIZ_TUP))

    stopped = bool(stop_after)
    out['Exam1'] = 0. if 'Exam1' in flunk_set else base('exam', 0, 2)

    # the makeup: whoever sat it has nothing on exam2a, and vice versa
    retake = spec.get('retake')
    if retake is not None:
        out['Exam2a'] = None
        out['Exam2b'] = clamp(rng.gauss(retake, .04))
    else:
        out['Exam2a'] = None if stopped else base('exam', 1, 2)
        out['Exam2b'] = None

    return out


def late_dict(rng, spec, score):
    """ hours late per assignment, for whatever was submitted at all """
    days = spec.get('late_days', 0)
    n_late = spec.get('late_n')

    out = {}
    submitted = [a for a, v in score.items() if v is not None]
    if n_late is not None:
        chosen = set(rng.sample(submitted, min(n_late, len(submitted))))
    else:
        chosen = set(submitted) if days else set()

    for ass in ASSIGN_DICT:
        if ass in chosen and days:
            # a few hours past the deadline is not the same as a day late
            hour = days * 24 - rng.choice((0, 0, 1, 3))
            out[ass] = f'{max(hour, 1)}:00:00'
        else:
            out[ass] = '00:00:00'
    return out


def row_list_of(rng):
    """ every student, named ones first """
    out = []

    for first, last, _why, spec in CAST_TUP:
        out.append((first, last, spec))

    used = {(f, l) for f, l, _, _ in CAST_TUP}
    while len(out) < N_STUDENT:
        first = rng.choice(FIRST_TUP)
        last = rng.choice(LAST_TUP)
        if (first, last) in used:
            continue
        used.add((first, last))

        level = clamp(rng.gauss(.82, .11))
        spec = dict(hw=clamp(level + rng.gauss(.03, .05)),
                    quiz=clamp(level + rng.gauss(-.02, .06)),
                    exam=clamp(level + rng.gauss(0, .07)))

        roll = rng.random()
        if roll < .08:
            spec['late_days'] = 1
            spec['late_n'] = rng.randint(1, 3)
        if roll > .94:
            spec['retake'] = clamp(level + rng.gauss(.02, .05))
        if .90 < roll <= .94:
            spec['miss'] = (rng.choice(HW_TUP),)

        out.append((first, last, spec))

    return out


def email_of(first, last):
    def clean(text):
        return ''.join(c for c in text.lower() if c.isalpha())
    return f'{clean(first)}.{clean(last)}@uni.edu'


def csv_line(cell_list):
    """ one csv row, quoting only what has to be quoted """
    return ','.join(f'"{c}"' if ',' in c else c for c in cell_list)


def student_list_of(rng):
    """ the whole class, as the plain data both writers work from

    Generated once so that the two files cannot drift into being different
    classes: everything below only decides how to spell it.
    """
    out = []
    for idx, (first, last, spec) in enumerate(row_list_of(rng)):
        score = score_dict(rng, spec)
        out.append(dict(
            first=first, last=last,
            sid=f'{900000000 + idx * 7717:09d}S',
            email=email_of(first, last),
            section=f'CS 2810 Section {1 + idx % 2:02d}',
            score=score,
            late=late_dict(rng, spec, score)))
    return out


def write_scope(stud_list):
    """ the gradescope export: four columns per assignment """
    header = ['First Name', 'Last Name', 'SID', 'Email', 'Sections']
    for ass in ASSIGN_DICT:
        header += [ass + suffix for suffix in SUFFIX_TUP]

    line_list = [','.join(header)]

    for stud in stud_list:
        cell_list = [stud['first'], stud['last'], stud['sid'],
                     stud['email'], stud['section']]

        for ass, points in ASSIGN_DICT.items():
            frac = stud['score'][ass]
            if frac is None:
                # nothing submitted: gradescope leaves the score and the
                # submission time blank
                cell_list += ['', str(points), '', '']
            else:
                cell_list += [f'{round(frac * points, 1):g}', str(points),
                              SUB_TIME, stud['late'][ass]]

        line_list.append(csv_line(cell_list))

    F_SCOPE.write_text('\n'.join(line_list) + '\n')


def write_canvas(stud_list):
    """ the same class as canvas exports it

    Canvas says the same things differently: max points live in a row of
    their own rather than a column per assignment, every assignment column
    carries canvas' own id, the group and course rollups it computes are
    marked read only, and lateness is absent entirely -- canvas knows it,
    but only through its api.
    """
    ass_col_dict = {ass: f'{ass} ({101000 + i * 37})'
                    for i, ass in enumerate(ASSIGN_DICT)}
    rollup_list = [f'{group} Current Score'
                   for group in dict.fromkeys(GROUP_DICT.values())]
    rollup_list.append('Current Score')

    header = ['Student', 'ID', 'SIS User ID', 'SIS Login ID', 'Section']
    header += list(ass_col_dict.values()) + rollup_list

    # canvas' own row: max points per assignment, and '(read only)' against
    # the columns it computes for itself
    point_list = ['    Points Possible', '', '', '', '']
    point_list += [str(points) for points in ASSIGN_DICT.values()]
    point_list += ['(read only)'] * len(rollup_list)

    line_list = [','.join(header), csv_line(point_list)]

    for i, stud in enumerate(stud_list):
        cell_list = [f'{stud["last"]}, {stud["first"]}',
                     str(4000000 + i * 13), stud['sid'], stud['email'],
                     stud['section']]

        for ass, points in ASSIGN_DICT.items():
            frac = stud['score'][ass]
            # an ungraded canvas cell is blank, which is how "no submission"
            # survives the trip -- a 0 there would be a zero somebody earned
            cell_list.append('' if frac is None
                             else f'{round(frac * points, 1):g}')

        # the rollups are canvas' arithmetic, not ours; nothing reads them
        cell_list += [''] * len(rollup_list)

        line_list.append(csv_line(cell_list))

    F_CANVAS.write_text('\n'.join(line_list) + '\n')


def write_public():
    """ the policy_PUBLIC.yaml the page's student example loads

    Built by the package rather than written out here, so the example is the
    real output of the real code path -- including the assignment roster,
    which a student's sheet is filled in from and which would otherwise have
    to be kept in step with ASSIGN_DICT by hand.
    """
    import sys
    import warnings

    sys.path.insert(0, str(ROOT))
    from finalgrade import student
    from finalgrade.policy import Policy

    text = YAML_INSTRUCTOR.format(
        drc=email_of(*CAST_TUP[0][:2]),
        waived=email_of(*CAST_TUP[1][:2]),
        forgiven=email_of(*CAST_TUP[6][:2]))

    f_private = ROOT / 'web' / '_ex_policy_private.yaml'
    f_private.write_text(text)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            policy = Policy.from_file(f_private)
            # graded first, the way the browser and the cli both do it: a
            # policy that will not grade this class has no business being the
            # example of one that does
            policy(str(F_SCOPE))
            F_PUBLIC.write_text(student.policy_text(policy, str(F_SCOPE)))
    finally:
        f_private.unlink()

    for email in (email_of(*cast[:2]) for cast in CAST_TUP):
        assert email not in F_PUBLIC.read_text(), email


def main():
    rng = random.Random(SEED)
    stud_list = student_list_of(rng)

    write_scope(stud_list)
    write_canvas(stud_list)
    write_public()

    for f_out in (F_SCOPE, F_CANVAS, F_PUBLIC):
        print(f'wrote {f_out}')
    print(f'  {N_STUDENT} students, {len(ASSIGN_DICT)} assignments, '
          f'{len(CAST_TUP)} of them named for what they do')


if __name__ == '__main__':
    main()
