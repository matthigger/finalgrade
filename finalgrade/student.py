""" the half of a policy a student may be handed, and their row to grade

An instructor's policy.yaml names students: who is waived from what, whose
late day bank is larger than the class's, and why.  None of that can go to a
class.  What can is the part that is the same for everyone -- the weights,
the rules, the thresholds -- plus, for one student, the rows that are about
them and nobody else.

Two files make a student's own estimate: that policy, and their own row of
the export.  Given both, the page grades them with the same code that graded
the class, so the number they are shown is the number they have.  That is the
whole reason this is a subset of the instructor's file rather than a second
description of the same course: a second description can disagree.

Nothing here is anyone's grade but the student's own, and nothing crosses
over that Policy does not model -- the file is rebuilt from a Policy rather
than edited down from text, so a comment cannot carry what a section could
not.
"""
import dataclasses
import io

import pandas as pd

from .assign_list import normalize
from .errors import FinalgradeError, PolicyError
from .gradebook import Gradebook
from .policy import YAML_KEY_DICT

__all__ = ['policy_text', 'one_row_csv', 'add_scores',
           'resolve_thresh']

# every section of a policy, sorted by whether it goes to the class.  the
# two tuples below have to account for all of YAML_KEY_DICT -- checked at
# import, so a section added to Policy is a failure here rather than a
# section that quietly ships to a class.
#
# The line between them is not privacy but arithmetic: one file is posted
# once, for everybody, so it can only hold what is true of everybody.  A
# section keyed by student is not true of everybody even when it is about
# the student reading it.
#
# SHARE_TUP    the same for everyone, so it says nothing about anyone
# DROP_TUP     never handed out, for the reason given at each below
SHARE_TUP = ('cat_weight_dict', 'cat_drop_dict', 'cat_keep_dict',
             'cat_late_dict', 'remove_list', 'sub_dict', 'plan_dict',
             'extra_list', 'grade_thresh')
DROP_TUP = (
    # every section keyed by a student.  a student who was told one of these
    # applies to them writes it in themselves -- the file says how -- which
    # is a line of yaml against the alternative of a file per student, kept
    # in step with the roster all term and emailed one at a time
    'waive_dict',
    'late_waive_dict',
    'max_dict',
    # a roster is a list of the class's email addresses, and a gradebook of
    # one student has nobody to prune anyway
    'email_list',
    # the instructor's own words about why a grade was adjusted.  it moves
    # no grade, so it is nothing an estimate needs, and their wording is not
    # something to hand over by accident
    'note_dict',
    # a completion rate over a class of one is 100% or 0%: kept as written
    # it would drop every assignment the student has yet to hand in, which
    # is the opposite of what it is for.  policy_text resolves it against
    # the whole gradebook into the exclusions it actually came to
    'exclude_complete_thresh',
)

_missing_set = set(YAML_KEY_DICT) - set(SHARE_TUP + DROP_TUP)
if _missing_set:
    raise ImportError(
        'finalgrade.student does not say whether a student may see '
        f'{", ".join(sorted(_missing_set))} -- add it to SHARE_TUP or '
        'DROP_TUP')

# the one thing inside a course-wide section that is keyed by student
LATE_MINE = 'excuse_day_offset'

# the file's own explanation of itself, since it arrives as an attachment
# with no covering note and is the only thing a student has to go on
HEADER = """\
# ---------------------------------------------------------------------------
# YOUR GRADE, WORKED OUT BY YOU -- start here
#
#   1. get your grades as a csv: the one your instructor sent you, or your
#      own download from gradescope or canvas
#   2. go to  https://matthigger.github.io/finalgrade
#   3. drop this file and that csv on the page, together
#
# the page then works your grade out the same way your instructor's run does,
# and shows you how: every score, what was late and what it cost, which
# scores were dropped, and how the categories combined.  you can type a score
# into work that has not been graded yet to see what it would do.
#
# nothing you do there is sent anywhere -- the page downloads a python
# interpreter and runs it in the tab, on your computer.  and an estimate is
# not a grade: only your instructor's run is that.
# ---------------------------------------------------------------------------
#
# PUBLIC: this file is the same one the whole class has, so it holds only what
# is true of everybody -- the weights, the score rules, the late rate and the
# letter cutoffs.  it says nothing about you, and nothing about anybody else.
#
# so if you were told that something applies to you alone -- an assignment
# waived, a late penalty forgiven, extra late days -- it is not in here, and
# your estimate is wrong until you add it.  the page has a control for each of
# them under "adjustments for you", which is the easy way.  by hand, it looks
# like this, with your own email address:
#
#   waive:
#     you@uni.edu: hw3
#
#   waive_late:
#     you@uni.edu: hw5
#
# and extra late days go inside the late_penalty block for the category they
# apply to, alongside excuse_day:
#
#       excuse_day_offset:
#         you@uni.edu: 3
#
# every setting in this file is documented at
#   https://github.com/matthigger/finalgrade/blob/main/doc/policy.md
"""


