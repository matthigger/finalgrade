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
from finalgrade.policy import Policy, yaml

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

    def test_weighted_by_points_like_any_other_mean(self):
        # the 100% is worth 10 points and the 50% is worth 30
        assert get_mean_drop_low([1, .5, 0], [10, 30, 10], keep_n=2) == \
            pytest.approx(25 / 40)

    def test_nothing_to_count_is_no_mean(self):
        assert np.isnan(get_mean_drop_low([], [], keep_n=2))

    def test_the_lightest_zero_is_the_one_counted(self):
        """ where the choice is arbitrary, take the one that costs least """
        assert get_keep_idx(np.array([1., NAN, NAN]),
                            np.array([10., 90., 10.]), keep_n=2) == [0, 2]

    def test_extra_credit_is_added_and_is_never_a_zero(self):
        # the two counted are the .9 and the .5; the extra 1.0 goes on top
        assert get_mean_drop_low([.9, .5, 1.], [10, 10, 10], keep_n=2,
                                 extra=[False, False, True]) == \
            pytest.approx(24 / 20)
        # counted as a 0% it would take away the credit it is there to add
        assert get_mean_drop_low([1., NAN], [10, 10], keep_n=2,
                                 extra=[False, True]) == pytest.approx(1.)


class TestPipeline:
    """ end to end, from a csv and a policy """

    def test_the_means(self, f_scope_puz):
        _, df = policy_puz()(f_scope_puz)

        np.testing.assert_allclose([.95, .4, 0.], df['mean_puzzle'])
        # hw is 100% for everyone, weighted equally with the puzzles
        np.testing.assert_allclose([.975, .7, .5], df['mean'])

    def test_read_from_yaml(self, f_scope_puz, write_policy):
        """ and the category name normalized on the way in """
        policy = Policy.from_file(write_policy(
            'category:\n  weight:\n    puzzle: 1\n    hw: 1\n'
            '  keep_high:\n    PUZZLE: 2\n'))

        assert policy.cat_keep_dict == {'puzzle': 2}
        np.testing.assert_allclose([.95, .4, 0.],
                                   policy(f_scope_puz)[1]['mean_puzzle'])

    def test_waive_cannot_lower_the_number_required(self, f_scope_puz):
        """ excused from one of four, bob still needs his best two: the
        rule is about how many count, not which were assigned """
        _, df = policy_puz(waive_dict={'bob@u.edu': ['puzzle2']})(f_scope_puz)

        assert df.loc['bob@u.edu', 'mean_puzzle'] == pytest.approx(.4)

    def test_a_zero_grades_as_no_rule_and_says_so(self, f_scope_puz):
        """ it is what the widget writes the moment a rule is picked, so it
        must not quietly change a grade -- but nor should it stay unnoticed
        """
        policy = Policy(cat_weight_dict={'puzzle': 1, 'hw': 1},
                        cat_keep_dict={'puzzle': 0})

        with pytest.warns(UserWarning, match='keep_high is 0'):
            _, df = policy(f_scope_puz)

        # every score counts, exactly as if the rule were not there
        _, plain = Policy(cat_weight_dict={'puzzle': 1, 'hw': 1})(f_scope_puz)
        np.testing.assert_allclose(plain['mean_puzzle'], df['mean_puzzle'])

    def test_short_category_counts_everything_and_warns(self, tmp_path):
        f = write_scope(tmp_path / 'scope.csv', {'Puzzle1': 10, 'Puzzle2': 10},
                        [{'email': 'a@u.edu', 'scores': {'Puzzle1': 10}}])
        policy = Policy(cat_weight_dict={'puzzle': 1},
                        cat_keep_dict={'puzzle': 5})

        with pytest.warns(UserWarning, match='keep_high'):
            _, df = policy(f)

        # both puzzles count, one of them never handed in -> 10 / 20
        assert df.loc['a@u.edu', 'mean_puzzle'] == pytest.approx(.5)


