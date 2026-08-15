"""Shared pytest policy and fixture builders.

Puts the repository root on sys.path so the test suite runs against the
working tree without requiring an editable install.
"""
import pathlib
import sys

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

TEST_FOLDER = REPO_ROOT / 'test'

# gradescope emits four columns per assignment, in this order
ASS_SUFFIX_TUP = ('', ' - Max Points', ' - Submission Time',
                  ' - Lateness (H:M:S)')

SUB_TIME = '2023-01-01 12:00:00 -0500'

# maps a metadata column header to the key used in a student dict
META_KEY = {'first name': 'first', 'last name': 'last', 'sid': 'sid',
            'email': 'email', 'sections': 'section',
            'section_name': 'section', 'crn': 'crn'}
META_DEFAULT = {'first': 'first', 'last': 'last', 'sid': '1234S',
                'section': 'sec01', 'crn': '12345'}


def _meta_value(stud, col):
    key = META_KEY.get(col.strip().lower(), col.strip().lower())
    if key in stud:
        return str(stud[key])
    if key in META_DEFAULT:
        return META_DEFAULT[key]
    raise KeyError(f'no value for metadata column: {col}')


def write_scope(f_out, assignments, students, meta_header=None):
    """ writes a gradescope-style csv

    Args:
        f_out (Path): csv to write
        assignments (dict): assignment name -> max points
        students (list): dicts with keys 'email', 'first', 'last', 'sid',
            'section', 'scores' (assignment -> points, omit for no submission)
            and optionally 'late' (assignment -> 'H:M:S')
        meta_header (list): override the metadata column names (defaults to
            the standard gradescope five)

    Returns:
        f_out (Path)
    """
    if meta_header is None:
        meta_header = ['First Name', 'Last Name', 'SID', 'Email', 'Sections']

    header = list(meta_header)
    for ass in assignments:
        header += [ass + suffix for suffix in ASS_SUFFIX_TUP]

    line_list = [','.join(header)]
    for stud in students:
        row = [_meta_value(stud, col) for col in meta_header]
        for ass, max_pt in assignments.items():
            score = stud.get('scores', {}).get(ass, '')
            late = stud.get('late', {}).get(ass, '00:00:00')
            row += [str(score), str(max_pt), SUB_TIME if score != '' else '',
                    late]
        line_list.append(','.join(row))

    f_out = pathlib.Path(f_out)
    f_out.write_text('\n'.join(line_list) + '\n')
    return f_out


# --------------------------------------------------------------------------
# the shared 3-student fixture used by most end-to-end tests
#
# assignments: hw1, hw2, hw3 (10 pts each), quiz1 (10 pts)
#
#          hw1   hw2   hw3   quiz1 | lateness
# alice     10     8     6      10 | none
# bob       10    10    10       5 | hw1 24h  (-> 1 late day)
# carol      0     6     6       6 | hw1 48h, hw2 24h  (-> 3 late days)
#
# category means (points-weighted, no drops / penalties):
#   alice  hw 24/30 = .8   quiz 1.0
#   bob    hw 30/30 = 1.0  quiz  .5
#   carol  hw 12/30 = .4   quiz  .6
# --------------------------------------------------------------------------
ASSIGN_STD = {'HW1': 10, 'HW2': 10, 'HW3': 10, 'Quiz1': 10}

STUDENT_STD = [
    {'email': 'alice@u.edu', 'first': 'alice', 'last': 'anders', 'sid': '001S',
     'scores': {'HW1': 10, 'HW2': 8, 'HW3': 6, 'Quiz1': 10}},
    {'email': 'bob@u.edu', 'first': 'bob', 'last': 'baker', 'sid': '002S',
     'scores': {'HW1': 10, 'HW2': 10, 'HW3': 10, 'Quiz1': 5},
     'late': {'HW1': '24:00:00'}},
    {'email': 'carol@u.edu', 'first': 'carol', 'last': 'chen', 'sid': '003S',
     'scores': {'HW1': 0, 'HW2': 6, 'HW3': 6, 'Quiz1': 6},
     'late': {'HW1': '48:00:00', 'HW2': '24:00:00'}},
]


@pytest.fixture
def f_scope_std(tmp_path):
    """ the standard 3-student scope csv described above """
    return write_scope(tmp_path / 'scope.csv', ASSIGN_STD, STUDENT_STD)


@pytest.fixture
def write_policy(tmp_path):
    """ returns a fn which writes yaml text to a policy file """
    def _write(text, name='policy.yaml'):
        f = tmp_path / name
        f.write_text(text)
        return f
    return _write
