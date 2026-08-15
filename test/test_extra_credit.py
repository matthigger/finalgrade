"""Extra credit: points that count towards what a student earned, and not
towards what was available.

Written against the same 3-student fixture the golden pipeline tests use, so
every expected number below can be checked by hand:

          hw1  hw2  hw3  quiz1
alice      10    8    6     10
bob        10   10   10      5
carol       0    6    6      6
"""
import numpy as np
import pytest

from conftest import ASSIGN_STD, STUDENT_STD, write_scope
from finalgrade.get_mean_drop_low import get_drop_idx, get_mean_drop_low
from finalgrade.policy import Policy


class TestArithmetic:
    """ the weighting itself, away from any csv """

    def test_extra_leaves_denominator_alone(self):
        # .8 and .8 out of 1 each, plus a third worth 1 that is extra:
        # (.8 + .8 + 1) / 2
        assert get_mean_drop_low([.8, .8, 1], [1, 1, 1],
                                 extra=[False, False, True]) == 1.3

    def test_no_extra_is_the_plain_mean(self):
        assert get_mean_drop_low([.8, .8, 1], [1, 1, 1]) == pytest.approx(
            (.8 + .8 + 1) / 3)

    def test_can_pass_one_hundred_percent(self):
        # the whole point: extra credit is how a category goes above 100
        assert get_mean_drop_low([1, 1], [1, 1],
                                 extra=[False, True]) == 2.0

    def test_skipping_extra_costs_nothing(self):
        # a zero on extra credit is the same grade as never having been
        # offered it, which is what makes it optional rather than a trap
        assert get_mean_drop_low([.75, 0], [1, 1], extra=[False, True]) == \
            get_mean_drop_low([.75], [1])

    def test_extra_alone_has_no_mean(self):
        # a numerator with nothing to be a fraction of
        assert np.isnan(get_mean_drop_low([1.], [1.], extra=[True]))

    def test_drop_low_never_drops_extra(self):
        # the 0 is extra and the worst score, but dropping it would take the
        # credit away rather than the damage -- there is no damage
        idx_list = get_drop_idx(np.array([.9, .5, 0.]), np.array([1., 1., 1.]),
                                drop_n=1, extra=[False, False, True])
        assert idx_list == [1]

    def test_extra_survives_a_drop(self):
        # .9 kept, .5 dropped, extra 1.0 added: (.9 + 1) / 1
        assert get_mean_drop_low([.9, .5, 1.], [1, 1, 1], drop_n=1,
                                 extra=[False, False, True]) == \
            pytest.approx(1.9)


@pytest.fixture
def f_scope_extra(tmp_path):
    """ the standard fixture plus a 10 point bonus, unevenly attempted """
    assign = dict(ASSIGN_STD, Bonus1=10)
    student_list = [
        dict(s, scores=dict(s['scores'], Bonus1=points))
        for s, points in zip(STUDENT_STD, (10, 0, 5))]
    return write_scope(tmp_path / 'scope.csv', assign, student_list)


