""" which of a student's scores count in a category, and their mean

drop_low discards a student's worst few; keep_high counts only their best
few.  A category takes one or the other, never both: which of a student's
scores count is one question with one answer.

They differ on an assignment with no score at all -- nan here, which is what
a waiver, a canvas excusal or an ungraded assignment reaches this far as
(work simply not handed in is already a 0 in both exports):

    drop_low     nan is an absence and is skipped, so a student with two of
                 six homeworks is averaged over the two
    keep_high    nan is a zero, because the count is what was required: two
                 of six puzzles where the best three count is over three

get_count_idx answers that question once.  The mean is built from it, and so
is the late penalty (Gradebook.get_late_penalty), because an assignment that
is not part of a student's grade is not one they can be late on.
"""
import numpy as np


def _as_arr(perc, weight, extra):
    """ the three per-assignment arrays, typed and of the same length """
    weight = np.array(weight, dtype=float)
    perc = np.array(perc, dtype=float)
    extra = (np.zeros(len(perc), dtype=bool) if extra is None
             else np.array(extra, dtype=bool))
    return perc, weight, extra


def get_drop_idx(perc, weight, drop_n=0, extra=None):
    """ which assignments drop_low would discard, by index

    Split out so that an audit can name them: a student asking why a grade
    is what it is is often asking which one was dropped, and that answer is
    different for every student.

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

    # worst percentage first, and the heavier assignment first when two are
    # equal
    iter_ass = sorted((perc[idx], -weight[idx], idx) for idx in idx_ok)
    return [idx for _, _, idx in iter_ass[:drop_n]]


def get_keep_idx(perc, weight, keep_n=0, extra=None):
    """ which assignments keep_high counts, by index

    A missing score is a zero here, which is the whole of what keep_high
    means: when the best three of six puzzles count, a student who attempted
    two is averaged over three, the third a zero.  So the indices returned
    may name an assignment this student has no score for -- the caller
    counts it as 0%.

    Once every assignment is already counted there is nothing left to make
    the number up with, so a keep_n larger than the category keeps all of
    it and the mean is the ordinary one.

    Args:
        perc (np.array): percentage earned per assignment, nan where there
            is no score
        weight (np.array): weight of each assignment
        keep_n (int): number of assignments to keep
        extra (np.array): True where an assignment is extra credit, which is
            always counted and is never one of the keep_n -- it can only
            raise a grade, so a student is never better off leaving it out

    Returns:
        idx_list (list): indices into perc, best first, at most keep_n long
    """
    if not keep_n:
        return []

    perc, weight, extra = _as_arr(perc, weight, extra)

    idx_ok = [idx for idx in range(len(perc))
              if not np.isnan(weight[idx]) and not extra[idx]]

    # best percentage first, and the lighter assignment first when two are
    # equal, so that a zero counted for a missing score does the least
    # damage it can.  like drop_low this need not maximize a grade when
    # weights differ, only be the same choice for every student
    iter_ass = sorted((-np.nan_to_num(perc[idx]), weight[idx], idx)
                      for idx in idx_ok)
    return [idx for _, _, idx in iter_ass[:keep_n]]


def get_count_idx(perc, weight, drop_n=0, keep_n=0, extra=None):
    """ which of one student's assignments are part of their category mean

    An assignment with no score or no weight is not a low score, it is an
    absence of one, and averaging it in either direction would be inventing
    data -- so it is left out.  keep_high is the exception, and says so
    (see the module docstring).

    Args:
        perc (np.array): percentage earned per assignment, nan for no score
        weight (np.array): weight of each assignment
        drop_n (int): number of assignments to drop, exclusive with keep_n
        keep_n (int): number of assignments to count
        extra (np.array): True where an assignment is extra credit

    Returns:
        idx_list (list): indices into perc, ascending
    """
    if drop_n and keep_n:
        raise ValueError('a category takes drop_low or keep_high, not both')

    perc, weight, extra = _as_arr(perc, weight, extra)

    if keep_n:
        idx_set = set(get_keep_idx(perc, weight, keep_n, extra))
        # extra credit is added to whatever the counted scores came to,
        # which is what makes it extra
        idx_set |= {idx for idx in range(len(perc)) if extra[idx]
                    and not (np.isnan(perc[idx]) or np.isnan(weight[idx]))}
        return sorted(idx_set)

    idx_ok = [idx for idx in range(len(perc))
              if not (np.isnan(weight[idx]) or np.isnan(perc[idx]))]

    drop_set = set(get_drop_idx(perc, weight, drop_n, extra))
    return [idx for idx in idx_ok if idx not in drop_set]


def get_mean_drop_low(perc, weight, drop_n=0, keep_n=0, extra=None):
    """ Compute one category's mean, weighted by points.

    Over the assignments get_count_idx leaves counting.

    note: this doesn't necessarily maximize grade with varying weight ... might
    be worth optimizing down the road but its not obvious (to me) how to do
    this

    Args:
        perc (np.array): percentage earned per assignment
        weight (np.array): weight of each assignment
        drop_n (int): number of assignments to drop
        keep_n (int): number of assignments to count, exclusive with drop_n
        extra (np.array): True where an assignment is extra credit.  its
            points count towards what was earned and not towards what was
            available, which is the whole of what "extra" means -- so a
            category can pass 100%, and a student who skips it is no worse
            off than if it had never been set

    Returns:
        mean (float): mean score, weighted by weight over whichever
            assignments counted.  nan where nothing counted
    """
    perc, weight, extra = _as_arr(perc, weight, extra)

    idx_list = get_count_idx(perc, weight, drop_n, keep_n, extra)
    perc, weight, extra = perc[idx_list], weight[idx_list], extra[idx_list]

    # only keep_high counts a slot it has no score for, and that slot is the
    # zero it asks for
    perc = np.nan_to_num(perc)

    # what was available is what was required: extra credit is not part of it
    denom = weight[~extra].sum()
    if not denom:
        # nothing counted, so there is no average -- extra credit alone is a
        # numerator with nothing to be a fraction of
        return np.nan

    return float(np.inner(perc, weight) / denom)
