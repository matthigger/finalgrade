""" grades in the shape banner will import

Banner matches a row to a student by three fields at once -- CRN, term code
and a 9 digit student id -- and silently ignores any row where all three
don't line up.  So the whole job here is producing those three columns
exactly, from a gradebook that has none of them.

Two of the three are the same for everybody, but a CRN names one section.
Given a section -> CRN mapping every row carries the one CRN that matches it
and the whole course uploads at once; without one the CRNs ride along in
numbered columns and banner is told which to match on, one import per
section.  See doc/upload_banner.md.

That mapping is not part of a grading policy -- it says where these grades
go, not how they were earned -- so it is never read from or written to a
policy.yaml.
"""
import difflib
from warnings import warn

import pandas as pd

from .errors import GradebookError

# banner wants the id without the 'S' that NUIDs often carry, padded to 9
ID_WIDTH = 9

# banner's own spelling of each field.  worth matching exactly: banner
# pre-selects a column whose header it recognises, which is one dropdown
# nobody can then get wrong at import time
COL_ID = 'Student ID'
COL_TERM = 'Term Code'
COL_CRN = 'CRN'
COL_GRADE = 'Final Grade'

# where a student's section is written, in the exports this package reads.
# gradescope has been seen spelling it both ways; the canvas reader lands on
# 'sections'.  checked in this order, first hit wins
COL_SECTION_TUP = ('sections', 'section_name', 'section', 'sectionname')


def banner_id(sid):
    """ a gradescope student id as banner's 9 digit one

    Args:
        sid: the id as the gradebook has it (a string, or an int when the
            csv had no leading zero to preserve)

    Returns:
        s_id (str): 9 digits, no suffix
    """
    s_id = str(sid).strip()
    if s_id[-1:].upper() == 'S':
        s_id = s_id[:-1]
    return s_id.zfill(ID_WIDTH)


def section_col(df_grade):
    """ the column naming each student's section, if the export has one

    Args:
        df_grade (pd.DataFrame): grade_full

    Returns:
        col (str): the column name, or None when there is no section column
    """
    for col in COL_SECTION_TUP:
        if col in df_grade.columns:
            return col
    return None


def get_section(df_grade):
    """ each student's section, lowercased and stripped

    Args:
        df_grade (pd.DataFrame): grade_full

    Returns:
        s_section (pd.Series): '' where the export left the section blank

    Raises:
        GradebookError: these grades have no section column
    """
    col = section_col(df_grade)
    if col is None:
        raise GradebookError(
            'these grades name no section, so no CRN can be matched to one.  '
            'either re-export the gradebook with its section column, or give '
            'the CRNs without sections (banner then matches one section per '
            'import)')
    return df_grade[col].fillna('').astype(str).str.strip().str.lower()


def section_list(df_grade):
    """ the distinct sections these grades cover

    A student enrolled in two sections is one section here, spelled the way
    the export spelled it: which of the two a single banner row belongs to is
    the user's call, not something to guess by splitting on a comma.

    Args:
        df_grade (pd.DataFrame): grade_full

    Returns:
        sec_list (list): sorted, without the blanks
    """
    if section_col(df_grade) is None:
        return []
    s_section = get_section(df_grade)
    return sorted(set(s_section[s_section != '']))


def resolve_section(crn_dict, sec_list):
    """ the sections a user named, as the sections the gradebook has

    A gradescope section reads 'cs2810-34240-mathematics-of-data-models-sec-
    02-spring-2022', so it is matched by the part of it you typed -- the same
    partial match a category uses to catch its assignments.  A section with a
    blank CRN is one the user chose not to upload, and drops out here.

    Args:
        crn_dict (dict): section name (or a fragment of one) -> CRN
        sec_list (list): the sections the gradebook actually has

    Returns:
        out_dict (dict): full section name -> CRN, as strings

    Raises:
        GradebookError: a name matched no section, or more than one, or two
            names landed on the same section with different CRNs
    """
    out_dict = dict()
    for name, crn in (crn_dict or {}).items():
        crn = str('' if crn is None else crn).strip()
        if not crn:
            continue

        key = str(name).strip().lower()
        if key in sec_list:
            # an exact section wins outright, so that one section's name
            # being a fragment of another's cannot make it unnameable
            match_list = [key]
        else:
            match_list = [sec for sec in sec_list if key in sec]

        if not match_list:
            near_list = difflib.get_close_matches(key, sec_list, n=1)
            hint = f', did you mean "{near_list[0]}"?' if near_list else ''
            raise GradebookError(
                f'no section matches "{name}"{hint}\n'
                f'    sections here: {", ".join(sec_list) or "<none>"}')
        if len(match_list) > 1:
            raise GradebookError(
                f'"{name}" matches {len(match_list)} sections, so which of '
                f'them gets CRN {crn} is ambiguous: {", ".join(match_list)}')

        sec = match_list[0]
        if out_dict.get(sec, crn) != crn:
            raise GradebookError(
                f'section "{sec}" is given two CRNs ({out_dict[sec]} and '
                f'{crn}), and a banner row can only match one')
        out_dict[sec] = crn

    return out_dict


