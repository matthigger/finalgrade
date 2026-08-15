"""Reading a canvas gradebook export as a source of grades.

The mirror of canvas.py, which writes one.  Canvas' csv says the same things
gradescope's does, in three structurally different ways:

    max points   a 'Points Possible' row, not a column per assignment
    lateness     absent (canvas knows it, but only through its api)
    student key  no email column at all in some courses, only ids

so this module's job is to say those three things in gradescope's terms.
"""
import logging
import re
from collections import Counter

import pandas as pd

from .canvas import N_COL_CANVAS_META
from ..assign_list import AssignmentList, normalize
from ..errors import CanvasError

logger = logging.getLogger('gradescope_mean')

COL_STUDENT = 'Student'
COL_SIS_USER = 'SIS User ID'
COL_SIS_LOGIN = 'SIS Login ID'
COL_SECTION = 'Section'

# every canvas export leads with these, in this order
COL_REQUIRED_TUP = (COL_STUDENT, COL_SIS_USER, COL_SIS_LOGIN, COL_SECTION)

# canvas puts max points in a row of its own, and marks the columns it
# computes for itself (group and overall totals) as read only there
ROW_POINTS = 'points possible'
VAL_READ_ONLY = '(read only)'

# an excused assignment: exactly what a waiver already means here
VAL_EXCUSED = 'EX'

# the canvas test student is course scaffolding, not an enrollment
STUDENT_TEST = 'student, test'

# canvas appends its own assignment id to every assignment column.  it changes
# whenever an assignment is recreated, so it can't be part of a name that a
# config file refers to
RE_ASS_ID = re.compile(r'\s*\(\d+\)$')


def is_canvas_export(f_csv):
    """ True when a csv looks like a canvas gradebook export

    Args:
        f_csv (str): any csv

    Returns:
        is_canvas (bool)
    """
    try:
        col_list = list(pd.read_csv(str(f_csv), nrows=0).columns)
    except Exception:
        return False
    return COL_STUDENT in col_list and COL_SIS_USER in col_list


def read_canvas(f_canvas):
    """ reads a canvas gradebook export

    Args:
        f_canvas (str): csv downloaded from canvas

    Returns:
        part_dict (dict): df_score (points earned per student-assignment),
            points (max points per assignment) and df_meta (one row per
            student).  no df_late_minutes: canvas' csv has no lateness.
    """
    df = pd.read_csv(str(f_canvas), dtype=str)

    missing_tup = tuple(col for col in COL_REQUIRED_TUP
                        if col not in df.columns)
    if missing_tup:
        raise CanvasError('not a canvas gradebook export, missing column(s): '
                          f'{", ".join(missing_tup)}')

    s_point, df_body = _split_point_row(df)
    col_ass_list = _get_ass_col_list(df, s_point)
    if not col_ass_list:
        raise CanvasError(
            'canvas export has no assignment columns (only the identity '
            'columns and canvas\' own group / overall totals)')

    index = _get_index(df_body)
    name_dict = _get_name_dict(col_ass_list)
    AssignmentList._warn_prefix([normalize(name)
                                 for name in name_dict.values()])

    # sorted by name, as the gradescope reader leaves them: assignment order
    # is a property of the gradebook, not of which csv it was read from
    col_ass_list = sorted(col_ass_list,
                          key=lambda col: normalize(name_dict[col]))

    df_score = _get_score(df_body[col_ass_list])
    df_score.index = index
    df_score.columns = [normalize(name_dict[col]) for col in col_ass_list]

    points = _get_points(s_point, col_ass_list, name_dict)

    return dict(df_score=df_score, points=points,
                df_meta=_get_meta(df_body, index))


def _split_point_row(df):
    """ separates canvas' 'Points Possible' row from the student rows

    the test student goes too: it's an artifact of the course, and its blank
    sis id would otherwise look like a student we failed to identify.
    """
    s_student = df[COL_STUDENT].fillna('').str.strip().str.lower()

    is_point = s_student == ROW_POINTS
    if not is_point.any():
        raise CanvasError(
            "canvas export has no 'Points Possible' row, so no assignment "
            'has a max points (re-download the whole gradebook)')

    return df[is_point].iloc[0], df[~is_point & (s_student != STUDENT_TEST)]


def _get_ass_col_list(df, s_point):
    """ the assignment columns: those canvas doesn't compute for itself """
    return [col for col in df.columns[N_COL_CANVAS_META:]
            if str(s_point[col]).strip().lower() != VAL_READ_ONLY]


