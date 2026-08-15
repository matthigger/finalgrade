import pytest

import finalgrade
from finalgrade.policy import *
from finalgrade.errors import PolicyError, GradebookError
from finalgrade.gradebook import *

test_folder = pathlib.Path(finalgrade.__file__).parents[1] / 'test'


@pytest.fixture
def gradebook():
    return Gradebook(str(test_folder / 'scope.csv'))


class TestGradebook:
    def test_init(self, gradebook):
        df_perc_exp = pd.read_csv(test_folder / 'df_perc_exp.csv', \
                                  index_col='email')
        df_meta_exp = pd.read_csv(test_folder / 'df_meta_exp.csv',
                                  index_col='email',
                                  converters={'sid': str, 'crn': str})

        pd.testing.assert_frame_equal(df_meta_exp, gradebook.df_meta,
                                      check_dtype=False)
        pd.testing.assert_frame_equal(df_perc_exp, gradebook.df_perc)
        np.testing.assert_allclose([1, 2, 3, 4], gradebook.points)
        np.testing.assert_allclose([0, 1, 2, 3, 4],
                                   gradebook.df_lateday.loc[:, 'hw1'])

    def test_waive(self, gradebook):
        waive_dict = {'last0@nu.edu': ['hw1', ],
                      'last1@nu.edu': ['hw1', 'hw2']}
        gradebook.waive(waive_dict)

        assert np.isnan(gradebook.df_perc.loc['last0@nu.edu', 'hw1'])
        assert np.isnan(gradebook.df_perc.loc['last1@nu.edu', 'hw1'])
        assert np.isnan(gradebook.df_perc.loc['last1@nu.edu', 'hw2'])

        assert np.isnan(gradebook.df_lateday.loc['last0@nu.edu', 'hw1'])
        assert np.isnan(gradebook.df_lateday.loc['last1@nu.edu', 'hw1'])
        assert np.isnan(gradebook.df_lateday.loc['last1@nu.edu', 'hw2'])

    def test_substitute(self, gradebook):
        sub_dict = {'hw2': ['hw3'],
                    'hw1': ['hw1', 'hw2']}
        gradebook.substitute(sub_dict)

        np.testing.assert_allclose([1, 1, 1, 1, 1], gradebook.df_perc['hw2'])
        np.testing.assert_allclose([1, 0, 0, .5, .5], gradebook.df_perc['hw1'])

    def test_remove0(self, gradebook):
        ass = 'hw1'
        gradebook.remove(ass)

        assert ass not in gradebook.df_perc.columns
        assert ass not in gradebook.df_lateday.columns
        assert ass not in gradebook.ass_list
        np.testing.assert_allclose([2, 3, 4], gradebook.points)

    def test_remove1(self, gradebook):
        ass = 'hw'
        gradebook.remove(ass, multi=True)

        np.testing.assert_allclose([4], gradebook.points)

    def test_get_late_penalty(self, gradebook):
        # remember: students use [0, 1, 2, 3, 4] late days on 'hw1'
        _, s_penalty = gradebook.get_late_penalty(cat='hw1',
                                                  penalty_per_day=.1,
                                                  excuse_day=0)
        penalty_exp = np.array([0, -.1, -.2, -.3, -.4])
        np.testing.assert_allclose(penalty_exp, s_penalty)

        # with 3 assignments in category, mean penalty goes down to 1/3
        _, s_penalty = gradebook.get_late_penalty(cat='hw', penalty_per_day=.1,
                                                  excuse_day=0)
        np.testing.assert_allclose(penalty_exp / 3, s_penalty)

        # waive any lateness on last4@nu.edu's hw1 assignment
        _, s_penalty = gradebook.get_late_penalty(
            cat='hw1',
            penalty_per_day=.1,
            excuse_day=0,
            waive_dict={'last4@nu.edu': ['hw1', ]})
        penalty_exp = np.array([0, -.1, -.2, -.3, 0])
        np.testing.assert_allclose(penalty_exp, s_penalty)

        # with 1 excused late date for all students, penalties drop a notch
        _, s_penalty = gradebook.get_late_penalty(cat='hw1',
                                                  penalty_per_day=.1,
                                                  excuse_day=1)
        penalty_exp = np.array([0, 0, -.1, -.2, -.3])
        np.testing.assert_allclose(penalty_exp, s_penalty)

        # excusing different number of assignments per student
        _, s_penalty = \
            gradebook.get_late_penalty(cat='hw1', penalty_per_day=.1,
                                       excuse_day=1,
                                       excuse_day_offset={'last4@nu.edu': 3,
                                                          'last3@nu.edu': -1})
        penalty_exp = np.array([0, 0, -.1, -.3, 0])
        np.testing.assert_allclose(penalty_exp, s_penalty)

    def test_average(self, gradebook):
        df_grade = gradebook.average()
        np.testing.assert_allclose([.8, .7, .7, .8, .8], df_grade['mean'])
        assert ['B-', 'C-', 'C-', 'B-', 'B-'] == df_grade['letter'].tolist()

        df_grade = gradebook.average(cat_weight_dict={'hw': 3, 'quiz': 1})
        np.testing.assert_allclose([2 / 3, .5, .5, 2 / 3, 2 / 3],
                                   df_grade['mean_hw'])
        np.testing.assert_allclose([1, 1, 1, 1, 1], df_grade['mean_quiz'])
        np.testing.assert_allclose([.75, .625, .625, .75, .75],
                                   df_grade['mean'])

        df_grade = gradebook.average(cat_weight_dict={'hw': 1, 'quiz': 0},
                                     cat_drop_dict={'hw': 1})
        np.testing.assert_allclose([1, .75, .75, .8, .8], df_grade['mean'])

        kwargs = {'penalty_per_day': 1}
        df_grade = gradebook.average(cat_weight_dict={'hw': 1, 'quiz': 0},
                                     cat_late_dict={'hw': kwargs})
        np.testing.assert_allclose([2 / 3, 1 / 6, 0, 0, 0],
                                   df_grade['mean_hw'])
        np.testing.assert_allclose([0, -1, -2, -3, -4],
                                   df_grade['late days remain (hw)'])

        kwargs = {'penalty_per_day': 1,
                  'excuse_day': 2}
        df_grade = gradebook.average(cat_weight_dict={'hw': 1, 'quiz': 0},
                                     cat_late_dict={'hw': kwargs})
        np.testing.assert_allclose([2, 1, 0, -1, -2],
                                   df_grade['late days remain (hw)'])

        with pytest.warns(UserWarning):
            # warns other assignments not included
            gradebook.average(cat_weight_dict={'hw1': 1})

        with pytest.warns(UserWarning):
            # warns hw1 in two categories
            gradebook.average(cat_weight_dict={'hw': 1, 'hw1': 1, 'quiz': 1})

        # waive all assignments in a category for a student (use only remaining
        # categories)
        gradebook.waive(waive_dict={'last3@nu.edu': ['hw1', 'hw2', 'hw3']})
        df_grade = gradebook.average(cat_weight_dict={'hw': 1, 'quiz': 1})
        assert df_grade.loc['last3@nu.edu', 'mean'] == 1

    def test_average_full(self, gradebook):
        df_full = gradebook.average_full()

        # should contain meta columns, grade columns, and percentage columns
        assert 'firstname' in df_full.columns
        assert 'lastname' in df_full.columns
        assert 'mean' in df_full.columns
        assert 'letter' in df_full.columns
        assert 'hw1' in df_full.columns
        assert df_full.shape[0] == 5

    def test_remove_thresh(self, gradebook):
        # all assignments have 100% completion in test data; thresh=0 removes
        # nothing (completeness is > 0 for all)
        n_before = len(gradebook.ass_list)
        gradebook.remove_thresh(min_complete_thresh=0)
        assert len(gradebook.ass_list) == n_before

    def test_remove_thresh_high(self, gradebook):
        # waive hw1 for all students so it has 0% completion, then set high
        # threshold
        for email in gradebook.df_perc.index:
            gradebook.df_perc.loc[email, 'hw1'] = 0
        gradebook.remove_thresh(min_complete_thresh=0.5)
        assert 'hw1' not in gradebook.ass_list

    def test_get_late_penalty_negative_raises(self, gradebook):
        with pytest.raises(PolicyError):
            gradebook.get_late_penalty(cat='hw1', penalty_per_day=-0.1)

    def test_waive_nonexistent_warns(self, gradebook):
        waive_dict = {'last0@nu.edu': ['nonexistent_hw']}
        with pytest.warns(UserWarning, match='waive-fail'):
            gradebook.waive(waive_dict)

    def test_prune_email(self, gradebook):
        email_list = ['last0@nu.edu', 'not-in-list@nu.edu']
        with pytest.warns():
            gradebook.prune_email(email_list)

        assert gradebook.df_perc.shape[0] == 1
        assert gradebook.df_meta.shape[0] == 1
        assert gradebook.df_lateday.shape[0] == 1

        email_list = ['last0@gmail.com']
        gradebook.prune_email(email_list, ignore_suffix=True)
        assert gradebook.df_perc.shape[0] == 1

    def test_prune_email_no_ignore_suffix(self, gradebook):
        email_list = ['last0@nu.edu', 'last1@nu.edu']
        gradebook.prune_email(email_list, ignore_suffix=False)
        assert gradebook.df_perc.shape[0] == 2
        assert gradebook.df_meta.shape[0] == 2
        assert gradebook.df_lateday.shape[0] == 2

    def test_resolve_email_exact(self, gradebook):
        """_resolve_email returns exact match when present"""
        assert gradebook._resolve_email('last0@nu.edu') == 'last0@nu.edu'

    def test_resolve_email_prefix(self, gradebook):
        """_resolve_email matches by prefix when suffix differs"""
        assert gradebook._resolve_email('last0@other.edu') == 'last0@nu.edu'

    def test_resolve_email_no_match(self, gradebook):
        """_resolve_email returns original if no prefix match"""
        assert gradebook._resolve_email('nonexist@x.edu') == 'nonexist@x.edu'

    def test_waive_by_prefix(self, gradebook):
        """waive should work with a different email suffix (issue #9)"""
        waive_dict = {'last0@husky.neu.edu': ['hw1']}
        gradebook.waive(waive_dict)
        assert np.isnan(gradebook.df_perc.loc['last0@nu.edu', 'hw1'])

    def test_late_penalty_excuse_offset_by_prefix(self, gradebook):
        """excuse_day_offset should match by email prefix (issue #9)"""
        _, s_pen = gradebook.get_late_penalty(
            cat='hw1', penalty_per_day=.1, excuse_day=0,
            excuse_day_offset={'last4@different.edu': 4})
        # last4 is 4 days late, with 4 excuse days → 0 penalty
        assert s_pen.loc['last4@nu.edu'] == 0.0

    def test_late_minutes_raw(self, gradebook):
        """df_late_minutes stores raw minutes (no grace period applied)"""
        # hw1 lateness in scope.csv: 00:00:00, 24:00:00, 48:00:00, 72:00:00,
        # 96:00:00
        expected_minutes = [0, 24 * 60, 48 * 60, 72 * 60, 96 * 60]
        np.testing.assert_allclose(expected_minutes,
                                   gradebook.df_late_minutes['hw1'])

    def test_compute_lateday_default(self, gradebook):
        """Default 60-min grace gives same late days as before"""
        df_late = gradebook.get_lateday(grace_period_minutes=60)
        np.testing.assert_allclose([0, 1, 2, 3, 4], df_late['hw1'])

    def test_compute_lateday_zero_grace(self, gradebook):
        """With 0 grace, any lateness counts"""
        df_late = gradebook.get_lateday(grace_period_minutes=0)
        # 00:00:00 → 0 days, 24:00:00 → 1 day, etc.
        np.testing.assert_allclose([0, 1, 2, 3, 4], df_late['hw1'])

    def test_compute_lateday_large_grace(self, gradebook):
        """Grace period larger than 24h should forgive first day"""
        df_late = gradebook.get_lateday(grace_period_minutes=25 * 60)
        # 0h→0, 24h→0 (under 25h grace), 48h→1, 72h→2, 96h→3
        np.testing.assert_allclose([0, 0, 1, 2, 3], df_late['hw1'])

    def test_grace_period_boundary_issue16(self, tmp_path):
        """Issue #16: 49h lateness with 60-min grace should be 2 days, not 3.

        Old formula: ceil(49/24) = 3 (bug)
        New formula: ceil((49*60 - 60) / 1440) = ceil(2880/1440) = 2
        """
        # create CSV with a single student 49 hours late
        csv_content = (
            'First Name,Last Name,SID,Email,section_name,'
            'HW1,HW1 - Max Points,HW1 - Submission Time,'
            'HW1 - Lateness (H:M:S)\n'
            'Jane,Doe,999S,jane@uni.edu,sec1,'
            '8,10,2023-01-01 12:00:00 -0500,49:00:00\n'
        )
        f = tmp_path / 'scope.csv'
        f.write_text(csv_content)
        gb = Gradebook(str(f))

        # with default 60-min grace: 49h → 2 days (NOT 3)
        df_late = gb.get_lateday(grace_period_minutes=60)
        assert df_late.loc['jane@uni.edu', 'hw1'] == 2

    def test_grace_period_minutes_in_late_penalty(self, gradebook):
        """grace_period_minutes passed through get_late_penalty"""
        # with default 60-min grace, student1 has 1 late day on hw1
        _, s_pen = gradebook.get_late_penalty(
            cat='hw1', penalty_per_day=.1, excuse_day=0,
            grace_period_minutes=60)
        assert s_pen.loc['last1@nu.edu'] == pytest.approx(-.1)

        # with 25-hour grace, student1's 24h lateness is forgiven
        _, s_pen = gradebook.get_late_penalty(
            cat='hw1', penalty_per_day=.1, excuse_day=0,
            grace_period_minutes=25 * 60)
        assert s_pen.loc['last1@nu.edu'] == 0.0

    def test_grace_period_via_config(self, tmp_path):
        """grace_period_minutes works end-to-end through Policy"""
        import shutil
        f_scope = tmp_path / 'scope.csv'
        shutil.copy(test_folder / 'scope.csv', f_scope)

        policy_content = """\
category:
  weight:
    hw: 1
    quiz: 0
  drop_low: null
  late_penalty:
    hw:
      penalty_per_day: 1
      excuse_day: 0
      grace_period_minutes: 1500
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
        _, df_full = policy(f_scope)

        # 1500 min = 25h grace → student1 (24h late) is forgiven
        # so student1 has 0 unexcused late days
        assert df_full.loc['last1@nu.edu', 'late days remain (hw)'] == 0
