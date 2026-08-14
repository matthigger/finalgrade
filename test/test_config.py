import pathlib
import tempfile

import numpy as np
import pytest

import gradescope_mean
from gradescope_mean.config import *

test_folder = pathlib.Path(gradescope_mean.__file__).parents[1] / 'test'


class TestConfig:
    def test_default_config(self):
        """Default config (no categories) should process without error"""
        f_scope = test_folder / 'scope.csv'
        config = Config()
        gradebook, df_grade_full = config(f_scope)
        assert 'mean' in df_grade_full.columns
        assert 'letter' in df_grade_full.columns
        assert df_grade_full.shape[0] == 5

    def test_config_with_categories(self):
        """Config with category weights should produce per-category means"""
        f_scope = test_folder / 'scope.csv'
        config = Config(cat_weight_dict={'hw': 3, 'quiz': 1})
        gradebook, df_grade_full = config(f_scope)
        assert 'mean_hw' in df_grade_full.columns
        assert 'mean_quiz' in df_grade_full.columns

    def test_config_with_drops(self):
        f_scope = test_folder / 'scope.csv'
        config = Config(cat_weight_dict={'hw': 1, 'quiz': 0},
                        cat_drop_dict={'hw': 1})
        gradebook, df_grade_full = config(f_scope)
        np.testing.assert_allclose(
            [1, .75, .75, .8, .8], df_grade_full['mean'])

    def test_config_with_waive(self):
        f_scope = test_folder / 'scope.csv'
        config = Config(waive_dict={'last0@nu.edu': 'hw1'})
        gradebook, df_grade_full = config(f_scope)
        assert np.isnan(gradebook.df_perc.loc['last0@nu.edu', 'hw1'])

    def test_config_with_remove(self):
        f_scope = test_folder / 'scope.csv'
        config = Config(remove_list=['quiz'])
        gradebook, df_grade_full = config(f_scope)
        assert 'quiz1' not in gradebook.ass_list

    def test_from_file_default(self):
        """Loading default config.yaml should work"""
        config = Config.from_file(F_CONFIG_DEFAULT)
        f_scope = test_folder / 'scope.csv'
        gradebook, df_grade_full = config(f_scope)
        assert df_grade_full.shape[0] == 5

    def test_from_file_custom(self, tmp_path):
        """Test from_file with a custom YAML config"""
        config_content = """\
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
        f_config = tmp_path / 'config.yaml'
        f_config.write_text(config_content)

        config = Config.from_file(f_config)
        f_scope = test_folder / 'scope.csv'
        gradebook, df_grade_full = config(f_scope)
        assert 'mean_hw' in df_grade_full.columns
        assert 'mean_quiz' in df_grade_full.columns

    def test_from_file_with_late_waive(self, tmp_path):
        """Test that waive_late is loaded from config file"""
        config_content = """\
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
        f_config = tmp_path / 'config.yaml'
        f_config.write_text(config_content)

        config = Config.from_file(f_config)
        assert 'last4@nu.edu' in config.late_waive_dict