def _get_name_dict(col_ass_list):
    """ maps each canvas assignment column to the name we grade it under

    the trailing canvas assignment id is dropped, so that config files keep
    working when an assignment is recreated -- unless dropping it would make
    two assignments indistinguishable, in which case it's the only thing
    telling them apart and it stays.
    """
    name_dict = {col: RE_ASS_ID.sub('', col).strip() or col
                 for col in col_ass_list}

    name_count = Counter(normalize(name) for name in name_dict.values())
    return {col: (col if name_count[normalize(name)] > 1 else name)
            for col, name in name_dict.items()}


def _get_index(df_body):
    """ chooses what to key students by, and returns it

    gradebook is keyed by email, and so is every email matching feature in
    the config.  canvas has no email column: 'SIS Login ID' holds one in some
    courses and an sis id in others, so use it when it looks like an email
    and fall back to the sis id when it doesn't.
    """
    s_login = df_body[COL_SIS_LOGIN].fillna('').str.strip()
    if len(s_login) and (s_login != '').all() and s_login.str.contains('@').all():
        index = pd.Index(s_login.str.lower(), name='email')
        logger.info(f'keying students by {COL_SIS_LOGIN} (an email)')
    else:
        index = pd.Index(
            df_body[COL_SIS_USER].fillna('').str.strip().str.lower(),
            name='student')
        logger.info(
            f'keying students by {COL_SIS_USER}: this canvas export has no '
            'email, so waive / email_list config entries must use that id')

    blank_tup = tuple(sorted(
        df_body.loc[index == '', COL_STUDENT].fillna('<no name>')))
    if blank_tup:
        raise CanvasError(
            'canvas export has students with no id, who cannot be matched '
            f'to anything: {", ".join(blank_tup)}')

    if index.has_duplicates:
        dupe_tup = tuple(sorted(set(index[index.duplicated()])))
        raise CanvasError('duplicate student in canvas csv (each must appear '
                          f'once): {", ".join(dupe_tup)}')

    return index


def _get_score(df_raw):
    """ canvas grade cells, as numbers

    a blank cell is ungraded, which counts as 0 exactly as it does in
    gradescope.  'EX' is excused, which is what a waiver means here: nan.
    """
    df_out = pd.DataFrame(index=df_raw.index)
    for col in df_raw.columns:
        s_txt = df_raw[col].fillna('').astype(str).str.strip()
        is_excused = s_txt.str.upper() == VAL_EXCUSED

        s_num = pd.to_numeric(s_txt.where(~is_excused, '0'), errors='coerce')
        bad_tup = tuple(sorted(set(s_txt[s_num.isna() & (s_txt != '')])))
        if bad_tup:
            raise CanvasError(f'canvas grade is not a number, in column '
                              f'{col!r}: {", ".join(bad_tup)}')

        df_out[col] = s_num.fillna(0).mask(is_excused)
    return df_out


def _get_points(s_point, col_ass_list, name_dict):
    """ max points per assignment, from canvas' 'Points Possible' row """
    s_out = pd.to_numeric(s_point[col_ass_list], errors='coerce')

    bad_tup = tuple(sorted(col for col in col_ass_list
                           if pd.isna(s_out[col])))
    if bad_tup:
        raise CanvasError('canvas assignment has no max points: '
                          f'{", ".join(bad_tup)}')

    s_out.index = [normalize(name_dict[col]) for col in col_ass_list]
    return s_out.astype(float)


def _get_meta(df_body, index):
    """ first / last name, sis id and section, in gradescope's terms """
    # canvas writes 'Last, First'
    df_name = df_body[COL_STUDENT].fillna('').str.split(',', n=1, expand=True)
    s_last = df_name[0]
    s_first = df_name[1] if df_name.shape[1] > 1 else pd.Series(
        '', index=df_body.index)

    return pd.DataFrame({
        'firstname': s_first.fillna('').str.strip().str.lower().values,
        'lastname': s_last.fillna('').str.strip().str.lower().values,
        # sid keeps canvas' sis id verbatim: it's what canvas_merge joins on
        # to upload grades back, where case and leading zeros both matter
        'sid': df_body[COL_SIS_USER].fillna('').str.strip().values,
        'sections': df_body[COL_SECTION].fillna('').str.strip(
        ).str.lower().values,
    }, index=index)
