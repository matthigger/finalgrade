#!/usr/bin/env python3

import argparse
from datetime import datetime

import pandas as pd

parser = argparse.ArgumentParser(description='preps xls for banner upload ('
                                             'https://github.com/matthigger/gradescope_mean/blob/main/doc/upload_banner.md)')
parser.add_argument('grade_full', type=str,
                    help='output csv of gradescope_mean CLI')
parser.add_argument('term_code', type=str,
                    help='banner term code (new column)')
parser.add_argument('-c', '--crn', action='append', dest='crn_list',
                    help='crn of course, may be passed multiple times, '
                         'each creates a new column in output xls')


def main(args=None):
    if args is None:
        args = parser.parse_args()

    df = pd.read_csv(args.grade_full)

    df['Term Code'] = args.term_code

    for idx, crn in enumerate(args.crn_list or ()):
        df[f'CRN{idx}'] = crn

    # modify student ID to banner format
    df['Student ID'] = df['sid'].map(lambda x: str(x).strip('S').zfill(9))
    del df['sid']

    # output csv
    timestamp = datetime.now().strftime('%b%d_%H%M')
    f_canvas_out = args.grade_full.replace('.csv', f'_banner_{timestamp}.xlsx')
    df.to_excel(f_canvas_out, index=False)


if __name__ == '__main__':
    main()
