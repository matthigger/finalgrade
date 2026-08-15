""" the report that says what a policy would do, before it does it

Written against the Report rather than the rendered text wherever the point
is a fact about grading; render() is only asserted on where the point is that
a human can see the fact.
"""
import pytest

from finalgrade.check import build_report, render
from finalgrade.policy import Policy


class TestMapping:
    def test_category_catches_assignments(self, f_scope_std):
        report = build_report(
            Policy(cat_weight_dict={'hw': 50, 'quiz': 50}), str(f_scope_std))

        cat_dict = {cat.name: cat.ass_list for cat in report.cat_list}
        assert cat_dict == {'hw': ['hw1', 'hw2', 'hw3'], 'quiz': ['quiz1']}
        assert report.ok

    def test_weight_is_normalized(self, f_scope_std):
        """ weights need not sum to 100, so the report shows the share """
        report = build_report(
            Policy(cat_weight_dict={'hw': 3, 'quiz': 1}), str(f_scope_std))

        frac_dict = {cat.name: cat.weight_frac for cat in report.cat_list}
        assert frac_dict == {'hw': .75, 'quiz': .25}

    def test_category_matching_nothing_is_an_error(self, f_scope_std):
        report = build_report(
            Policy(cat_weight_dict={'hw': 50, 'exam': 50}), str(f_scope_std))

        assert not report.ok
        assert any('exam' in s for s in report.error_list)

    def test_every_problem_at_once(self, f_scope_std):
        """ the reason this exists: average() raises on the first error, so
        the unmatched category used to hide the uncategorized assignment """
        report = build_report(
            Policy(cat_weight_dict={'hw': 50, 'exam': 50}), str(f_scope_std))

        assert any('exam' in s for s in report.error_list)
        assert 'quiz1' in report.ass_problem_dict

    def test_assignment_in_no_category_is_blamed_on_it(self, f_scope_std):
        """ against the assignment, so the page can show it on that row
        rather than in a list of complaints somewhere else """
        report = build_report(
            Policy(cat_weight_dict={'hw': 100}), str(f_scope_std))

        ass_dict = {ass.name: ass.cat_list for ass in report.ass_list}
        assert ass_dict['quiz1'] == []
        assert any('no category' in s
                   for s in report.ass_problem_dict['quiz1'])
        # and not also in the general list: said twice, fixed once
        assert not any('quiz1' in s for s in report.warn_list)
        # a category that catches everything it names is still gradeable
        assert report.ok

    def test_assignment_in_two_categories_is_blamed_on_it(self, f_scope_std):
        """ 'hw' and 'w' both catch every hw: substring matching's own trap """
        report = build_report(
            Policy(cat_weight_dict={'hw': 50, 'w': 50}), str(f_scope_std))

        ass_dict = {ass.name: ass.cat_list for ass in report.ass_list}
        assert ass_dict['hw1'] == ['hw', 'w']
        assert any('counts twice' in s
                   for s in report.ass_problem_dict['hw1'])

    def test_no_category_weights_by_point(self, f_scope_std):
        report = build_report(Policy(), str(f_scope_std))

        assert report.weight_by_point
        assert report.cat_list == []
        assert report.ok

    def test_matches_what_average_actually_does(self, f_scope_std):
        """ the report is only worth anything if it agrees with grading """
        policy = Policy(cat_weight_dict={'hw': 50, 'quiz': 50})
        report = build_report(policy, str(f_scope_std))

        gradebook, df_grade = policy(str(f_scope_std))
        for cat in report.cat_list:
            assert f'mean_{cat.name}' in df_grade.columns


class TestSubmitted:
    def test_counts_submissions(self, f_scope_std):
        report = build_report(Policy(), str(f_scope_std))

        ass_dict = {ass.name: (ass.n_complete, ass.n_student)
                    for ass in report.ass_list}
        # carol scored 0 on hw1, which counts as not submitted (as it does
        # for exclude_complete_thresh)
        assert ass_dict['hw1'] == (2, 3)
        assert ass_dict['hw2'] == (3, 3)

    def test_student_count_follows_email_list(self, f_scope_std):
        report = build_report(
            Policy(email_list=['alice@u.edu']), str(f_scope_std))

        assert report.n_student == 1


