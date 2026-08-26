""" the api the browser build calls

These run in cpython, not in a browser: what they protect is the contract the
page depends on -- that every value crossing into javascript is plain data,
and that the browser's answer is the command line's answer.  Whether pyodide
can load the wheel is a question for the build, not for pytest.
"""
import json
import pathlib

import pytest

from finalgrade import web
from finalgrade.policy import Policy


@pytest.fixture
def csv_text(f_scope_std):
    return f_scope_std.read_text()


YAML_STD = 'category:\n  weight:\n    hw: 50\n    quiz: 50\n'

# the same, with something to say about each of the three students
YAML_STUDENT = """\
category:
  weight:
    hw: 50
    quiz: 50
  late_penalty:
    hw:
      penalty_per_day: .1
      excuse_day: 1
      excuse_day_offset:
        alice@u.edu: 2
waive:
  bob@u.edu: hw2
note:
  carol@u.edu: a private word
"""


def is_plain(obj):
    """ True when obj is something json can hold (so js can receive it) """
    try:
        json.dumps(obj)
    except (TypeError, ValueError):
        return False
    return True


class TestLoad:
    def test_describes_the_csv(self, csv_text):
        info = web.load_csv(csv_text)

        assert info['ok']
        assert info['source'] == 'gradescope'
        assert info['n_student'] == 3
        assert [a['name'] for a in info['ass_list']] == \
            ['hw1', 'hw2', 'hw3', 'quiz1']

    def test_is_plain_data(self, csv_text):
        assert is_plain(web.load_csv(csv_text))

    def test_bad_csv_is_a_message_not_an_exception(self):
        info = web.load_csv('not,a,gradebook\n1,2,3\n')

        assert not info['ok']
        assert info['error']

    def test_warnings_come_back_as_values(self, tmp_path):
        """ the page shows them; nothing here should print to a console """
        from conftest import ASSIGN_STD, STUDENT_STD, write_scope

        f_scope = write_scope(tmp_path / 'scope.csv',
                              dict(ASSIGN_STD, Survey=0), STUDENT_STD)
        info = web.load_csv(f_scope.read_text())

        assert any('0 points' in s for s in info['warn_list'])
        assert info['zero_point_list'] == ['survey']


class TestCheck:
    def test_reports_the_split(self, csv_text):
        rep = web.check_policy(csv_text, YAML_STD)

        assert rep['ok']
        cat_dict = {c['name']: c['ass_list'] for c in rep['cat_list']}
        assert cat_dict == {'hw': ['hw1', 'hw2', 'hw3'], 'quiz': ['quiz1']}

    def test_is_plain_data(self, csv_text):
        assert is_plain(web.check_policy(csv_text, YAML_STD))

    def test_names_the_users_file_not_a_temp_path(self, csv_text):
        rep = web.check_policy(csv_text, YAML_STD, name='spring25.csv')

        assert rep['f_grade'] == 'spring25.csv'
        assert 'spring25.csv' in rep['text']
        assert '/tmp' not in rep['text']

    def test_unparseable_yaml_is_a_message(self, csv_text):
        rep = web.check_policy(csv_text, 'category:\n\tweight: 1\n')

        assert not rep['ok']
        assert rep['error_list']

    def test_agrees_with_build_report(self, csv_text, f_scope_std):
        """ the page must show what `check` shows """
        from finalgrade.check import build_report

        rep_web = web.check_policy(csv_text, YAML_STD)
        rep_cli = build_report(Policy(cat_weight_dict={'hw': 50, 'quiz': 50}),
                               str(f_scope_std))

        assert rep_web['ok'] == rep_cli.ok
        assert [c['ass_list'] for c in rep_web['cat_list']] == \
            [c.ass_list for c in rep_cli.cat_list]


class TestSamePolicyAsTheCli:
    """ the page grades with the whole policy, not most of it

    web.grade averages the gradebook twice, so it spells out what to average
    with -- and a setting left out of that call works on the command line
    and silently does nothing in the browser, which is the worst of both.
    """

    def test_every_setting_reaches_the_average(self, csv_text, f_scope_std):
        import inspect as inspect_mod

        from finalgrade.gradebook import Gradebook

        arg_set = set(inspect_mod.signature(Gradebook.average).parameters)
        arg_set.discard('self')

        assert arg_set == set(Policy().average_kwargs())

    def test_extra_credit_moves_the_browser_grade(self, csv_text,
                                                  f_scope_std):
        yaml_extra = YAML_STD + 'assignments:\n  extra_credit:\n    - hw3\n'

        plain = web.grade(csv_text, YAML_STD)
        extra = web.grade(csv_text, yaml_extra)

        assert plain['ok'] and extra['ok']
        # hw3's 10 points leave the denominator, so nobody can be worse off
        # and alice, who scored on it, must be better off
        assert extra['mean_avg'] > plain['mean_avg']

        _, df_cli = Policy(cat_weight_dict={'hw': 50, 'quiz': 50},
                           extra_list=['hw3'])(str(f_scope_std))
        assert extra['csv'] == df_cli.to_csv()


