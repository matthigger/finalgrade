""" what a config would do to a gradebook, without computing any grades

The config's hardest question is which assignments a category catches:
categories match by substring, so `hw: 50` quietly takes in `hw1` and also
`review_hw` -- and you only found out by running the thing and reading the
warnings that scrolled past.  Report() answers that question up front.

It is deliberately data first and text second.  render() is one way to show a
Report; a browser is meant to be another, so nothing here formats anything it
also computes.
"""
import warnings
from dataclasses import dataclass, field

from .errors import GradescopeMeanError
from .gradebook import Gradebook


@dataclass
class AssignmentRow:
    """ one assignment, and what the config does with it """
    name: str
    points: float = None
    n_complete: int = None
    n_student: int = None
    # weighted categories that catch this assignment (usually exactly one)
    cat_list: list = field(default_factory=list)
    # why it isn't graded, or None when it is
    excluded_by: str = None

    @property
    def complete_frac(self):
        if not self.n_student:
            return None
        return self.n_complete / self.n_student


@dataclass
class CategoryRow:
    """ one weighted category, and the assignments it caught """
    name: str
    weight: float
    weight_frac: float
    drop_low: int = 0
    late: dict = None
    ass_list: list = field(default_factory=list)


@dataclass
class Report:
    """ a config and a gradebook, as far as they can be checked together """
    f_grade: str = ''
    source: str = 'gradescope'
    n_student: int = 0
    ass_list: list = field(default_factory=list)
    excluded_list: list = field(default_factory=list)
    cat_list: list = field(default_factory=list)
    error_list: list = field(default_factory=list)
    warn_list: list = field(default_factory=list)
    # true when no category is weighted: every assignment counts by points
    weight_by_point: bool = False

    @property
    def ok(self):
        return not self.error_list


def build_report(config, f_grade):
    """ runs everything but the averaging, and says what happened

    Problems are collected rather than raised: a check that stops at the first
    error can only ever show you one, and the whole point is to see the shape
    of the config at once.

    Args:
        config (Config): grading policy
        f_grade (str): a gradescope or canvas csv

    Returns:
        report (Report)
    """
    from .canvas.read import is_canvas_export

    report = Report(f_grade=str(f_grade),
                    source='canvas' if is_canvas_export(f_grade)
                    else 'gradescope')

    with warnings.catch_warnings(record=True) as warn_list:
        warnings.simplefilter('always')
        try:
            gradebook = Gradebook.from_file(f_grade)
        except GradescopeMeanError as e:
            report.error_list.append(str(e))
            return report
        finally:
            report.warn_list += [str(w.message) for w in warn_list]

    # stats before the pipeline runs, so an excluded assignment can still say
    # how many students had submitted it
    points_0 = gradebook.points.copy()
    complete_0 = (gradebook.df_perc.fillna(0) != 0).sum()
    n_student_0 = len(gradebook.df_perc)

    record = dict()
    with warnings.catch_warnings(record=True) as warn_list:
        warnings.simplefilter('always')
        try:
            config.prepare(gradebook, record=record)
        except GradescopeMeanError as e:
            report.error_list.append(str(e))
        finally:
            report.warn_list += [str(w.message) for w in warn_list]

    report.n_student = len(gradebook.df_perc)
    complete = (gradebook.df_perc.fillna(0) != 0).sum()

    cat_ass_dict = _get_cat_ass_dict(config, gradebook)
    report.weight_by_point = not config.cat_weight_dict

    for ass in gradebook.ass_list:
        report.ass_list.append(AssignmentRow(
            name=ass,
            points=float(points_0.get(ass, float('nan'))),
            n_complete=int(complete.get(ass, 0)),
            n_student=report.n_student,
            cat_list=[cat for cat, a_list in cat_ass_dict.items()
                      if ass in a_list]))

    for ass, reason in sorted(record.items()):
        # a 0 point assignment never reached the gradebook, so it has no
        # completion count to report
        has_stat = ass in complete_0.index
        report.excluded_list.append(AssignmentRow(
            name=ass,
            points=float(points_0[ass]) if ass in points_0.index else None,
            n_complete=int(complete_0[ass]) if has_stat else None,
            n_student=n_student_0 if has_stat else None,
            excluded_by=reason))

    weight_sum = sum(config.cat_weight_dict.values()) or 1
    for cat, weight in config.cat_weight_dict.items():
        report.cat_list.append(CategoryRow(
            name=cat,
            weight=weight,
            weight_frac=weight / weight_sum,
            drop_low=config.cat_drop_dict.get(cat, 0),
            late=config.cat_late_dict.get(cat),
            ass_list=cat_ass_dict[cat]))

    _add_problem(report, config, gradebook)

    return report


