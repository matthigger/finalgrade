""" drop_low: the worst n scores go, but never the last one standing

A whole term's policy is written in one sitting, so drop_low routinely names
more assignments than are graded yet -- drop 3 of 10 hw, run in week 4 with
3 of them in.  Taking all three would leave the category with no mean at
all, which is not a low grade but no grade: average() reads it as a student
with no homework and hands the category's weight to whatever else is
weighted, so a 40% hw and a 100% quiz come out an A.

So the floor: the highest score survives whatever drop_low says, and the
category is warned about, since keeping one score is not the rule that was
written.  It also keeps drop_low monotone -- a larger drop_low can never
grade lower than a smaller one -- and lands it on keep_high: 1, which is the
same rule said outright.
"""
import numpy as np
import pytest

from conftest import write_scope
from finalgrade.audit import build_log
from finalgrade.check import build_report
from finalgrade.gradebook import rule_warn_list
from finalgrade.policy import Policy

# one hw and one quiz, so a hw category that vanishes leaves the quiz to
# carry the whole grade
ASSIGN_ONE = {'HW1': 10, 'Quiz1': 10}
STUDENT_ONE = [
    {'email': 'alice@u.edu', 'first': 'alice', 'last': 'anders',
     'sid': '001S', 'scores': {'HW1': 4, 'Quiz1': 10}},
]


@pytest.fixture
def f_scope_one(tmp_path):
    return write_scope(tmp_path / 'scope.csv', ASSIGN_ONE, STUDENT_ONE)


def policy_one(**kwargs):
    return Policy(cat_weight_dict={'hw': 50, 'quiz': 50},
                  cat_drop_dict={'hw': 1}, **kwargs)


class TestTheCategoryKeepsItsMean:
    def test_the_only_hw_is_not_dropped(self, f_scope_one):
        with pytest.warns(UserWarning, match='drop_low'):
            _, df = policy_one()(str(f_scope_one))

        assert df.loc['alice@u.edu', 'mean_hw'] == pytest.approx(.4)

    def test_the_grade_still_counts_the_hw(self, f_scope_one):
        """ the bug this floor is for: hw's weight went to the quiz """
        with pytest.warns(UserWarning):
            _, df = policy_one()(str(f_scope_one))

        row = df.loc['alice@u.edu']
        assert row['mean'] == pytest.approx(.7)
        assert row['letter'] == 'C-'

    def test_a_wholly_waived_category_still_has_no_mean(self, f_scope_one):
        """ the floor is about dropping, and a waiver is not a drop

        Nothing was assigned, so there is nothing to keep and the category
        genuinely has no mean -- the one case where handing its weight to
        the others is right.
        """
        with pytest.warns(UserWarning):
            _, df = policy_one(waive_dict={'alice@u.edu': ['hw1']})(
                str(f_scope_one))

        row = df.loc['alice@u.edu']
        assert np.isnan(row['mean_hw'])
        assert row['mean'] == pytest.approx(1.)


class TestItWarns:
    def test_grading_says_so(self, f_scope_one):
        with pytest.warns(UserWarning) as record:
            policy_one()(str(f_scope_one))

        said = [s for s in (str(w.message) for w in record)
                if 'drop_low' in s]
        assert said
        assert 'keeps their highest score' in said[0]
        assert 'keep_high: 1' in said[0]

    def test_check_says_so_before_grading(self, f_scope_one):
        report = build_report(policy_one(), str(f_scope_one))

        assert any('drop_low' in s for s in report.warn_list)
        # a floored drop_low still grades, so it is not an error
        assert report.ok

    def test_check_and_grading_word_it_identically(self, f_scope_one):
        """ the page shows both, where two spellings read as two problems """
        policy = policy_one()

        with pytest.warns(UserWarning) as record:
            policy(str(f_scope_one))
        said_list = [str(w.message) for w in record]

        rule_list = [s for s in build_report(policy, str(f_scope_one))
                     .warn_list if 'drop_low' in s]
        assert rule_list
        for text in rule_list:
            assert text in said_list

    def test_a_drop_the_category_can_hold_says_nothing(self):
        assert not rule_warn_list('hw', ['hw1', 'hw2', 'hw3'],
                                  [False] * 3, drop_n=2)

    def test_the_message_names_the_counts(self):
        warn_list = rule_warn_list('hw', ['hw1', 'hw2'], [False] * 2,
                                   drop_n=2)

        assert len(warn_list) == 1
        assert 'drop_low is 2' in warn_list[0]
        assert 'hw holds 2' in warn_list[0]

    def test_extra_credit_is_not_one_of_the_droppable(self):
        """ it is never dropped, so it cannot make the drop fit either """
        warn_list = rule_warn_list('hw', ['hw1', 'bonus'], [False, True],
                                   drop_n=1)

        assert len(warn_list) == 1
        assert 'drop_low is 1' in warn_list[0]

    def test_an_all_extra_category_is_left_to_its_own_complaint(self):
        """ average() already warns that it has no mean to raise, and one
        problem gets one warning """
        assert not rule_warn_list('bonus', ['bonus1'], [True], drop_n=1)


class TestTheLogExplainsIt:
    def test_the_undropped_drop_is_accounted_for(self, tmp_path):
        """ a student counting the drops comes up one short, and is owed why
        """
        f = write_scope(tmp_path / 'scope.csv',
                        {'HW1': 10, 'HW2': 10, 'HW3': 10},
                        [{'email': 'a@u.edu', 'scores': {'HW1': 10, 'HW2': 8,
                                                         'HW3': 0}}])
        policy = Policy(cat_weight_dict={'hw': 1}, cat_drop_dict={'hw': 3})

        with pytest.warns(UserWarning):
            gradebook, df = policy(str(f))
        log = build_log(gradebook, policy, df)

        drop = next(e for e in log['a@u.edu'] if e['kind'] == 'drop')
        assert 'hw3' in drop['text'] and 'hw2' in drop['text']
        assert 'drop_low is 3' in drop['text']
        assert 'highest score is kept' in drop['text']

        # and the grade is that highest score
        assert df.loc['a@u.edu', 'mean_hw'] == pytest.approx(1.)

    def test_a_drop_that_fits_explains_nothing_extra(self, tmp_path):
        f = write_scope(tmp_path / 'scope.csv',
                        {'HW1': 10, 'HW2': 10, 'HW3': 10},
                        [{'email': 'a@u.edu', 'scores': {'HW1': 10, 'HW2': 8,
                                                         'HW3': 0}}])
        policy = Policy(cat_weight_dict={'hw': 1}, cat_drop_dict={'hw': 1})

        gradebook, df = policy(str(f))
        log = build_log(gradebook, policy, df)

        drop = next(e for e in log['a@u.edu'] if e['kind'] == 'drop')
        assert 'drop_low is' not in drop['text']
