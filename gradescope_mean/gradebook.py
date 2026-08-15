import logging
from math import ceil
from warnings import warn

import numpy as np
import pandas as pd

from .assign_list import AssignmentList, AssignmentNotFoundError, normalize
from .errors import ConfigError, GradebookError
from .get_mean_drop_low import get_mean_drop_low
from .perc_to_letter import perc_to_letter

logger = logging.getLogger('gradescope_mean')

# minutes of grace before a submission counts as late
GRACE_DEFAULT = 60

MINUTES_PER_DAY = 24 * 60


def minutes_to_days(minutes, grace_period_minutes=GRACE_DEFAULT):
    """ converts raw lateness in minutes to whole late days

    nan (a waived assignment) stays nan so that waivers survive.
    """
    if pd.isna(minutes):
        return np.nan
    effective = minutes - grace_period_minutes
    if effective <= 0:
        return 0
    return ceil(effective / MINUTES_PER_DAY)


def get_late_minutes(s_hour_min_sec):
    """ returns total lateness in minutes (ignoring seconds) """
    if not isinstance(s_hour_min_sec, str) or not s_hour_min_sec.strip():
        # blank lateness cell: not late
        return 0
    part_list = s_hour_min_sec.split(':')
    return int(part_list[0]) * 60 + int(part_list[1])


def read_scope(f_scope):
    """ reads a gradescope csv export

    Args:
        f_scope (str): csv downloaded from gradescope

    Returns:
        part_dict (dict): df_score (points earned per student-assignment),
            points (max points per assignment), df_meta (one row per student)
            and df_late_minutes
    """
    df_scope = pd.read_csv(str(f_scope), index_col='Email')

    # groom input data
    df_scope.columns = list(map(normalize, df_scope.columns))
    df_scope.index = df_scope.index.map(lambda s: str(s).lower())
    df_scope.index.name = str(df_scope.index.name).lower()

    if df_scope.index.has_duplicates:
        dupe_list = sorted(set(df_scope.index[df_scope.index.duplicated()]))
        raise GradebookError(
            'duplicate email in gradescope csv (each student must appear '
            f'once): {", ".join(dupe_list)}')

    ass_list = AssignmentList.from_columns(df_scope.columns)

    # metadata is whatever isn't part of an assignment.  (counting a fixed
    # number of leading columns breaks on exports with an extra column)
    ass_col_set = ass_list.get_column_set()
    meta_col_list = [col for col in df_scope.columns
                     if col not in ass_col_set]

    # a missing score means "no submission", which counts as 0.  a missing
    # lateness cell means "not late".  (a blanket fillna(0) would put an int
    # into the H:M:S strings, which then fails to parse)
    for ass in ass_list:
        df_scope[ass] = df_scope[ass].fillna(0)
        df_scope[ass + ass_list.LATE] = \
            df_scope[ass + ass_list.LATE].fillna('00:00:00')

    # meta data (lowercased, except student ids)
    df_meta = df_scope.loc[:, meta_col_list].copy()
    for col in meta_col_list:
        if col == 'sid':
            # student ids are sometimes ints, lets not cast to str
            continue
        df_meta[col] = df_meta[col].fillna('').astype(str).map(str.lower)

    # points per assignment
    point_list = []
    for ass in ass_list:
        col_max_pt = ass + ass_list.MAX_PTS
        if df_scope[col_max_pt].nunique(dropna=False) != 1:
            raise GradebookError(
                f'assignment has more than one max points value: {ass}')
        point_list.append(df_scope[col_max_pt].values[0])
    points = pd.Series(point_list, index=list(ass_list), dtype=float)

    df_score = df_scope.loc[:, list(ass_list)].copy()

    # raw lateness in minutes (grace period applied on demand)
    df_late_minutes = pd.DataFrame(index=df_scope.index)
    for ass in ass_list:
        df_late_minutes[ass] = \
            df_scope[ass + ass_list.LATE].map(get_late_minutes)

    return dict(df_score=df_score, points=points, df_meta=df_meta,
                df_late_minutes=df_late_minutes)