def _prefix(email):
    """ the part of an email that policy matching is done on """
    return str(email).split('@')[0].strip().lower()


def _put(data, key_tup, value):
    """ writes value at key_tup, making the sections above it as needed """
    node = data
    for key in key_tup[:-1]:
        node = node.setdefault(key, dict())
    node[key_tup[-1]] = value


def _late_section(cat_late_dict):
    """ every late_penalty block, with the per-student offsets taken out """
    out_dict = dict()
    for cat, late_dict in cat_late_dict.items():
        if not isinstance(late_dict, dict):
            continue
        out_dict[cat] = {key: val for key, val in late_dict.items()
                         if key != LATE_MINE}
    return out_dict


def _thresh_exclude(policy, f_grade):
    """ the assignments exclude_complete_thresh came to, by name

    Run rather than recomputed: the threshold is applied part way through
    prepare(), after the exclusions and substitutions that decide what there
    is to count, so the only way to be sure of its answer is to ask it.  The
    same policy with the threshold taken out says what the class would have
    had without it, and the difference is what it removed.
    """
    import warnings

    def survivor_set(thresh):
        _policy = dataclasses.replace(policy, exclude_complete_thresh=thresh)
        gradebook = Gradebook.from_file(f_grade)
        _policy.prepare(gradebook)
        return set(gradebook.ass_list)

    with warnings.catch_warnings():
        # the same csv is about to be graded for real, which is where these
        # belong.  twice is noise, and one of them is raised by a class of
        # one that this is here to prevent
        warnings.simplefilter('ignore')
        return sorted(survivor_set(0) - survivor_set(
            policy.exclude_complete_thresh))


def resolve_thresh(policy, f_grade):
    """ the same policy with exclude_complete_thresh written out by name

    Every student's file needs the same answer to it, and asking costs two
    runs over the class, so the instructor's policy is resolved once and the
    files are written from the result.

    Args:
        policy (Policy): the instructor's own policy
        f_grade (str): the csv the class is graded from

    Returns:
        policy (Policy): with the threshold replaced by the exclusions it
            came to, or the policy itself when it set no threshold
    """
    if not policy.exclude_complete_thresh:
        return policy

    return dataclasses.replace(
        policy, exclude_complete_thresh=0,
        remove_list=list(policy.remove_list) + _thresh_exclude(policy,
                                                               f_grade))


def policy_text(policy, f_grade=None):
    """ the policy to hand the class, as the text of a yaml file

    One file, posted once, holding what is true of everybody: the weights,
    the score rules, the late rate, the cutoffs.  Every section keyed by a
    student is left out, whoever they are -- a file that is right for one
    student is wrong for the other ninety nine, and the file that is right
    for all of them is the one that mentions none of them.

    A student who was told something applies to them alone adds it
    themselves; the header says how.

    Args:
        policy (Policy): the instructor's own policy
        f_grade (str): the csv the class is graded from.  needed only to
            resolve exclude_complete_thresh, which cannot be evaluated over
            one student -- without it a policy using the threshold is
            refused rather than handed over meaning something else

    Returns:
        text (str): contents of a policy.yaml
    """
    from . import edit

    if policy.exclude_complete_thresh:
        if f_grade is None:
            raise PolicyError(
                'exclude_complete_thresh is a completion rate over a class, '
                'and a student has a class of one: it would drop every '
                'assignment they have not handed in.  the gradebook is '
                'needed to write down which assignments it excluded')
        policy = resolve_thresh(policy, f_grade)

    data = dict()

    for attr in SHARE_TUP:
        value = getattr(policy, attr)
        if attr == 'cat_late_dict':
            value = _late_section(value)
        if not value:
            continue
        _put(data, YAML_KEY_DICT[attr], value)

    return HEADER + '\n' + edit.dump(_plainish(data))