class TestThroughThePipeline:
    """ what the setting does to a real gradebook """

    def test_a_category_of_only_extra_credit_warns(self, f_scope_extra):
        # bonus1 is alone in its category, so there is no mean for it to
        # lift and the points land nowhere.  saying so is the whole job:
        # the grades come out exactly as if the bonus had never been offered
        with pytest.warns(UserWarning, match='all extra credit'):
            _, df = Policy(cat_weight_dict={'hw': 1, 'quiz': 1, 'bonus': 1},
                           extra_list=['bonus1'])(f_scope_extra)

        # hw is untouched: 24/30, 30/30, 12/30
        np.testing.assert_allclose([.8, 1., .4], df['mean_hw'])
        assert df['mean_bonus'].isna().all()
        # and a nan category is skipped rather than poisoning the average
        np.testing.assert_allclose([.9, .75, .5], df['mean'])

    def test_extra_inside_a_category(self, tmp_path):
        # a bonus homework, weighted with the rest of the homework
        assign = dict(ASSIGN_STD, HW4=10)
        student_list = [
            dict(s, scores=dict(s['scores'], HW4=points))
            for s, points in zip(STUDENT_STD, (10, 0, 5))]
        f_scope = write_scope(tmp_path / 'scope.csv', assign, student_list)

        _, df = Policy(cat_weight_dict={'hw': 1, 'quiz': 1},
                       extra_list=['hw4'])(f_scope)

        # denominator stays 30 -- hw4's 10 points are not part of what was
        # available -- so alice gets 34/30, bob 30/30, carol 17/30
        np.testing.assert_allclose([34 / 30, 1., 17 / 30], df['mean_hw'])

    def test_without_the_setting_it_is_an_ordinary_assignment(self, tmp_path):
        assign = dict(ASSIGN_STD, HW4=10)
        student_list = [
            dict(s, scores=dict(s['scores'], HW4=points))
            for s, points in zip(STUDENT_STD, (10, 0, 5))]
        f_scope = write_scope(tmp_path / 'scope.csv', assign, student_list)

        _, df = Policy(cat_weight_dict={'hw': 1, 'quiz': 1})(f_scope)
        np.testing.assert_allclose([34 / 40, 30 / 40, 17 / 40], df['mean_hw'])

    def test_name_is_matched_as_a_fragment(self, tmp_path):
        # the same partial matching assignments/exclude uses: `hw4` and `hw`
        # would both catch hw4, and neither has to be spelled in full
        assign = dict(ASSIGN_STD, HW4=10)
        student_list = [
            dict(s, scores=dict(s['scores'], HW4=points))
            for s, points in zip(STUDENT_STD, (10, 0, 5))]
        f_scope = write_scope(tmp_path / 'scope.csv', assign, student_list)

        _, df = Policy(cat_weight_dict={'hw': 1, 'quiz': 1},
                       extra_list=['hw4'])(f_scope)
        np.testing.assert_allclose([34 / 30, 1., 17 / 30], df['mean_hw'])

    def test_drop_low_leaves_extra_credit_alone(self, tmp_path):
        # hw4 is extra and carol's worst score, but drop_low is there to
        # forgive a bad assignment, and an unearned bonus is not one
        assign = dict(ASSIGN_STD, HW4=10)
        student_list = [
            dict(s, scores=dict(s['scores'], HW4=points))
            for s, points in zip(STUDENT_STD, (10, 0, 0))]
        f_scope = write_scope(tmp_path / 'scope.csv', assign, student_list)

        _, df = Policy(cat_weight_dict={'hw': 1, 'quiz': 1},
                       cat_drop_dict={'hw': 1},
                       extra_list=['hw4'])(f_scope)

        # carol drops her hw1 zero, not her hw4 zero: (6 + 6 + 0) / 20
        np.testing.assert_allclose(12 / 20, df.loc['carol@u.edu', 'mean_hw'])


class TestPolicyFile:
    """ the yaml spelling of it """

    def test_read_from_file(self, tmp_path, f_scope_extra):
        f_policy = tmp_path / 'policy.yaml'
        f_policy.write_text("""\
category:
  weight:
    hw: 1
    quiz: 1
    bonus: 1
assignments:
  extra_credit:
    - bonus1
""")
        policy = Policy.from_file(f_policy)
        assert policy.extra_list == ['bonus1']

    def test_empty_section_is_a_list(self, tmp_path):
        f_policy = tmp_path / 'policy.yaml'
        f_policy.write_text("""\
category:
  weight:
    hw: 1
assignments:
  extra_credit:
""")
        assert Policy.from_file(f_policy).extra_list == []

    def test_a_string_is_split(self, tmp_path):
        # `extra_credit: hw4, hw5` is what a hurried instructor writes, and
        # iterating a string would mark every assignment containing an h
        f_policy = tmp_path / 'policy.yaml'
        f_policy.write_text("""\
category:
  weight:
    hw: 1
assignments:
  extra_credit: hw4, hw5
""")
        assert Policy.from_file(f_policy).extra_list == ['hw4', 'hw5']
