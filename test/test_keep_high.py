""" keep_high: the best n scores count, and a slot with no score is a zero

The use case is a set of interchangeable assignments -- six puzzles, any two
count -- attempted a different number of times by every student, which is
exactly what drop_low cannot say.  The behaviour that needs pinning down is
what happens to a student short of the number required: they are averaged
over zeros, where drop_low would have averaged over what they had.
"""
import numpy as np
import pytest

from conftest import write_scope
from finalgrade import edit, web
from finalgrade.audit import build_log
from finalgrade.check import build_report, render
from finalgrade.errors import PolicyError
from finalgrade.get_mean_drop_low import get_keep_idx, get_mean_drop_low
from finalgrade.policy import Policy

NAN = np.nan

# 4 puzzles a student picks 2 of, and one hw so the grade has a second half
#
#          puz1  puz2  puz3  puz4  hw1 | best 2 puzzles
# alice      10     9     2     -    10 | (10 + 9) / 20  = .95
# bob         8     -     -     -    10 | (8 + 0)  / 20  = .40
# carol       -     -     -     -    10 | (0 + 0)  / 20  = .00
ASSIGN_PUZ = {'Puzzle1': 10, 'Puzzle2': 10, 'Puzzle3': 10, 'Puzzle4': 10,
              'HW1': 10}

STUDENT_PUZ = [
    {'email': 'alice@u.edu', 'first': 'alice', 'last': 'anders', 'sid': '001S',
     'scores': {'Puzzle1': 10, 'Puzzle2': 9, 'Puzzle3': 2, 'HW1': 10}},
    {'email': 'bob@u.edu', 'first': 'bob', 'last': 'baker', 'sid': '002S',
     'scores': {'Puzzle1': 8, 'HW1': 10}},
    {'email': 'carol@u.edu', 'first': 'carol', 'last': 'chen', 'sid': '003S',
     'scores': {'HW1': 10}},
]

YAML_PUZ = """\
category:
  weight:
    puzzle: 1
    hw: 1
  keep_high:
    puzzle: 2
"""


@pytest.fixture
def f_scope_puz(tmp_path):
    """ the 3-student puzzle csv described above """
    return write_scope(tmp_path / 'scope.csv', ASSIGN_PUZ, STUDENT_PUZ)


def policy_puz(**kwargs):
    return Policy(cat_weight_dict={'puzzle': 1, 'hw': 1},
                  cat_keep_dict={'puzzle': 2}, **kwargs)


class TestMean:
    """ the arithmetic, on arrays, where every value is visible """

    def test_keeps_the_best(self):
        assert get_mean_drop_low([1, .9, .2], [10] * 3, keep_n=2) == \
            pytest.approx(.95)

    def test_a_missing_score_is_a_zero(self):
        """ the whole point: two attempts where three count is over three """
        assert get_mean_drop_low([1, .8, NAN, NAN], [10] * 4, keep_n=3) == \
            pytest.approx(.6)

    def test_one_attempt_of_many(self):
        assert get_mean_drop_low([.9, NAN, NAN, NAN, NAN, NAN], [10] * 6,
                                 keep_n=2) == pytest.approx(.45)

    def test_no_attempt_at_all_is_zero_not_missing(self):
        """ they did none of the work required, which is a 0% and not a
        category to be skipped over """
        assert get_mean_drop_low([NAN] * 4, [10] * 4, keep_n=2) == 0

    def test_keeping_more_than_exists_keeps_all_of_it(self):
        """ nothing is left to make the number up with """
        assert get_mean_drop_low([1, .5], [10, 10], keep_n=3) == \
            get_mean_drop_low([1, .5], [10, 10])

    def test_no_assignment_is_still_no_mean(self):
        assert np.isnan(get_mean_drop_low([], [], keep_n=2))

    def test_weighted_by_points_like_any_other_mean(self):
        # the 100% is worth 10 points and the 50% is worth 30
        assert get_mean_drop_low([1, .5, 0], [10, 30, 10], keep_n=2) == \
            pytest.approx(25 / 40)

    def test_more_attempts_never_lower_the_mean(self):
        """ a student who tries a fifth puzzle cannot be punished for it """
        perc = [.9, .8, NAN, NAN]
        with_more = [.9, .8, .1, NAN]
        assert get_mean_drop_low(with_more, [10] * 4, keep_n=2) >= \
            get_mean_drop_low(perc, [10] * 4, keep_n=2)

    def test_exclusive_with_drop_low(self):
        with pytest.raises(ValueError, match='not both'):
            get_mean_drop_low([1, .5], [10, 10], drop_n=1, keep_n=1)


