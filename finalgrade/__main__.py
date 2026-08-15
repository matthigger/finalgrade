#!/usr/bin/env python3

import argparse
import logging
import pathlib
import sys
from collections import Counter

import pandas as pd

import finalgrade
from finalgrade.errors import GradescopeMeanError

logger = logging.getLogger('finalgrade')

# ---------- top-level parser ----------
parser = argparse.ArgumentParser(
    prog='finalgrade',
    description='Grade synthesis from Gradescope CSV exports. '
                'See: https://github.com/matthigger/gradescope_mean')
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
    '--config', dest='f_config', default=None,
    help='YAML configuration file. If omitted and config.yaml exists in the '
         'same directory as the CSV it will be used; otherwise the default '
         'config is copied there. Use --new-config to force a fresh copy.')
grade_parser.add_argument(
    '--new-config', dest='new_config', action='store_true',
    help='force creation of a fresh default config.yaml (ignores existing)')
grade_parser.add_argument(
    '-o', '--output', dest='f_output', default=None,
    help='output CSV path (default: grade_full.csv in same directory as '
         'the Gradescope CSV)')
grade_parser.add_argument(
    '--plot', dest='f_hist', nargs='?', const='hist.html', default=None,
    help='generate histogram HTML per assignment category '
         '(default filename: hist.html)')
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
    help='show which assignments each category catches, and what the config '
         'would do, without computing any grades')
check_parser.add_argument(
    'f_scope', type=str,
    help='Gradescope CSV, or a Canvas gradebook export')
check_parser.add_argument(
    '--config', dest='f_config', default=None,
    help='YAML configuration file (default: config.yaml beside the CSV)')
check_parser.add_argument(
    '-q', '--quiet', action='store_true',
    help='suppress informational output')

# ---------- "canvas" subcommand ----------
canvas_parser = subparsers.add_parser(
    'canvas',
    help='prepare grade CSV for Canvas upload '
         '(see: https://github.com/matthigger/gradescope_mean/blob/main/doc'
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
         '(see: https://github.com/matthigger/gradescope_mean/blob/main/doc'
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
    """Configure logging level based on --quiet flag."""
    level = logging.WARNING if quiet else logging.INFO
    logging.basicConfig(level=level, format='%(message)s', force=True)


def _safe_stem(text):
    """Makes a string safe to use as a filename component."""
    stem = ''.join(c if (c.isalnum() or c in '-_') else '_'
                   for c in str(text)).strip('_')
    return stem or 'unknown'


def _banner_id(sid):
    """Formats a gradescope SID as a 9-digit banner student id."""
    s_id = str(sid).strip()
    if s_id[-1:].upper() == 'S':
        s_id = s_id[:-1]
    return s_id.zfill(9)


def _resolve_config(args, folder, force_new=False):
    """The config named by --config, or the one beside the csv."""
    if args.f_config is not None:
        return finalgrade.Config.from_file(args.f_config)
    return finalgrade.Config.resolve_config(
        folder, f_grade=args.f_scope, force_new=force_new)


def cmd_check(args):
    """Execute the 'check' subcommand."""
    _setup_logging(quiet=True)

    folder = pathlib.Path(args.f_scope).resolve().parent
    config = _resolve_config(args, folder)

    report = finalgrade.build_report(config=config, f_grade=args.f_scope)
    print(finalgrade.render(report))

    if not report.ok:
        sys.exit(2)


def cmd_grade(args):
    """Execute the 'grade' subcommand."""
    _setup_logging(args.quiet)

    folder = pathlib.Path(args.f_scope).resolve().parent
    config = _resolve_config(args, folder, force_new=args.new_config)

    # process
    gradebook, df_grade_full = config(f_scope=args.f_scope)

    # output
    f_output = args.f_output or str(folder / 'grade_full.csv')
    df_grade_full.to_csv(f_output)
    logger.info(f'wrote {f_output}')

    # per-student CSVs
    if args.per_stud:
        _folder = folder / 'per_student'
        _folder.mkdir(exist_ok=True)
        stem_count = Counter()
        for email, row in df_grade_full.iterrows():
            last = _safe_stem(row.get('lastname', ''))
            first = _safe_stem(row.get('firstname', ''))
            stem = f'{last}_{first}'
            stem_count[stem] += 1
            if stem_count[stem] > 1:
                # two students share a name: disambiguate with the email
                stem = f'{stem}_{_safe_stem(str(email).split("@")[0])}'
            pd.DataFrame(row).to_csv(_folder / f'{stem}.csv')
        logger.info(f'wrote per-student CSVs to {_folder}')

    # late days CSV (using each category's own grace period, so that the
    # export matches the late days actually penalised)
    if args.f_late_csv is not None:
        f_late = folder / args.f_late_csv
        df_lateday = gradebook.get_lateday(cat_late_dict=config.cat_late_dict)
        df_lateday.to_csv(f_late.with_suffix('.csv'))
        logger.info(f'wrote {f_late}')

    # histogram
    if args.f_hist:
        fig = finalgrade.plot_hist(
            df_grade_full=df_grade_full,
            cat_weight_dict=config.cat_weight_dict)
        f_html = folder / args.f_hist
        fig.write_html(str(f_html), include_plotlyjs='cdn')
        logger.info(f'wrote {f_html}')



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

    # sid must stay a string: leading zeros are significant to banner
    df = pd.read_csv(args.grade_full, dtype={'sid': str})
    df['Term Code'] = args.term_code

    if args.crn_list:
        for idx, crn in enumerate(args.crn_list):
            df[f'CRN{idx}'] = crn

    # modify student ID to banner format
    df['Student ID'] = df['sid'].map(_banner_id)
    del df['sid']

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
        'canvas': cmd_canvas,
        'banner': cmd_banner,
    }

    try:
        dispatch[args.command](args)
    except GradescopeMeanError as e:
        # an expected, actionable problem: the user needs the message, not a
        # traceback
        logger.error(f'error: {e}')
        sys.exit(2)


if __name__ == '__main__':
    main()
