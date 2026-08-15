import pytest

from finalgrade.perc_to_letter import *

GRADE_THRESH_UNORDERED = {.00: 'E',
                          .93: 'A',
                          .90: 'A-',
                          .87: 'B+',
                          .83: 'B',
                          .80: 'B-',
                          .77: 'C+',
                          .73: 'C',
                          .70: 'C-',
                          .67: 'D+',
                          .63: 'D',
                          .60: 'D-'}


class TestPercToLetter:
    def test_basic_values(self):
        val_letter_list = [(1, 'A'), (.9, 'A-'), (.91, 'A-'), (.6, 'D-'),
                           (np.nan, 'no-grade')]

        for val, letter_exp in val_letter_list:
            letter = perc_to_letter(val)
            assert letter == letter_exp, f'error in perc_to_letter: {val}'

            letter = perc_to_letter(val, grade_thresh=GRADE_THRESH_UNORDERED)
            assert letter == letter_exp, f'error in perc_to_letter: {val}'

    def test_exact_boundary_a(self):
        assert perc_to_letter(.93) == 'A'

    def test_just_below_a(self):
        assert perc_to_letter(.9299) == 'A-'

    def test_exact_boundary_b_plus(self):
        assert perc_to_letter(.87) == 'B+'

    def test_zero_score(self):
        assert perc_to_letter(0.0) == 'E'

    def test_perfect_score(self):
        assert perc_to_letter(1.0) == 'A'

    def test_above_100_percent(self):
        # extra credit scenario
        assert perc_to_letter(1.05) == 'A'

    def test_nan_returns_custom_letter(self):
        assert perc_to_letter(np.nan, nan_letter='N/A') == 'N/A'

    def test_negative_raises(self):
        with pytest.raises(ValueError):
            perc_to_letter(-0.1)

    def test_custom_thresholds(self):
        custom = {.5: 'pass', .0: 'fail'}
        assert perc_to_letter(.75, grade_thresh=custom) == 'pass'
        assert perc_to_letter(.3, grade_thresh=custom) == 'fail'

    def test_all_grade_letters(self):
        """Verify every standard letter grade is reachable"""
        expected = [
            (.95, 'A'), (.91, 'A-'), (.88, 'B+'), (.85, 'B'),
            (.81, 'B-'), (.78, 'C+'), (.74, 'C'), (.71, 'C-'),
            (.68, 'D+'), (.64, 'D'), (.61, 'D-'), (.01, 'E'),
        ]
        for perc, letter in expected:
            assert perc_to_letter(perc) == letter, f'{perc} -> {letter}'