class TestGrade:
    def test_returns_a_csv(self, csv_text):
        res = web.grade(csv_text, YAML_STD)

        assert res['ok']
        assert res['csv'].startswith('email,')
        assert res['n_student'] == 3

    def test_is_plain_data(self, csv_text):
        assert is_plain(web.grade(csv_text, YAML_STD))

    def test_agrees_with_the_command_line(self, csv_text, f_scope_std):
        """ the whole claim of the browser build, in one assertion """
        res = web.grade(csv_text, YAML_STD)

        policy = Policy(cat_weight_dict={'hw': 50, 'quiz': 50})
        gradebook, df_grade = policy(str(f_scope_std))

        assert res['csv'] == df_grade.to_csv()

    def test_letters_are_ordered_by_grade(self, csv_text):
        res = web.grade(csv_text, YAML_STD)

        from finalgrade.perc_to_letter import GRADE_THRESH
        order_list = [ltr for _, ltr in sorted(GRADE_THRESH.items(),
                                               reverse=True)]
        got_list = [l['letter'] for l in res['letter_list']]
        assert got_list == [ltr for ltr in order_list if ltr in got_list]

    def test_config_error_is_a_message(self, csv_text):
        res = web.grade(csv_text, 'category:\n  weight:\n    exam: 100\n')

        assert not res['ok']
        assert 'exam' in res['error']

    def test_distribution_matches_the_students(self, csv_text):
        res = web.grade(csv_text, YAML_STD)

        assert sum(l['n'] for l in res['letter_list']) == res['n_student']
        assert len(res['mean_list']) == res['n_student']


class TestSeed:
    def test_seeds_from_the_csv(self, csv_text):
        text = web.seed_policy(csv_text, 'scope.csv')

        assert 'quiz1' in text
        assert 'scope.csv' in text

    def test_bad_csv_still_yields_an_editable_config(self):
        text = web.seed_policy('not,a,gradebook\n1,2,3\n')

        assert text == web.default_yaml()

    def test_seeded_config_checks_clean(self, csv_text):
        """ what the page puts in the editor must not start out broken """
        rep = web.check_policy(csv_text, web.seed_policy(csv_text))

        assert rep['ok']


class TestRoster:
    def test_every_student_is_listed(self, csv_text):
        info = web.load_csv(csv_text)

        assert [s['email'] for s in info['student_list']] == \
            ['alice@u.edu', 'bob@u.edu', 'carol@u.edu']

    def test_names_come_along_for_searching(self, csv_text):
        info = web.load_csv(csv_text)

        alice = info['student_list'][0]
        assert alice['first'] == 'alice'
        assert alice['last'] == 'anders'


class TestFormState:
    def test_reads_the_categories(self, csv_text):
        state = web.form_state(YAML_STD)

        assert [(c['name'], c['weight'], c['weight_frac'])
                for c in state['cat_list']] == \
            [('hw', 50, .5), ('quiz', 50, .5)]

    def test_reads_drops_and_late(self):
        state = web.form_state(
            'category:\n  weight:\n    hw: 1\n  drop_low:\n    hw: 2\n'
            '  late_penalty:\n    hw:\n      penalty_per_day: .15\n')

        cat = state['cat_list'][0]
        assert cat['drop_low'] == 2
        assert cat['late'] == {'penalty_per_day': .15}

    def test_reads_waivers_of_both_kinds(self):
        state = web.form_state('waive:\n  a@u.edu: hw1, hw2\n'
                               'waive_late:\n  b@u.edu: hw3\n')

        assert state['waive_list'] == [
            dict(email='a@u.edu', ass_list=['hw1', 'hw2'])]
        assert state['waive_late_list'] == [
            dict(email='b@u.edu', ass_list=['hw3'])]

    def test_a_yaml_list_of_waivers_reads_the_same(self):
        """ the readme's comma form and a real list must look alike here """
        state = web.form_state('waive:\n  a@u.edu:\n    - hw1\n    - hw2\n')

        assert state['waive_list'][0]['ass_list'] == ['hw1', 'hw2']

    def test_is_plain_data(self, csv_text):
        assert is_plain(web.form_state(web.seed_policy(csv_text)))

    def test_half_typed_yaml_says_so_rather_than_raising(self):
        state = web.form_state('category:\n\tweight: 1\n')

        assert not state['ok']
        assert state['error']

    def test_empty_config_is_empty_not_broken(self):
        state = web.form_state('')

        assert state['ok']
        assert state['cat_list'] == []