def _get_cat_ass_dict(config, gradebook):
    """ category -> assignments it catches, exactly as average() computes it
    """
    ass_list = list(gradebook.ass_list)
    return {cat: [ass for ass in ass_list if cat in ass]
            for cat in config.cat_weight_dict}


def _add_problem(report, config, gradebook):
    """ the checks average() makes, as report entries rather than exceptions
    """
    empty_list = sorted(cat.name for cat in report.cat_list
                        if not cat.ass_list)
    if empty_list:
        report.error_list.append(
            f'category matches no assignment: {", ".join(empty_list)} '
            f'(assignments are: {", ".join(a.name for a in report.ass_list)})')

    if config.cat_late_dict and not gradebook.has_lateness:
        report.error_list.append(
            f'late_penalty configured for '
            f'{", ".join(sorted(config.cat_late_dict))}, but a canvas csv '
            'export records no submission times')

    if config.cat_weight_dict:
        none_list = [a.name for a in report.ass_list if not a.cat_list]
        if none_list:
            report.warn_list.append(
                f'assignment not in any category: {", ".join(none_list)}')

        many_list = [a.name for a in report.ass_list if len(a.cat_list) > 1]
        if many_list:
            report.warn_list.append(
                f'assignment in multiple categories: {", ".join(many_list)}')

    if not report.ass_list:
        report.error_list.append('no assignment is left to grade')


def _fmt_late(late):
    """ a late penalty as one short phrase """
    if not late:
        return '-'
    part_list = [f'{late.get("penalty_per_day", 0) * 100:g}%/day']
    if late.get('excuse_day'):
        part_list.append(f'{late["excuse_day"]:g} excused')
    grace = late.get('grace_period_minutes')
    if grace is not None:
        part_list.append(f'{grace:g}m grace')
    return ', '.join(part_list)


def text_table(header_tup, row_list):
    """ a left aligned text table, sized to its contents """
    if not row_list:
        return []
    all_list = [header_tup] + row_list
    width_list = [max(len(str(row[idx])) for row in all_list)
                  for idx in range(len(header_tup))]

    def fmt(row):
        return '  '.join(str(val).ljust(width)
                         for val, width in zip(row, width_list)).rstrip()

    return [fmt(header_tup), fmt(tuple('-' * w for w in width_list))] + \
           [fmt(row) for row in row_list]


def render(report):
    """ a Report as text, for the terminal

    Args:
        report (Report)

    Returns:
        s_report (str)
    """
    line_list = [
        f'grade source : {report.f_grade} ({report.source})',
        f'students     : {report.n_student}',
        f'assignments  : {len(report.ass_list)} graded, '
        f'{len(report.excluded_list)} excluded',
        '',
    ]

    row_list = []
    for ass in report.ass_list:
        if report.weight_by_point:
            cat = '(by points)'
        elif not ass.cat_list:
            cat = '(none) <- not graded in any category'
        elif len(ass.cat_list) > 1:
            cat = f'{", ".join(ass.cat_list)} <- in more than one'
        else:
            cat = ass.cat_list[0]
        row_list.append((ass.name, f'{ass.points:g}',
                         f'{ass.n_complete}/{ass.n_student}', cat))
    line_list += text_table(('assignment', 'points', 'submitted', 'category'),
                        row_list)

    if report.excluded_list:
        line_list.append('')
        row_list = [
            (ass.name,
             '-' if ass.points is None else f'{ass.points:g}',
             '-' if ass.n_complete is None
             else f'{ass.n_complete}/{ass.n_student}',
             ass.excluded_by)
            for ass in report.excluded_list]
        line_list += text_table(
            ('excluded', 'points', 'submitted', 'why'), row_list)

    line_list.append('')
    if report.weight_by_point:
        line_list.append(
            'no category is weighted: every assignment counts in proportion '
            'to its own points')
    else:
        row_list = [
            (cat.name, f'{cat.weight_frac * 100:.1f}%',
             str(cat.drop_low) if cat.drop_low else '-',
             _fmt_late(cat.late),
             ', '.join(cat.ass_list) or '(none) <- matches no assignment')
            for cat in report.cat_list]
        line_list += text_table(
            ('category', 'weight', 'drop', 'late', 'assignments'), row_list)

    if report.warn_list or report.error_list:
        line_list.append('')
        for s in report.error_list:
            line_list.append(f'error: {s}')
        for s in report.warn_list:
            line_list.append(f'warn : {s}')

    line_list.append('')
    line_list.append('config looks usable' if report.ok
                     else 'config has an error, grading would stop here')

    return '\n'.join(line_list)
