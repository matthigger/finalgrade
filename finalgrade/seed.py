""" a new policy.yaml that already knows this course's assignments

The packaged policy.yaml is the same file for everybody: every section null,
with examples about student0@uni.edu and a fictional hw1.  So the first thing
anyone does is invent assignment names and find out later, from a warning,
that they never matched anything.

Writing the real names into the file removes the guessing.  The suggested
category split is written commented out on purpose: uncommenting is one
keystroke, whereas a plausible looking weight nobody asked for is a wrong
grade, and this package's whole posture is that those are worse than errors.
"""
import re

from .assign_list import normalize
from .check import text_table

# the leading word of an assignment name, which is what usually names its
# category: 'hw1' -> 'hw', 'exam-midterm' -> 'exam'
RE_PREFIX = re.compile(r'[^\W\d_]+')

# where the seeded block is spliced into the packaged policy
ANCHOR = 'category:'


def guess_cat_list(ass_list, cat_hint_list=None):
    """ category names likely to split these assignments

    Args:
        ass_list (list): normalized assignment names
        cat_hint_list (list): categories the grade source already names
            (canvas assignment groups).  Only those that actually match an
            assignment are used -- a canvas group called 'Problem Sets' says
            nothing about assignments named 'ps1'.

    Returns:
        cat_list (list): guessed category names, in assignment order
    """
    cat_list = []
    covered_set = set()

    for hint in (cat_hint_list or []):
        cat = normalize(hint)
        match_list = [ass for ass in ass_list if cat and cat in ass]
        if match_list and cat not in cat_list:
            cat_list.append(cat)
            covered_set.update(match_list)

    for ass in ass_list:
        if ass in covered_set:
            continue
        match = RE_PREFIX.match(ass)
        cat = match.group(0) if match else ass
        if cat not in cat_list:
            cat_list.append(cat)

    return cat_list


def _comment(line_list):
    """ prefixes each line with '# ', leaving blank lines bare """
    return [f'# {line}'.rstrip() for line in line_list]


def _assignment_block(gradebook):
    """ the assignments found, as a comment table """
    n_student = len(gradebook.df_perc)
    complete = (gradebook.df_perc.fillna(0) != 0).sum()

    row_list = [(ass, f'{gradebook.points[ass]:g}',
                 f'{int(complete[ass])}/{n_student}')
                for ass in gradebook.ass_list]

    line_list = [f'the {len(row_list)} assignments found, as this file must '
                 'spell them:', '']
    line_list += ['    ' + line
                  for line in text_table(('assignment', 'points', 'submitted'),
                                         row_list)]

    if gradebook.zero_point_list:
        line_list += ['', 'not gradeable, worth 0 points: '
                      + ', '.join(gradebook.zero_point_list)]

    return line_list


def _category_block(gradebook):
    """ a suggested category split, commented out """
    ass_list = list(gradebook.ass_list)
    cat_list = guess_cat_list(ass_list, gradebook.cat_hint_list)

    source = ('your canvas assignment groups'
              if gradebook.cat_hint_list else
              'the first word of each assignment name')

    line_list = [
        '',
        f'a guess at your categories, from {source}.',
        '',
        'it is commented out: as written, every assignment counts in',
        'proportion to its own points.  uncomment and edit to weight by',
        'category instead -- weights are normalized, so they need not sum',
        'to 100.  each comment is what that category would actually catch.',
        '',
        'category:',
        '  weight:',
    ]

    weight = round(100 / len(cat_list)) if cat_list else 0
    for cat in cat_list:
        # what the tool will actually catch, which is a substring match over
        # every assignment -- not just the ones that suggested this name
        match_list = [ass for ass in ass_list if cat in ass]
        line_list.append(f'    {cat}: {weight}'.ljust(24)
                         + f'# {", ".join(match_list)}')

    if gradebook.cat_hint_list:
        unused_list = [hint for hint in gradebook.cat_hint_list
                       if normalize(hint) not in cat_list]
        if unused_list:
            line_list += [
                '',
                'canvas also has these assignment groups, whose names',
                'match no assignment here: ' + ', '.join(unused_list)]

    return line_list


def seed_text(gradebook, f_grade, text_default):
    """ the packaged policy, with this course's assignments written in

    Args:
        gradebook (Gradebook): as read, before any policy is applied
        f_grade (str): the csv it was read from, named in the comment
        text_default (str): contents of the packaged policy.yaml

    Returns:
        text (str): contents for a new policy.yaml
    """
    import pathlib

    line_list = ['=' * 69,
                 f'written for {pathlib.Path(f_grade).name}', '']
    line_list += _assignment_block(gradebook)
    line_list += _category_block(gradebook)
    line_list += ['', '=' * 69]

    block = '\n'.join(_comment(line_list)) + '\n\n'

    line_default_list = text_default.splitlines(keepends=True)
    for idx, line in enumerate(line_default_list):
        if line.startswith(ANCHOR):
            return ''.join(line_default_list[:idx]) + block + \
                ''.join(line_default_list[idx:])

    # no anchor: the packaged policy was rewritten without a category section.
    # appending still beats losing the assignment list
    return text_default + '\n' + block