class TestEditConfig:
    def test_applies_an_edit(self):
        res = web.edit_policy('', 'add_category', '{"cat": "hw"}')

        assert res['ok']
        assert 'hw' in res['yaml']

    def test_keeps_the_file_when_an_edit_cannot_apply(self):
        text = 'category:\n\tweight: 1\n'
        res = web.edit_policy(text, 'add_category', '{"cat": "hw"}')

        assert not res['ok']
        assert res['yaml'] == text

    def test_unknown_action(self):
        res = web.edit_policy('', 'drop_everything', '{}')

        assert not res['ok']

    def test_bad_json_is_a_message(self):
        res = web.edit_policy('', 'add_category', 'not json')

        assert not res['ok']
        assert res['yaml'] == ''

    def test_a_policy_built_only_by_edits_grades(self, csv_text, f_scope_std):
        """ end to end: what the widgets produce is what grading reads """
        yaml_text = web.seed_policy(csv_text)
        for action, args in (
                ('add_category', '{"cat": "hw"}'),
                ('add_category', '{"cat": "quiz"}'),
                ('set_drop_low', '{"cat": "hw", "n": 1}'),
                ('set_waive', '{"email": "alice@u.edu",'
                              ' "ass_list": ["hw1"]}')):
            res = web.edit_policy(yaml_text, action, args)
            assert res['ok'], res['error']
            yaml_text = res['yaml']

        assert web.check_policy(csv_text, yaml_text)['ok']

        result = web.grade(csv_text, yaml_text)
        assert result['ok']
        assert result['n_student'] == 3

        # the waiver the widget wrote is the waiver grading applied
        state = web.form_state(yaml_text)
        assert state['waive_list'] == [
            dict(email='alice@u.edu', ass_list=['hw1'])]


