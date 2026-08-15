""" the numbers behind a grade, arranged for looking at

A gradebook answers "what did everyone get".  This answers the two questions
that come next: *who* is at a given number, and *what did the policy do to
them* -- the second being the one a spreadsheet can't answer, because the
drops and the late penalties are exactly what a spreadsheet hides.

So every series comes in two versions:

    raw     the grade before drop_low and late_penalty were applied
    final   the grade as it stands

Waivers and exclusions are in both.  They decide what was assigned, which is
a different kind of statement from an adjustment to a score, and a "raw"
that pretended a waived assignment was still owed would be a number nobody
was ever graded on.
"""
import numpy as np
import pandas as pd

# how many bins a histogram gets, unless the data is too small to fill them
N_BIN = 20


def build_view(gradebook, config, df_final, df_raw):
    """ every series the inspector can draw, in one payload

    Args:
        gradebook (Gradebook): after config.prepare
        config (Config): the policy df_final was computed with
        df_final (pd.DataFrame): average_full with the policy applied
        df_raw (pd.DataFrame): average_full with no drops or late penalties

    Returns:
        view_dict (dict): view_list, value_dict and the students they index
    """
    view_list = [dict(key='total', label='final grade', kind='total')]
    value_dict = {'total': _pair(df_final.get('mean'), df_raw.get('mean'))}

    for cat in config.cat_weight_dict:
        key = f'cat:{cat}'
        col = f'mean_{cat}'
        view_list.append(dict(key=key, label=cat, kind='category'))
        value_dict[key] = _pair(df_final.get(col), df_raw.get(col))

    for ass in gradebook.ass_list:
        key = f'ass:{ass}'
        view_list.append(dict(key=key, label=ass, kind='assignment'))
        # an assignment has no drops or penalties of its own: the two series
        # are the same, and the toggle says so rather than pretending
        value_dict[key] = _pair(gradebook.df_perc[ass], None)

    return dict(view_list=view_list, value_dict=value_dict)


def _pair(s_final, s_raw):
    """ one view's two series, aligned to the student order, json ready """
    return dict(final=_num_list(s_final),
                raw=_num_list(s_raw) if s_raw is not None else None)


def _num_list(s):
    """ a series as plain floats, with nan as None (json has no nan) """
    if s is None:
        return []
    return [None if pd.isna(x) else float(x) for x in s]


def histogram(value_list, name_list, n_bin=N_BIN, lo=None, hi=None):
    """ counts per bin, plus who is in each one

    The names are the point of it: a distribution tells you the shape of the
    class, but the question an instructor actually has is which students sit
    just under a cutoff, and that needs the bar to name them.

    Args:
        value_list (list): values, None where the student has none
        name_list (list): one label per value, same order
        n_bin (int): bins across the range
        lo (float): left edge, defaults to the data's minimum (or 0)
        hi (float): right edge, defaults to the data's maximum (or 1)

    Returns:
        hist (dict): edge_list, count_list and who_list (names per bin)
    """
    pair_list = [(v, n) for v, n in zip(value_list, name_list)
                 if v is not None]

    if not pair_list:
        return dict(edge_list=[], count_list=[], who_list=[], n=0)

    val_list = [v for v, _ in pair_list]
    lo = min(0., min(val_list)) if lo is None else lo
    hi = max(1., max(val_list)) if hi is None else hi
    if hi <= lo:
        hi = lo + 1

    edge_arr = np.linspace(lo, hi, n_bin + 1)
    # right edge inclusive on the last bin, so a perfect score is not its own
    # bin of one hanging off the end
    idx_arr = np.clip(np.digitize(val_list, edge_arr[1:-1]), 0, n_bin - 1)

    who_list = [[] for _ in range(n_bin)]
    for idx, (_, name) in zip(idx_arr, pair_list):
        who_list[int(idx)].append(name)

    return dict(edge_list=[float(x) for x in edge_arr],
                count_list=[len(who) for who in who_list],
                who_list=who_list,
                n=len(pair_list))