class TestKeepIdx:
    """ which assignments were counted, which an audit has to name """

    def test_best_first(self):
        assert get_keep_idx(np.array([.2, 1., .9]), np.array([10.] * 3),
                            keep_n=2) == [1, 2]

    def test_a_missing_score_can_be_counted(self):
        """ it is the zero the mean is short of """
        assert get_keep_idx(np.array([1., NAN, NAN]), np.array([10.] * 3),
                            keep_n=2)[0] == 0

    def test_none_kept_without_a_rule(self):
        assert get_keep_idx(np.array([1.]), np.array([10.])) == []

    def test_the_lightest_zero_is_the_one_counted(self):
        """ where the choice is arbitrary, take the one that costs least """
        idx_list = get_keep_idx(np.array([1., NAN, NAN]),
                                np.array([10., 90., 10.]), keep_n=2)
        assert idx_list == [0, 2]


class TestExtraCredit:
    def test_extra_is_counted_and_is_not_one_of_the_n(self):
        # the two kept are the .9 and the .5; the extra 1.0 is added on top
        assert get_mean_drop_low([.9, .5, 1.], [10, 10, 10], keep_n=2,
                                 extra=[False, False, True]) == \
            pytest.approx(24 / 20)

    def test_a_skipped_extra_costs_nothing(self):
        assert get_mean_drop_low([.9, .5, NAN], [10, 10, 10], keep_n=2,
                                 extra=[False, False, True]) == \
            pytest.approx(.7)

    def test_extra_is_never_a_padded_zero(self):
        """ counted as a 0% it would take away the credit it is there to add
        """
        assert get_mean_drop_low([1., NAN], [10, 10], keep_n=2,
                                 extra=[False, True]) == pytest.approx(1.)


class TestPipeline:
    """ end to end, from a csv and a policy """

    def test_category_mean(self, f_scope_puz):
        _, df = policy_puz()(f_scope_puz)

        np.testing.assert_allclose([.95, .4, 0.], df['mean_puzzle'])

    def test_final_grade(self, f_scope_puz):
        _, df = policy_puz()(f_scope_puz)

        # hw is 100% for everyone, weighted equally with the puzzles
        np.testing.assert_allclose([.975, .7, .5], df['mean'])

    def test_read_from_yaml(self, f_scope_puz, write_policy):
        policy = Policy.from_file(write_policy(YAML_PUZ))

        assert policy.cat_keep_dict == {'puzzle': 2}
        np.testing.assert_allclose([.95, .4, 0.],
                                   policy(f_scope_puz)[1]['mean_puzzle'])

    def test_a_category_name_is_normalized(self, write_policy):
        policy = Policy.from_file(write_policy(
            'category:\n  weight:\n    puzzle: 1\n'
            '  keep_high:\n    PUZZLE: 2\n'))

        assert policy.cat_keep_dict == {'puzzle': 2}

    def test_waive_cannot_lower_the_number_required(self, f_scope_puz):
        """ excused from one of four, bob still needs his best two: the
        rule is about how many count, not which were assigned """
        _, df = policy_puz(waive_dict={'bob@u.edu': ['puzzle2']})(f_scope_puz)

        assert df.loc['bob@u.edu', 'mean_puzzle'] == pytest.approx(.4)

    def test_short_category_counts_everything_and_warns(self, tmp_path):
        f = write_scope(tmp_path / 'scope.csv', {'Puzzle1': 10, 'Puzzle2': 10},
                        [{'email': 'a@u.edu', 'scores': {'Puzzle1': 10}}])
        policy = Policy(cat_weight_dict={'puzzle': 1},
                        cat_keep_dict={'puzzle': 5})

        with pytest.warns(UserWarning, match='keep_high'):
            _, df = policy(f)

        # both puzzles count, one of them missing -> 10 / 20
        assert df.loc['a@u.edu', 'mean_puzzle'] == pytest.approx(.5)


