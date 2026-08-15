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


class TestWeightTable:
    def test_a_row_per_assignment(self, csv_text):
        res = web.grade(csv_text, 'category:\n  weight:\n    hw: 50\n'
                                  '    quiz: 50\n')

        assert [r['assignment'] for r in res['row_list']] == \
            ['hw1', 'hw2', 'hw3', 'quiz1']

    def test_weight_within_a_category_is_by_points(self, csv_text):
        """ inside a category, average() weights by each assignment's points
        """
        res = web.grade(csv_text, 'category:\n  weight:\n    hw: 50\n'
                                  '    quiz: 50\n')

        row_dict = {r['assignment']: r for r in res['row_list']}
        # the three hw are 10 points each, so each is a third of the category
        assert row_dict['hw1']['weight_in_cat'] == pytest.approx(1 / 3)
        assert row_dict['quiz1']['weight_in_cat'] == 1

    def test_total_weight_sums_to_one(self, csv_text):
        res = web.grade(csv_text, 'category:\n  weight:\n    hw: 70\n'
                                  '    quiz: 30\n')

        total = sum(r['weight_total'] for r in res['row_list'])
        assert total == pytest.approx(1)

    def test_total_weight_follows_the_category(self, csv_text):
        res = web.grade(csv_text, 'category:\n  weight:\n    hw: 70\n'
                                  '    quiz: 30\n')

        row_dict = {r['assignment']: r for r in res['row_list']}
        assert row_dict['quiz1']['weight_total'] == pytest.approx(.3)
        assert row_dict['hw1']['weight_total'] == pytest.approx(.7 / 3)

    def test_with_no_categories_everything_is_weighted_by_points(self,
                                                                 csv_text):
        res = web.grade(csv_text, '')

        total = sum(r['weight_total'] for r in res['row_list'])
        assert total == pytest.approx(1)
        # four assignments of 10 points each
        assert res['row_list'][0]['weight_total'] == pytest.approx(.25)

    def test_mean_ignores_zeros(self, csv_text):
        """ a zero is far more often 'never submitted' than 'earned nothing'
        """
        res = web.grade(csv_text, YAML_DROP)

        row_dict = {r['assignment']: r for r in res['row_list']}
        # hw1: alice 10, bob 10, carol 0 -> the mean of what was scored is 1
        assert row_dict['hw1']['mean_nonzero'] == pytest.approx(1)
        assert row_dict['hw1']['n_complete'] == 2
        assert row_dict['hw1']['n_student'] == 3

    def test_an_assignment_in_no_category_still_appears(self, csv_text):
        res = web.grade(csv_text, 'category:\n  weight:\n    hw: 100\n')

        row_dict = {r['assignment']: r for r in res['row_list']}
        assert row_dict['quiz1']['category'] is None
        assert row_dict['quiz1']['weight_total'] == 0

    def test_is_plain_data(self, csv_text):
        import json
        json.dumps(web.grade(csv_text, YAML_DROP)['row_list'])


class TestCanvasExport:
    def canvas_text(self, tmp_path):
        import sys
        sys.path.insert(0, 'test')
        from test_canvas_read import write_canvas
        import pathlib
        return pathlib.Path(write_canvas(tmp_path / 'canvas.csv')).read_text()

    def test_merges_grades_into_the_canvas_gradebook(self, tmp_path):
        text = self.canvas_text(tmp_path)

        res = web.canvas_export(
            csv_text=text, yaml_text='category:\n  weight:\n    hw: 60\n'
                                     '    exam: 40\n',
            canvas_text=text, name='canvas.csv')

        assert res['ok'], res.get('error')
        assert 'mean' in res['csv'].splitlines()[0]
        assert 'SIS User ID' not in res['csv'] or 'Student' in res['csv']

    def test_scaled_to_100_so_canvas_does_not_round(self, tmp_path):
        text = self.canvas_text(tmp_path)

        res = web.canvas_export(
            csv_text=text, yaml_text='category:\n  weight:\n    hw: 100\n',
            canvas_text=text, name='canvas.csv', scale100=True)

        # alice has 28 of 30 hw points: .9333 -> 93.33, not 0.93
        assert '93.3' in res['csv']

    def test_a_broken_config_is_a_message(self, tmp_path):
        text = self.canvas_text(tmp_path)

        res = web.canvas_export(
            csv_text=text, yaml_text='category:\n  weight:\n    nope: 100\n',
            canvas_text=text, name='canvas.csv')

        assert not res['ok']
        assert 'nope' in res['error']

    def test_a_file_that_is_not_a_canvas_export(self, csv_text, tmp_path):
        res = web.canvas_export(
            csv_text=csv_text, yaml_text='', canvas_text='a,b\n1,2\n',
            name='scope.csv')

        assert not res['ok']
        assert res['error']


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
