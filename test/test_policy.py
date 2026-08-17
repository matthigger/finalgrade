import pathlib
import tempfile

import numpy as np
import pytest

import finalgrade
from finalgrade.policy import *

test_folder = pathlib.Path(finalgrade.__file__).parents[1] / 'test'


class TestConfig:
    def test_default_config(self):
        """Default policy (no categories) should process without error"""
        f_scope = test_folder / 'scope.csv'
        policy = Policy()
        gradebook, df_grade_full = policy(f_scope)
        assert 'mean' in df_grade_full.columns
        assert 'letter' in df_grade_full.columns
        assert df_grade_full.shape[0] == 5

    def test_config_with_categories(self):
        """Policy with category weights should produce per-category means"""
        f_scope = test_folder / 'scope.csv'
        policy = Policy(cat_weight_dict={'hw': 3, 'quiz': 1})
        gradebook, df_grade_full = policy(f_scope)
        assert 'mean_hw' in df_grade_full.columns
        assert 'mean_quiz' in df_grade_full.columns

    def test_config_with_drops(self):
        f_scope = test_folder / 'scope.csv'
        policy = Policy(cat_weight_dict={'hw': 1, 'quiz': 0},
                        cat_drop_dict={'hw': 1})
        gradebook, df_grade_full = policy(f_scope)
        np.testing.assert_allclose(
            [1, .75, .75, .8, .8], df_grade_full['mean'])

    def test_config_with_waive(self):
        f_scope = test_folder / 'scope.csv'
        policy = Policy(waive_dict={'last0@nu.edu': 'hw1'})
        gradebook, df_grade_full = policy(f_scope)
        assert np.isnan(gradebook.df_perc.loc['last0@nu.edu', 'hw1'])

    def test_config_with_remove(self):
        f_scope = test_folder / 'scope.csv'
        policy = Policy(remove_list=['quiz'])
        gradebook, df_grade_full = policy(f_scope)
        assert 'quiz1' not in gradebook.ass_list

    def test_from_file_default(self):
        """Loading default policy.yaml should work"""
        policy = Policy.from_file(F_POLICY_DEFAULT)
        f_scope = test_folder / 'scope.csv'
        gradebook, df_grade_full = policy(f_scope)
        assert df_grade_full.shape[0] == 5

    def test_from_file_custom(self, tmp_path):
        """Test from_file with a custom YAML policy"""
        policy_content = """\
category:
  weight:
    hw: 3
    quiz: 1
  drop_low:
    hw: 1
  late_penalty: null

assignments:
  exclude_complete_thresh: null
  exclude: null
  substitute: null

waive: null

waive_late: null

email_list: null
"""
        f_policy = tmp_path / 'policy.yaml'
        f_policy.write_text(policy_content)

        policy = Policy.from_file(f_policy)
        f_scope = test_folder / 'scope.csv'
        gradebook, df_grade_full = policy(f_scope)
        assert 'mean_hw' in df_grade_full.columns
        assert 'mean_quiz' in df_grade_full.columns

    def test_from_file_with_late_waive(self, tmp_path):
        """Test that waive_late is loaded from policy file"""
        policy_content = """\
category:
  weight:
    hw: 1
    quiz: 0
  drop_low: null
  late_penalty:
    hw:
      penalty_per_day: 0.1
      excuse_day: 0

assignments:
  exclude_complete_thresh: null
  exclude: null
  substitute: null

waive: null

waive_late:
  last4@nu.edu: hw1

email_list: null
"""
        f_policy = tmp_path / 'policy.yaml'
        f_policy.write_text(policy_content)

        policy = Policy.from_file(f_policy)
        assert 'last4@nu.edu' in policy.late_waive_dict


