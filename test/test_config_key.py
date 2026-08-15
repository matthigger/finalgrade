""" settings the config format has no place for

A misspelled key is the quietest way this config can fail: nothing reads it,
so `late_penalty123` is not a late penalty applied wrongly, it is a late
penalty not applied at all, on a gradebook that otherwise looks finished.
"""
import pytest

from finalgrade.config import KEY_TREE, YAML_KEY_DICT, Config
from finalgrade.errors import ConfigError


def config_from(write_config, text):
    return Config.from_file(write_config(text))


class TestUnknownKey:
    def test_nested(self, write_config):
        with pytest.raises(ConfigError, match='late_penalty123'):
            config_from(write_config, 'category:\n'
                                      '  weight:\n    hw: 100\n'
                                      '  late_penalty123:\n    hw:\n'
                                      '      penalty_per_day: .15\n')

    def test_top_level(self, write_config):
        with pytest.raises(ConfigError, match='waive_lates'):
            config_from(write_config, 'waive_lates:\n  a@u.edu: hw1\n')

    def test_inside_a_late_penalty(self, write_config):
        """ these are passed on as keyword arguments, so an unknown one used
        to surface as a TypeError from deep inside grading """
        with pytest.raises(ConfigError, match='excuse_days'):
            config_from(write_config, 'category:\n'
                                      '  weight:\n    hw: 100\n'
                                      '  late_penalty:\n    hw:\n'
                                      '      penalty_per_day: .15\n'
                                      '      excuse_days: 3\n')

    def test_suggests_the_intended_key(self, write_config):
        with pytest.raises(ConfigError, match='did you mean "late_penalty"'):
            config_from(write_config,
                        'category:\n  late_penaltyy:\n    hw: 1\n')

    def test_lists_what_is_allowed_there(self, write_config):
        with pytest.raises(ConfigError, match='exclude_complete_thresh'):
            config_from(write_config,
                        'assignments:\n  excludes:\n    - quiz\n')

    def test_reports_every_one_at_once(self, write_config):
        with pytest.raises(ConfigError) as exc_info:
            config_from(write_config, 'categor:\n  weight:\n    hw: 1\n'
                                      'waive_lates:\n  a@u.edu: hw1\n')

        assert 'categor' in str(exc_info.value)
        assert 'waive_lates' in str(exc_info.value)


class TestUserNamesAreNotKeys:
    def test_category_names_are_free(self, write_config):
        """ 'anything' is a category, not a misspelled setting """
        config = config_from(write_config,
                             'category:\n  weight:\n    anything: 100\n')
        assert config.cat_weight_dict == {'anything': 100}

    def test_waived_emails_are_free(self, write_config):
        config = config_from(write_config, 'waive:\n  zzz@nowhere.edu: hw1\n')
        assert 'zzz@nowhere.edu' in config.waive_dict

    def test_late_penalty_categories_are_free(self, write_config):
        config = config_from(write_config,
                             'category:\n  weight:\n    zzz: 1\n'
                             '  late_penalty:\n    zzz:\n'
                             '      penalty_per_day: .1\n')
        assert 'zzz' in config.cat_late_dict

    def test_grade_thresh_keys_are_free(self, write_config):
        config = config_from(write_config,
                             'grade_thresh:\n  .5: pass\n  0: no\n')
        assert config.grade_thresh == {.5: 'pass', 0: 'no'}

    def test_packaged_default_passes(self):
        from finalgrade.config import F_CONFIG_DEFAULT
        Config.from_file(F_CONFIG_DEFAULT)

    def test_seeded_config_passes(self, f_scope_std, tmp_path):
        from finalgrade import web
        f_seed = tmp_path / 'seeded.yaml'
        f_seed.write_text(web.seed_config(f_scope_std.read_text()))
        Config.from_file(f_seed)


class TestWrongShape:
    def test_section_given_a_scalar(self, write_config):
        with pytest.raises(ConfigError, match='category'):
            config_from(write_config, 'category: 5\n')

    def test_grade_thresh_given_a_number(self, write_config):
        """ used to reach python as AttributeError: float has no .items """
        with pytest.raises(ConfigError, match='grade_thresh'):
            config_from(write_config, 'grade_thresh: 0.9\n')

    def test_waive_given_a_list(self, write_config):
        with pytest.raises(ConfigError, match='waive'):
            config_from(write_config, 'waive:\n  - a@u.edu\n')


class TestStringWhereAListBelongs:
    def test_exclude_takes_one_name(self, write_config):
        """ the regression: a string was iterated a letter at a time, so
        `exclude: hw2` excluded everything containing h, w or 2 """
        config = config_from(write_config, 'assignments:\n  exclude: hw2\n')

        assert config.remove_list == ['hw2']

    def test_exclude_takes_a_comma_list(self, write_config):
        """ the same comma style `waive` already documents """
        config = config_from(write_config,
                             'assignments:\n  exclude: hw2, quiz1\n')

        assert config.remove_list == ['hw2', 'quiz1']

    def test_email_list_takes_a_string(self, write_config):
        config = config_from(write_config, 'email_list: a@u.edu, b@u.edu\n')

        assert config.email_list == ['a@u.edu', 'b@u.edu']

    def test_it_no_longer_eats_every_homework(self, f_scope_std,
                                              write_config):
        f_config = write_config('assignments:\n  exclude: hw2\n')
        gradebook, df_grade = Config.from_file(f_config)(str(f_scope_std))

        assert list(gradebook.ass_list) == ['hw1', 'hw3', 'quiz1']


class TestSchema:
    def test_tree_follows_the_table(self):
        """ the schema is derived, so a new section cannot be rejected as
        unknown by the checker that is supposed to allow it """
        for key_tup in YAML_KEY_DICT.values():
            node = KEY_TREE
            for key in key_tup:
                assert key in node
                node = node[key] or {}