def finalize(df_score, points, df_meta, df_late_minutes=None):
    """ the shared tail of both readers: drop the unusable, take percentages

    Args:
        df_score (pd.DataFrame): points earned per student-assignment
        points (pd.Series): max points per assignment
        df_meta (pd.DataFrame): one metadata row per student
        df_late_minutes (pd.DataFrame): minutes late per student-assignment,
            or None when the source records no lateness (a canvas csv)

    Returns:
        part_dict (dict): the parts a Gradebook is made of
    """
    # an assignment worth 0 points can only produce inf / nan percentages and
    # contributes nothing to any weighted mean, so drop it
    zero_list = sorted(points.index[points == 0])
    if zero_list:
        warn(f'assignment worth 0 points, excluded from grading: '
             f'{", ".join(zero_list)}')
        points = points.drop(index=zero_list)
        df_score = df_score.drop(columns=zero_list)
        if df_late_minutes is not None:
            df_late_minutes = df_late_minutes.drop(columns=zero_list)

    if not len(points):
        # every mean would be nan, so say so here rather than let a gradebook
        # of nothing propagate.  a canvas course whose only columns are ones
        # this tool uploaded (means, letter grades) lands exactly here
        raise GradebookError(
            'no assignment is worth any points, so there is nothing to '
            'grade (an assignment needs a max points above 0)')

    # every score is a fraction of that assignment's max points
    df_perc = df_score.div(points, axis='columns')

    has_lateness = df_late_minutes is not None
    if not has_lateness:
        # nothing is late, and get_late_penalty refuses to pretend otherwise
        df_late_minutes = pd.DataFrame(0, index=df_score.index,
                                       columns=df_score.columns)

    return dict(df_perc=df_perc, df_late_minutes=df_late_minutes,
                points=points, df_meta=df_meta, has_lateness=has_lateness)


