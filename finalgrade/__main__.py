#!/usr/bin/env python3

import argparse
import logging
import pathlib
import sys
from collections import Counter

import pandas as pd

import finalgrade
from finalgrade.audit import build_log, late_detail, student_frame
from finalgrade.errors import FinalgradeError, PolicyError

logger = logging.getLogger('finalgrade')

# ---------- top-level parser ----------
parser = argparse.ArgumentParser(
    prog='finalgrade',
    description='Grade synthesis from Gradescope CSV exports. '
                'See: https://github.com/matthigger/finalgrade')
parser.add_argument('--version', action='version',
                    version=f'%(prog)s {finalgrade.__version__}')
subparsers = parser.add_subparsers(dest='command')

# ---------- "grade" subcommand (default / main workflow) ----------
grade_parser = subparsers.add_parser(
    'grade',
    help='compute final grades from a Gradescope CSV export')
grade_parser.add_argument(
    'f_scope', type=str,
    help='Gradescope CSV (Assignments > Download Grades > CSV), or a Canvas '
         'gradebook export (Grades > Export); the two are told apart by '
         'their columns')
grade_parser.add_argument(
    '--policy', dest='f_policy', default=None,
    help='YAML policy file. If omitted and policy.yaml exists in the '
         'same directory as the CSV it will be used; otherwise the default '
         'policy is copied there. Use --new-policy to force a fresh copy.')
grade_parser.add_argument(
    '--new-policy', dest='new_policy', action='store_true',
    help='force creation of a fresh default policy.yaml (ignores existing)')
grade_parser.add_argument(
    '-o', '--output', dest='f_output', default=None,
    help='output CSV path (default: grade_full.csv in same directory as '
         'the Gradescope CSV)')
grade_parser.add_argument(
    '--late_csv', dest='f_late_csv', default=None,
    help='output CSV of late days per student-assignment pair')
grade_parser.add_argument(
    '--per_student', dest='per_stud', action='store_true',
    help='output a CSV per student into a per_student/ folder')
grade_parser.add_argument(
    '-q', '--quiet', action='store_true',
    help='suppress informational output')

# ---------- "check" subcommand ----------
check_parser = subparsers.add_parser(
    'check',
    help='show which assignments each category catches, and what the policy '
         'would do, without computing any grades')
check_parser.add_argument(
    'f_scope', type=str,
    help='Gradescope CSV, or a Canvas gradebook export')
check_parser.add_argument(
    '--policy', dest='f_policy', required=True,
    help='YAML policy file to check. Required: "finalgrade grade" seeds a '
         'policy beside the csv, but check will not write one for you — a '
         'report on a file finalgrade just invented answers no question you '
         'had')
check_parser.add_argument(
    '-q', '--quiet', action='store_true',
    help='suppress informational output')

# ---------- "student" subcommand ----------
student_parser = subparsers.add_parser(
    'student',
    help='write the files students need to work their own grade out: one '
         'policy.yaml to post for the class, and one csv per student')
student_parser.add_argument(
    'f_scope', type=str,
    help='Gradescope CSV, or a Canvas gradebook export')
student_parser.add_argument(
    '--policy', dest='f_policy', required=True,
    help='YAML policy file. Required: the point of these files is that they '
         'agree with the grades you ran, and a policy finalgrade invented '
         'has graded nobody')
student_parser.add_argument(
    '-o', '--output', dest='f_output', default=None,
    help='folder to write into (default: student/ beside the CSV)')
student_parser.add_argument(
    '--email', dest='email', default=None,
    help='write one student\'s csv rather than the whole class\'s')
student_parser.add_argument(
    '-q', '--quiet', action='store_true',
    help='suppress informational output')

# ---------- "canvas" subcommand ----------
canvas_parser = subparsers.add_parser(
    'canvas',
    help='prepare grade CSV for Canvas upload '
         '(see: https://github.com/matthigger/finalgrade/blob/main/doc'
         '/upload_canvas.md)')
canvas_parser.add_argument(
    'grade_full', type=str,
    help='output CSV of "finalgrade grade" command')
