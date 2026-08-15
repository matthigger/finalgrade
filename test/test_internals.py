"""Unit tests for the refactored internals.

These are deliberately narrow: they pin the structural invariants that the
end-to-end tests rely on but cannot see.
"""
import dataclasses

import numpy as np
import pandas as pd
import pytest

from conftest import ASSIGN_STD, STUDENT_STD, write_scope
from finalgrade.assign_list import AssignmentList
from finalgrade.config import YAML_KEY_DICT, Config
from finalgrade.errors import (ConfigError, GradebookError,
                                    GradescopeMeanError)
from finalgrade.gradebook import (GRACE_DEFAULT, Gradebook,
                                       minutes_to_days)


@pytest.fixture
def gradebook(tmp_path):
    return Gradebook(str(write_scope(tmp_path / 'scope.csv', ASSIGN_STD,
                                     STUDENT_STD)))


class TestSingleSourceOfTruth:
    """ derived state must always follow its source, with no bookkeeping """

    def test_ass_list_follows_df_perc(self, gradebook):
        assert list(gradebook.ass_list) == list(gradebook.df_perc.columns)

        gradebook.df_perc = gradebook.df_perc.drop(columns=['hw1'])
        assert 'hw1' not in gradebook.ass_list

    def test_points_indexed_by_name(self, gradebook):
        assert isinstance(gradebook.points, pd.Series)
        assert set(gradebook.points.index) == set(gradebook.ass_list)
        assert gradebook.points['hw1'] == 10

    def test_remove_keeps_everything_in_step(self, gradebook):
        gradebook.remove('hw1')
        for name, container in (
                ('ass_list', gradebook.ass_list),
                ('df_perc', gradebook.df_perc.columns),
                ('df_late_minutes', gradebook.df_late_minutes.columns),
                ('df_lateday', gradebook.df_lateday.columns),
                ('points', gradebook.points.index)):
            assert 'hw1' not in container, name

    def test_prune_keeps_everything_in_step(self, gradebook):
        gradebook.prune_email(['alice@u.edu'])
        assert len(gradebook.df_perc) == 1
        assert len(gradebook.df_meta) == 1
        assert len(gradebook.df_late_minutes) == 1
        assert len(gradebook.df_lateday) == 1

    def test_waive_nulls_the_source_so_lateness_follows(self, gradebook):
        assert gradebook.df_lateday.loc['carol@u.edu', 'hw1'] == 2

        gradebook.waive({'carol@u.edu': ['hw1']})

        assert np.isnan(gradebook.df_perc.loc['carol@u.edu', 'hw1'])
        assert np.isnan(gradebook.df_late_minutes.loc['carol@u.edu', 'hw1'])
        # derived, so it cannot disagree with the source
        assert np.isnan(gradebook.df_lateday.loc['carol@u.edu', 'hw1'])


class TestLateDay:
    def test_minutes_to_days_grace(self):
        assert minutes_to_days(0) == 0
        assert minutes_to_days(59) == 0
        assert minutes_to_days(60) == 0
        assert minutes_to_days(61) == 1
        # 49h with 60min grace is 2 days, not 3 (issue #16)
        assert minutes_to_days(49 * 60) == 2

    def test_minutes_to_days_preserves_nan(self):
        assert np.isnan(minutes_to_days(np.nan))

    def test_zero_grace(self):
        assert minutes_to_days(1, grace_period_minutes=0) == 1

    def test_get_lateday_per_category_grace(self, gradebook):
        """ each category uses its own grace period """
        # bob is exactly 24h late on hw1
        assert gradebook.get_lateday()['hw1']['bob@u.edu'] == 1

        df = gradebook.get_lateday(cat_late_dict={
            'hw': {'penalty_per_day': .1, 'grace_period_minutes': 25 * 60}})
        assert df['hw1']['bob@u.edu'] == 0
        # quiz has no late_penalty entry, so it keeps the default grace
        assert df['quiz1']['alice@u.edu'] == 0

    def test_df_lateday_is_derived_not_stored(self, gradebook):
        assert 'df_lateday' not in vars(gradebook)
        assert gradebook.df_lateday.equals(
            gradebook.get_lateday(GRACE_DEFAULT))