class TestStudentCsv:
    """ the file --per_student writes, for one student, on demand """

    def test_holds_the_whole_row(self, csv_text):
        res = web.student_csv(csv_text, YAML_STD, 'alice@u.edu')

        assert res['ok'], res.get('error')
        assert 'mean_hw' in res['csv']
        assert 'hw1' in res['csv']
        assert 'letter' in res['csv']

    def test_it_is_that_student_and_no_other(self, csv_text):
        res = web.student_csv(csv_text, YAML_STD, 'alice@u.edu')

        assert 'alice@u.edu' in res['csv']
        assert 'bob@u.edu' not in res['csv']

    def test_named_after_the_student(self, csv_text):
        res = web.student_csv(csv_text, YAML_STD, 'alice@u.edu')

        assert res['filename'] == 'anders_alice.csv'

    def test_the_page_can_predict_that_name(self, csv_text):
        """ the link says the filename before the file exists, so the page
        works it out itself -- from the same rule, or it would lie """
        import re

        info = web.load_csv(csv_text)

        def js_rule(stud):
            def safe(text):
                out = re.sub(r'[^a-zA-Z0-9\-_]', '_', str(text or ''))
                return out.strip('_') or 'unknown'
            last, first = safe(stud['last']), safe(stud['first'])
            if last == 'unknown' and first == 'unknown':
                return safe(stud['email'].split('@')[0]) + '.csv'
            return f'{last}_{first}.csv'

        for stud in info['student_list']:
            res = web.student_csv(csv_text, YAML_STD, stud['email'])
            assert res['filename'] == js_rule(stud), stud['email']

    def test_a_student_with_no_name(self, tmp_path):
        """ canvas exports sometimes have an id and nothing else """
        from conftest import ASSIGN_STD, write_scope

        f_scope = write_scope(tmp_path / 'scope.csv', ASSIGN_STD, [
            {'email': 'x9@u.edu', 'first': '', 'last': '', 'sid': '9S',
             'scores': {'HW1': 5}}])

        res = web.student_csv(f_scope.read_text(), '', 'x9@u.edu')

        assert res['filename'] == 'x9.csv'

    def test_matches_what_the_cli_writes(self, csv_text, f_scope_std,
                                         tmp_path):
        """ same file, so an emailed breakdown cannot disagree with a run """
        import pandas as pd

        from finalgrade.__main__ import main, parser

        policy = Policy(cat_weight_dict={'hw': 50, 'quiz': 50})
        _, df_grade = policy(str(f_scope_std))
        f_policy = tmp_path / 'policy.yaml'
        f_policy.write_text(YAML_STD)

        main(parser.parse_args(['grade', str(f_scope_std), '--policy',
                                str(f_policy), '--per_student', '-q']))

        f_cli = f_scope_std.parent / 'per_student' / 'anders_alice.csv'
        res = web.student_csv(csv_text, YAML_STD, 'alice@u.edu')

        assert res['csv'] == f_cli.read_text()
        assert 'alice' in pd.read_csv(f_cli).columns[1]
        # including the log at the end: the whole point of the file is that
        # it answers the question the grade provokes
        assert '\ncategory,' in res['csv']
        assert '\nfinal,' in res['csv']

    def test_the_log_is_appended_as_kind_then_text(self, csv_text):
        """ the two columns the rest of the file already uses """
        res = web.student_csv(csv_text, YAML_STD, 'carol@u.edu')

        assert res['ok']
        line_list = res['csv'].strip().split('\n')

        tail = [ln for ln in line_list
                if ln.startswith(('category,', 'final,'))]
        assert tail, res['csv']
        assert tail[-1].startswith('final,')
        assert 'final grade' in tail[-1]

        # and it comes after the numbers, rather than among them
        assert line_list.index(tail[0]) > line_list.index('mean_hw,0.4')

    def test_an_unknown_student(self, csv_text):
        res = web.student_csv(csv_text, YAML_STD, 'nobody@u.edu')

        assert not res['ok']
        assert 'nobody@u.edu' in res['error']

    def test_a_broken_config_is_a_message(self, csv_text):
        res = web.student_csv(csv_text, 'category:\n  weight:\n    no: 1\n',
                              'alice@u.edu')

        assert not res['ok']

    def test_is_plain_data(self, csv_text):
        assert is_plain(web.student_csv(csv_text, YAML_STD, 'alice@u.edu'))


class TestStudentPolicy:
    """ the one file an instructor posts for the class """

    def test_one_file_for_a_whole_class(self, csv_text):
        res = web.student_policy(csv_text, YAML_STUDENT)

        assert res['ok'], res.get('error')
        assert res['filename'] == 'policy_PUBLIC.yaml'
        for email in ('alice@u.edu', 'bob@u.edu', 'carol@u.edu'):
            assert email not in res['yaml']

    def test_it_grades_an_unadjusted_student_the_same(self, csv_text):
        """ the browser's claim, made once more for the student's own page

        A student types in what the export already says about them, and the
        page reaches the grade the instructor's run reached.
        """
        res = web.student_policy(csv_text, YAML_PLAIN)

        assert res['ok'], res.get('error')
        was = web.grade(csv_text, YAML_PLAIN)
        now = web.grade(filled_sheet(res['yaml'], ALICE_SCORE), res['yaml'])

        assert now['ok'], now.get('error')
        assert [s['mean'] for s in now['student_list']] == \
            [s['mean'] for s in was['student_list']
             if s['email'] == 'alice@u.edu']

    def test_the_term_s_work_travels_with_it(self, csv_text):
        """ without the roster a student has nothing to fill in """
        res = web.student_policy(csv_text, YAML_PLAIN)

        for ass in ('hw1', 'hw2', 'hw3', 'quiz1'):
            assert ass in res['yaml']

    def test_a_broken_policy_is_a_message(self, csv_text):
        res = web.student_policy(csv_text,
                                 'category:\n  weight:\n    no: 1\n')

        assert not res['ok']

    def test_is_plain_data(self, csv_text):
        assert is_plain(web.student_policy(csv_text, YAML_STUDENT))


YAML_HW1 = 'category:\n  weight:\n    hw: 100\n'

# singles nobody out, so the shared file is right for every one of them
YAML_PLAIN = YAML_STD


# what alice really got, on the standard three student csv
ALICE_SCORE = {'hw1': 10, 'hw2': 8, 'hw3': 6, 'quiz1': 10}


def filled_sheet(yaml_text, score_dict, day_dict=None):
    """ the sheet a posted policy makes, with those scores typed into it """
    import json

    sheet = web.student_sheet(yaml_text)
    assert sheet['ok'], sheet.get('error')

    res = web.what_if(sheet['csv'], yaml_text, json.dumps(score_dict),
                      json.dumps(day_dict or {}))
    assert res['ok'], res.get('error')
    return res['csv']


