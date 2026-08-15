import logging

import pandas as pd

from ..errors import CanvasError

logger = logging.getLogger('gradescope_mean')

# metadata columns the grade pipeline may emit.  which of these are present
# depends on the gradescope export (some courses have 'sections', others
# 'section_name', others neither), so they are dropped only if found.
# 'totallateness(h:m:s)' is a trailing column recent gradescope exports add;
# it isn't an assignment, so it lands in the metadata and must be dropped too
# (canvas turns any unrecognized column into a new assignment).
GRADESCOPE_META_COL_TUP = ('firstname', 'lastname', 'sid', 'sections',
                           'section_name', 'crn', 'email',
                           'totallateness(h:m:s)')

# canvas exports lead with these identity columns; the rest are its own
# gradebook columns, which we discard
N_COL_CANVAS_META = 5


def canvas_merge(f_canvas, df_grade, del_col_list=None,
                 rm_gradescope_meta=True, scale100=True):
    """ merges canvas and gradescope data

    neither argument is modified.

    Args:
        f_canvas (str): canvas csv output
        df_grade (pd.DataFrame): processed grades, consistent with
            gradebook.average() output
        del_col_list (list): columns to delete from the final output csv.
            a name not present is an error (unlike the metadata columns
            removed by rm_gradescope_meta, which vary by export)
        rm_gradescope_meta (bool): if True, drops whichever of
            GRADESCOPE_META_COL_TUP are present
        scale100 (bool): if True, scales grades by 100 (canvas displays with
            precision 2 and rounds this final value ...)

    Returns:
        df_canvas_out (pd.DataFrame): canvas consistent dataframe of grades
    """
    del_col_list = list(del_col_list) if del_col_list else []

    # work on copies: callers keep their dataframes intact
    df_grade = df_grade.copy()

    # load df_canvas & merge
    df_canvas = pd.read_csv(f_canvas)
    df_canvas = df_canvas.iloc[:, :N_COL_CANVAS_META]

    df_canvas = df_canvas.set_index('SIS User ID')
    df_grade = df_grade.set_index('sid')

    # a blank id identifies nobody, but pandas matches nan to nan on an index
    # merge.  left un-dropped, every student without a sid would cross-join
    # against canvas' own id-less rows ('Points Possible', the test student),
    # putting real grades on them.  canvas' id-less rows stay in the output
    # (they're part of its csv format), they simply match nothing.
    df_grade_id = df_grade[df_grade.index.notna()]

    # remember which columns came from the gradebook, so that scaling and
    # deletion below can select by name rather than by position
    grade_col_list = list(df_grade.columns)

    df_canvas_out = df_canvas.merge(df_grade_id,
                                    left_index=True,
                                    right_index=True,
                                    how='left')

    # one row in, one row out.  a duplicated id on either side would silently
    # fan out into extra rows, which canvas would then import as real grades
    if len(df_canvas_out) != len(df_canvas):
        sid_dupe = sorted(map(str, set(
            df_canvas.index[df_canvas.index.duplicated()].dropna()).union(
            df_grade_id.index[df_grade_id.index.duplicated()])))
        raise CanvasError(
            'student id appears more than once, so grades cannot be matched '
            f'one-to-one: {", ".join(sid_dupe)}')

    def log_missing(df, sid_missing, msg, n_cols=3):
        logger.info(msg)
        if not len(sid_missing):
            logger.info('  <no students>')
            return
        for sid in sorted(sid_missing):
            logger.info(f'  {df.loc[sid, :].iloc[:n_cols].to_dict()}')

    # find and report canvas students not in gradescope (and vice versa).
    # id-less rows are excluded: nan is in both sets, so leaving it in makes
    # every set difference empty and hides genuine mismatches.
    sid_canvas_set = set(df_canvas.index[df_canvas.index.notna()])
    sid_grade_set = set(df_grade_id.index)

    log_missing(df=df_canvas,
                sid_missing=sid_canvas_set - sid_grade_set,
                msg='students in canvas, not in gradescope:')
    log_missing(df=df_grade_id,
                sid_missing=sid_grade_set - sid_canvas_set,
                msg='students in gradescope, not in canvas:')

    # students with no sid at all can never match, so report them separately
    n_no_id = len(df_grade) - len(df_grade_id)
    if n_no_id:
        logger.info(f'students in gradescope with no student id (unmatched): '
                    f'{n_no_id}')
        for _, row in df_grade[df_grade.index.isna()].iloc[:, :3].iterrows():
            logger.info(f'  {row.to_dict()}')

    df_canvas_out.index.name = 'sid'
    df_canvas_out.reset_index(inplace=True)

    # explicitly requested deletions must exist; metadata deletions are
    # best-effort, since which metadata columns exist varies by export
    for col in del_col_list:
        if col not in df_canvas_out.columns:
            raise KeyError(
                f'cannot delete column not in grades: {col} '
                f'(available: {", ".join(map(str, df_canvas_out.columns))})')
        del df_canvas_out[col]

    if rm_gradescope_meta:
        for col in GRADESCOPE_META_COL_TUP:
            if col in df_canvas_out.columns:
                del df_canvas_out[col]

    if scale100:
        for col in grade_col_list:
            if col not in df_canvas_out.columns:
                continue
            if 'late days remain' in col:
                # don't scale late days
                continue
            if pd.api.types.is_numeric_dtype(df_canvas_out[col].dtype):
                df_canvas_out[col] = df_canvas_out[col] * 100

    return df_canvas_out
