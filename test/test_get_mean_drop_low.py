from math import isclose

import pytest

from finalgrade.get_mean_drop_low import *


class TestGetMeanDropLow:
    def test_basic_equal_weight(self):
        assert isclose(get_mean_drop_low([1, .9, .8], [1, 1, 1]), .9)

    def test_zero_weight_ignored(self):
        assert isclose(get_mean_drop_low([1, .9, .8], [1, 0, 0]), 1)

    def test_drop_lowest(self):
        assert isclose(get_mean_drop_low([1, .9, .8], [1, 1, 1], drop_n=1),
                        .95)

    def test_nan_perc_skipped(self):
        assert isclose(get_mean_drop_low([1, .8, np.nan], [1, 1, 1]), .9)

    def test_nan_perc_with_drop(self):
        assert isclose(get_mean_drop_low([1, .8, np.nan], [1, 1, 1],
                                          drop_n=1), 1)

    def test_drop_prefers_low_perc_high_weight(self):
        # two tied at .8; should drop the one with weight=10
        assert isclose(get_mean_drop_low([1, .8, .8], [1, 1, 10], drop_n=1),
                        .9)

    def test_single_assignment(self):
        assert isclose(get_mean_drop_low([.75], [10]), .75)

    def test_single_assignment_dropped(self):
        """ the only score is the best score, so it stays """
        assert isclose(get_mean_drop_low([.75], [10], drop_n=1), .75)

    def test_all_nan(self):
        result = get_mean_drop_low([np.nan, np.nan], [1, 1])
        assert np.isnan(result)

    def test_empty_arrays(self):
        result = get_mean_drop_low([], [])
        assert np.isnan(result)

    def test_drop_n_exceeds_assignments(self):
        assert isclose(get_mean_drop_low([1, .9], [1, 1], drop_n=5), 1)

    def test_a_bigger_drop_never_grades_lower(self):
        """ the floor's reason: drop_low forgives, so more cannot cost more

        Without it drop_n at or past the category is nan, which grades below
        every smaller drop_n and below no rule at all.
        """
        perc, weight = [1., .8, 0.], [10, 10, 10]
        mean_list = [get_mean_drop_low(perc, weight, drop_n=n)
                     for n in range(6)]

        assert mean_list == sorted(mean_list)
        assert [round(m, 2) for m in mean_list] == [.6, .9, 1., 1., 1., 1.]

    def test_the_floor_keeps_the_best_not_the_first(self):
        assert isclose(get_mean_drop_low([.2, .9, .5], [10] * 3, drop_n=3),
                       .9)

    def test_the_floor_counts_only_what_could_be_dropped(self):
        """ a waived score is an absence, so it is not one of the three """
        assert isclose(get_mean_drop_low([.2, .9, np.nan], [10] * 3,
                                         drop_n=3), .9)

    def test_unequal_weights(self):
        # weighted avg: (1*2 + .5*8) / (2+8) = 6/10 = .6
        assert isclose(get_mean_drop_low([1, .5], [2, 8]), .6)

    def test_perfect_scores(self):
        assert isclose(get_mean_drop_low([1, 1, 1], [1, 1, 1]), 1.0)

    def test_zero_scores(self):
        assert isclose(get_mean_drop_low([0, 0, 0], [1, 1, 1]), 0.0)
