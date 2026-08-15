import pathlib

import openpyxl
import pandas as pd
import pytest

import finalgrade
from finalgrade.__main__ import main, parser
from finalgrade.config import Config

test_folder = pathlib.Path(finalgrade.__file__).parents[1] / 'test'


@pytest.fixture
def grade_full_csv(tmp_path):
    """Create a grade_full.csv from test data"""
    config = Config()
    _, df_grade_full = config(f_scope=test_folder / 'scope.csv')
    f = tmp_path / 'grade_full.csv'
    df_grade_full.to_csv(f)
    return str(f)


def _banner_args(grade_full_csv, *extra):
    return parser.parse_args(['banner', grade_full_csv, '202310', *extra])


class TestBanner:
    def test_basic_banner_export(self, grade_full_csv, tmp_path):
        main(_banner_args(grade_full_csv, '-c', '12345', '-q'))

        xlsx_list = list(tmp_path.glob('*banner*.xlsx'))
        assert len(xlsx_list) == 1

        df = pd.read_excel(xlsx_list[0])
        assert 'Term Code' in df.columns
        assert 'CRN0' in df.columns
        assert 'Student ID' in df.columns
        assert 'sid' not in df.columns

    def test_multiple_crns(self, grade_full_csv, tmp_path):
        main(_banner_args(grade_full_csv, '-c', '11111', '-c', '22222', '-q'))

        xlsx_list = list(tmp_path.glob('*banner*.xlsx'))
        assert len(xlsx_list) == 1

        df = pd.read_excel(xlsx_list[0])
        assert 'CRN0' in df.columns
        assert 'CRN1' in df.columns

    def test_no_crn(self, grade_full_csv, tmp_path):
        """ -c is optional """
        main(_banner_args(grade_full_csv, '-q'))
        assert len(list(tmp_path.glob('*banner*.xlsx'))) == 1

    def test_student_id_keeps_leading_zeros(self, grade_full_csv, tmp_path):
        """ banner ids are 9 digit strings; a leading zero is significant

        read the raw cells: pd.read_excel coerces these to ints, which would
        hide exactly the bug being checked for.
        """
        main(_banner_args(grade_full_csv, '-q'))

        f_xlsx = next(tmp_path.glob('*banner*.xlsx'))
        ws = openpyxl.load_workbook(f_xlsx).active
        header_list = [c.value for c in ws[1]]
        idx = header_list.index('Student ID')

        for row in list(ws.iter_rows(min_row=2)):
            value = row[idx].value
            assert isinstance(value, str)
            assert value.isdigit()
            assert len(value) >= 9

        # scope.csv's first student is 0123456789S: the trailing S goes, the
        # leading zero stays, and zfill only pads ids shorter than 9
        assert ws[2][idx].value == '0123456789'