canvas_parser.add_argument(
    'canvas', type=str,
    help='CSV of grades downloaded from Canvas')
canvas_parser.add_argument(
    '--scale100', action='store_true',
    help='scale output by 100 (grades between 0-100) to avoid Canvas '
         'rounding ambiguity')
canvas_parser.add_argument(
    '-q', '--quiet', action='store_true',
    help='suppress informational output')

# ---------- "banner" subcommand ----------
banner_parser = subparsers.add_parser(
    'banner',
    help='prepare Excel file for Banner upload '
         '(see: https://github.com/matthigger/finalgrade/blob/main/doc'
         '/upload_banner.md)')
banner_parser.add_argument(
    'grade_full', type=str,
    help='output CSV of "finalgrade grade" command')
banner_parser.add_argument(
    'term_code', type=str,
    help='Banner term code (added as a new column)')
banner_parser.add_argument(
    '-c', '--crn', action='append', dest='crn_list',
    help='CRN of course section (may be passed multiple times)')
banner_parser.add_argument(
    '-q', '--quiet', action='store_true',
    help='suppress informational output')


def _setup_logging(quiet):
    """Set logging level based on --quiet flag."""
    level = logging.WARNING if quiet else logging.INFO
    logging.basicConfig(level=level, format='%(message)s', force=True)


def _safe_stem(text):
    """Makes a string safe to use as a filename component."""
    stem = ''.join(c if (c.isalnum() or c in '-_') else '_'
                   for c in str(text)).strip('_')
    return stem or 'unknown'


def _resolve_config(args, folder, force_new=False):
    """The policy named by --policy, or the one beside the csv."""
    if args.f_policy is not None:
        return finalgrade.Policy.from_file(args.f_policy)
    return finalgrade.Policy.resolve_policy(
        folder, f_grade=args.f_scope, force_new=force_new)


def cmd_check(args):
    """Execute the 'check' subcommand."""
    _setup_logging(quiet=True)

    # the policy is named outright, and a missing one is an error rather than
    # a file this command quietly writes: check reports on the policy you
    # wrote, and seeding one here would only report back the defaults
    f_policy = pathlib.Path(args.f_policy)
    if not f_policy.is_file():
        raise PolicyError(
            f'no such policy file: {f_policy} — '
            f'"finalgrade grade {args.f_scope}" writes one beside the csv')

    policy = finalgrade.Policy.from_file(f_policy)

    report = finalgrade.build_report(policy=policy, f_grade=args.f_scope)
    print(finalgrade.render(report))

    if not report.ok:
        sys.exit(2)


def cmd_grade(args):
    """Execute the 'grade' subcommand."""
    _setup_logging(args.quiet)

    folder = pathlib.Path(args.f_scope).resolve().parent
    policy = _resolve_config(args, folder, force_new=args.new_policy)

    # process.  the log is only worth keeping when a per-student file will
    # carry it, but it costs nothing to collect
    prepare_log = dict()
    gradebook, df_grade_full = policy(f_scope=args.f_scope, log=prepare_log)

    # output
    f_output = args.f_output or str(folder / 'grade_full.csv')
    df_grade_full.to_csv(f_output)
    logger.info(f'wrote {f_output}')

    # per-student CSVs
    if args.per_stud:
        _folder = folder / 'per_student'
        _folder.mkdir(exist_ok=True)
        log_dict = build_log(gradebook, policy, df_grade_full,
                             log=prepare_log,
                             late_dict=late_detail(gradebook, policy)[0])
        stem_count = Counter()
        for email, row in df_grade_full.iterrows():
            last = _safe_stem(row.get('lastname', ''))
            first = _safe_stem(row.get('firstname', ''))
            stem = f'{last}_{first}'
            stem_count[stem] += 1
            if stem_count[stem] > 1:
                # two students share a name: disambiguate with the email
                stem = f'{stem}_{_safe_stem(str(email).split("@")[0])}'
            student_frame(row, log_dict.get(str(email), [])).to_csv(
                _folder / f'{stem}.csv')
        logger.info(f'wrote per-student CSVs to {_folder}')

    # late days CSV (using each category's own grace period, so that the
    # export matches the late days actually penalised)
    if args.f_late_csv is not None:
        f_late = folder / args.f_late_csv
        df_lateday = gradebook.get_lateday(cat_late_dict=policy.cat_late_dict)
        df_lateday.to_csv(f_late.with_suffix('.csv'))
        logger.info(f'wrote {f_late}')


