"""Property based tests for the grade arithmetic.

get_mean_drop_low is the one piece of real numerical logic in the package;
these check the invariants a grading policy relies on, over inputs no one
would think to enumerate by hand.
"""
import numpy as np
import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from finalgrade.get_mean_drop_low import get_mean_drop_low
from finalgrade.perc_to_letter import GRADE_THRESH, perc_to_letter

# percentages earned, and assignment point values
perc_st = st.floats(min_value=0, max_value=1.5, allow_nan=False,
                    allow_infinity=False, width=32)
weight_st = st.floats(min_value=.5, max_value=1000, allow_nan=False,
                      allow_infinity=False, width=32)


@st.composite
def perc_weight(draw, min_size=1, max_size=12):
    n = draw(st.integers(min_value=min_size, max_value=max_size))
    perc = draw(st.lists(perc_st, min_size=n, max_size=n))
    weight = draw(st.lists(weight_st, min_size=n, max_size=n))
    return np.array(perc), np.array(weight)


class TestGetMeanDropLow:
    @given(pw=perc_weight())
    def test_mean_within_range(self, pw):
        """ a weighted mean can never leave the range of its inputs """
        perc, weight = pw
        mean = get_mean_drop_low(perc, weight)
        assert perc.min() - 1e-6 <= mean <= perc.max() + 1e-6

    @given(pw=perc_weight(min_size=2))
    def test_dropping_never_lowers_the_mean(self, pw):
        """ dropping the lowest score cannot hurt a student

        this is the whole point of the feature, and it holds for any weights:
        the smallest element is always <= the mean, so removing it cannot
        decrease the mean.
        """
        perc, weight = pw
        prev = get_mean_drop_low(perc, weight, drop_n=0)
        for drop_n in range(1, len(perc)):
            mean = get_mean_drop_low(perc, weight, drop_n=drop_n)
            assert mean >= prev - 1e-6, f'drop_n={drop_n} lowered the mean'
            prev = mean

    @given(pw=perc_weight(), data=st.data())
    def test_order_invariant(self, pw, data):
        """ shuffling the assignments cannot change the grade """
        perc, weight = pw
        drop_n = data.draw(st.integers(min_value=0,
                                       max_value=max(len(perc) - 1, 0)))
        idx = data.draw(st.permutations(range(len(perc))))
        idx = list(idx)

        mean = get_mean_drop_low(perc, weight, drop_n=drop_n)
        mean_shuffled = get_mean_drop_low(perc[idx], weight[idx],
                                          drop_n=drop_n)
        assert mean == pytest.approx(mean_shuffled, abs=1e-6)

    @given(pw=perc_weight(), value=perc_st)
    def test_constant_scores_give_that_score(self, pw, value):
        """ if every assignment has the same percentage, so does the mean """
        _, weight = pw
        perc = np.full(len(weight), value)
        assert get_mean_drop_low(perc, weight) == pytest.approx(value,
                                                               abs=1e-6)

    @given(pw=perc_weight())
    def test_dropping_everything_is_nan(self, pw):
        """ no assignments left to average """
        perc, weight = pw
        assert np.isnan(get_mean_drop_low(perc, weight, drop_n=len(perc)))

    @given(pw=perc_weight(min_size=2))
    def test_nan_is_ignored_not_counted(self, pw):
        """ a waived (nan) assignment behaves as if never assigned """
        perc, weight = pw
        mean_without = get_mean_drop_low(perc[1:], weight[1:])

        perc_nan = perc.copy().astype(float)
        perc_nan[0] = np.nan
        mean_with_nan = get_mean_drop_low(perc_nan, weight)

        assert mean_with_nan == pytest.approx(mean_without, abs=1e-6)

    @given(pw=perc_weight(), scale=st.floats(min_value=.5, max_value=100,
                                             allow_nan=False, width=32))
    def test_weights_are_scale_invariant(self, pw, scale):
        """ points are relative: doubling every assignment changes nothing """
        perc, weight = pw
        mean = get_mean_drop_low(perc, weight)
        mean_scaled = get_mean_drop_low(perc, weight * scale)
        assert mean == pytest.approx(mean_scaled, abs=1e-6)


class TestPercToLetter:
    @given(perc=st.floats(min_value=0, max_value=1.5, allow_nan=False,
                          width=32))
    @settings(max_examples=200)
    def test_always_returns_a_letter(self, perc):
        assert perc_to_letter(perc) in set(GRADE_THRESH.values())

    @given(perc_low=st.floats(min_value=0, max_value=1, allow_nan=False,
                              width=32),
           perc_high=st.floats(min_value=0, max_value=1, allow_nan=False,
                               width=32))
    def test_monotone(self, perc_low, perc_high):
        """ a higher percentage never earns a worse letter """
        assume(perc_low < perc_high)
        thresh_list = sorted(GRADE_THRESH)

        def rank(letter):
            for idx, thresh in enumerate(thresh_list):
                if GRADE_THRESH[thresh] == letter:
                    return idx
            raise AssertionError(letter)

        assert rank(perc_to_letter(perc_low)) <= \
            rank(perc_to_letter(perc_high))
