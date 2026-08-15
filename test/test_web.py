""" the api the browser build calls

These run in cpython, not in a browser: what they protect is the contract the
page depends on -- that every value crossing into javascript is plain data,
and that the browser's answer is the command line's answer.  Whether pyodide
can load the wheel is a question for the build, not for pytest.
"""
import json
import pathlib

import pytest

from finalgrade import web
from finalgrade.config import Config


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
        from finalgrade.check import build_report

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

        from finalgrade.perc_to_letter import GRADE_THRESH
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


class TestRoster:
    def test_every_student_is_listed(self, csv_text):
        info = web.load_csv(csv_text)

        assert [s['email'] for s in info['student_list']] == \
            ['alice@u.edu', 'bob@u.edu', 'carol@u.edu']

    def test_names_come_along_for_searching(self, csv_text):
        info = web.load_csv(csv_text)

        alice = info['student_list'][0]
        assert alice['first'] == 'alice'
        assert alice['last'] == 'anders'


class TestFormState:
    def test_reads_the_categories(self, csv_text):
        state = web.form_state(YAML_STD)

        assert [(c['name'], c['weight'], c['weight_frac'])
                for c in state['cat_list']] == \
            [('hw', 50, .5), ('quiz', 50, .5)]

    def test_reads_drops_and_late(self):
        state = web.form_state(
            'category:\n  weight:\n    hw: 1\n  drop_low:\n    hw: 2\n'
            '  late_penalty:\n    hw:\n      penalty_per_day: .15\n')

        cat = state['cat_list'][0]
        assert cat['drop_low'] == 2
        assert cat['late'] == {'penalty_per_day': .15}

    def test_reads_waivers_of_both_kinds(self):
        state = web.form_state('waive:\n  a@u.edu: hw1, hw2\n'
                               'waive_late:\n  b@u.edu: hw3\n')

        assert state['waive_list'] == [
            dict(email='a@u.edu', ass_list=['hw1', 'hw2'])]
        assert state['waive_late_list'] == [
            dict(email='b@u.edu', ass_list=['hw3'])]

    def test_a_yaml_list_of_waivers_reads_the_same(self):
        """ the readme's comma form and a real list must look alike here """
        state = web.form_state('waive:\n  a@u.edu:\n    - hw1\n    - hw2\n')

        assert state['waive_list'][0]['ass_list'] == ['hw1', 'hw2']

    def test_is_plain_data(self, csv_text):
        assert is_plain(web.form_state(web.seed_config(csv_text)))

    def test_half_typed_yaml_says_so_rather_than_raising(self):
        state = web.form_state('category:\n\tweight: 1\n')

        assert not state['ok']
        assert state['error']

    def test_empty_config_is_empty_not_broken(self):
        state = web.form_state('')

        assert state['ok']
        assert state['cat_list'] == []


class TestEditConfig:
    def test_applies_an_edit(self):
        res = web.edit_config('', 'add_category', '{"cat": "hw"}')

        assert res['ok']
        assert 'hw' in res['yaml']

    def test_keeps_the_file_when_an_edit_cannot_apply(self):
        text = 'category:\n\tweight: 1\n'
        res = web.edit_config(text, 'add_category', '{"cat": "hw"}')

        assert not res['ok']
        assert res['yaml'] == text

    def test_unknown_action(self):
        res = web.edit_config('', 'drop_everything', '{}')

        assert not res['ok']

    def test_bad_json_is_a_message(self):
        res = web.edit_config('', 'add_category', 'not json')

        assert not res['ok']
        assert res['yaml'] == ''

    def test_a_policy_built_only_by_edits_grades(self, csv_text, f_scope_std):
        """ end to end: what the widgets produce is what grading reads """
        yaml_text = web.seed_config(csv_text)
        for action, args in (
                ('add_category', '{"cat": "hw"}'),
                ('add_category', '{"cat": "quiz"}'),
                ('set_drop_low', '{"cat": "hw", "n": 1}'),
                ('set_waive', '{"email": "alice@u.edu",'
                              ' "ass_list": ["hw1"]}')):
            res = web.edit_config(yaml_text, action, args)
            assert res['ok'], res['error']
            yaml_text = res['yaml']

        assert web.check_config(csv_text, yaml_text)['ok']

        result = web.grade(csv_text, yaml_text)
        assert result['ok']
        assert result['n_student'] == 3

        # the waiver the widget wrote is the waiver grading applied
        state = web.form_state(yaml_text)
        assert state['waive_list'] == [
            dict(email='alice@u.edu', ass_list=['hw1'])]


class TestStudentCsv:
    """ the file --per_student writes, for one student, on demand """

    def test_holds_the_whole_row(self, csv_text):
        res = web.student_csv(csv_text, YAML_STD, 'alice@u.edu')

        assert res['ok'], res.get('error')
        assert 'mean_hw' in res['csv']
        assert 'hw1' in res['csv']
        assert 'letter' in res['csv']

    def test_it_is_that_student_and_no_other(self, csv_text):
        res = web.student_csv(csv_text, YAML_STD, 'alice@u.edu')

        assert 'alice@u.edu' in res['csv']
        assert 'bob@u.edu' not in res['csv']

    def test_named_after_the_student(self, csv_text):
        res = web.student_csv(csv_text, YAML_STD, 'alice@u.edu')

        assert res['filename'] == 'anders_alice.csv'

    def test_matches_what_the_cli_writes(self, csv_text, f_scope_std,
                                         tmp_path):
        """ same file, so an emailed breakdown cannot disagree with a run """
        import pandas as pd

        from finalgrade.__main__ import main, parser

        config = Config(cat_weight_dict={'hw': 50, 'quiz': 50})
        _, df_grade = config(str(f_scope_std))
        f_config = tmp_path / 'config.yaml'
        f_config.write_text(YAML_STD)

        main(parser.parse_args(['grade', str(f_scope_std), '--config',
                                str(f_config), '--per_student', '-q']))

        f_cli = f_scope_std.parent / 'per_student' / 'anders_alice.csv'
        res = web.student_csv(csv_text, YAML_STD, 'alice@u.edu')

        assert res['csv'] == f_cli.read_text()
        assert 'alice' in pd.read_csv(f_cli).columns[1]

    def test_an_unknown_student(self, csv_text):
        res = web.student_csv(csv_text, YAML_STD, 'nobody@u.edu')

        assert not res['ok']
        assert 'nobody@u.edu' in res['error']

    def test_a_broken_config_is_a_message(self, csv_text):
        res = web.student_csv(csv_text, 'category:\n  weight:\n    no: 1\n',
                              'alice@u.edu')

        assert not res['ok']

    def test_is_plain_data(self, csv_text):
        assert is_plain(web.student_csv(csv_text, YAML_STD, 'alice@u.edu'))


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
