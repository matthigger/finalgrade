""" the api the browser build calls

These run in cpython, not in a browser: what they protect is the contract the
page depends on -- that every value crossing into javascript is plain data,
and that the browser's answer is the command line's answer.  Whether pyodide
can load the wheel is a question for the build, not for pytest.
"""
import json
import pathlib

import pytest

from gradescope_mean import web
from gradescope_mean.config import Config


@pytest.fixture
def csv_text(f_scope_std):
    return f_scope_std.read_text()


YAML_STD = 'category:\n  weight:\n    hw: 50\n    quiz: 50\n'


def is_plain(obj):
    """ True when obj is something json can hold (so js can receive it) """
    try:
        json.dumps(obj)
    except (TypeError, ValueError):
        return False
    return True


class TestLoad:
    def test_describes_the_csv(self, csv_text):
        info = web.load_csv(csv_text)

        assert info['ok']
        assert info['source'] == 'gradescope'
        assert info['n_student'] == 3
        assert [a['name'] for a in info['ass_list']] == \
            ['hw1', 'hw2', 'hw3', 'quiz1']

    def test_is_plain_data(self, csv_text):
        assert is_plain(web.load_csv(csv_text))

    def test_bad_csv_is_a_message_not_an_exception(self):
        info = web.load_csv('not,a,gradebook\n1,2,3\n')

        assert not info['ok']
        assert info['error']

    def test_warnings_come_back_as_values(self, tmp_path):
        """ the page shows them; nothing here should print to a console """
        from conftest import ASSIGN_STD, STUDENT_STD, write_scope

        f_scope = write_scope(tmp_path / 'scope.csv',
                              dict(ASSIGN_STD, Survey=0), STUDENT_STD)
        info = web.load_csv(f_scope.read_text())

        assert any('0 points' in s for s in info['warn_list'])
        assert info['zero_point_list'] == ['survey']


class TestCheck:
    def test_reports_the_split(self, csv_text):
        rep = web.check_config(csv_text, YAML_STD)

        assert rep['ok']
        cat_dict = {c['name']: c['ass_list'] for c in rep['cat_list']}
        assert cat_dict == {'hw': ['hw1', 'hw2', 'hw3'], 'quiz': ['quiz1']}

    def test_is_plain_data(self, csv_text):
        assert is_plain(web.check_config(csv_text, YAML_STD))

    def test_names_the_users_file_not_a_temp_path(self, csv_text):
        rep = web.check_config(csv_text, YAML_STD, name='spring25.csv')

        assert rep['f_grade'] == 'spring25.csv'
        assert 'spring25.csv' in rep['text']
        assert '/tmp' not in rep['text']

    def test_unparseable_yaml_is_a_message(self, csv_text):
        rep = web.check_config(csv_text, 'category:\n\tweight: 1\n')

        assert not rep['ok']
        assert rep['error_list']

    def test_agrees_with_build_report(self, csv_text, f_scope_std):
        """ the page must show what `check` shows """
        from gradescope_mean.check import build_report

        rep_web = web.check_config(csv_text, YAML_STD)
        rep_cli = build_report(Config(cat_weight_dict={'hw': 50, 'quiz': 50}),
                               str(f_scope_std))

        assert rep_web['ok'] == rep_cli.ok
        assert [c['ass_list'] for c in rep_web['cat_list']] == \
            [c.ass_list for c in rep_cli.cat_list]


class TestGrade:
    def test_returns_a_csv(self, csv_text):
        res = web.grade(csv_text, YAML_STD)

        assert res['ok']
        assert res['csv'].startswith('email,')
        assert res['n_student'] == 3

    def test_is_plain_data(self, csv_text):
        assert is_plain(web.grade(csv_text, YAML_STD))

    def test_agrees_with_the_command_line(self, csv_text, f_scope_std):
        """ the whole claim of the browser build, in one assertion """
        res = web.grade(csv_text, YAML_STD)

        config = Config(cat_weight_dict={'hw': 50, 'quiz': 50})
        gradebook, df_grade = config(str(f_scope_std))

        assert res['csv'] == df_grade.to_csv()

    def test_letters_are_ordered_by_grade(self, csv_text):
        res = web.grade(csv_text, YAML_STD)

        from gradescope_mean.perc_to_letter import GRADE_THRESH
        order_list = [ltr for _, ltr in sorted(GRADE_THRESH.items(),
                                               reverse=True)]
        got_list = [l['letter'] for l in res['letter_list']]
        assert got_list == [ltr for ltr in order_list if ltr in got_list]

    def test_config_error_is_a_message(self, csv_text):
        res = web.grade(csv_text, 'category:\n  weight:\n    exam: 100\n')

        assert not res['ok']
        assert 'exam' in res['error']

    def test_distribution_matches_the_students(self, csv_text):
        res = web.grade(csv_text, YAML_STD)

        assert sum(l['n'] for l in res['letter_list']) == res['n_student']
        assert len(res['mean_list']) == res['n_student']


class TestSeed:
    def test_seeds_from_the_csv(self, csv_text):
        text = web.seed_config(csv_text, 'scope.csv')

        assert 'quiz1' in text
        assert 'scope.csv' in text

    def test_bad_csv_still_yields_an_editable_config(self):
        text = web.seed_config('not,a,gradebook\n1,2,3\n')

        assert text == web.default_yaml()

    def test_seeded_config_checks_clean(self, csv_text):
        """ what the page puts in the editor must not start out broken """
        rep = web.check_config(csv_text, web.seed_config(csv_text))

        assert rep['ok']


class TestNoStrayFiles:
    def test_nothing_is_left_behind(self, csv_text, tmp_path, monkeypatch):
        """ a browser has no filesystem to litter, but a temp dir still does

        (compared before and after: the scope csv fixture lives here too)
        """
        monkeypatch.chdir(tmp_path)
        before_set = set(pathlib.Path(tmp_path).iterdir())

        web.load_csv(csv_text)
        web.check_config(csv_text, YAML_STD)
        web.grade(csv_text, YAML_STD)
        web.seed_config(csv_text)

        assert set(pathlib.Path(tmp_path).iterdir()) == before_set

    def test_temp_dir_is_cleaned_up(self, csv_text):
        """ every call makes one, and every call has to remove it """
        import tempfile

        folder = pathlib.Path(tempfile.gettempdir())
        before_set = set(folder.iterdir())

        for _ in range(3):
            web.grade(csv_text, YAML_STD)

        assert set(folder.iterdir()) == before_set
