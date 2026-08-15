import pathlib

import openpyxl
import pandas as pd
import pytest

import finalgrade
from finalgrade.__main__ import main, parser
from finalgrade.policy import Policy

test_folder = pathlib.Path(finalgrade.__file__).parents[1] / 'test'


@pytest.fixture
def grade_full_csv(tmp_path):
    """Create a grade_full.csv from test data"""
    policy = Policy()
    _, df_grade_full = policy(f_scope=test_folder / 'scope.csv')
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


class TestBannerId:
    def test_the_s_suffix_goes(self):
        from finalgrade.banner import banner_id

        assert banner_id('1234567S') == '001234567'

    def test_a_short_id_is_padded(self):
        from finalgrade.banner import banner_id

        assert banner_id('42') == '000000042'

    def test_an_int_id_survives(self):
        """ read_scope leaves sid uncast, so it is sometimes a number """
        from finalgrade.banner import banner_id

        assert banner_id(1234567) == '001234567'


class TestBannerWeb:
    """ the browser build writes the same workbook, from the same function """

    @pytest.fixture
    def csv_text(self, f_scope_std):
        return f_scope_std.read_text()

    def test_builds_a_workbook(self, csv_text):
        import base64
        import io

        from finalgrade import web

        res = web.banner_export(csv_text, '', '202310', '["12345"]')

        assert res['ok'], res.get('error')
        data = base64.b64decode(res['xlsx_b64'])
        # a zip container, which is what an xlsx is
        assert data[:2] == b'PK'

        # read as text: pandas coerces these to ints otherwise, which would
        # hide whether they were written as digits at all
        df = pd.read_excel(io.BytesIO(data), dtype=str)
        assert list(df['Term Code']) == ['202310'] * 3
        assert list(df['CRN0']) == ['12345'] * 3
        assert 'sid' not in df.columns

    def test_it_matches_the_command_line(self, csv_text, f_scope_std,
                                         tmp_path):
        import base64
        import io

        from finalgrade import web
        from finalgrade.banner import to_banner

        res = web.banner_export(csv_text, '', '202310', '["12345"]')
        df_web = pd.read_excel(io.BytesIO(base64.b64decode(res['xlsx_b64'])),
                               dtype={'Student ID': str})

        _, df_grade = Policy()(str(f_scope_std))
        f = tmp_path / 'grade_full.csv'
        df_grade.to_csv(f)
        df_cli = to_banner(pd.read_csv(f, dtype={'sid': str}),
                           term_code='202310', crn_list=['12345'])

        assert list(df_web['Student ID']) == list(df_cli['Student ID'])
        assert list(df_web['mean'].round(6)) == list(df_cli['mean'].round(6))

    def test_no_term_code_is_refused(self, csv_text):
        from finalgrade import web

        res = web.banner_export(csv_text, '', '   ', '[]')

        assert not res['ok']
        assert 'term code' in res['error']

    def test_a_broken_config_is_a_message(self, csv_text):
        from finalgrade import web

        res = web.banner_export(
            csv_text, 'category:\n  weight:\n    nope: 1\n', '202310', '[]')

        assert not res['ok']
        assert 'nope' in res['error']

    def test_crns_are_optional(self, csv_text):
        from finalgrade import web

        assert web.banner_export(csv_text, '', '202310', '[]')['ok']
