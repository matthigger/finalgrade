""" a score that is not in the grade cannot be late

One rule across waive, drop_low and keep_high: an assignment that is not
part of a student's category mean charges no late days, and is not one of
the assignments a late day is a fraction of.  Being late on work that does
not count costs nothing, because there is nothing for it to cost.

The second half is the easy one to miss.  penalty_per_day is documented as a
fraction of an average assignment, so the divisor has to be the assignments
that count for that student -- not every assignment in the category, some of
which were never theirs.
"""
import numpy as np
import pytest

from conftest import write_scope
from finalgrade.audit import build_log, late_detail
from finalgrade.policy import Policy

# hw1 is handed in five days late and scored badly, so every rule here
# discards it; hw2 and hw3 are on time and good
ASSIGN = {'HW1': 10, 'HW2': 10, 'HW3': 10, 'Quiz1': 10}

STUDENT = [
    dict(email='dana@u.edu', first='dana', last='d', sid='1S',
         scores={'HW1': 2, 'HW2': 9, 'HW3': 9, 'Quiz1': 10},
         late={'HW1': '120:00:00'}),
]

LATE = {'hw': dict(penalty_per_day=.10, excuse_day=0,
                   grace_period_minutes=60)}


@pytest.fixture
def f_scope(tmp_path):
    return write_scope(tmp_path / 'scope.csv', ASSIGN, STUDENT)


def mean_hw(f_scope, **kwargs):
    policy = Policy(cat_weight_dict={'hw': 1, 'quiz': 1}, cat_late_dict=LATE,
                    **kwargs)
    _, df = policy(f_scope)
    return df.loc['dana@u.edu', 'mean_hw']


class TestNotCountedNotCharged:
    def test_a_late_score_that_counts_is_charged(self, f_scope):
        """ the baseline: no rule, so hw1 counts and its 5 days do too """
        # (2 + 9 + 9) / 30 = .6667, less 5 days x 10% over 3 hw = .1667
        assert mean_hw(f_scope) == pytest.approx(2 / 3 - .5 / 3)

    def test_drop_low_takes_the_late_days_with_the_score(self, f_scope):
        # hw1 dropped: 18/20 = .9, and nothing left that was late
        assert mean_hw(f_scope, cat_drop_dict={'hw': 1}) == pytest.approx(.9)

    def test_keep_high_only_charges_what_it_counted(self, f_scope):
        # best 2 are hw2 and hw3: 18/20 = .9, hw1's days are not dana's
        assert mean_hw(f_scope, cat_keep_dict={'hw': 2}) == pytest.approx(.9)

    def test_waive_takes_the_late_days_with_the_score(self, f_scope):
        assert mean_hw(f_scope, waive_dict={'dana@u.edu': ['hw1']}) == \
            pytest.approx(.9)


class TestDivisor:
    def test_a_late_day_is_a_fraction_of_what_counts(self, f_scope):
        """ hw3 waived leaves dana two hw, so a late day is a half of one

        Charging it over all three would make the day cheaper than the
        policy says it is, on the strength of an assignment she was excused
        from.
        """
        got = mean_hw(f_scope, waive_dict={'dana@u.edu': ['hw3']})

        # (2 + 9) / 20 = .55, less 5 days x 10% over the 2 hw left
        assert got == pytest.approx(.55 - .5 / 2)
        # and not over all three
        assert got != pytest.approx(.55 - .5 / 3)

    def test_a_wholly_waived_category_leaves_the_grade_to_the_others(
            self, f_scope):
        """ nothing counts, so there is no hw mean and no late day to
        charge against one -- and the quiz still stands """
        policy = Policy(cat_weight_dict={'hw': 1, 'quiz': 1},
                        cat_late_dict=LATE,
                        waive_dict={'dana@u.edu': ['hw1', 'hw2', 'hw3']})
        _, df = policy(f_scope)
        row = df.loc['dana@u.edu']

        assert np.isnan(row['mean_hw'])
        # her quiz still stands, and is her whole grade
        assert row['mean'] == pytest.approx(1.)


class TestTheLogAgrees:
    def test_the_arithmetic_matches_the_grade(self, f_scope):
        """ late_detail recomputes the penalty, so it has to be told the
        same thing average() was or it explains a number nobody got """
        policy = Policy(cat_weight_dict={'hw': 1, 'quiz': 1},
                        cat_late_dict=LATE, cat_keep_dict={'hw': 2})
        gradebook, df = policy(f_scope)
        detail = late_detail(gradebook, policy)[0]['hw']['dana@u.edu']

        assert detail['penalty'] == pytest.approx(0)
        # spread over the two that counted, not the three in the category
        assert detail['n_ass'] == 2

    def test_uncharged_days_are_not_called_counted(self, f_scope):
        policy = Policy(cat_weight_dict={'hw': 1, 'quiz': 1},
                        cat_late_dict=LATE, cat_drop_dict={'hw': 1})
        gradebook, df = policy(f_scope)
        log = build_log(gradebook, policy, df)

        text = next(e['text'] for e in log['dana@u.edu']
                    if e['kind'] == 'late' and 'hw1' in e['text'])
        assert 'costs no late days' in text
        assert 'counted as' not in text