class TestStudentSheet:
    """ the blank sheet a posted policy is enough to fill in """

    def test_it_holds_one_student(self, csv_text):
        policy = web.student_policy(csv_text, YAML_STUDENT)['yaml']
        res = web.student_sheet(policy)

        assert res['ok'], res.get('error')
        info = web.load_csv(res['csv'])
        assert info['n_student'] == 1

    def test_one_student_is_what_makes_the_page_a_student_s(self, csv_text):
        """ the page reads n_student == 1 and swaps; nothing else tells it """
        policy = web.student_policy(csv_text, YAML_STUDENT)['yaml']
        info = web.load_csv(web.student_sheet(policy)['csv'])

        assert info['student_list'][0]['email'] == res_email()

    def test_it_says_how_many_there_are_to_fill_in(self, csv_text):
        """ the sheet holds no columns, so it cannot say for itself """
        policy = web.student_policy(csv_text, YAML_STUDENT)['yaml']
        res = web.student_sheet(policy)

        assert res['n_ass'] == 4

    def test_a_policy_with_no_roster_is_a_message(self):
        res = web.student_sheet('category:\n  weight:\n    hw: 100\n')

        assert not res['ok']
        assert 'no assignments' in res['error']

    def test_a_broken_policy_is_a_message(self):
        res = web.student_sheet('category:\n  weight:\n    hw: nonsense\n')

        assert not res['ok']
        assert res['error']

    def test_the_sheet_grades_an_unadjusted_student(self, csv_text):
        """ every one of the three, since YAML_PLAIN adjusts nobody """
        policy = web.student_policy(csv_text, YAML_PLAIN)['yaml']
        was = {s['email']: s['mean']
               for s in web.grade(csv_text, YAML_PLAIN)['student_list']}

        for email, score in (('alice@u.edu', ALICE_SCORE),
                             ('bob@u.edu', {'hw1': 10, 'hw2': 10, 'hw3': 10,
                                            'quiz1': 5}),
                             ('carol@u.edu', {'hw1': 0, 'hw2': 6, 'hw3': 6,
                                              'quiz1': 6})):
            res = web.grade(filled_sheet(policy, score), policy)

            assert res['ok'], res.get('error')
            assert len(res['student_list']) == 1
            assert res['student_list'][0]['mean'] == was[email], email

    def test_is_plain_data(self, csv_text):
        policy = web.student_policy(csv_text, YAML_STUDENT)['yaml']
        assert is_plain(web.student_sheet(policy))

    def test_the_scores_come_back_with_the_sheet(self, csv_text):
        """ the whole point of saving it: the typing is in the file """
        policy = web.student_policy(csv_text, YAML_PLAIN)['yaml']
        saved = filled_sheet(policy, ALICE_SCORE)

        graded = web.grade(saved, policy)['student_list'][0]
        got = {a['name']: a['perc'] for a in graded['ass_list']
               if a['perc'] is not None}

        assert sorted(got) == sorted(ALICE_SCORE)

    def test_a_breakdown_says_which_file_was_wanted(self, csv_text):
        """ a student is offered two csvs and only one can be read back

        The reader's own complaint would be about a missing Email column,
        which reads as a broken file rather than as the wrong one.
        """
        policy = web.student_policy(csv_text, YAML_PLAIN)['yaml']
        saved = filled_sheet(policy, ALICE_SCORE)
        breakdown = web.student_csv(saved, policy, 'you')

        assert breakdown['ok'], breakdown.get('error')
        res = web.load_csv(breakdown['csv'], 'your_grade_explained.csv')

        assert not res['ok']
        assert 'breakdown' in res['error']

    def test_a_real_export_is_not_mistaken_for_one(self, csv_text):
        assert web.load_csv(csv_text)['ok']

    def test_a_filled_sheet_dropped_back_in_grades_the_same(self, csv_text):
        """ how a term's typing survives, since nothing is kept between visits

        A filled sheet is a gradebook of one student, so the page reads it as
        somebody's own grade exactly as it reads the blank one -- which is why
        the file the page offers to save is the sheet with the scores in it.
        """
        yaml_late = ('category:\n  weight:\n    hw: 100\n'
                     '  late_penalty:\n    hw:\n'
                     '      penalty_per_day: 0.1\n      excuse_day: 0\n')
        policy = web.student_policy(csv_text, yaml_late)['yaml']
        saved = filled_sheet(policy, ALICE_SCORE, {'hw1': 3})

        # the page reads it back as one student, so solo mode still fires
        assert web.load_csv(saved)['n_student'] == 1

        first = web.grade(saved, policy)['student_list'][0]
        second = web.grade(saved, policy)['student_list'][0]

        assert second['mean'] == first['mean']
        # and the lateness it carries is the lateness that was entered
        late = {a['name']: a['late_days'] for a in second['ass_list']
                if a['late_days']}
        assert late == {'hw1': 3}


