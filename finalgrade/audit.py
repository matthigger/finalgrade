""" how one student's grade was arrived at, step by step

A final grade is a single number standing in for a dozen decisions, and the
question that follows it -- from the student, or from a chair, or from you in
August about a course you taught in April -- is always the same: how.

So every step that moved this student's number says so, in order: what stood
in for what, what was waived, what was late and what that cost, which of
their scores was dropped, and how the categories combined.  The pipeline
reports the first two itself (only it knows what it did); everything after
is reconstructed here from the same numbers grading used.
"""
from .get_mean_drop_low import get_drop_idx
from .gradebook import MINUTES_PER_DAY


def fmt_late(minutes):
    """ raw lateness as a person would say it: 2d 14h 13m """
    minutes = int(round(minutes))
    day, rest = divmod(minutes, MINUTES_PER_DAY)
    hour, minute = divmod(rest, 60)

    part_list = []
    if day:
        part_list.append(f'{day}d')
    if hour:
        part_list.append(f'{hour}h')
    if minute or not part_list:
        part_list.append(f'{minute}m')
    return ' '.join(part_list)


def build_log(gradebook, policy, df_grade, log=None, late_dict=None):
    """ the events behind every student's grade

    Args:
        gradebook (Gradebook): after policy.prepare
        policy (Policy): the policy it was prepared with
        df_grade (pd.DataFrame): average_full's output
        log (dict): what prepare() already recorded, email -> events
        late_dict (dict): category -> email -> the late arithmetic, as
            web._late_detail computes it

    Returns:
        log_dict (dict): email -> list of events, in the order they happened
    """
    out = {str(email): list((log or {}).get(email, []))
           for email in df_grade.index}

    _add_late(gradebook, policy, out, late_dict or {})
    _add_drop(gradebook, policy, out)
    _add_mean(policy, df_grade, out)

    return out


def _add_late(gradebook, policy, out, late_dict):
    """ what was late, and what the lateness cost the category """
    if not gradebook.has_lateness:
        return

    df_day = gradebook.get_lateday(cat_late_dict=policy.cat_late_dict)

    for email in out:
        if email not in gradebook.df_late_minutes.index:
            continue

        for ass in gradebook.ass_list:
            minutes = gradebook.df_late_minutes.at[email, ass]
            day = df_day.at[email, ass]
            if not minutes or minutes != minutes:
                continue

            out[email].append(dict(
                kind='late',
                text=f'{ass} was {fmt_late(minutes)} late'
                     + (f', counted as {day:g} late '
                        f'{"day" if day == 1 else "days"}' if day else
                        ', inside the grace period')))

    for cat, per_email in late_dict.items():
        for email, detail in per_email.items():
            if email not in out or not detail:
                continue
            if not detail['days_used']:
                continue

            if detail['penalty']:
                out[email].append(dict(
                    kind='penalty',
                    text=f'{cat}: {detail["days_used"]:g} late days, '
                         f'{detail["days_excused"]:g} excused, so '
                         f'{detail["days_unexcused"]:g} cost '
                         f'{abs(detail["penalty"]):.1%} of the category'))
            else:
                out[email].append(dict(
                    kind='penalty',
                    text=f'{cat}: {detail["days_used"]:g} late days, all '
                         f'within the {detail["days_excused"]:g} excused'))


def _add_drop(gradebook, policy, out):
    """ which of this student's scores drop_low actually discarded """
    ass_list = list(gradebook.ass_list)

    for cat, drop_n in policy.cat_drop_dict.items():
        if not drop_n:
            continue
        cat_ass_list = [a for a in ass_list if cat in a]
        if not cat_ass_list:
            continue

        point_arr = gradebook.points.loc[cat_ass_list].values

        for email in out:
            if email not in gradebook.df_perc.index:
                continue
            perc_arr = gradebook.df_perc.loc[email, cat_ass_list].values
            idx_list = get_drop_idx(perc_arr, point_arr, drop_n)
            if not idx_list:
                continue

            name_list = [f'{cat_ass_list[i]} ({perc_arr[i]:.0%})'
                         for i in idx_list]
            out[email].append(dict(
                kind='drop',
                text=f'{cat}: dropped {", ".join(name_list)}, '
                     f'the lowest of {len(cat_ass_list)}'))


def _add_mean(policy, df_grade, out):
    """ how the categories combined into the number at the top """
    import pandas as pd

    weight_dict = policy.cat_weight_dict
    total = sum(weight_dict.values()) or 1

    for email in out:
        if email not in df_grade.index:
            continue
        row = df_grade.loc[email]

        for cat, weight in weight_dict.items():
            col = f'mean_{cat}'
            if col not in df_grade.columns or pd.isna(row[col]):
                continue
            out[email].append(dict(
                kind='category',
                text=f'{cat}: {row[col]:.1%}, worth {weight / total:.0%} '
                     f'of the grade'))

        if 'mean' in df_grade.columns and not pd.isna(row['mean']):
            letter = row['letter'] if 'letter' in df_grade.columns else ''
            out[email].append(dict(
                kind='final',
                text=f'final grade {row["mean"]:.2%}'
                     + (f', which is {letter}' if letter else '')))