def _add_crn(df_out, crn_dict):
    """ one CRN per row, from the section that row is in

    Rows left without a CRN go: banner would discard them anyway, and the
    point of a mapping is a workbook whose every row matches.

    Args:
        df_out (pd.DataFrame): grade_full, part way into banner's shape
        crn_dict (dict): section (or a fragment of one) -> CRN

    Returns:
        df_out (pd.DataFrame): with a CRN column, and only the rows that
            have one
    """
    s_section = get_section(df_out)
    crn_dict = resolve_section(crn_dict, section_list(df_out))

    if not crn_dict:
        raise GradebookError(
            'no section was given a CRN, so no row could match a banner '
            'course')

    df_out[COL_CRN] = s_section.map(crn_dict)

    is_lost = df_out[COL_CRN].isna()
    if is_lost.any():
        lost_list = sorted(set(s_section[is_lost].replace('', '<blank>')))
        warn(f'{int(is_lost.sum())} students are left out of the banner '
             f'workbook, their section has no CRN: {", ".join(lost_list)}')

    return df_out[~is_lost]


def to_banner(df_grade, term_code, crn_list=None, crn_dict=None,
              letter_only=True):
    """ the grades, with the three columns banner matches on

    Args:
        df_grade (pd.DataFrame): grade_full, with an 'sid' column
        term_code (str): banner's 6 digit term, e.g. '202310'
        crn_list (list): one 5 digit CRN per section.  banner is told which
            column to match on at import time, so several can ride along --
            it discards the mismatched ones with a warning
        crn_dict (dict): section -> CRN, which puts the right CRN on every
            row instead, so every section uploads at once.  an empty one is
            a mapping that named nothing, which is an error; None is no
            mapping asked for
        letter_only (bool): keep only the columns banner reads -- the three
            it matches on and the final grade.  False keeps every grade
            column alongside them

    Returns:
        df_out (pd.DataFrame): ready to write as xlsx

    Raises:
        KeyError: the grades have no sid column to build an id from
        GradebookError: the CRNs and the gradebook's sections disagree
    """
    if 'sid' not in df_grade.columns:
        raise KeyError(
            "these grades have no 'sid' column, so no banner student id can "
            'be built from them')
    if crn_list and crn_dict is not None:
        raise GradebookError(
            'CRNs were given both per section and as a bare list; use one or '
            'the other, since a row can only carry one CRN per column')

    df_out = df_grade.copy()
    df_out[COL_TERM] = str(term_code)
    df_out[COL_ID] = df_out['sid'].map(banner_id)
    del df_out['sid']

    if crn_dict is not None:
        df_out = _add_crn(df_out, crn_dict)
        crn_col_list = [COL_CRN]
    else:
        crn_col_list = []
        for idx, crn in enumerate(crn_list or []):
            col = f'{COL_CRN}{idx}'
            df_out[col] = str(crn)
            crn_col_list.append(col)

    if letter_only:
        if 'letter' not in df_out.columns:
            raise GradebookError(
                "these grades have no 'letter' column, so there is no final "
                'grade to upload (--full sends the grade columns they do '
                'have)')
        df_out = df_out.rename(columns={'letter': COL_GRADE})
        return df_out[[COL_TERM, *crn_col_list, COL_ID, COL_GRADE]]

    # banner's own fields first, so the import's column pickers open on them,
    # and in the order the trimmed workbook uses -- the toggle decides how
    # much comes along, not what the columns are called or how they are read
    lead_list = [COL_TERM, *crn_col_list, COL_ID]
    rest_list = [col for col in df_out.columns if col not in lead_list]
    return df_out[lead_list + rest_list]


def to_xlsx_bytes(df_out):
    """ an xlsx file, in memory

    Args:
        df_out (pd.DataFrame): as returned by to_banner

    Returns:
        data (bytes): the workbook
    """
    import io

    stream = io.BytesIO()
    with pd.ExcelWriter(stream, engine='openpyxl') as writer:
        df_out.to_excel(writer, index=False)
    return stream.getvalue()
