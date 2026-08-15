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
import pandas as pd

from .errors import FinalgradeError
from .get_mean_drop_low import get_drop_idx
from .gradebook import MINUTES_PER_DAY, match_set


def late_detail(gradebook, policy):
    """ what the late penalty did to each student, per category

    A category mean carries its late penalty inside it, so a student looking
    at 78% cannot see whether it is a 78% or an 86% with two unexcused days
    against it.  This is the arithmetic that turns one into the other.

    Returns:
        late_dict (dict): category -> email -> the days and the penalty
        day_dict (dict): email -> assignment -> late days used
    """
    if not policy.cat_late_dict or not gradebook.has_lateness:
        return dict(), dict()

    late_dict = dict()
    for cat, kwargs in policy.cat_late_dict.items():
        try:
            s_unexcused, s_penalty = gradebook.get_late_penalty(
                cat=cat, waive_dict=policy.late_waive_dict, **kwargs)
        except FinalgradeError:
            continue

        excused = kwargs.get('excuse_day', 0) or 0
        offset_dict = kwargs.get('excuse_day_offset') or {}

        # the penalty is spread across the category's assignments, which is
        # what turns "10% a day" into a much smaller dent in the average
        n_ass = len([a for a in gradebook.ass_list if cat in a])

        late_dict[cat] = {}
        for email in gradebook.df_perc.index:
            unexcused = float(s_unexcused.get(email, 0))
            allowed = excused + float(offset_dict.get(email, 0))
            late_dict[cat][str(email)] = dict(
                # unexcused is days used minus days allowed, so used is the
                # sum of the two -- the number a student actually recognises
                days_used=round(unexcused + allowed, 2),
                days_excused=allowed,
                days_unexcused=max(round(unexcused, 2), 0),
                penalty=float(s_penalty.get(email, 0)),
                rate=float(kwargs.get('penalty_per_day', 0) or 0),
                n_ass=n_ass)

    df_day = gradebook.get_lateday(cat_late_dict=policy.cat_late_dict)
    day_dict = {
        str(email): {ass: float(v) for ass, v in row.items()
                     if pd.notna(v) and v}
        for email, row in df_day.iterrows()}

    return late_dict, day_dict


def student_frame(row, log_list=()):
    """ one student's whole file: every number, then how it was arrived at

    The log goes at the end of the same two columns the rest of the file
    uses -- what kind of step it was, then what happened -- so the file that
    answers "what did I get" also answers "why", and an instructor forwards
    one attachment instead of explaining it in the mail.

    Args:
        row (pd.Series): the student's row of average_full's output
        log_list (list): their events, as build_log records them

    Returns:
        df_stud (pd.DataFrame): one column, ready for to_csv
    """
    df_stud = pd.DataFrame(row)
    if not len(log_list):
        return df_stud

    col = df_stud.columns[0]
    # a blank line first: the numbers above are a table and the log below is
    # prose, and a reader should not have to work out where one ends
    key_list = [''] + [str(event['kind']) for event in log_list]
    val_list = [''] + [str(event['text']) for event in log_list]

    return pd.concat([df_stud,
                      pd.DataFrame({col: val_list}, index=key_list)])


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

    # the order the pipeline works in, so each number is traceable to the
    # one above it: the penalty acts on a mean the drop has already changed
    _add_late(gradebook, policy, out)
    _add_drop(gradebook, policy, out)
    _add_penalty(out, late_dict or {}, df_grade)
    _add_mean(policy, df_grade, out)

    return out


def _add_late(gradebook, policy, out):
    """ what was handed in late, and by how much

    Only where a penalty exists.  Elsewhere lateness changed nothing, and a
    log of how a grade was computed that lists things which didn't affect it
    is a log nobody finishes reading.
    """
    if not gradebook.has_lateness or not policy.cat_late_dict:
        return

    charged_list = [ass for ass in gradebook.ass_list
                    if any(cat in ass for cat in policy.cat_late_dict)]
    if not charged_list:
        return

    df_day = gradebook.get_lateday(cat_late_dict=policy.cat_late_dict)

    for email in out:
        if email not in gradebook.df_late_minutes.index:
            continue

        for ass in charged_list:
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


def _add_penalty(out, late_dict, df_grade):
    """ what the lateness came to, once the drops had already happened """
    for cat, per_email in late_dict.items():
        for email, detail in per_email.items():
            if email not in out or not detail or not detail['days_used']:
                continue
            out[email] += _penalty_event(cat, detail, df_grade, email)


def _penalty_event(cat, detail, df_grade, email):
    """ the days charged, and what they came to once spread over the category

    Two lines because it is two facts, and the second is the one nobody can
    do in their head: a penalty of 10% a day, charged once, is a tenth of one
    assignment -- which across ten assignments is 1% of the average.  Read as
    "10% a day" alone it sounds ten times worse than it is.
    """
    used = detail['days_used']
    excused = detail['days_excused']
    over = detail['days_unexcused']

    day_text = (f'{cat}: {used:g} late {_day(used)} used, '
                f'{excused:g} excused')
    day_text += (f', so {over:g} {_is(over)} charged' if over
                 else ', all of them within the allowance')

    event_list = [dict(kind='late', text=day_text)]

    if not detail['penalty']:
        return event_list

    rate = detail.get('rate') or 0
    n_ass = detail.get('n_ass') or 0
    hit = abs(detail['penalty'])

    sum_text = f'{cat}: '
    if rate and n_ass:
        # exactly the arithmetic get_late_penalty does
        sum_text += (f'{over:g} {_day(over)} × {rate:.0%} a day, spread over '
                     f'{n_ass} {"assignment" if n_ass == 1 else "assignments"}'
                     f', is {hit:.1%} off the average')
    else:
        sum_text += f'{hit:.1%} off the average'

    col = f'mean_{cat}'
    if col in df_grade.columns:
        after = df_grade.at[email, col]
        if pd.notna(after):
            before = after + hit
            sum_text += (f' — {before:.1%} becomes {after:.1%}'
                         if before <= 1.0001 else
                         f' — taking it to {after:.1%}')

    return event_list + [dict(kind='penalty', text=sum_text)]


def _day(n):
    return 'day' if n == 1 else 'days'


def _is(n):
    return 'is' if n == 1 else 'are'


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
        extra_set = match_set(gradebook.ass_list, policy.extra_list)
        extra_arr = [a in extra_set for a in cat_ass_list]

        for email in out:
            if email not in gradebook.df_perc.index:
                continue
            perc_arr = gradebook.df_perc.loc[email, cat_ass_list].values
            idx_list = get_drop_idx(perc_arr, point_arr, drop_n,
                                    extra_arr)
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