class TestConfigValidation:
    """Tests for issue #19: better policy file validation."""

    def test_empty_waive_value_warns(self):
        """waive: email: (empty) should warn and be ignored, not crash"""
        with pytest.warns(UserWarning, match='empty assignment list'):
            policy = Policy(waive_dict={'a@b.edu': None})
        assert policy.waive_dict == {}

    def test_empty_string_waive_warns(self):
        """waive: email: '' should warn and be ignored"""
        with pytest.warns(UserWarning, match='empty assignment list'):
            policy = Policy(waive_dict={'a@b.edu': ''})
        assert policy.waive_dict == {}

    def test_empty_late_waive_value_warns(self):
        """waive_late: email: (empty) should warn and be ignored"""
        with pytest.warns(UserWarning, match='empty assignment list'):
            policy = Policy(late_waive_dict={'a@b.edu': None})
        assert policy.late_waive_dict == {}

    def test_waive_as_yaml_list(self):
        """waive values can be YAML lists, not just comma-separated strings"""
        policy = Policy(waive_dict={'a@b.edu': ['hw1', 'hw2']})
        assert policy.waive_dict == {'a@b.edu': ['hw1', 'hw2']}

    def test_negative_category_weight_raises(self):
        """Negative category weight should raise ValueError"""
        with pytest.raises(ValueError, match='category weight'):
            Policy(cat_weight_dict={'hw': -1})

    def test_string_category_weight_raises(self):
        """Non-numeric category weight should raise ValueError"""
        with pytest.raises(ValueError, match='category weight'):
            Policy(cat_weight_dict={'hw': 'abc'})

    def test_negative_drop_raises(self):
        """Negative drop_low should raise ValueError"""
        with pytest.raises(ValueError, match='drop_low'):
            Policy(cat_drop_dict={'hw': -1})

    def test_float_drop_raises(self):
        """Float drop_low should raise ValueError"""
        with pytest.raises(ValueError, match='drop_low'):
            Policy(cat_drop_dict={'hw': 1.5})

    def test_invalid_exclude_complete_thresh_raises(self):
        """exclude_complete_thresh > 1 should raise ValueError"""
        with pytest.raises(ValueError, match='exclude_complete_thresh'):
            Policy(exclude_complete_thresh=1.5)

    # late_penalty values.  a late_penalty category needs a weight too, else
    # _check_category_keys raises first and these would pass for the wrong
    # reason
    @staticmethod
    def _late(late_dict):
        return Policy(cat_weight_dict={'hw': 1},
                      cat_late_dict={'hw': late_dict})

    def test_whole_number_penalty_per_day_raises(self):
        """15 meaning 15% is a hundredfold penalty, not a valid rate"""
        with pytest.raises(ValueError, match='write .15 rather than 15'):
            self._late({'penalty_per_day': 15})

    def test_fraction_penalty_per_day_accepted(self):
        """the same rate written as a fraction is what was meant"""
        policy = self._late({'penalty_per_day': .15})
        assert policy.cat_late_dict['hw']['penalty_per_day'] == .15

    def test_penalty_per_day_of_one_accepted(self):
        """a full assignment per late day is a rate, not an error"""
        policy = self._late({'penalty_per_day': 1})
        assert policy.cat_late_dict['hw']['penalty_per_day'] == 1

    def test_negative_penalty_per_day_raises(self):
        """a negative rate would raise credit for being late"""
        with pytest.raises(ValueError, match='penalty_per_day'):
            self._late({'penalty_per_day': -.1})

    def test_non_numeric_penalty_per_day_raises(self):
        with pytest.raises(ValueError, match='penalty_per_day'):
            self._late({'penalty_per_day': 'a lot'})

    def test_missing_penalty_per_day_raises(self):
        """a late_penalty block with no rate applies no penalty at all"""
        with pytest.raises(ValueError, match='needs a penalty_per_day'):
            self._late({'excuse_day': 3})

    def test_negative_excuse_day_raises(self):
        with pytest.raises(ValueError, match='excuse_day'):
            self._late({'penalty_per_day': .1, 'excuse_day': -3})

    def test_non_numeric_grace_period_raises(self):
        with pytest.raises(ValueError, match='grace_period_minutes'):
            self._late({'penalty_per_day': .1,
                        'grace_period_minutes': 'soon'})

    def test_late_penalty_not_a_mapping_raises(self):
        """`late_penalty: {hw: 15}` names no setting at all"""
        with pytest.raises(ValueError, match='indented below it'):
            self._late(15)

    def test_excuse_day_offset_not_a_mapping_raises(self):
        with pytest.raises(ValueError, match='excuse_day_offset'):
            self._late({'penalty_per_day': .1, 'excuse_day_offset': 4})

    def test_non_numeric_excuse_day_offset_raises(self):
        with pytest.raises(ValueError, match='excuse_day_offset'):
            self._late({'penalty_per_day': .1,
                        'excuse_day_offset': {'a@b.edu': 'two'}})

    def test_whole_number_penalty_from_file_raises(self, tmp_path):
        """the path a grader actually takes: a policy file, then check"""
        f_policy = tmp_path / 'policy.yaml'
        f_policy.write_text('category:\n'
                            '  weight:\n'
                            '    hw: 100\n'
                            '  late_penalty:\n'
                            '    hw:\n'
                            '      penalty_per_day: 15\n')
        with pytest.raises(ValueError, match='write .15 rather than 15'):
            Policy.from_file(f_policy)

    def test_null_values_in_yaml(self, tmp_path):
        """Policy with all nulls (as in default) should load cleanly"""
        policy_content = """\
category:
  weight: null
  drop_low: null
  late_penalty: null
assignments:
  exclude_complete_thresh: null
  exclude: null
  substitute: null
waive: null
waive_late: null
email_list: null
"""
        f_policy = tmp_path / 'policy.yaml'
        f_policy.write_text(policy_content)
        policy = Policy.from_file(f_policy)
        assert policy.cat_weight_dict == {}
        assert policy.waive_dict == {}
        assert policy.exclude_complete_thresh == 0

    def test_missing_sections_in_yaml(self, tmp_path):
        """Policy with missing sections should use defaults"""
        policy_content = """\
category:
  weight:
    hw: 1
"""
        f_policy = tmp_path / 'policy.yaml'
        f_policy.write_text(policy_content)
        policy = Policy.from_file(f_policy)
        assert policy.cat_weight_dict == {'hw': 1}
        assert policy.waive_dict == {}

    def test_invalid_yaml_raises(self, tmp_path):
        """Malformed YAML should raise a clear ValueError"""
        f_policy = tmp_path / 'policy.yaml'
        f_policy.write_text(': invalid: [yaml:')
        with pytest.raises(ValueError, match='failed to parse policy'):
            Policy.from_file(f_policy)

    def test_non_mapping_yaml_raises(self, tmp_path):
        """YAML that parses to a list (not dict) should raise ValueError"""
        f_policy = tmp_path / 'policy.yaml'
        f_policy.write_text('- item1\n- item2\n')
        with pytest.raises(ValueError, match='must be a YAML mapping'):
            Policy.from_file(f_policy)