class TestPolicyRefuses:
    def test_both_rules_on_one_category(self):
        with pytest.raises(PolicyError, match='not both'):
            Policy(cat_weight_dict={'hw': 1}, cat_drop_dict={'hw': 1},
                   cat_keep_dict={'hw': 2})

    def test_an_unweighted_category(self):
        with pytest.raises(PolicyError, match='keep_high'):
            Policy(cat_weight_dict={'hw': 1}, cat_keep_dict={'puzzle': 2})

    def test_a_count_that_is_not_a_whole_number_of_assignments(self):
        for n in (-1, 1.5):
            with pytest.raises(PolicyError, match='keep_high'):
                Policy(cat_weight_dict={'hw': 1}, cat_keep_dict={'hw': n})


class TestAudit:
    def test_what_was_counted_is_named(self, f_scope_puz):
        policy = policy_puz()
        gradebook, df = policy(f_scope_puz)
        log = build_log(gradebook, policy, df)

        alice = next(e for e in log['alice@u.edu'] if e['kind'] == 'keep')
        assert 'puzzle1 (100%)' in alice['text']
        assert 'puzzle2 (90%)' in alice['text']
        # her 20% was not one of the two
        assert 'puzzle3' not in alice['text']

        # bob is short of the number, and his zero has a name of its own
        bob = next(e for e in log['bob@u.edu'] if e['kind'] == 'keep')
        assert 'puzzle1 (80%)' in bob['text'] and '(0%)' in bob['text']

    def test_a_zero_with_no_score_behind_it_says_so(self, f_scope_puz):
        """ waived, canvas-excused or not yet graded: nothing to quote """
        def keep_log(*ass_list):
            policy = policy_puz(waive_dict={'bob@u.edu': list(ass_list)})
            gradebook, df = policy(f_scope_puz)
            log = build_log(gradebook, policy, df)
            return next(e['text'] for e in log['bob@u.edu']
                        if e['kind'] == 'keep')

        assert 'zero for want of a score' in keep_log(
            'puzzle2', 'puzzle3', 'puzzle4')
        # nothing left to name at all, the shape a planned category has
        assert 'no score at all' in keep_log(
            'puzzle1', 'puzzle2', 'puzzle3', 'puzzle4')


class TestReport:
    def test_the_two_rules_share_one_column(self, f_scope_puz):
        """ and a keep_high the category cannot hold is a warning, not an
        error: the grades it gives are still the ones meant """
        report = build_report(
            Policy(cat_weight_dict={'puzzle': 1, 'hw': 1},
                   cat_keep_dict={'puzzle': 9}, cat_drop_dict={'hw': 1}),
            str(f_scope_puz))
        text = render(report)

        assert 'drop/keep' in text
        assert 'keep 9' in text and 'drop 1' in text
        assert any('keep_high' in s for s in report.warn_list)
        assert report.ok

    def test_check_and_grading_word_it_identically(self, tmp_path):
        """ the page shows the report's warnings and grading's, so any
        difference in wording reads as a second, separate problem.  extra
        credit is what used to split them: it is not one of the assignments
        keep_high can count, and only one of the two knew that
        """
        f = write_scope(tmp_path / 'scope.csv',
                        {'Puzzle1': 10, 'Puzzle2': 10, 'Puzzle3': 10},
                        [{'email': 'a@u.edu', 'scores': {'Puzzle1': 10}}])
        policy = Policy(cat_weight_dict={'puzzle': 1},
                        cat_keep_dict={'puzzle': 3},
                        extra_list=['puzzle3'])

        with pytest.warns(UserWarning) as record:
            policy(f)
        said_list = [str(w.message) for w in record]

        rule_list = [s for s in build_report(policy, str(f)).warn_list
                     if 'keep_high' in s]
        assert rule_list
        for text in rule_list:
            assert text in said_list

    def test_a_rule_set_to_zero_is_warned_about(self, f_scope_puz):
        """ and shown as "keep 0" rather than as no rule, so that the report
        and the file say the same thing """
        report = build_report(
            Policy(cat_weight_dict={'puzzle': 1, 'hw': 1},
                   cat_keep_dict={'puzzle': 0}), str(f_scope_puz))

        assert any('keep_high is 0' in s for s in report.warn_list)
        assert 'keep 0' in render(report)
        assert report.ok


