#!/usr/bin/env python3
""" writes web/example.csv, the gradebook the page's "try an example" loads

A demo gradebook is only worth anything if it exercises the awkward cases,
so this one is built around students who each break something: nobody who
submitted nothing, somebody who stopped halfway, a retake sitting in a second
column, a whole category never attempted.  They are named after what they do,
so the histogram and the student panel can be read without a key.

    python web/make_example.py

Deterministic: the same file every time, so a rebuild is not a diff.
"""
import pathlib
import random

ROOT = pathlib.Path(__file__).resolve().parents[1]
F_OUT = ROOT / 'web' / 'example.csv'

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


def main():
    rng = random.Random(SEED)

    header = ['First Name', 'Last Name', 'SID', 'Email', 'Sections']
    for ass in ASSIGN_DICT:
        header += [ass + suffix for suffix in SUFFIX_TUP]

    line_list = [','.join(header)]

    for idx, (first, last, spec) in enumerate(row_list_of(rng)):
        score = score_dict(rng, spec)
        late = late_dict(rng, spec, score)

        section = f'CS 2810 Section {1 + idx % 2:02d}'
        cell_list = [first, last, f'{900000000 + idx * 7717:09d}S',
                     email_of(first, last), section]

        for ass, points in ASSIGN_DICT.items():
            frac = score[ass]
            if frac is None:
                # nothing submitted: gradescope leaves the score and the
                # submission time blank
                cell_list += ['', str(points), '', '']
            else:
                cell_list += [f'{round(frac * points, 1):g}', str(points),
                              SUB_TIME, late[ass]]

        line_list.append(','.join(f'"{c}"' if ',' in c else c
                                  for c in cell_list))

    F_OUT.write_text('\n'.join(line_list) + '\n')
    print(f'wrote {F_OUT}')
    print(f'  {N_STUDENT} students, {len(ASSIGN_DICT)} assignments, '
          f'{len(CAST_TUP)} of them named for what they do')


if __name__ == '__main__':
    main()
