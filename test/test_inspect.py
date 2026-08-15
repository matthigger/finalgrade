""" the numbers behind a grade, and the two versions of every one of them

The raw series exists to answer one question -- what did my drops and late
penalties actually do -- so what these tests protect is that the two series
differ by the policy and by nothing else.
"""
import pytest

from finalgrade import web
from finalgrade.inspect import histogram


@pytest.fixture
def csv_text(f_scope_std):
    return f_scope_std.read_text()


YAML_DROP = """\
category:
  weight:
    hw: 100
  drop_low:
    hw: 1
assignments:
  exclude:
    - quiz
"""

YAML_LATE = """\
category:
  weight:
    hw: 100
  late_penalty:
    hw:
      penalty_per_day: .5
      excuse_day: 0
assignments:
  exclude:
    - quiz
"""


class TestViews:
    def test_one_view_per_thing_worth_plotting(self, csv_text):
        res = web.grade(csv_text, 'category:\n  weight:\n    hw: 50\n'
                                  '    quiz: 50\n')

        assert [v['key'] for v in res['view_list']] == [
            'total', 'cat:hw', 'cat:quiz',
            'ass:hw1', 'ass:hw2', 'ass:hw3', 'ass:quiz1']

    def test_every_series_is_one_value_per_student(self, csv_text):
        res = web.grade(csv_text, YAML_DROP)

        for key, pair in res['value_dict'].items():
            assert len(pair['final']) == res['n_student'], key

    def test_values_line_up_with_the_students(self, csv_text):
        res = web.grade(csv_text, YAML_DROP)

        total = res['value_dict']['total']['final']
        for stud, val in zip(res['student_list'], total):
            assert stud['mean'] == val


class TestRawIsBeforeThePolicy:
    def test_dropping_a_low_score_only_moves_the_final(self, csv_text):
        res = web.grade(csv_text, YAML_DROP)
        pair = res['value_dict']['cat:hw']

        # carol's worst hw is a 0, so dropping it can only help her
        assert pair['final'][2] > pair['raw'][2]

    def test_a_late_penalty_only_lowers_the_final(self, csv_text):
        res = web.grade(csv_text, YAML_LATE)
        pair = res['value_dict']['cat:hw']

        # bob is a day late, carol three; alice is never late
        assert pair['final'][0] == pair['raw'][0]
        assert pair['final'][1] < pair['raw'][1]
        assert pair['final'][2] < pair['raw'][2]

    def test_with_no_policy_the_two_are_identical(self, csv_text):
        res = web.grade(csv_text, 'category:\n  weight:\n    hw: 50\n'
                                  '    quiz: 50\n')

        for key, pair in res['value_dict'].items():
            if pair['raw'] is not None:
                assert pair['final'] == pair['raw'], key

    def test_waivers_are_in_both(self, csv_text):
        """ a waiver says the work was never assigned, which is not an
        adjustment to a score and so belongs on both sides """
        res = web.grade(csv_text, YAML_DROP + 'waive:\n  alice@u.edu: hw1\n')
        pair = res['value_dict']['ass:hw1']

        assert pair['final'][0] is None

    def test_an_assignment_has_no_raw_of_its_own(self, csv_text):
        """ drops and penalties act on a category, so there is nothing to
        compare for one assignment, and the page says so instead of drawing
        two identical bars """
        res = web.grade(csv_text, YAML_DROP)

        assert res['value_dict']['ass:hw1']['raw'] is None


class TestStudentList:
    def test_one_row_per_student_with_their_grade(self, csv_text):
        res = web.grade(csv_text, YAML_DROP)

        alice = res['student_list'][0]
        assert alice['email'] == 'alice@u.edu'
        assert alice['first'] == 'alice'
        assert alice['letter']
        assert 'hw' in alice['cat_dict']
        assert 'hw1' in alice['ass_dict']

    def test_is_plain_data(self, csv_text):
        import json
        json.dumps(web.grade(csv_text, YAML_DROP))


class TestHistogram:
    def test_counts_and_names_line_up(self):
        hist = histogram([0.1, 0.15, 0.95], ['a', 'b', 'c'], n_bin=2)

        assert hist['count_list'] == [2, 1]
        assert hist['who_list'] == [['a', 'b'], ['c']]

    def test_a_perfect_score_is_not_its_own_bin(self):
        """ digitize would otherwise put 1.0 past the last edge """
        hist = histogram([1.0], ['a'], n_bin=4)

        assert hist['count_list'][-1] == 1

    def test_students_with_no_grade_are_left_out(self):
        hist = histogram([0.5, None], ['a', 'b'], n_bin=2)

        assert hist['n'] == 1
        assert sum(hist['count_list']) == 1

    def test_nothing_to_plot(self):
        hist = histogram([None], ['a'], n_bin=4)

        assert hist['count_list'] == []
        assert hist['n'] == 0

    def test_range_covers_zero_to_one_even_for_a_tight_class(self):
        """ a cutoff at 60% has to be visible even if nobody is near it """
        hist = histogram([0.9, 0.92], ['a', 'b'], n_bin=10)

        assert hist['edge_list'][0] == 0
        assert hist['edge_list'][-1] == 1

    def test_it_survives_a_grade_above_one(self):
        """ extra credit happens """
        hist = histogram([1.2], ['a'], n_bin=5)

        assert sum(hist['count_list']) == 1
        assert hist['edge_list'][-1] >= 1.2


class TestBinValues:
    def test_the_browser_entry_point(self):
        import json

        hist = web.bin_values(json.dumps([0.2, 0.9]),
                              json.dumps(['a', 'b']), 2)

        # bins are [0, .5) and [.5, 1]
        assert hist['count_list'] == [1, 1]
        assert hist['who_list'] == [['a'], ['b']]