class TestEmailResolution:
    def test_email_by_prefix(self, gradebook):
        assert gradebook.email_by_prefix['alice'] == 'alice@u.edu'

    def test_resolve_exact(self, gradebook):
        assert gradebook._resolve_email('alice@u.edu') == 'alice@u.edu'

    def test_resolve_by_prefix(self, gradebook):
        assert gradebook._resolve_email('alice@other.edu') == 'alice@u.edu'

    def test_resolve_no_match_returns_input(self, gradebook):
        assert gradebook._resolve_email('nobody@u.edu') == 'nobody@u.edu'

    def test_prefix_map_follows_pruning(self, gradebook):
        gradebook.prune_email(['alice@u.edu'])
        assert set(gradebook.email_by_prefix) == {'alice'}


class TestConfigDataclass:
    def test_yaml_key_dict_covers_every_field(self):
        """ a new Config field must be wired into from_file

        forgetting this is exactly how waive_late came to be silently
        ignored when loaded from yaml (commit ff737cc)
        """
        field_set = {f.name for f in dataclasses.fields(Config)}
        assert field_set == set(YAML_KEY_DICT)

    def test_defaults_are_empty_containers(self):
        config = Config()
        assert config.cat_weight_dict == {}
        assert config.remove_list == []
        assert config.waive_dict == {}
        assert config.exclude_complete_thresh == 0

    def test_none_coalesces_to_empty(self):
        config = Config(cat_weight_dict=None, remove_list=None,
                        exclude_complete_thresh=None)
        assert config.cat_weight_dict == {}
        assert config.remove_list == []
        assert config.exclude_complete_thresh == 0

    def test_from_file_round_trips_every_section(self, tmp_path):
        f = tmp_path / 'config.yaml'
        f.write_text("""\
category:
  weight:
    hw: 2
  drop_low:
    hw: 1
  late_penalty:
    hw:
      penalty_per_day: .1
assignments:
  exclude:
    - practice
  substitute:
    hw1:
      - hw1v2
  exclude_complete_thresh: .5
waive:
  a@u.edu: hw1
waive_late:
  b@u.edu: hw2
grade_thresh:
  .9: A
  0: E
email_list:
  - a@u.edu
""")
        config = Config.from_file(f)
        assert config.cat_weight_dict == {'hw': 2}
        assert config.cat_drop_dict == {'hw': 1}
        assert config.cat_late_dict == {'hw': {'penalty_per_day': .1}}
        assert config.remove_list == ['practice']
        assert config.sub_dict == {'hw1': ['hw1v2']}
        assert config.exclude_complete_thresh == .5
        assert config.waive_dict == {'a@u.edu': ['hw1']}
        assert config.late_waive_dict == {'b@u.edu': ['hw2']}
        assert config.grade_thresh == {.9: 'A', 0: 'E'}
        assert config.email_list == ['a@u.edu']


class TestErrors:
    def test_hierarchy_is_value_error(self):
        """ existing callers catching ValueError keep working """
        for cls in (ConfigError, GradebookError):
            assert issubclass(cls, GradescopeMeanError)
            assert issubclass(cls, ValueError)

    def test_duplicate_email_is_gradebook_error(self, tmp_path):
        f = write_scope(tmp_path / 'scope.csv', ASSIGN_STD,
                        STUDENT_STD + [dict(STUDENT_STD[0])])
        with pytest.raises(GradebookError, match='(?i)duplicate'):
            Gradebook(str(f))

    def test_substitute_missing_assignment_is_config_error(self, gradebook):
        with pytest.raises(ConfigError, match='(?i)substitute'):
            gradebook.substitute({'hw1': ['nonexistent']})

    def test_late_penalty_no_match_is_config_error(self, gradebook):
        with pytest.raises(ConfigError, match='(?i)match'):
            gradebook.get_late_penalty(cat='lab', penalty_per_day=.1)


class TestAssignmentDetection:
    def test_column_set_round_trip(self):
        ass_list = AssignmentList(['hw1'])
        col_set = ass_list.get_column_set()
        assert AssignmentList.from_columns(col_set) == ['hw1']

    def test_metadata_is_whatever_is_not_an_assignment(self, tmp_path):
        f = write_scope(
            tmp_path / 'scope.csv', ASSIGN_STD, STUDENT_STD,
            meta_header=['First Name', 'Last Name', 'SID', 'Email',
                         'Sections', 'CRN'])
        gradebook = Gradebook(str(f))
        assert 'crn' in gradebook.df_meta.columns
        assert 'crn' not in gradebook.ass_list

    def test_sid_is_not_lowercased(self, tmp_path):
        students = [dict(STUDENT_STD[0], sid='00A1B2S')]
        f = write_scope(tmp_path / 'scope.csv', ASSIGN_STD, students)
        gradebook = Gradebook(str(f))
        assert gradebook.df_meta['sid'].iloc[0] == '00A1B2S'
