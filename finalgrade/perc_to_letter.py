import numpy as np

GRADE_THRESH = {.93: 'A',
                .90: 'A-',
                .87: 'B+',
                .83: 'B',
                .80: 'B-',
                .77: 'C+',
                .73: 'C',
                .70: 'C-',
                .67: 'D+',
                .63: 'D',
                .60: 'D-',
                .00: 'E'}


def perc_to_letter(perc, grade_thresh=None, float_bonus=1e-8,
                   nan_letter='no-grade'):
    """ converts a percentage to a letter grade

    Args:
        perc (float): percentage (on assignment)
        grade_thresh (dict): keys are lower thresholds (inclusive) to get
            grade, values are letter grades
        float_bonus (float): due to floating point rounding errors, we give all
            students a slight bonus to ensure they don't miss out on any
            thresholds their grades meet their floating point average may just
            fall short of
        nan_letter (str): assigned to nan inputs

    Returns:
        grade (str): letter grade
    """
    if grade_thresh is None:
        # default (guaranteed sorted)
        mark_thresh_iter = iter(GRADE_THRESH.items())
    else:
        # user input (we must sort)
        mark_thresh_iter = sorted(grade_thresh.items(), reverse=True)

    if np.isnan(perc):
        return nan_letter

    for thresh, mark in mark_thresh_iter:
        if perc + float_bonus >= thresh:
            return mark

    raise ValueError(f'no grade threshold matched for perc={perc}')