class Gradebook:
    """ a grade for every student-assignment pair & manipulations

    There is exactly one source of truth for each thing:

        df_perc          scores       (nan where waived)
        df_late_minutes  lateness     (nan where waived)
        points           max points, indexed by assignment name

    Everything else is derived.  ass_list follows df_perc's columns and
    df_lateday is computed from df_late_minutes on demand, so no method has
    to keep parallel structures in step -- which is what previously allowed
    a waived assignment to keep its late penalty.

    Attributes:
        df_perc (pd.DataFrame): index is email of student and each col is
            assignment, values are percentage earned (nan for waived).
        df_meta (pd.DataFrame): index is email, columns are metadata (first
            name, last name, section, id ...)
        df_late_minutes (pd.DataFrame): index is email, cols are assignment,
            values are raw minutes late (nan for waived)
        points (pd.Series): max points, indexed by assignment name
        has_lateness (bool): whether the source recorded lateness at all.
            a canvas csv doesn't, so df_late_minutes is all zeros there and
            a configured late penalty is an error rather than a silent no-op.
    """

    def __init__(self, f_scope):
        """ builds from a gradescope csv export

        (Gradebook.from_canvas builds the same object from a canvas one,
        Gradebook.from_file picks between them)
        """
        self._set_part_dict(finalize(**read_scope(f_scope)))

    @classmethod
    def from_canvas(cls, f_canvas):
        """ builds from a canvas gradebook export

        Args:
            f_canvas (str): csv downloaded from canvas

        Returns:
            gradebook (Gradebook)
        """
        from .canvas.read import read_canvas
        gradebook = cls.__new__(cls)
        gradebook._set_part_dict(finalize(**read_canvas(f_canvas)))
        return gradebook

    @classmethod
    def from_file(cls, f_grade):
        """ builds from either export, told apart by their columns

        Args:
            f_grade (str): a gradescope or canvas csv

        Returns:
            gradebook (Gradebook)
        """
        from .canvas.read import is_canvas_export
        if is_canvas_export(f_grade):
            return cls.from_canvas(f_grade)
        return cls(f_grade)

    def _set_part_dict(self, part_dict):
        """ adopts the parts a gradebook is made of (see class docstring) """
        self.df_perc = part_dict['df_perc']
        self.df_late_minutes = part_dict['df_late_minutes']
        self.points = part_dict['points']
        self.df_meta = part_dict['df_meta']
        self.has_lateness = part_dict['has_lateness']

    @property
    def ass_list(self):
        """ assignments currently in the gradebook (follows df_perc) """
        return AssignmentList(self.df_perc.columns)

    @property
    def df_lateday(self):
        """ late days per student-assignment at the default grace period """
        return self.get_lateday()

    def get_lateday(self, grace_period_minutes=GRACE_DEFAULT,
                    cat_late_dict=None):
        """ late days per student-assignment

        Args:
            grace_period_minutes (int): grace applied to any assignment not
                covered by cat_late_dict
            cat_late_dict (dict): category -> late penalty kwargs.  each
                category's assignments use that category's own
                grace_period_minutes, so the result matches the penalties
                actually applied.

        Returns:
            df_lateday (pd.DataFrame)
        """
        df_lateday = self.df_late_minutes.map(
            lambda m: minutes_to_days(m, grace_period_minutes))

        for cat, kwargs in (cat_late_dict or {}).items():
            grace = kwargs.get('grace_period_minutes', GRACE_DEFAULT)
            for ass in self.ass_list.match_iter(cat):
                df_lateday[ass] = self.df_late_minutes[ass].map(
                    lambda m: minutes_to_days(m, grace))

        return df_lateday

    @property
    def email_by_prefix(self):
        """ maps the part of each email before '@' to the full email """
        return {email.split('@')[0]: email for email in self.df_perc.index}

    def _resolve_email(self, email):
        """Resolve an email to a matching index entry by prefix.

        Exact match is tried first; if that fails, the prefix before '@'
        is compared against all index entries.  Returns the matched index
        email, or the original email if no match is found.
        """
        if email in self.df_perc.index:
            return email
        return self.email_by_prefix.get(email.split('@')[0], email)

    def waive(self, waive_dict):
        """ waives assignment (per student): the score and its lateness both
        stop counting, as if the work had never been assigned

        Args:
            waive_dict (dict): keys are emails, values are lists of assignments
        """
        for email, ass_list in waive_dict.items():
            email = self._resolve_email(email)
            for ass in ass_list:
                try:
                    _ass = self.ass_list.match(ass)
                except AssignmentNotFoundError:
                    warn(f'waive-fail: not found "{ass}" for {email}')
                    continue
                self.df_perc.loc[email, _ass] = np.nan
                # nulling the single source of truth is what makes the late
                # penalty follow the waiver
                self.df_late_minutes.loc[email, _ass] = np.nan

    def substitute(self, sub_dict):
        """ substitutes some assignment percentages (if sub is higher)

        This method is useful when there are multiple versions of a quiz, each
        with their own gradescope assignment.  It allows you to consolidate
        them into a single assignment (be sure to exclude the substituted
        assignments so they don't count)

        Args:
            sub_dict (dict): keys are target assignment, values are list of
                all assignments which could be substituted
        """
        # we keep all the new, substituted grades in a dict before substituting
        # (were we to substitute, the order of substitutions could cause issue)
        new_col_dict = dict()
        for ass_to, ass_from_list in sub_dict.items():
            ass_all_list = list(ass_from_list)
            if ass_to not in ass_all_list:
                # ensure ass_to is in the list of potential substitutes
                ass_all_list = ass_all_list + [ass_to]

            missing_list = sorted(set(ass_all_list) - set(self.df_perc.columns))
            if missing_list:
                raise ConfigError(
                    f'substitute assignment not found: '
                    f'{", ".join(missing_list)} (assignments are: '
                    f'{", ".join(self.df_perc.columns)})')

            # get max percentage across all assignments, substitute it
            new_col_dict[ass_to] = self.df_perc.loc[:, ass_all_list].max(axis=1)

        # substitute
        for ass_to, s in new_col_dict.items():
            self.df_perc[ass_to] = s

    def prune_email(self, email_list, ignore_suffix=True):
        """ discards rows not in email_list, warns if emails in list not a row

        row order always follows the input csv, never set iteration order,
        so that repeated runs produce identical output.

        Args:
            email_list (list): list of strings
            ignore_suffix (bool): if True, emails match on the part before '@'
        """
        def get_key(email):
            return email.split('@')[0] if ignore_suffix else email

        key_scope_list = [get_key(email) for email in self.df_meta.index]
        if len(key_scope_list) != len(set(key_scope_list)):
            dupe_list = sorted({key for key in key_scope_list
                                if key_scope_list.count(key) > 1})
            raise GradebookError(
                'two students share an email prefix, pass ignore_suffix='
                f'False: {", ".join(dupe_list)}')

        key_scope_set = set(key_scope_list)
        key_target_set = {get_key(email) for email in email_list}

        # warn if any emails not found (sorted: warnings must be stable too)
        key_missing_set = key_target_set - key_scope_set
        if key_missing_set:
            s = '\n'.join(sorted(key_missing_set))
            warn(f'email not found in scope:\n{s}')

            key_extra_set = key_scope_set - key_target_set
            if key_extra_set:
                s = '\n'.join(sorted(key_extra_set))
                warn(f'maybe its one of these?\n{s}')

        # discard rows not in email_list, preserving the csv's row order
        keep_bool_list = [key in key_target_set for key in key_scope_list]
        idx_keep = self.df_meta.index[keep_bool_list]

        self.df_perc = self.df_perc.loc[idx_keep, :]
        self.df_meta = self.df_meta.loc[idx_keep, :]
        self.df_late_minutes = self.df_late_minutes.loc[idx_keep, :]

    def remove_thresh(self, min_complete_thresh):
        """ removes assignments which not enough students have submitted

        Args:
            min_complete_thresh (float): below this completion threshold
                an assignment will be excluded (msg printed to user).  0 and
                nan both count as not completed
        """
        # find percent missing per assignment per ass, rm if above thresh
        s_complete_perc = 1 - (self.df_perc.fillna(0) == 0).mean(axis=0)
        for ass, comp_perc in s_complete_perc.sort_values().items():
            if comp_perc < min_complete_thresh:
                msg = f'removed: {comp_perc * 100:.0f}% complete {ass}'
                self.remove(ass, skip_match=True)
            else:
                msg = f'   kept: {comp_perc * 100:.0f}% complete {ass}'
            logger.info(msg)

    def remove(self, ass, multi=False, skip_match=False):
        """ deletes an assignment

        Args:
            ass (s): an assignments to remove from gradebook
            multi (bool): if True, allows for multiple assignments to be
                removed
            skip_match (bool): when True, assignment name is assumed exact and
                no matching is done.  (defaults False)
        """
        if multi:
            # remove all assignments which match given string
            for _ass in tuple(self.ass_list.match_iter(ass)):
                self.remove(_ass, multi=False, skip_match=True)
            return

        # normalize assignment name
        if not skip_match:
            ass = self.ass_list.match(ass)

        # no index bookkeeping: ass_list follows df_perc's columns
        self.df_perc = self.df_perc.drop(columns=[ass])
        self.df_late_minutes = self.df_late_minutes.drop(columns=[ass])
        self.points = self.points.drop(index=[ass])

    def get_late_penalty(self, cat, penalty_per_day, excuse_day=0,
                         excuse_day_offset=None, waive_dict=None,
                         grace_period_minutes=GRACE_DEFAULT):
        """ computes modifier to category mean to incorporate late penalty

        Let late_day be the total number of days late (across all hws of one
        student).  then the penalty applied is:

            -penalty_per_day * max(late_day - excuse_day, 0)

        to an average assignment score.  For example, when penalty_per_day=.15
        then every unexcused late day effectively negates %15 of a single hw.
        (since all hws needn't have same weight, penalty applied to average hw)

        Args:
            cat (str): category of assignment to apply penalty to
            penalty_per_day (float): percentage of hw penalty per unexcused day
                late.  positive values will lower grades.
            excuse_day (int): number of excused late days each student has (can
                be used on any assignment).  excuse_day_adjust allows this
                default to be modified per student
            excuse_day_offset (dict): keys are student emails, values are
                added to excuse_day value to be used for corresponding student
            waive_dict (dict): keys are student emails, values are lists
                of assignments whose late days are to be waived
            grace_period_minutes (int): minutes of grace before lateness
                counts.  Defaults to 60 (1 hour).

        Returns:
            s_unexcuse_late_day (pd.Series): number of unexcused late days
                remaining (negative if late penalty applied)
            s_penalty (pd.Series): index is email.  values are adjustments
        """
        if penalty_per_day < 0:
            raise ConfigError(
                'penalty_per_day should be positive to lower credit when late')

        if not self.has_lateness:
            # applying a penalty here would compute zero for everybody, which
            # reads as "nobody was late" rather than "we can't tell"
            raise ConfigError(
                f'late_penalty configured for category {cat!r}, but this '
                'grade source records no submission times (a canvas csv '
                'export has no lateness columns)')

        if waive_dict is None:
            waive_dict = dict()

        # get late days across category (waived assignments are already nan in
        # df_late_minutes, so they carry through as nan here)
        ass_cat_list = list(self.ass_list.match_iter(s_assign=cat))
        if not ass_cat_list:
            raise ConfigError(
                f'late_penalty category matches no assignment: "{cat}"')

        df_late = self.get_lateday(
            grace_period_minutes=grace_period_minutes).loc[:, ass_cat_list]

        # waive late days per email / assignment
        for email, ass_list in waive_dict.items():
            email = self._resolve_email(email)
            for ass in ass_list:
                ass = self.ass_list.match(ass)
                if ass in df_late.columns:
                    df_late.loc[email, ass] = np.nan

        # get number of excuse days per student
        s_late_day = df_late.sum(axis=1, skipna=True)
        s_excuse_day = pd.Series(index=s_late_day.index, data=excuse_day,
                                 dtype=float)
        if excuse_day_offset is not None:
            for email, offset in excuse_day_offset.items():
                email = self._resolve_email(email)
                if email in s_excuse_day:
                    s_excuse_day[email] += offset
                else:
                    warn(f'email not found, excuse_day_offset ({offset}) not '
                         f'applied: {email}')

        # get unexcused late days per student
        s_unexcuse_late_day = s_late_day - s_excuse_day

        # get penalty
        s_penalty = - penalty_per_day * s_unexcuse_late_day / len(ass_cat_list)
        s_penalty = s_penalty.apply(lambda x: min(x, 0))

        return s_unexcuse_late_day, s_penalty

    def average_full(self, *args, **kwargs):
        """ like average, but adds metadata & percentage columns to output
        """
        df_grade = self.average(*args, **kwargs)

        return pd.concat((self.df_meta, df_grade, self.df_perc), axis=1)

    def average(self, cat_weight_dict=None, cat_drop_dict=None,
                cat_late_dict=None, grade_thresh=None, late_waive_dict=None):
        """ final grades, weighted by points (default) or category weights

        Args:
            cat_weight_dict (dict): keys are strings which define categories
                values are unnormalized (positive) weights assigned to each
                category.  (e.g. if HW / exam each worth 50% of grade then
                cat_weight_dict {'hw': 50, 'exam': 50}.  Assignment names must
                each contain exactly one category such that categories
                partition all assignments.  (Default: no categories given, each
                assignment weighted by points given on gradescope)
            cat_drop_dict (dict): keys are categories (matching some key
                in cat_weight_dict). values are ints, the number of lowest
                 percentage assignments to drop in each category.  any category
                 without an entry in cat_drop_dict will not have any lowest
                 assignments dropped.  (default: no lowest assignments dropped)
            cat_late_dict (dict): keys are assignment categories.  values are
                dictionaries unpacked as arguments into
                Gradebook.get_late_penalty()

        Returns:
            df_grade (pd.DataFrame): final grade
        """
        if not cat_weight_dict:
            # all assignments contain ''
            cat_weight_dict = {'': 1}

        if cat_late_dict is None:
            cat_late_dict = dict()

        if cat_drop_dict is None:
            cat_drop_dict = dict()
        else:
            unknown_set = set(cat_drop_dict.keys()) - set(cat_weight_dict)
            if unknown_set:
                raise ConfigError(
                    f'drop_low category has no weight: '
                    f'{", ".join(sorted(unknown_set))}')

        ass_list = self.ass_list
        cat_ass_dict = {cat: [ass for ass in ass_list if cat in ass]
                        for cat in cat_weight_dict}

        # a category matching nothing is a typo: it would be silently ignored
        empty_list = sorted(cat for cat, a_list in cat_ass_dict.items()
                            if not a_list)
        if empty_list:
            raise ConfigError(
                f'category matches no assignment: {", ".join(empty_list)} '
                f'(assignments are: {", ".join(ass_list)})')

        # warn when categories don't partition the assignments
        cat_count = pd.Series(0, index=list(ass_list))
        for ass_cat_list in cat_ass_dict.values():
            cat_count[ass_cat_list] += 1
        if (cat_count != 1).any():
            ass_none_list = sorted(cat_count.index[cat_count < 1])
            if ass_none_list:
                warn(f'assignment not in any category: '
                     f'{", ".join(ass_none_list)}')
            ass_many_list = sorted(cat_count.index[cat_count > 1])
            if ass_many_list:
                warn(f'assignment in multiple categories: '
                     f'{", ".join(ass_many_list)}')

        df_grade = pd.DataFrame({'mean': 0.}, index=self.df_perc.index)
        weight_total = pd.Series(0., index=self.df_perc.index)

        for cat, ass_cat_list in cat_ass_dict.items():
            perc_cat = self.df_perc.loc[:, ass_cat_list].values
            point_cat = self.points.loc[ass_cat_list].values
            drop_n = cat_drop_dict.get(cat, 0)

            s_mean = f'mean_{cat}'
            df_grade[s_mean] = pd.Series(
                [get_mean_drop_low(perc=perc_cat[idx, :], weight=point_cat,
                                   drop_n=drop_n)
                 for idx in range(perc_cat.shape[0])],
                index=self.df_perc.index)

            if cat in cat_late_dict:
                s_unexcused_late, s_penalty = self.get_late_penalty(
                    cat=cat,
                    waive_dict=late_waive_dict,
                    **cat_late_dict[cat])

                df_grade[s_mean] += s_penalty

                # ensure penalty doesn't drop mean below 0
                df_grade[s_mean] = df_grade[s_mean].map(lambda x: max(x, 0))

                # add late days remaining to output
                df_grade[f'late days remain ({cat})'] = -s_unexcused_late

            # add category's contribution to overall mean
            cat_missing = df_grade[s_mean].isna()
            for email in cat_missing.index[cat_missing]:
                logger.info(f'{email} has no assignments in category: {cat} '
                            f'(ignored in final mean)')
            weight_total += cat_weight_dict[cat] * ~cat_missing

            df_grade['mean'] += df_grade[s_mean].fillna(0) * \
                cat_weight_dict[cat]

        # a student with no assignments at all has no meaningful mean
        df_grade['mean'] = df_grade['mean'].where(weight_total > 0) \
            / weight_total.where(weight_total > 0)

        # compute letter grade
        df_grade['letter'] = df_grade['mean'].map(
            lambda perc: perc_to_letter(perc, grade_thresh=grade_thresh))

        if 'mean_' in df_grade.columns:
            # delete dummy category (equivalent to default behavior)
            del df_grade['mean_']

        return df_grade