def _plainish(obj):
    """ ruamel's own types, dumped as the plain ones they came from

    A Policy read from a file holds ruamel's dict and str subclasses.  Dumped
    as they are they carry the anchors and formatting of the file they came
    from, which is the instructor's file.
    """
    if isinstance(obj, dict):
        # keys as well as values: grade_thresh is keyed by number, and a
        # number spelled as a string is refused when the file is read back
        return {_plainish(k): _plainish(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_plainish(v) for v in obj]
    if isinstance(obj, bool) or obj is None:
        return obj
    if isinstance(obj, int):
        return int(obj)
    if isinstance(obj, float):
        return float(obj)
    if isinstance(obj, str):
        return str(obj)
    return obj


# ---------- the student's own row of the export ----------

def _canvas_col(df):
    """ (the column canvas keys students by, the points possible row), or
    (None, None) when this isn't a canvas export """
    from .canvas.read import COL_SIS_LOGIN, COL_STUDENT, COL_SIS_USER
    from .canvas.read import ROW_POINTS

    if COL_STUDENT not in df.columns or COL_SIS_USER not in df.columns:
        return None, None

    is_point = df[COL_STUDENT].fillna('').astype(str).str.strip().str.lower() \
        == ROW_POINTS
    login = df[COL_SIS_LOGIN].fillna('').astype(str).str.strip()
    col = COL_SIS_LOGIN if login.str.contains('@').any() else COL_SIS_USER
    return col, is_point


def _read_frame(csv_text):
    """ the csv as it was written, without pandas reading anything into it """
    try:
        return pd.read_csv(io.StringIO(csv_text), dtype=str,
                           keep_default_na=False)
    except Exception as e:
        raise FinalgradeError(f'could not read the csv: {e}') from e


def _id_col(df):
    """ (the column holding student emails, the rows that aren't students) """
    col, is_point = _canvas_col(df)
    if col is not None:
        return col, is_point

    for _col in df.columns:
        if normalize(_col) == 'email':
            return _col, pd.Series(False, index=df.index)

    raise FinalgradeError(
        'that csv is neither a gradescope export (no Email column) nor a '
        'canvas one (no Student / SIS User ID columns)')


def one_row_csv(csv_text, email):
    """ the export cut down to one student, still a csv of the same kind

    What an instructor sends a student so that the student has something to
    grade.  It is their own row and the header over it -- for canvas, the
    points possible row as well, without which no assignment has a maximum.

    Args:
        csv_text (str): a gradescope or canvas export of a whole class
        email (str): the student to keep

    Returns:
        csv_text (str): an export of one student
    """
    df = _read_frame(csv_text)
    col, is_point = _id_col(df)

    want = _prefix(email)
    is_mine = df[col].fillna('').astype(str).map(_prefix) == want
    if not is_mine.any():
        raise FinalgradeError(
            f'{email} is not among the students in that csv')

    out = io.StringIO()
    df[is_point | is_mine].to_csv(out, index=False)
    return out.getvalue()


# ---------- what if this score were that ----------

def _find_col(df, ass):
    """ the column holding ass's score, or None """
    want = normalize(ass)
    for col in df.columns:
        if normalize(col) == want:
            return col
    return None


def _add_gradescope_ass(df, ass, points):
    """ the four columns gradescope writes for one assignment, all blank """
    df[ass] = ''
    df[ass + ' - Max Points'] = str(points)
    df[ass + ' - Submission Time'] = ''
    df[ass + ' - Lateness (H:M:S)'] = ''


def add_scores(csv_text, score_dict, point_dict=None, email=None):
    """ the same export with some scores written into it

    How a student asks what a grade would be: a score typed into work that
    has not been graded yet becomes a score in the csv, and the csv is graded
    by the code that grades the course.  Nothing about the policy changes, so
    there is no second way for the arithmetic to come out.

    An assignment with no column yet -- one the policy only plans -- gets the
    columns an export would have given it, out of point_dict.

    An answer of None is one that has not been given, and is skipped rather
    than written as a blank: a blank score is a zero somebody did not hand
    in, which is not what an unanswered question means.  Taking an answer
    back out is done by asking again without it, from the csv as it came.

    Args:
        csv_text (str): a gradescope or canvas export
        score_dict (dict): assignment name -> points earned.  None for an
            assignment left unanswered, which is left as the csv had it
        point_dict (dict): assignment name -> max points, for assignments the
            csv has no column for (a policy's `planned` section)
        email (str): whose scores these are.  optional when the csv holds one
            student, which is the case this is written for

    Returns:
        csv_text (str): the export, with those scores in it
    """
    if not score_dict:
        return csv_text

    df = _read_frame(csv_text)
    col_id, is_point = _id_col(df)
    is_canvas = _canvas_col(df)[0] is not None

    if email is None:
        row_list = list(df.index[~is_point])
        if len(row_list) != 1:
            raise FinalgradeError(
                'a what-if needs to know which student it is about: that '
                f'csv holds {len(row_list)} of them')
        idx = row_list[0]
    else:
        want = _prefix(email)
        is_mine = (df[col_id].fillna('').astype(str).map(_prefix) == want) \
            & ~is_point
        if not is_mine.any():
            raise FinalgradeError(
                f'{email} is not among the students in that csv')
        idx = df.index[is_mine][0]

    point_dict = point_dict or dict()
    score_dict = {ass: score for ass, score in score_dict.items()
                  if score is not None and str(score).strip() != ''}
    if not score_dict:
        return csv_text

    for ass, score in score_dict.items():
        col = _find_col(df, ass)

        if col is None:
            # the policy plans this assignment; the export has never seen it
            points = point_dict.get(ass) or point_dict.get(normalize(ass))
            if not points:
                raise FinalgradeError(
                    f'{ass} is not in that csv, and nothing says what it is '
                    f'out of')
            if is_canvas:
                col = f'{ass}'
                df[col] = ''
                df.loc[is_point, col] = str(points)
            else:
                _add_gradescope_ass(df, ass, points)
                col = ass

        # the lateness beside it is left exactly as the export had it: what
        # a score would have been is a question about the score, and
        # answering it by also forgiving the days it was late would quietly
        # take a penalty off the estimate
        df.at[idx, col] = str(score)

    out = io.StringIO()
    df.to_csv(out, index=False)
    return out.getvalue()