class TestEdit:
    def test_sets_and_clears_the_count(self):
        out = edit.apply('category:\n  weight:\n    puzzle: 1\n',
                         'set_keep_high', dict(cat='puzzle', n=2))
        assert yaml.load(out)['category']['keep_high'] == {'puzzle': 2}

        out = edit.apply(out, 'clear_rule', dict(cat='puzzle'))
        assert not yaml.load(out)['category']['keep_high']

    def test_a_zero_is_a_rule_the_file_keeps(self):
        """ the widget writes it the moment the rule is picked, before any
        number is typed.  discarding it put the select back where it was,
        which reads as a page that is not responding """
        out = edit.apply('category:\n  weight:\n    puzzle: 1\n',
                         'set_keep_high', dict(cat='puzzle', n=0))

        assert yaml.load(out)['category']['keep_high'] == {'puzzle': 0}

    def test_a_zero_still_replaces_the_other_rule(self):
        out = edit.apply('category:\n  weight:\n    hw: 1\n'
                         '  drop_low:\n    hw: 2\n',
                         'set_keep_high', dict(cat='hw', n=0))
        data = yaml.load(out)

        assert data['category']['keep_high'] == {'hw': 0}
        assert not data['category']['drop_low']

    def test_the_two_rules_replace_each_other(self):
        """ exclusive, so the widget cannot leave both behind """
        out = edit.apply('category:\n  weight:\n    hw: 1\n'
                         '  drop_low:\n    hw: 2\n',
                         'set_keep_high', dict(cat='hw', n=3))
        data = yaml.load(out)
        assert data['category']['keep_high'] == {'hw': 3}
        assert not data['category']['drop_low']

        data = yaml.load(edit.apply(out, 'set_drop_low', dict(cat='hw', n=1)))
        assert data['category']['drop_low'] == {'hw': 1}
        assert not data['category']['keep_high']

    def test_setting_one_rule_does_not_invent_the_other(self):
        """ a section the file never had is one the user never wanted """
        out = edit.apply('category:\n  weight:\n    hw: 1\n',
                         'set_drop_low', dict(cat='hw', n=1))

        assert 'keep_high' not in out

    def test_clearing_a_rule_that_was_never_there_writes_nothing(self):
        bare = 'category:\n  weight:\n    hw: 1\n'
        out = edit.apply(bare, 'clear_rule', dict(cat='hw'))

        assert 'keep_high' not in out and 'drop_low' not in out

    def test_removing_a_category_takes_its_rule_with_it(self):
        out = edit.apply('category:\n  weight:\n    hw: 1\n'
                         '  keep_high:\n    hw: 3\n',
                         'remove_category', dict(cat='hw'))

        assert not yaml.load(out)['category']['keep_high']


class TestWeb:
    def test_the_form_reads_it(self):
        state = web.form_state(YAML_PUZ)

        cat = next(c for c in state['cat_list'] if c['name'] == 'puzzle')
        assert cat['keep_high'] == 2
        # None, not 0: the page has to tell "no rule" from a rule set to 0,
        # or picking one and typing nothing looks like nothing happened
        assert cat['drop_low'] is None

    def test_the_form_tells_a_zero_from_no_rule(self):
        state = web.form_state('category:\n  weight:\n    hw: 1\n'
                               '  keep_high:\n    hw: 0\n')

        cat = state['cat_list'][0]
        assert cat['keep_high'] == 0
        assert cat['drop_low'] is None

    def test_raw_is_the_grade_without_the_rule(self, f_scope_puz):
        """ the inspector's 'before' has to have keep_high switched off, or
        the toggle shows the same number twice """
        res = web.grade(f_scope_puz.read_text(), YAML_PUZ)
        assert res['ok'], res['error']

        pair = res['value_dict']['cat:puzzle']
        idx = [s['email'] for s in res['student_list']].index('alice@u.edu')
        # her best 2 are 100% and 90%; every puzzle counted is 21 of 40
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

        assert 'keep_high' in yaml_text
        assert web.check_policy(csv_text, yaml_text)['ok']
