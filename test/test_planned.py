""" work that hasn't been set yet, and the difference between kinds of zero

Two things a gradebook used to be unable to say: that an assignment exists
but hasn't happened, and that a zero was earned rather than simply never
handed in.  Both are needed before a policy can be written for a whole term
in one sitting, or a student can be told why their grade is what it is.
"""
import pytest

from finalgrade import web
from finalgrade.errors import PolicyError
from finalgrade.gradebook import Gradebook
from finalgrade.policy import Policy

YAML_PLAN = """\
category:
  weight:
    hw: 100
assignments:
  exclude:
    - quiz
  planned:
    hw9: 10
"""


class TestPlanned:
    def test_it_appears_as_an_assignment(self, f_scope_std):
        gradebook, _ = Policy(cat_weight_dict={'hw': 100},
                              remove_list=['quiz'],
                              plan_dict={'hw9': 10})(str(f_scope_std))

        assert 'hw9' in gradebook.ass_list
        assert gradebook.points['hw9'] == 10

    def test_it_changes_nobody_s_grade(self, f_scope_std):
        """ the whole point: a policy can name it before it has happened """
        plain = Policy(cat_weight_dict={'hw': 100}, remove_list=['quiz'])
        planned = Policy(cat_weight_dict={'hw': 100}, remove_list=['quiz'],
                         plan_dict={'hw9': 10})

        _, df_plain = plain(str(f_scope_std))
        _, df_planned = planned(str(f_scope_std))

        assert list(df_plain['mean']) == list(df_planned['mean'])

    def test_nobody_has_a_score_for_it(self, f_scope_std):
        gradebook, _ = Policy(cat_weight_dict={'hw': 100},
                              remove_list=['quiz'],
                              plan_dict={'hw9': 10})(str(f_scope_std))

        assert gradebook.df_perc['hw9'].isna().all()

    def test_it_lands_in_the_category_it_names(self, f_scope_std):
        """ so it can be weighted now and scored later """
        gradebook, df_grade = Policy(cat_weight_dict={'hw': 100},
                                     remove_list=['quiz'],
                                     plan_dict={'hw9': 10})(str(f_scope_std))

        assert 'mean_hw' in df_grade.columns

    def test_the_real_thing_outranks_the_plan_for_it(self, f_scope_std):
        """ next week the csv has hw1 in it; the plan must not blank it """
        gradebook, _ = Policy(cat_weight_dict={'hw': 100},
                              remove_list=['quiz'],
                              plan_dict={'hw1': 999})(str(f_scope_std))

        assert gradebook.points['hw1'] == 10
        assert not gradebook.df_perc['hw1'].isna().all()

    def test_the_completion_threshold_does_not_eat_it(self, f_scope_std):
        """ 0% submitted is exactly what not-yet-assigned looks like """
        gradebook, _ = Policy(cat_weight_dict={'hw': 100},
                              remove_list=['quiz'],
                              exclude_complete_thresh=.5,
                              plan_dict={'hw9': 10})(str(f_scope_std))

        assert 'hw9' in gradebook.ass_list

    def test_it_needs_points(self):
        with pytest.raises(PolicyError, match='positive max points'):
            Policy(plan_dict={'hw9': 0})

    def test_through_the_browser_api(self, f_scope_std):
        res = web.grade(f_scope_std.read_text(), YAML_PLAN)

        assert res['ok'], res.get('error')
        name_list = [r['assignment'] for r in res['row_list']]
        assert 'hw9' in name_list

    def test_the_student_panel_calls_it_not_set(self, f_scope_std):
        res = web.grade(f_scope_std.read_text(), YAML_PLAN)

        alice = res['student_list'][0]
        hw9 = next(a for a in alice['ass_list'] if a['name'] == 'hw9')
        assert hw9['planned']
        assert hw9['perc'] is None
        assert not hw9['submitted']


