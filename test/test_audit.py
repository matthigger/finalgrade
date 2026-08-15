""" the record of how one grade was arrived at

A final grade is one number standing in for a dozen decisions.  What these
protect is that each decision that moved the number says so, and that no
decision claims to have happened when it didn't.
"""
import warnings

import pytest

from finalgrade import web
from finalgrade.audit import fmt_late
from finalgrade.policy import Policy

YAML_FULL = """\
category:
  weight:
    hw: 75
    quiz: 25
  drop_low:
    hw: 1
  late_penalty:
    hw:
      penalty_per_day: .2
      excuse_day: 1
waive:
  carol@u.edu: hw3
"""


@pytest.fixture
def graded(f_scope_std):
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        return web.grade(f_scope_std.read_text(), YAML_FULL)


def log_of(graded, email):
    stud = next(s for s in graded['student_list'] if s['email'] == email)
    return stud['log_list']


def kinds(log):
    return [e['kind'] for e in log]


class TestWhatHappened:
    def test_a_waiver_is_recorded(self, graded):
        log = log_of(graded, 'carol@u.edu')

        assert any(e['kind'] == 'waive' and 'hw3' in e['text'] for e in log)

    def test_lateness_is_recorded_in_hours_and_minutes(self, graded):
        """ '1 late day' hides whether that was a minute or a day """
        log = log_of(graded, 'bob@u.edu')

        late = [e for e in log if e['kind'] == 'late']
        assert late
        assert any('hw1' in e['text'] and 'h' in e['text'] for e in late)

    def test_the_penalty_shows_its_arithmetic(self, graded):
        log = log_of(graded, 'carol@u.edu')

        hit = next(e for e in log if e['kind'] == 'penalty')
        # carol is 3 days late across hw, 1 excused, so 2 are charged
        assert 'excused' in hit['text']

    def test_the_dropped_assignment_is_named(self, graded):
        """ which one was dropped is different for every student """
        log = log_of(graded, 'alice@u.edu')

        drop = next(e for e in log if e['kind'] == 'drop')
        assert 'hw3' in drop['text']

    def test_each_category_reports_its_share(self, graded):
        log = log_of(graded, 'alice@u.edu')

        cat = [e['text'] for e in log if e['kind'] == 'category']
        assert any('hw' in t and '75%' in t for t in cat)
        assert any('quiz' in t and '25%' in t for t in cat)

    def test_the_final_grade_comes_last(self, graded):
        log = log_of(graded, 'alice@u.edu')

        assert kinds(log)[-1] == 'final'
        assert 'final grade' in log[-1]['text']

    def test_lateness_with_no_penalty_is_not_an_event(self, f_scope_std):
        """ bob is late on hw1, but if hw carries no penalty it changed
        nothing, and a log of what moved a grade should not list it """
        res = web.grade(f_scope_std.read_text(),
                        'category:\n  weight:\n    hw: 75\n    quiz: 25\n')

        log = log_of(res, 'bob@u.edu')
        assert not [e for e in log if e['kind'] in ('late', 'penalty')]

    def test_only_the_penalised_category_is_listed(self, f_scope_std):
        """ quiz lateness is trivia when only hw is penalised """
        res = web.grade(
            f_scope_std.read_text(),
            'category:\n  weight:\n    hw: 75\n    quiz: 25\n'
            '  late_penalty:\n    quiz:\n      penalty_per_day: .1\n')

        log = log_of(res, 'bob@u.edu')
        assert not [e for e in log
                    if e['kind'] == 'late' and 'hw' in e['text']]

    def test_a_student_with_nothing_unusual_still_gets_a_log(self, graded):
        log = log_of(graded, 'alice@u.edu')

        assert kinds(log).count('final') == 1

    def test_it_is_plain_data(self, graded):
        import json
        json.dumps(graded['student_list'])


class TestFmtLate:
    def test_days_hours_minutes(self):
        assert fmt_late(2 * 1440 + 3 * 60 + 7) == '2d 3h 7m'

    def test_hours_only(self):
        assert fmt_late(180) == '3h'

    def test_minutes_only(self):
        assert fmt_late(45) == '45m'

    def test_nothing_is_still_a_duration(self):
        assert fmt_late(0) == '0m'


class TestStudentSubstitution:
    def test_it_takes_the_better_of_the_two(self, f_scope_std):
        """ alice has hw1 100% and hw3 60%; hw3 may take hw1's score """
        policy = Policy(stud_sub_dict={'alice@u.edu': {'hw3': ['hw1']}})
        gradebook, _ = policy(str(f_scope_std))

        assert gradebook.df_perc.at['alice@u.edu', 'hw3'] == 1

    def test_it_touches_nobody_else(self, f_scope_std):
        policy = Policy(stud_sub_dict={'alice@u.edu': {'hw3': ['hw1']}})
        gradebook, _ = policy(str(f_scope_std))

        assert gradebook.df_perc.at['bob@u.edu', 'hw3'] == 1.0
        assert gradebook.df_perc.at['carol@u.edu', 'hw3'] == .6

    def test_it_is_recorded_in_the_log(self, f_scope_std):
        res = web.grade(f_scope_std.read_text(),
                        'substitute_student:\n'
                        '  alice@u.edu:\n    hw3: hw1\n')

        log = log_of(res, 'alice@u.edu')
        sub = next(e for e in log if e['kind'] == 'substitute')
        assert 'hw3' in sub['text'] and 'hw1' in sub['text']

    def test_a_substitution_that_changes_nothing_is_not_an_event(
            self, f_scope_std):
        """ naming the winner of a tie reads as a decision nobody made """
        res = web.grade(f_scope_std.read_text(),
                        'substitute_student:\n'
                        '  alice@u.edu:\n    hw1: hw3\n')

        log = log_of(res, 'alice@u.edu')
        assert not [e for e in log if e['kind'] == 'substitute']

    def test_a_typo_in_the_student_is_refused(self, f_scope_std):
        from finalgrade.errors import PolicyError

        policy = Policy(stud_sub_dict={'alicce@u.edu': {'hw3': ['hw1']}})
        with pytest.raises(PolicyError, match='alicce'):
            policy(str(f_scope_std))

    def test_through_the_browser_edit(self, f_scope_std):
        res = web.edit_policy('', 'set_student_sub',
                              '{"email": "alice@u.edu", "target": "hw3",'
                              ' "ass_list": ["hw1"]}')

        assert res['ok']
        assert 'substitute_student' in res['yaml']
        assert 'hw3: hw1' in res['yaml']
