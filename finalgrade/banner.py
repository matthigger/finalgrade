""" grades in the shape banner will import

Banner matches a row to a student by three fields at once -- CRN, term code
and a 9 digit student id -- and silently ignores any row where all three
don't line up.  So the whole job here is producing those three columns
exactly, from a gradebook that has none of them.

See doc/upload_banner.md for where they come from and how the import works.
"""
import pandas as pd

# banner wants the id without the 'S' that NUIDs often carry, padded to 9
ID_WIDTH = 9


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


def to_banner(df_grade, term_code, crn_list=None):
    """ the grades, with the three columns banner matches on

    Args:
        df_grade (pd.DataFrame): grade_full, with an 'sid' column
        term_code (str): banner's 6 digit term, e.g. '202310'
        crn_list (list): one 5 digit CRN per section.  banner is told which
            column to match on at import time, so several can ride along --
            it discards the mismatched ones with a warning

    Returns:
        df_out (pd.DataFrame): ready to write as xlsx

    Raises:
        KeyError: the grades have no sid column to build an id from
    """
    if 'sid' not in df_grade.columns:
        raise KeyError(
            "these grades have no 'sid' column, so no banner student id can "
            'be built from them')

    df_out = df_grade.copy()
    df_out['Term Code'] = str(term_code)

    for idx, crn in enumerate(crn_list or []):
        df_out[f'CRN{idx}'] = str(crn)

    df_out['Student ID'] = df_out['sid'].map(banner_id)
    del df_out['sid']

    return df_out


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