class TestPolicyRefuses:
    def test_both_rules_on_one_category(self):
        with pytest.raises(PolicyError, match='not both'):
            Policy(cat_weight_dict={'hw': 1}, cat_drop_dict={'hw': 1},
                   cat_keep_dict={'hw': 2})

    def test_both_rules_on_different_categories_is_fine(self):
        policy = Policy(cat_weight_dict={'hw': 1, 'puzzle': 1},
                        cat_drop_dict={'hw': 1},
                        cat_keep_dict={'puzzle': 2})

        assert policy.cat_keep_dict == {'puzzle': 2}

    def test_a_zero_keep_high_is_no_rule_at_all(self):
        """ so it does not collide with a drop_low that is really there """
        policy = Policy(cat_weight_dict={'hw': 1}, cat_drop_dict={'hw': 1},
                        cat_keep_dict={'hw': 0})

        assert policy.cat_drop_dict == {'hw': 1}

    def test_an_unweighted_category(self):
        with pytest.raises(PolicyError, match='keep_high'):
            Policy(cat_weight_dict={'hw': 1}, cat_keep_dict={'puzzle': 2})

    def test_a_negative_count(self):
        with pytest.raises(PolicyError, match='keep_high'):
            Policy(cat_weight_dict={'hw': 1}, cat_keep_dict={'hw': -1})

    def test_a_fractional_count(self):
        with pytest.raises(PolicyError, match='keep_high'):
            Policy(cat_weight_dict={'hw': 1}, cat_keep_dict={'hw': 1.5})

    def test_the_wrong_shape(self, write_policy):
        with pytest.raises(PolicyError, match='keep_high'):
            Policy.from_file(write_policy(
                'category:\n  weight:\n    hw: 1\n  keep_high: 2\n'))

    def test_a_misspelling_is_not_silently_ignored(self, write_policy):
        with pytest.raises(PolicyError, match='keep_hgih'):
            Policy.from_file(write_policy(
                'category:\n  weight:\n    hw: 1\n'
                '  keep_hgih:\n    hw: 2\n'))


class TestAudit:
    def test_what_was_counted_is_named(self, f_scope_puz):
        policy = policy_puz()
        gradebook, df = policy(f_scope_puz)
        log = build_log(gradebook, policy, df)

        event = next(e for e in log['alice@u.edu'] if e['kind'] == 'keep')
        assert 'puzzle1' in event['text'] and 'puzzle2' in event['text']
        # her 20% was not one of the two
        assert 'puzzle3' not in event['text']

    def test_a_counted_zero_is_named(self, f_scope_puz):
        """ the student short of the number will ask about exactly this.
        nothing handed in is a 0 in the export, so it has a name """
        policy = policy_puz()
        gradebook, df = policy(f_scope_puz)
        log = build_log(gradebook, policy, df)

        event = next(e for e in log['bob@u.edu'] if e['kind'] == 'keep')
        assert 'puzzle1 (80%)' in event['text']
        assert '(0%)' in event['text']

    def test_a_counted_zero_with_no_score_behind_it_is_owned_up_to(
            self, f_scope_puz):
        """ a waived assignment has no score to quote, so it is counted """
        policy = policy_puz(waive_dict={
            'bob@u.edu': ['puzzle2', 'puzzle3', 'puzzle4']})
        gradebook, df = policy(f_scope_puz)
        log = build_log(gradebook, policy, df)

        event = next(e for e in log['bob@u.edu'] if e['kind'] == 'keep')
        assert '1 zero for want of a score' in event['text']

    def test_nothing_to_name_says_that_instead(self, f_scope_puz):
        """ the shape a planned category has before anything is graded """
        policy = policy_puz(waive_dict={
            'bob@u.edu': ['puzzle1', 'puzzle2', 'puzzle3', 'puzzle4']})
        gradebook, df = policy(f_scope_puz)
        log = build_log(gradebook, policy, df)

        event = next(e for e in log['bob@u.edu'] if e['kind'] == 'keep')
        assert 'no score at all' in event['text']
        assert df.loc['bob@u.edu', 'mean_puzzle'] == 0


class TestReport:
    def test_the_rule_is_shown(self, f_scope_puz):
        report = build_report(policy_puz(), str(f_scope_puz))

        keep_dict = {cat.name: cat.keep_high for cat in report.cat_list}
        assert keep_dict == {'puzzle': 2, 'hw': 0}
        assert report.ok
        assert 'keep 2' in render(report)

    def test_drop_and_keep_share_one_column(self, f_scope_puz):
        report = build_report(
            Policy(cat_weight_dict={'puzzle': 1, 'hw': 1},
                   cat_keep_dict={'puzzle': 2},
                   cat_drop_dict={'hw': 1}), str(f_scope_puz))
        text = render(report)

        assert 'drop/keep' in text
        assert 'keep 2' in text and 'drop 1' in text

    def test_more_kept_than_exist_warns(self, f_scope_puz):
        report = build_report(
            Policy(cat_weight_dict={'puzzle': 1, 'hw': 1},
                   cat_keep_dict={'puzzle': 9}), str(f_scope_puz))

        assert any('keep_high' in s for s in report.warn_list)
        # a warning, not an error: the grades it gives are still meant
        assert report.ok


