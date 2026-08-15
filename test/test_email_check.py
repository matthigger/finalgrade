""" an email the config names but the gradebook doesn't have

This used to be a warning, and worse than a warning: writing to a label that
isn't in the index made pandas *add* the row, so a typo in `waive` invented a
student and silently failed to waive anything for the real one.  Both halves
are covered here.
"""
import warnings

import pytest

from gradescope_mean.config import Config
from gradescope_mean.errors import ConfigError
from gradescope_mean.gradebook import Gradebook


class TestTypoIsAnError:
    def test_waive(self, f_scope_std):
        config = Config(waive_dict={'alicce@u.edu': 'hw1'})

        with pytest.raises(ConfigError, match='alicce'):
            config(str(f_scope_std))

    def test_waive_late(self, f_scope_std):
        config = Config(late_waive_dict={'nobody@elsewhere.edu': 'hw1'})

        with pytest.raises(ConfigError, match='nobody'):
            config(str(f_scope_std))

    def test_excuse_day_offset(self, f_scope_std):
        config = Config(
            cat_weight_dict={'hw': 100},
            cat_late_dict={'hw': {'penalty_per_day': .1,
                                  'excuse_day_offset': {'nope@u.edu': 3}}})

        with pytest.raises(ConfigError, match='nope'):
            config(str(f_scope_std))

    def test_says_where_the_bad_email_is(self, f_scope_std):
        config = Config(waive_dict={'alicce@u.edu': 'hw1'})

        with pytest.raises(ConfigError, match='waive'):
            config(str(f_scope_std))

    def test_suggests_the_student_meant(self, f_scope_std):
        config = Config(waive_dict={'alicce@u.edu': 'hw1'})

        with pytest.raises(ConfigError, match='alice@u.edu'):
            config(str(f_scope_std))

    def test_reports_every_bad_email_at_once(self, f_scope_std):
        config = Config(waive_dict={'nope1@u.edu': 'hw1',
                                    'nope2@u.edu': 'hw2'})

        with pytest.raises(ConfigError) as exc_info:
            config(str(f_scope_std))

        assert 'nope1' in str(exc_info.value)
        assert 'nope2' in str(exc_info.value)


class TestStillAccepted:
    def test_matching_email_prefix(self, f_scope_std):
        """ alice@husky.u.edu must still match alice@u.edu """
        config = Config(waive_dict={'alice@husky.nu.edu': 'hw1'})

        gradebook, df_grade = config(str(f_scope_std))

        assert gradebook.df_perc.loc['alice@u.edu', 'hw1'] != \
            gradebook.df_perc.loc['bob@u.edu', 'hw1']

    def test_student_pruned_by_email_list(self, f_scope_std):
        """ a waiver kept from before the student dropped the course is not
        a typo, and must not block grading everybody else """
        config = Config(email_list=['alice@u.edu', 'bob@u.edu'],
                        waive_dict={'carol@u.edu': 'hw1'})

        gradebook, df_grade = config(str(f_scope_std))

        assert len(df_grade) == 2

    def test_email_list_itself_only_warns(self, f_scope_std):
        """ an enrolled student with no gradescope row is ordinary

        (recorded rather than pytest.warns: prune_email follows up with a
        'maybe its one of these?' warning, which pytest re-emits when it
        doesn't match -- and this suite turns warnings into errors)
        """
        config = Config(email_list=['alice@u.edu', 'never@u.edu'])

        with warnings.catch_warnings(record=True) as warn_list:
            warnings.simplefilter('always')
            gradebook, df_grade = config(str(f_scope_std))

        assert any('never' in str(w.message) for w in warn_list)
        assert len(df_grade) == 1


class TestNoInventedStudent:
    def test_waive_does_not_add_a_row(self, f_scope_std):
        """ the regression: .loc on a missing label enlarges the frame """
        gradebook = Gradebook.from_file(str(f_scope_std))
        n_before = len(gradebook.df_perc)

        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            gradebook.waive({'typo@nowhere.edu': ['hw1']})

        assert len(gradebook.df_perc) == n_before
        assert 'typo@nowhere.edu' not in gradebook.df_perc.index

    def test_late_waive_does_not_add_a_row(self, f_scope_std):
        gradebook = Gradebook.from_file(str(f_scope_std))
        n_before = len(gradebook.df_late_minutes)

        gradebook.get_late_penalty(
            cat='hw', penalty_per_day=.1,
            waive_dict={'typo@nowhere.edu': ['hw1']})

        assert len(gradebook.df_late_minutes) == n_before

    def test_pruned_student_waiver_leaves_the_roster_alone(self, f_scope_std):
        """ end to end: the pruned-student case must not resurrect them """
        config = Config(email_list=['alice@u.edu'],
                        waive_dict={'carol@u.edu': 'hw1'})

        gradebook, df_grade = config(str(f_scope_std))

        assert list(df_grade.index) == ['alice@u.edu']


class TestCheckReportsIt:
    def test_check_shows_the_bad_email(self, f_scope_std):
        from gradescope_mean.check import build_report

        report = build_report(Config(waive_dict={'alicce@u.edu': 'hw1'}),
                              str(f_scope_std))

        assert not report.ok
        assert any('alicce' in s for s in report.error_list)