class TestPlannedMeansTheGradebookLackedIt:
    """ planned is a fact about the gradebook, not about the policy naming it

    A policy may plan work the export already has -- the posted student
    policy carries the whole term's roster, and dropping a real gradebook
    beside it is a normal thing to do.  Read off the policy, every assignment
    in the course then reads "(planned)" while holding real scores.
    """

    ROSTER_YAML = """\
category:
  weight:
    hw: 100
    quiz: 100
assignments:
  planned:
    hw1: 10
    hw2: 10
    hw3: 10
    quiz1: 10
"""

    def test_a_planned_assignment_the_export_has_is_not_planned(
            self, f_scope_std):
        """ the real thing arrived, so it outranks the plan for it """
        res = web.grade(f_scope_std.read_text(), self.ROSTER_YAML)

        assert res['ok'], res.get('error')
        planned = [r['assignment'] for r in res['row_list'] if r['planned']]
        assert planned == []

    def test_nor_on_a_student_s_own_scores(self, f_scope_std):
        res = web.grade(f_scope_std.read_text(), self.ROSTER_YAML)
        row = res['student_list'][0]

        assert [a['name'] for a in row['ass_list'] if a['planned']] == []

    def test_work_the_export_lacks_is_still_planned(self, f_scope_std):
        """ the other half: a plan for work nobody has set still says so """
        yaml_text = self.ROSTER_YAML + '    hw9: 10\n'
        res = web.grade(f_scope_std.read_text(), yaml_text)

        assert res['ok'], res.get('error')
        planned = [r['assignment'] for r in res['row_list'] if r['planned']]
        assert planned == ['hw9']

    def test_the_gradebook_records_what_it_planted(self, f_scope_std,
                                                   write_policy):
        """ where the answer now comes from: the gradebook, not the policy """
        import warnings

        policy = Policy.from_file(
            write_policy(self.ROSTER_YAML + '    hw9: 10\n', 'roster.yaml'))

        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            gradebook, _ = policy(str(f_scope_std))

        # four of the five were already in the export; only hw9 was planted
        assert sorted(gradebook.planned_list) == ['hw9']
        assert 'hw9' in gradebook.ass_list


class TestSubmittedVersusZero:
    def test_a_blank_is_not_a_submission(self, tmp_path):
        from conftest import write_scope

        f_scope = write_scope(tmp_path / 'scope.csv', {'HW1': 10}, [
            {'email': 'a@u.edu', 'scores': {}},
            {'email': 'b@u.edu', 'scores': {'HW1': 0}}])

        gradebook = Gradebook.from_file(str(f_scope))

        assert not gradebook.df_submit.at['a@u.edu', 'hw1']
        assert gradebook.df_submit.at['b@u.edu', 'hw1']

    def test_both_still_count_as_zero(self, tmp_path):
        """ the distinction is for the reader, not for the arithmetic """
        from conftest import write_scope

        f_scope = write_scope(tmp_path / 'scope.csv', {'HW1': 10}, [
            {'email': 'a@u.edu', 'scores': {}},
            {'email': 'b@u.edu', 'scores': {'HW1': 0}}])

        gradebook = Gradebook.from_file(str(f_scope))

        assert gradebook.df_perc.at['a@u.edu', 'hw1'] == 0
        assert gradebook.df_perc.at['b@u.edu', 'hw1'] == 0

    def test_the_student_panel_tells_them_apart(self, tmp_path):
        from conftest import write_scope

        f_scope = write_scope(tmp_path / 'scope.csv', {'HW1': 10}, [
            {'email': 'a@u.edu', 'scores': {}},
            {'email': 'b@u.edu', 'scores': {'HW1': 0}}])

        res = web.grade(f_scope.read_text(), '')

        by_email = {s['email']: s for s in res['student_list']}
        never = next(a for a in by_email['a@u.edu']['ass_list']
                     if a['name'] == 'hw1')
        earned = next(a for a in by_email['b@u.edu']['ass_list']
                      if a['name'] == 'hw1')

        assert not never['submitted'] and never['perc'] == 0
        assert earned['submitted'] and earned['perc'] == 0

    def test_the_example_has_both(self):
        """ the demo has to show the distinction it claims to make """
        import pathlib

        import finalgrade
        f = pathlib.Path(finalgrade.__file__).parents[1] / 'web/ex_gradescope.csv'
        res = web.grade(f.read_text(), '')

        flat = [a for s in res['student_list'] for a in s['ass_list']]
        assert any(not a['submitted'] for a in flat)
        assert any(a['submitted'] and a['perc'] == 0 for a in flat)