class TestConfigValidation:
    """Tests for issue #19: better config file validation."""

    def test_empty_waive_value_warns(self):
        """waive: email: (empty) should warn and be ignored, not crash"""
        with pytest.warns(UserWarning, match='empty assignment list'):
            config = Config(waive_dict={'a@b.edu': None})
        assert config.waive_dict == {}

    def test_empty_string_waive_warns(self):
        """waive: email: '' should warn and be ignored"""
        with pytest.warns(UserWarning, match='empty assignment list'):
            config = Config(waive_dict={'a@b.edu': ''})
        assert config.waive_dict == {}

    def test_empty_late_waive_value_warns(self):
        """waive_late: email: (empty) should warn and be ignored"""
        with pytest.warns(UserWarning, match='empty assignment list'):
            config = Config(late_waive_dict={'a@b.edu': None})
        assert config.late_waive_dict == {}

    def test_waive_as_yaml_list(self):
        """waive values can be YAML lists, not just comma-separated strings"""
        config = Config(waive_dict={'a@b.edu': ['hw1', 'hw2']})
        assert config.waive_dict == {'a@b.edu': ['hw1', 'hw2']}

    def test_negative_category_weight_raises(self):
        """Negative category weight should raise ValueError"""
        with pytest.raises(ValueError, match='category weight'):
            Config(cat_weight_dict={'hw': -1})

    def test_string_category_weight_raises(self):
        """Non-numeric category weight should raise ValueError"""
        with pytest.raises(ValueError, match='category weight'):
            Config(cat_weight_dict={'hw': 'abc'})

    def test_negative_drop_raises(self):
        """Negative drop_low should raise ValueError"""
        with pytest.raises(ValueError, match='drop_low'):
            Config(cat_drop_dict={'hw': -1})

    def test_float_drop_raises(self):
        """Float drop_low should raise ValueError"""
        with pytest.raises(ValueError, match='drop_low'):
            Config(cat_drop_dict={'hw': 1.5})

    def test_invalid_exclude_complete_thresh_raises(self):
        """exclude_complete_thresh > 1 should raise ValueError"""
        with pytest.raises(ValueError, match='exclude_complete_thresh'):
            Config(exclude_complete_thresh=1.5)

    def test_null_values_in_yaml(self, tmp_path):
        """Config with all nulls (as in default) should load cleanly"""
        config_content = """\
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
        f_config = tmp_path / 'config.yaml'
        f_config.write_text(config_content)
        config = Config.from_file(f_config)
        assert config.cat_weight_dict == {}
        assert config.waive_dict == {}
        assert config.exclude_complete_thresh == 0

    def test_missing_sections_in_yaml(self, tmp_path):
        """Config with missing sections should use defaults"""
        config_content = """\
category:
  weight:
    hw: 1
"""
        f_config = tmp_path / 'config.yaml'
        f_config.write_text(config_content)
        config = Config.from_file(f_config)
        assert config.cat_weight_dict == {'hw': 1}
        assert config.waive_dict == {}

    def test_invalid_yaml_raises(self, tmp_path):
        """Malformed YAML should raise a clear ValueError"""
        f_config = tmp_path / 'config.yaml'
        f_config.write_text(': invalid: [yaml:')
        with pytest.raises(ValueError, match='failed to parse config'):
            Config.from_file(f_config)

    def test_non_mapping_yaml_raises(self, tmp_path):
        """YAML that parses to a list (not dict) should raise ValueError"""
        f_config = tmp_path / 'config.yaml'
        f_config.write_text('- item1\n- item2\n')
        with pytest.raises(ValueError, match='must be a YAML mapping'):
            Config.from_file(f_config)


class TestConfigEmailPrefix:
    """Tests for issue #9: email prefix matching in config."""

    def test_waive_with_different_suffix(self):
        """waive works when config email has different suffix than scope"""
        f_scope = test_folder / 'scope.csv'
        # last0 is last0@nu.edu in scope, but we use @husky.neu.edu here
        config = Config(waive_dict={'last0@husky.neu.edu': 'hw1'})
        gradebook, _ = config(f_scope)
        assert np.isnan(gradebook.df_perc.loc['last0@nu.edu', 'hw1'])

    def test_email_list_lowercased(self):
        """email_list entries should be lowercased"""
        config = Config(email_list=['FOO@BAR.EDU', 'Baz@Qux.Edu'])
        assert config.email_list == ['foo@bar.edu', 'baz@qux.edu']

    def test_waive_dict_keys_lowercased(self):
        """waive_dict email keys should be lowercased"""
        config = Config(waive_dict={'FOO@bar.edu': 'hw1'})
        assert 'foo@bar.edu' in config.waive_dict

    def test_late_waive_dict_keys_lowercased(self):
        """late_waive_dict email keys should be lowercased"""
        config = Config(late_waive_dict={'FOO@bar.edu': 'hw1'})
        assert 'foo@bar.edu' in config.late_waive_dict

    def test_excuse_day_offset_keys_lowercased(self):
        """excuse_day_offset emails inside cat_late_dict should be lowered"""
        # a late_penalty category must also carry a weight, else it would
        # never be applied
        config = Config(cat_weight_dict={'hw': 1}, cat_late_dict={
            'hw': {'penalty_per_day': 0.1, 'excuse_day': 0,
                   'excuse_day_offset': {'FOO@bar.edu': 2}}})
        offset = config.cat_late_dict['hw']['excuse_day_offset']
        assert 'foo@bar.edu' in offset