class TestEdit:
    YAML_DROP = ('category:\n  weight:\n    hw: 1\n'
                 '  drop_low:\n    hw: 2\n')

    def cfg(self, text):
        from finalgrade.policy import yaml
        return yaml.load(text)

    def test_sets_the_count(self):
        out = edit.apply('category:\n  weight:\n    puzzle: 1\n',
                         'set_keep_high', dict(cat='puzzle', n=2))

        assert self.cfg(out)['category']['keep_high'] == {'puzzle': 2}

    def test_zero_removes_it(self):
        out = edit.apply('category:\n  weight:\n    hw: 1\n'
                         '  keep_high:\n    hw: 2\n',
                         'set_keep_high', dict(cat='hw', n=0))

        assert not self.cfg(out)['category']['keep_high']

    def test_keeping_replaces_dropping(self):
        """ the two are exclusive, so the widget cannot leave both behind """
        out = edit.apply(self.YAML_DROP, 'set_keep_high',
                         dict(cat='hw', n=3))
        data = self.cfg(out)

        assert data['category']['keep_high'] == {'hw': 3}
        assert not data['category']['drop_low']

    def test_dropping_replaces_keeping(self):
        out = edit.apply('category:\n  weight:\n    hw: 1\n'
                         '  keep_high:\n    hw: 3\n',
                         'set_drop_low', dict(cat='hw', n=1))
        data = self.cfg(out)

        assert data['category']['drop_low'] == {'hw': 1}
        assert not data['category']['keep_high']

    def test_dropping_does_not_invent_a_keep_high_section(self):
        """ a section the file never had is one the user never wanted """
        out = edit.apply('category:\n  weight:\n    hw: 1\n',
                         'set_drop_low', dict(cat='hw', n=1))

        assert 'keep_high' not in out

    def test_removing_a_category_takes_its_rule_with_it(self):
        out = edit.apply('category:\n  weight:\n    hw: 1\n'
                         '  keep_high:\n    hw: 3\n',
                         'remove_category', dict(cat='hw'))

        assert not self.cfg(out)['category']['keep_high']

    def test_the_result_reads_back(self):
        out = edit.apply('category:\n  weight:\n    puzzle: 1\n',
                         'set_keep_high', dict(cat='puzzle', n=2))

        assert edit.load(out) is not None
        assert Policy(**{'cat_weight_dict': {'puzzle': 1},
                         'cat_keep_dict': {'puzzle': 2}})


class TestWeb:
    def test_the_form_reads_it(self):
        state = web.form_state(YAML_PUZ)

        cat = next(c for c in state['cat_list'] if c['name'] == 'puzzle')
        assert cat['keep_high'] == 2
        assert cat['drop_low'] == 0

    def test_grades_in_the_browser_match_the_command_line(self, f_scope_puz):
        res = web.grade(f_scope_puz.read_text(), YAML_PUZ)

        assert res['ok'], res['error']
        mean_dict = {s['email']: s['mean'] for s in res['student_list']}
        assert mean_dict['alice@u.edu'] == pytest.approx(.975)
        assert mean_dict['carol@u.edu'] == pytest.approx(.5)

    def test_raw_is_the_grade_without_the_rule(self, f_scope_puz):
        """ the inspector's 'before' has to have keep_high switched off, or
        the toggle shows the same number twice """
        res = web.grade(f_scope_puz.read_text(), YAML_PUZ)
        pair = res['value_dict']['cat:puzzle']

        email_list = [s['email'] for s in res['student_list']]
        idx = email_list.index('alice@u.edu')
        # alice's best 2 are 100% and 90%; every puzzle counted is 4 of 21
        assert pair['final'][idx] == pytest.approx(.95)
        assert pair['raw'][idx] == pytest.approx(21 / 40)

    def test_the_widget_writes_a_policy_that_grades(self, f_scope_puz):
        csv_text = f_scope_puz.read_text()
        yaml_text = web.seed_policy(csv_text)
        for action, args in (('add_category', '{"cat": "puzzle"}'),
                             ('add_category', '{"cat": "hw"}'),
                             ('set_keep_high', '{"cat": "puzzle", "n": 2}')):
            res = web.edit_policy(yaml_text, action, args)
            assert res['ok'], res['error']
            yaml_text = res['yaml']

        assert web.check_policy(csv_text, yaml_text)['ok']
        assert 'keep_high' in yaml_text