class TestConfigEmailPrefix:
    """Tests for issue #9: email prefix matching in policy."""

    def test_waive_with_different_suffix(self):
        """waive works when policy email has different suffix than scope"""
        f_scope = test_folder / 'scope.csv'
        # last0 is last0@nu.edu in scope, but we use @husky.neu.edu here
        policy = Policy(waive_dict={'last0@husky.neu.edu': 'hw1'})
        gradebook, _ = policy(f_scope)
        assert np.isnan(gradebook.df_perc.loc['last0@nu.edu', 'hw1'])

    def test_email_list_lowercased(self):
        """email_list entries should be lowercased"""
        policy = Policy(email_list=['FOO@BAR.EDU', 'Baz@Qux.Edu'])
        assert policy.email_list == ['foo@bar.edu', 'baz@qux.edu']

    def test_waive_dict_keys_lowercased(self):
        """waive_dict email keys should be lowercased"""
        policy = Policy(waive_dict={'FOO@bar.edu': 'hw1'})
        assert 'foo@bar.edu' in policy.waive_dict

    def test_late_waive_dict_keys_lowercased(self):
        """late_waive_dict email keys should be lowercased"""
        policy = Policy(late_waive_dict={'FOO@bar.edu': 'hw1'})
        assert 'foo@bar.edu' in policy.late_waive_dict

    def test_excuse_day_offset_keys_lowercased(self):
        """excuse_day_offset emails inside cat_late_dict should be lowered"""
        # a late_penalty category must also carry a weight, else it would
        # never be applied
        policy = Policy(cat_weight_dict={'hw': 1}, cat_late_dict={
            'hw': {'penalty_per_day': 0.1, 'excuse_day': 0,
                   'excuse_day_offset': {'FOO@bar.edu': 2}}})
        offset = policy.cat_late_dict['hw']['excuse_day_offset']
        assert 'foo@bar.edu' in offset