class TestExcluded:
    def test_excluded_says_which_rule_dropped_it(self, f_scope_std):
        report = build_report(
            Policy(remove_list=['quiz']), str(f_scope_std))

        excluded_dict = {ass.name: ass.excluded_by
                         for ass in report.excluded_list}
        assert excluded_dict == {'quiz1': 'assignments/exclude: quiz'}
        assert 'quiz1' not in [ass.name for ass in report.ass_list]

    def test_completion_threshold_names_itself(self, f_scope_std):
        report = build_report(
            Policy(exclude_complete_thresh=.9), str(f_scope_std))

        excluded_dict = {ass.name: ass.excluded_by
                         for ass in report.excluded_list}
        # hw1 has 2 of 3 submitted, below the .9 threshold
        assert 'exclude_complete_thresh' in excluded_dict['hw1']

    def test_excluded_keeps_its_submission_count(self, f_scope_std):
        """ counted before the pipeline ran, or it would be unanswerable """
        report = build_report(
            Policy(remove_list=['quiz']), str(f_scope_std))

        assert report.excluded_list[0].n_complete == 3


class TestBadInput:
    def test_unreadable_csv_is_an_error_not_a_traceback(self, tmp_path):
        f_csv = tmp_path / 'nonsense.csv'
        f_csv.write_text('not,a,gradebook\n1,2,3\n')

        report = build_report(Policy(), str(f_csv))

        assert not report.ok

    def test_config_error_is_collected(self, f_scope_std):
        """ prepare() raising must still leave a report to look at """
        report = build_report(
            Policy(sub_dict={'nope': ['also_nope']}), str(f_scope_std))

        assert not report.ok
        assert any('nope' in s for s in report.error_list)


class TestRender:
    def test_shows_the_split(self, f_scope_std):
        text = render(build_report(
            Policy(cat_weight_dict={'hw': 50, 'quiz': 50}), str(f_scope_std)))

        assert 'hw1, hw2, hw3' in text
        assert 'policy looks usable' in text

    def test_flags_the_uncaught_assignment_inline(self, f_scope_std):
        text = render(build_report(
            Policy(cat_weight_dict={'hw': 100}), str(f_scope_std)))

        # the warning is repeated on the assignment's own row: that is the
        # row someone reads when asking "why is quiz1 not counting?"
        line = next(ln for ln in text.splitlines() if ln.startswith('quiz1'))
        assert 'none' in line

    def test_says_when_grading_would_stop(self, f_scope_std):
        text = render(build_report(
            Policy(cat_weight_dict={'exam': 100}), str(f_scope_std)))

        assert 'policy has an error' in text

    def test_late_penalty_is_legible(self, f_scope_std):
        text = render(build_report(
            Policy(cat_weight_dict={'hw': 100},
                   cat_late_dict={'hw': {'penalty_per_day': .15,
                                         'excuse_day': 3}}),
            str(f_scope_std)))

        assert '15%/day' in text
        assert '3 excused' in text


class TestCli:
    def test_check_exits_nonzero_on_error(self, f_scope_std, write_policy,
                                          capsys):
        from finalgrade.__main__ import main, parser

        f_policy = write_policy('category:\n  weight:\n    exam: 100\n')
        args = parser.parse_args(
            ['check', str(f_scope_std), '--policy', str(f_policy)])

        with pytest.raises(SystemExit) as exc_info:
            main(args)

        assert exc_info.value.code == 2
        assert 'exam' in capsys.readouterr().out

    def test_check_is_quiet_and_clean_when_ok(self, f_scope_std, write_policy,
                                              capsys):
        from finalgrade.__main__ import main, parser

        f_policy = write_policy('category:\n  weight:\n    hw: 50\n'
                                '    quiz: 50\n')
        args = parser.parse_args(
            ['check', str(f_scope_std), '--policy', str(f_policy)])
        main(args)

        assert 'policy looks usable' in capsys.readouterr().out

    def test_check_writes_no_grades(self, f_scope_std, write_policy):
        """ check is a read: it must not leave grade_full.csv behind """
        from finalgrade.__main__ import main, parser

        f_policy = write_policy('category:\n  weight:\n    hw: 100\n')
        args = parser.parse_args(
            ['check', str(f_scope_std), '--policy', str(f_policy)])
        main(args)

        assert not (f_scope_std.parent / 'grade_full.csv').exists()