def res_email():
    from finalgrade import student
    return student.EMAIL_YOU


class TestWhatIf:
    """ a score typed into work that has not been graded yet """

    YAML_HW = 'category:\n  weight:\n    hw: 100\n'
    YAML_PLAN = ('category:\n  weight:\n    hw: 100\n'
                 'assignments:\n  planned:\n    hw4: 10\n')

    def mine(self, csv_text):
        """ alice's own sheet, with what she really got typed in """
        policy = web.student_policy(csv_text, self.YAML_HW)['yaml']
        return filled_sheet(policy, ALICE_SCORE)

    def sheet(self, csv_text, yaml_src):
        """ the posted policy, and the blank sheet it makes """
        policy = web.student_policy(csv_text, yaml_src)['yaml']
        return policy, web.student_sheet(policy)['csv']

    def test_a_typed_score_moves_the_grade(self, csv_text):
        mine = self.mine(csv_text)

        was = web.grade(mine, self.YAML_HW)['student_list'][0]['mean']
        res = web.what_if(mine, self.YAML_HW, '{"hw3": 10}')

        assert res['ok'], res.get('error')
        now = web.grade(res['csv'], self.YAML_HW)['student_list'][0]['mean']
        assert now > was

    def test_a_planned_assignment_can_be_answered(self, csv_text):
        """ the max points come out of the policy that planned it """
        res = web.what_if(self.mine(csv_text), self.YAML_PLAN, '{"hw4": 10}')

        assert res['ok'], res.get('error')
        graded = web.grade(res['csv'], self.YAML_PLAN)['student_list'][0]
        ass_dict = {a['name']: a for a in graded['ass_list']}

        assert ass_dict['hw4']['perc'] == 1
        assert ass_dict['hw4']['submitted']
        assert not ass_dict['hw4']['planned']

    def test_an_unanswered_plan_still_counts_for_nobody(self, csv_text):
        res = web.what_if(self.mine(csv_text), self.YAML_PLAN, '{}')
        graded = web.grade(res['csv'], self.YAML_PLAN)['student_list'][0]
        ass_dict = {a['name']: a for a in graded['ass_list']}

        assert ass_dict['hw4']['planned']
        assert ass_dict['hw4']['perc'] is None

    def test_no_answers_is_the_csv_it_was_given(self, csv_text):
        res = web.what_if(csv_text, YAML_STD, '{}')

        assert res['ok']
        assert res['csv'] == csv_text

    def test_nonsense_json_is_a_message(self, csv_text):
        res = web.what_if(csv_text, YAML_STD, 'not json')

        assert not res['ok']
        assert res['error']

    def test_an_assignment_nothing_knows_about(self, csv_text):
        res = web.what_if(self.mine(csv_text), YAML_STD, '{"hw9": 10}')

        assert not res['ok']
        assert 'hw9' in res['error']

    def test_is_plain_data(self, csv_text):
        assert is_plain(web.what_if(csv_text, YAML_STD, '{}'))


class TestNoStrayFiles:
    def test_nothing_is_left_behind(self, csv_text, tmp_path, monkeypatch):
        """ a browser has no filesystem to litter, but a temp dir still does

        (compared before and after: the scope csv fixture lives here too)
        """
        monkeypatch.chdir(tmp_path)
        before_set = set(pathlib.Path(tmp_path).iterdir())

        web.load_csv(csv_text)
        web.check_policy(csv_text, YAML_STD)
        web.grade(csv_text, YAML_STD)
        web.seed_policy(csv_text)

        assert set(pathlib.Path(tmp_path).iterdir()) == before_set

    def test_temp_dir_is_cleaned_up(self, csv_text):
        """ every call makes one, and every call has to remove it """
        import tempfile

        folder = pathlib.Path(tempfile.gettempdir())
        before_set = set(folder.iterdir())

        for _ in range(3):
            web.grade(csv_text, YAML_STD)

        assert set(folder.iterdir()) == before_set
