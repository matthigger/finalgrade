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

# how many bins a histogram gets.  30 across 0-100% puts an edge every 3⅓
# points, which is fine enough to see a cluster sitting on a letter cutoff
N_BIN = 30


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


def build_table(gradebook, config):
    """ one row per assignment: what it is worth, and what the class did

    The weights are the ones the config implies, not the ones any particular
    student got: inside a category assignments are weighted by their points,
    and drop_low then removes whichever is worst *for that student*, so a
    single number here would be a lie for everybody it wasn't computed on.

    Args:
        gradebook (Gradebook): after config.prepare
        config (Config): the policy

    Returns:
        row_list (list): dicts, in category then assignment order
    """
    ass_list = list(gradebook.ass_list)
    n_student = len(gradebook.df_perc)

    weight_dict = config.cat_weight_dict
    total = sum(weight_dict.values()) or 1

    # no categories: every assignment is weighted by its own points, which is
    # one unnamed group covering everything
    group_list = [(cat, weight_dict[cat] / total,
                   [a for a in ass_list if cat in a])
                  for cat in weight_dict] or [('', 1., ass_list)]

    row_list = []
    seen_set = set()
    for cat, cat_frac, cat_ass_list in group_list:
        point_sum = sum(float(gradebook.points[a]) for a in cat_ass_list)
        for ass in cat_ass_list:
            seen_set.add(ass)
            points = float(gradebook.points[ass])
            in_cat = points / point_sum if point_sum else None
            row_list.append(_row(gradebook, ass, cat, points, in_cat,
                                 None if in_cat is None else in_cat * cat_frac,
                                 n_student))

    # an assignment no category caught still has to appear, or the table
    # would quietly agree that it doesn't exist
    for ass in ass_list:
        if ass not in seen_set:
            row_list.append(_row(gradebook, ass, None,
                                 float(gradebook.points[ass]), None, 0.,
                                 n_student))

    return row_list


def _row(gradebook, ass, cat, points, in_cat, weight, n_student):
    """ one assignment's row of the table """
    s_perc = gradebook.df_perc[ass]

    # a zero is far more often "never submitted" than "submitted and earned
    # nothing", and averaging the two together describes neither
    s_scored = s_perc[s_perc.notna() & (s_perc != 0)]

    return dict(
        category=cat,
        assignment=ass,
        points=points,
        weight_in_cat=in_cat,
        weight_total=weight,
        mean_nonzero=float(s_scored.mean()) if len(s_scored) else None,
        n_complete=int(len(s_scored)),
        n_student=n_student)


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