def cmd_student(args):
    """Execute the 'student' subcommand."""
    _setup_logging(args.quiet)

    from . import student as student_mod
    from .web import _stem_dict

    folder = pathlib.Path(args.f_scope).resolve().parent
    policy = _resolve_config(args, folder)

    # graded first, so that these files cannot describe a policy that would
    # not grade the class they came from
    _, df_grade_full = policy(f_scope=args.f_scope)

    if args.email is not None:
        prefix = args.email.split('@')[0].lower()
        keep_list = [idx for idx in df_grade_full.index
                     if str(idx).split('@')[0].lower() == prefix]
        if not keep_list:
            raise PolicyError(
                f'{args.email} is not among the students being graded')
        df_grade_full = df_grade_full.loc[keep_list]

    out_folder = pathlib.Path(args.f_output or (folder / 'student'))
    out_folder.mkdir(parents=True, exist_ok=True)
    csv_text = pathlib.Path(args.f_scope).read_text()

    # one policy for the class.  the completion threshold is asked about once
    # here rather than once per student: it costs two runs over the whole
    # gradebook, and there is one answer to it
    f_policy = out_folder / 'policy_student.yaml'
    f_policy.write_text(student_mod.policy_text(
        student_mod.resolve_thresh(policy, args.f_scope)))

    grade_folder = out_folder / 'grades'
    grade_folder.mkdir(exist_ok=True)
    stem_dict = _stem_dict(df_grade_full)
    for email in df_grade_full.index:
        (grade_folder / f'{stem_dict[email]}.csv').write_text(
            student_mod.one_row_csv(csv_text, str(email)))

    logger.info(
        f'wrote {f_policy}\n'
        f'  post this once: it is your policy with every student taken out '
        f'of it, so it is the same file for the whole class\n'
        f'wrote {len(df_grade_full)} csv(s) to {grade_folder}\n'
        f'  one student\'s scores each, which is the half that cannot be '
        f'posted.  with both files a student can work their own grade out on '
        f'https://matthigger.github.io/finalgrade')


def cmd_canvas(args):
    """Execute the 'canvas' subcommand."""
    _setup_logging(args.quiet)

    from datetime import datetime

    df_grade_full = pd.read_csv(args.grade_full)
    df_canvas_out = finalgrade.canvas_merge(
        f_canvas=args.canvas,
        df_grade=df_grade_full,
        rm_gradescope_meta=True,
        scale100=args.scale100)

    timestamp = datetime.now().strftime('%b%d_%H%M')
    f_canvas_out = args.canvas.replace('.csv', f'{timestamp}.csv')
    df_canvas_out.to_csv(f_canvas_out, index=False)
    logger.info(f'wrote {f_canvas_out}')


def cmd_banner(args):
    """Execute the 'banner' subcommand."""
    _setup_logging(args.quiet)

    from datetime import datetime

    from .banner import to_banner

    # sid must stay a string: leading zeros are significant to banner
    df = pd.read_csv(args.grade_full, dtype={'sid': str})
    df = to_banner(df, term_code=args.term_code, crn_list=args.crn_list)

    timestamp = datetime.now().strftime('%b%d_%H%M')
    f_out = args.grade_full.replace('.csv', f'_banner_{timestamp}.xlsx')
    df.to_excel(f_out, index=False)
    logger.info(f'wrote {f_out}')


def main(args=None):
    if args is None:
        args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    dispatch = {
        'grade': cmd_grade,
        'check': cmd_check,
        'student': cmd_student,
        'canvas': cmd_canvas,
        'banner': cmd_banner,
    }

    try:
        dispatch[args.command](args)
    except FinalgradeError as e:
        # an expected, actionable problem: the user needs the message, not a
        # traceback
        logger.error(f'error: {e}')
        sys.exit(2)


if __name__ == '__main__':
    main()
