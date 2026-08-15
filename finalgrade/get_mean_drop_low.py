import numpy as np


def _clean(perc, weight, extra):
    """ the assignments that count, as arrays of the same length

    An assignment with no score or no weight is not a low score, it is an
    absence of one, and averaging it in either direction would be inventing
    data.
    """
    weight = np.array(weight, dtype=float)
    perc = np.array(perc, dtype=float)
    extra = (np.zeros(len(perc), dtype=bool) if extra is None
             else np.array(extra, dtype=bool))

    idx_keep = ~(np.isnan(weight) | np.isnan(perc))
    return perc[idx_keep], weight[idx_keep], extra[idx_keep]


def get_drop_idx(perc, weight, drop_n=0, extra=None):
    """ which assignments drop_low would discard, by index

    Split out of get_mean_drop_low so that an audit can name them: a student
    asking why a grade is what it is is often asking which one was dropped,
    and that answer is different for every student.

    Args:
        perc (np.array): percentage earned per assignment
        weight (np.array): weight of each assignment
        drop_n (int): number of assignments to drop
        extra (np.array): True where an assignment is extra credit, which is
            never dropped -- it can only raise a grade, so discarding it is
            never the help that dropping is meant to be

    Returns:
        idx_list (list): indices into perc, worst first
    """
    if not drop_n:
        return []

    idx_ok = [idx for idx in range(len(perc))
              if not (np.isnan(weight[idx]) or np.isnan(perc[idx]))
              and not (extra is not None and extra[idx])]

    # the same order get_mean_drop_low keeps: worst percentage first, and
    # the heavier assignment first when two are equal
    iter_ass = sorted((perc[idx], -weight[idx], idx) for idx in idx_ok)
    return [idx for _, _, idx in iter_ass[:drop_n]]


def get_mean_drop_low(perc, weight, drop_n=0, extra=None):
    """ drops low perc assignment (largest weight if tied), gets weighted mean

    we skip any assignments whose perc or weight is nan

    note: this doesn't necessarily maximize grade with varying weight ... might
    be worth optimizing down the road but its not obvious (to me) how to do
    this

    Args:
        perc (np.array): percentage earned per assignment
        weight (np.array): weight of each assignment
        drop_n (int): number of assignments to drop
        extra (np.array): True where an assignment is extra credit.  its
            points count towards what was earned and not towards what was
            available, which is the whole of what "extra" means -- so a
            category can pass 100%, and a student who skips it is no worse
            off than if it had never been set

    Returns:
        mean (float): mean score, weighted by weight after having dropped the
            most damaging drop_n assignments
    """
    perc, weight, extra = _clean(perc, weight, extra)

    if drop_n:
        drop_set = set(get_drop_idx(perc, weight, drop_n, extra))
        keep = [idx for idx in range(len(perc)) if idx not in drop_set]
        perc, weight, extra = perc[keep], weight[keep], extra[keep]

    # what was available is what was required: extra credit is not part of it
    denom = weight[~extra].sum()
    if not denom:
        # nothing counted, so there is no average -- extra credit alone is a
        # numerator with nothing to be a fraction of
        return np.nan

    return float(np.inner(perc, weight) / denom)
