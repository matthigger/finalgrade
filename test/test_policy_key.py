""" settings the policy format has no place for

A misspelled key is the quietest way this policy can fail: nothing reads it,
so `late_penalty123` is not a late penalty applied wrongly, it is a late
penalty not applied at all, on a gradebook that otherwise looks finished.
"""
import pytest

from finalgrade.policy import KEY_TREE, YAML_KEY_DICT, Policy
from finalgrade.errors import PolicyError


def policy_from(write_policy, text):
    return Policy.from_file(write_policy(text))


class TestUnknownKey:
    def test_nested(self, write_policy):
        with pytest.raises(PolicyError, match='late_penalty123'):
            policy_from(write_policy, 'category:\n'
                                      '  weight:\n    hw: 100\n'
                                      '  late_penalty123:\n    hw:\n'
                                      '      penalty_per_day: .15\n')

    def test_top_level(self, write_policy):
        with pytest.raises(PolicyError, match='waive_lates'):
            policy_from(write_policy, 'waive_lates:\n  a@u.edu: hw1\n')

    def test_inside_a_late_penalty(self, write_policy):
        """ these are passed on as keyword arguments, so an unknown one used
        to surface as a TypeError from deep inside grading """
        with pytest.raises(PolicyError, match='excuse_days'):
            policy_from(write_policy, 'category:\n'
                                      '  weight:\n    hw: 100\n'
                                      '  late_penalty:\n    hw:\n'
                                      '      penalty_per_day: .15\n'
                                      '      excuse_days: 3\n')

    def test_suggests_the_intended_key(self, write_policy):
        with pytest.raises(PolicyError, match='did you mean "late_penalty"'):
            policy_from(write_policy,
                        'category:\n  late_penaltyy:\n    hw: 1\n')

    def test_lists_what_is_allowed_there(self, write_policy):
        with pytest.raises(PolicyError, match='exclude_complete_thresh'):
            policy_from(write_policy,
                        'assignments:\n  excludes:\n    - quiz\n')

    def test_reports_every_one_at_once(self, write_policy):
        with pytest.raises(PolicyError) as exc_info:
            policy_from(write_policy, 'categor:\n  weight:\n    hw: 1\n'
                                      'waive_lates:\n  a@u.edu: hw1\n')

        assert 'categor' in str(exc_info.value)
        assert 'waive_lates' in str(exc_info.value)


class TestUserNamesAreNotKeys:
    def test_category_names_are_free(self, write_policy):
        """ 'anything' is a category, not a misspelled setting """
        policy = policy_from(write_policy,
                             'category:\n  weight:\n    anything: 100\n')
        assert policy.cat_weight_dict == {'anything': 100}

    def test_waived_emails_are_free(self, write_policy):
        policy = policy_from(write_policy, 'waive:\n  zzz@nowhere.edu: hw1\n')
        assert 'zzz@nowhere.edu' in policy.waive_dict

    def test_late_penalty_categories_are_free(self, write_policy):
        policy = policy_from(write_policy,
                             'category:\n  weight:\n    zzz: 1\n'
                             '  late_penalty:\n    zzz:\n'
                             '      penalty_per_day: .1\n')
        assert 'zzz' in policy.cat_late_dict

    def test_grade_thresh_keys_are_free(self, write_policy):
        policy = policy_from(write_policy,
                             'grade_thresh:\n  .5: pass\n  0: no\n')
        assert policy.grade_thresh == {.5: 'pass', 0: 'no'}

    def test_packaged_default_passes(self):
        from finalgrade.policy import F_POLICY_DEFAULT
        Policy.from_file(F_POLICY_DEFAULT)

    def test_seeded_config_passes(self, f_scope_std, tmp_path):
        from finalgrade import web
        f_seed = tmp_path / 'seeded.yaml'
        f_seed.write_text(web.seed_policy(f_scope_std.read_text()))
        Policy.from_file(f_seed)


class TestWrongShape:
    def test_section_given_a_scalar(self, write_policy):
        with pytest.raises(PolicyError, match='category'):
            policy_from(write_policy, 'category: 5\n')

    def test_grade_thresh_given_a_number(self, write_policy):
        """ used to reach python as AttributeError: float has no .items """
        with pytest.raises(PolicyError, match='grade_thresh'):
            policy_from(write_policy, 'grade_thresh: 0.9\n')

    def test_waive_given_a_list(self, write_policy):
        with pytest.raises(PolicyError, match='waive'):
            policy_from(write_policy, 'waive:\n  - a@u.edu\n')


class TestStringWhereAListBelongs:
    def test_exclude_takes_one_name(self, write_policy):
        """ the regression: a string was iterated a letter at a time, so
        `exclude: hw2` excluded everything containing h, w or 2 """
        policy = policy_from(write_policy, 'assignments:\n  exclude: hw2\n')

        assert policy.remove_list == ['hw2']

    def test_exclude_takes_a_comma_list(self, write_policy):
        """ the same comma style `waive` already documents """
        policy = policy_from(write_policy,
                             'assignments:\n  exclude: hw2, quiz1\n')

        assert policy.remove_list == ['hw2', 'quiz1']

    def test_email_list_takes_a_string(self, write_policy):
        policy = policy_from(write_policy, 'email_list: a@u.edu, b@u.edu\n')

        assert policy.email_list == ['a@u.edu', 'b@u.edu']

    def test_it_no_longer_eats_every_homework(self, f_scope_std,
                                              write_policy):
        f_policy = write_policy('assignments:\n  exclude: hw2\n')
        gradebook, df_grade = Policy.from_file(f_policy)(str(f_scope_std))

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
