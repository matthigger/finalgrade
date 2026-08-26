""" the policy a class may be handed, and the estimate a student makes with it

Two claims are being defended here.  The first is that the file says nothing
about anybody: it is posted once, for everybody, so it can only hold what is
true of everybody.  The second is that a student it singles out for nothing
gets their own grade out of it exactly -- an estimate that disagrees with the
grade is worse than no estimate at all, because it is the one the student
will quote back.

A student the policy does single out is the interesting case, and the one
these tests pin down: the shared file is wrong for them until their own
adjustment is written in, and right again once it is.
"""
import warnings

import pytest
from ruamel.yaml import YAML

from finalgrade import student
from finalgrade.errors import FinalgradeError, PolicyError
from finalgrade.policy import YAML_KEY_DICT, Policy

yaml = YAML(typ='safe')

# every kind of per-student setting at once, on the standard 3-student csv
YAML_FULL = """
category:
  weight:
    hw: 60
    quiz: 40
  drop_low:
    hw: 1
  late_penalty:
    hw:
      penalty_per_day: 0.1
      excuse_day: 1
      grace_period_minutes: 30
      excuse_day_offset:
        alice@u.edu: 2
        carol@u.edu: -1
waive:
  bob@u.edu: hw2
waive_late:
  carol@u.edu: hw1
max:
  alice@u.edu:
    hw3: hw2
note:
  carol@u.edu: extension agreed with the dean's office
  bob@u.edu: sat the makeup
email_list:
  - alice@u.edu
  - bob@u.edu
  - carol@u.edu
grade_thresh:
  0.9: A
  0.8: B
  0: C
"""

EMAIL_TUP = ('alice@u.edu', 'bob@u.edu', 'carol@u.edu')


@pytest.fixture
def policy_full(write_policy):
    return Policy.from_file(write_policy(YAML_FULL))


def graded(f_grade, policy):
    """ (mean, letter) per student, warnings kept out of the way """
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        _, df_grade = policy(str(f_grade))
    return {email: (row['mean'], row['letter'])
            for email, row in df_grade.iterrows()}


def student_grade(csv_text, yaml_text, tmp_path, name='mine.csv'):
    """ what the student's own sheet comes to, the way the page does it """
    f_csv = tmp_path / name
    f_csv.write_text(csv_text)
    f_policy = tmp_path / 'student.yaml'
    f_policy.write_text(yaml_text)
    return graded(f_csv, Policy.from_file(f_policy))


ME = student.EMAIL_YOU


def own_sheet(f_grade, policy, email):
    """ the sheet a student fills in, entering the scores they really got

    Which is how the parity claim is made now that nobody is handed an
    export: a student typing in what the gradebook already says about them
    should reach the grade the instructor's run reached, because it is the
    same arithmetic over the same numbers.

    Every assignment is entered, zeros included -- work nobody handed in is a
    zero in the instructor's run, so leaving it blank here would be answering
    a different question (see TestBlankIsNotZero).

    Args:
        f_grade (Path): the class's export
        policy (Policy): the instructor's own policy, for the grace periods
            that decide how many days late each submission counts as
        email (str): whose scores to enter

    Returns:
        csv_text (str): a sheet with that student's scores in it
    """
    import pandas as pd

    from finalgrade.gradebook import Gradebook

    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        gradebook = Gradebook.from_file(str(f_grade))
        day_frame = gradebook.get_lateday(
            cat_late_dict=policy.cat_late_dict)

    perc = gradebook.df_perc.loc[email]
    point_dict = {str(ass): float(pt) for ass, pt in gradebook.points.items()}

    score_dict = {ass: perc[ass] * point_dict[ass]
                  for ass in gradebook.ass_list}
    day_dict = {ass: int(day_frame.at[email, ass])
                for ass in score_dict
                if pd.notna(day_frame.at[email, ass])
                and day_frame.at[email, ass] > 0}

    return student.add_scores(student.blank_csv(), score_dict,
                              point_dict=point_dict, day_dict=day_dict)


@pytest.fixture(scope='module')
def f_example():
    """ the gradebook behind the page's "try an example" button """
    import pathlib

    import finalgrade
    return pathlib.Path(finalgrade.__file__).parents[1] / 'web' \
        / 'ex_gradescope.csv'


@pytest.fixture(scope='module')
def email_list(f_example):
    from finalgrade.gradebook import Gradebook

    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        gradebook = Gradebook.from_file(str(f_example))
    return [str(email) for email in gradebook.df_perc.index]


@pytest.fixture(scope='module')
def adjusted_tup(email_list):
    """ the three of the hundred the example policy singles out """
    return tuple(email_list[:3])


@pytest.fixture(scope='module')
def policy_example(tmp_path_factory, adjusted_tup):
    """ a plausible course policy, singling three of the hundred out """
    first, second, third = adjusted_tup
    text = f"""
category:
  weight:
    hw: 40
    quiz: 25
    exam: 35
  drop_low:
    hw: 1
  late_penalty:
    hw:
      penalty_per_day: .1
      excuse_day: 2
      excuse_day_offset:
        {first}: 5
        {second}: -2
assignments:
  substitute:
    exam2a:
      - exam2b
  exclude:
    - exam2b
waive:
  {second}: hw3
waive_late:
  {third}: hw1
max:
  {third}:
    quiz1: quiz2
note:
  {first}: a private word about the first of them
"""
    f_policy = tmp_path_factory.mktemp('policy') / 'policy.yaml'
    f_policy.write_text(text)
    return Policy.from_file(f_policy)


class TestTheSameGrade:
    """ the claim the whole feature rests on, for whoever it holds for """

    def test_a_class_wide_file_is_right_for_the_unadjusted(
            self, f_scope_std, tmp_path, write_policy):
        """ one file for everyone, when the policy singles nobody out """
        text_plain = ('category:\n  weight:\n    hw: 50\n    quiz: 50\n'
                      '  drop_low:\n    hw: 1\n')
        policy = Policy.from_file(write_policy(text_plain))
        want_dict = graded(f_scope_std, policy)

        text = student.policy_text(policy, f_scope_std)

        for email in EMAIL_TUP:
            got = student_grade(own_sheet(f_scope_std, policy, email),
                                text, tmp_path)
            assert got[ME] == want_dict[email], email

    def test_the_thresholds_come_along(self, policy_full):
        """ a letter needs the cutoffs that produced it """
        assert 'grade_thresh' in student.policy_text(policy_full)

    def test_the_course_wide_late_rate_comes_along(self, policy_full):
        text = student.policy_text(policy_full)
        late = yaml.load(text)['category']['late_penalty']['hw']

        assert late == {'penalty_per_day': .1, 'excuse_day': 1,
                        'grace_period_minutes': 30}


# adjustments chosen so that each one moves the grade it is about.  a waiver
# on a student whose scores are all equal, or one that drop_low would have
# discarded anyway, changes no number and so proves nothing here -- alice is
# 10, 8, 6 on the homework and nothing is dropped, so waiving her worst is
# 0.8 against 0.9, and carol is three days late with no excused days
YAML_BITES = """
category:
  weight:
    hw: 100
  late_penalty:
    hw:
      penalty_per_day: 0.1
      excuse_day: 0
      excuse_day_offset:
        carol@u.edu: 3
waive:
  alice@u.edu: hw3
"""


class TestAnAdjustmentWrittenBackIn:
    """ the shared file is wrong for a student it singles out, until they say

    Which is the trade this workflow makes: one file posted once, and the
    handful of students who were emailed about something add that one line.
    Both halves are worth pinning down -- that it is wrong without the line,
    so that nobody believes otherwise, and that the line is all it takes.
    """

    @pytest.fixture
    def policy_bites(self, write_policy):
        return Policy.from_file(write_policy(YAML_BITES, 'bites.yaml'))

    def test_a_waiver_without_it_is_wrong(self, f_scope_std, policy_bites,
                                          tmp_path):
        """ alice is waived from her worst hw, and the file cannot say """
        want = graded(f_scope_std, policy_bites)['alice@u.edu']
        mine = own_sheet(f_scope_std, policy_bites, 'alice@u.edu')

        text = student.policy_text(policy_bites, f_scope_std)
        got = student_grade(mine, text, tmp_path)

        assert want[0] == pytest.approx(.9)
        assert got[ME][0] == pytest.approx(.8)

    def test_a_waiver_written_back_in_is_right(self, f_scope_std,
                                               policy_bites, tmp_path):
        want = graded(f_scope_std, policy_bites)['alice@u.edu']
        mine = own_sheet(f_scope_std, policy_bites, 'alice@u.edu')

        # the line the header tells them to add, under their own name on
        # their own sheet
        text = student.policy_text(policy_bites, f_scope_std) \
            + f'\nwaive:\n  {ME}: hw3\n'
        got = student_grade(mine, text, tmp_path)

        assert got[ME] == want

    def test_extra_late_days_without_them_are_wrong(self, f_scope_std,
                                                    policy_bites, tmp_path):
        """ carol's three excused days are the only thing sparing her """
        want = graded(f_scope_std, policy_bites)['carol@u.edu']
        mine = own_sheet(f_scope_std, policy_bites, 'carol@u.edu')

        text = student.policy_text(policy_bites, f_scope_std)
        got = student_grade(mine, text, tmp_path)

        assert got[ME][0] < want[0]

    def test_extra_late_days_written_back_in(self, f_scope_std, policy_bites,
                                             tmp_path):
        """ the one that goes inside a block rather than at the bottom """
        want = graded(f_scope_std, policy_bites)['carol@u.edu']
        mine = own_sheet(f_scope_std, policy_bites, 'carol@u.edu')

        text = student.policy_text(policy_bites, f_scope_std).replace(
            '      excuse_day: 0\n',
            '      excuse_day: 0\n'
            f'      excuse_day_offset:\n        {ME}: 3\n')
        got = student_grade(mine, text, tmp_path)

        assert got[ME] == want

    def test_the_header_says_how(self, policy_full):
        """ the file arrives as an attachment with no covering note """
        text = student.policy_text(policy_full)

        for key in ('waive:', 'waive_late:', 'excuse_day_offset:'):
            assert key in text

        # as instructions, not as settings: every one of them is commented
        for line in text.split('\n'):
            if any(key in line for key in
                   ('waive:', 'waive_late:', 'excuse_day_offset:')):
                assert line.lstrip().startswith('#'), line


class TestNobodyElse:
    """ what may not be in the file, section by section """

    def test_it_names_nobody_at_all(self, policy_full):
        text = student.policy_text(policy_full)

        for email in EMAIL_TUP:
            assert email not in text

    def test_no_section_is_keyed_by_a_student(self, policy_full):
        data = yaml.load(student.policy_text(policy_full))

        for key in ('waive', 'waive_late', 'max', 'note', 'email_list'):
            assert key not in data
        assert 'excuse_day_offset' not in \
            data['category']['late_penalty']['hw']

    def test_the_note_stays_behind(self, policy_full):
        """ it moves no grade, and the wording is the instructor's """
        assert 'dean' not in student.policy_text(policy_full)

    def test_a_comment_cannot_carry_what_a_section_could_not(
            self, write_policy):
        """ the file is rebuilt, not edited down, so comments do not travel """
        policy = Policy.from_file(write_policy(
            '# alice gets an extra week, per the dean\n'
            'category:\n  weight:\n    hw: 100\n'))
        text = student.policy_text(policy)

        assert 'dean' not in text
        assert 'alice' not in text


class TestEverySectionIsAccountedFor:
    def test_no_section_is_unclassified(self):
        """ the guard that makes the two tuples above a decision, not a list

        A section added to Policy and to neither tuple has to fail here
        rather than be handed to a class by default.
        """
        every_set = set(student.SHARE_TUP + student.DROP_TUP)

        assert every_set == set(YAML_KEY_DICT)

    def test_no_section_is_in_two_minds(self):
        every_list = list(student.SHARE_TUP + student.DROP_TUP)

        assert len(every_list) == len(set(every_list))

    def test_every_per_student_section_is_dropped(self, policy_full):
        """ iter_email is Policy's own list of what names a student """
        where_set = {where.split('/')[0]
                     for _, where in policy_full.iter_email()}
        key_dict = {key_tup[0]: attr
                    for attr, key_tup in YAML_KEY_DICT.items()}

        for where in where_set:
            if where == 'late_penalty':
                # the one that lives inside a course-wide section
                assert student.LATE_MINE == 'excuse_day_offset'
                continue
            assert key_dict[where] in student.DROP_TUP, where


class TestCompletionThreshold:
    """ a completion rate over a class of one is 100% or 0% """

    @pytest.fixture
    def policy_thresh(self, write_policy):
        return Policy.from_file(write_policy(
            'category:\n  weight:\n    hw: 50\n    quiz: 50\n'
            'assignments:\n  exclude_complete_thresh: 0.5\n'))

    @pytest.fixture
    def f_grade_thresh(self, tmp_path):
        """ the standard csv plus one assignment nobody did """
        from conftest import ASSIGN_STD, STUDENT_STD, write_scope

        stud_list = [dict(s, scores=dict(s['scores'], Quiz2=0))
                     for s in STUDENT_STD]
        return write_scope(tmp_path / 'scope2.csv',
                           dict(ASSIGN_STD, Quiz2=10), stud_list)

    def test_it_is_written_out_as_the_exclusions_it_came_to(
            self, policy_thresh, f_grade_thresh):
        text = student.policy_text(policy_thresh,
                                   f_grade=str(f_grade_thresh))
        data = yaml.load(text)

        assert 'exclude_complete_thresh' not in data['assignments']
        assert data['assignments']['exclude'] == ['quiz2']

    def test_the_students_still_get_the_same_grade(self, policy_thresh,
                                                   f_grade_thresh, tmp_path):
        want_dict = graded(f_grade_thresh, policy_thresh)
        text = student.policy_text(policy_thresh,
                                   f_grade=str(f_grade_thresh))

        for email in EMAIL_TUP:
            got = student_grade(
                own_sheet(f_grade_thresh, policy_thresh, email), text,
                tmp_path)
            assert got[ME] == want_dict[email], email

    def test_without_the_gradebook_it_is_refused(self, policy_thresh):
        """ handing it over meaning something else is the one bad option """
        with pytest.raises(PolicyError, match='exclude_complete_thresh'):
            student.policy_text(policy_thresh)


class TestTheSheet:
    """ the blank sheet a posted policy is enough to produce """

    def test_it_holds_one_student_and_no_scores(self):
        text = student.blank_csv()

        assert len(text.strip().split('\n')) == 2
        assert student.EMAIL_YOU in text

    def test_it_is_still_a_gradebook(self, tmp_path):
        from finalgrade.gradebook import Gradebook

        f_out = tmp_path / 'mine.csv'
        f_out.write_text(student.blank_csv())
        gradebook = Gradebook.from_file(str(f_out))

        assert list(gradebook.df_perc.index) == [student.EMAIL_YOU]
        assert list(gradebook.ass_list) == []

    def test_the_policy_is_where_the_assignments_come_from(
            self, tmp_path, write_policy):
        """ the sheet has no columns; the roster puts them there """
        policy = Policy.from_file(write_policy(
            'category:\n  weight:\n    hw: 100\n'
            'assignments:\n  planned:\n    hw1: 10\n    hw2: 10\n'))
        f_out = tmp_path / 'mine.csv'
        f_out.write_text(student.blank_csv())

        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            gradebook, _ = policy(str(f_out))

        assert list(gradebook.ass_list) == ['hw1', 'hw2']

    def test_a_sheet_nobody_has_filled_in_grades_to_nothing(
            self, tmp_path, write_policy):
        """ every assignment is nan, which is what a waiver is """
        policy = Policy.from_file(write_policy(
            'category:\n  weight:\n    hw: 100\n'
            'assignments:\n  planned:\n    hw1: 10\n'))

        got = student_grade(student.blank_csv(),
                            student.policy_text(policy), tmp_path)

        import pandas as pd
        assert pd.isna(got[ME][0])

    def test_a_policy_with_no_roster_has_nothing_to_grade(self, tmp_path,
                                                          write_policy):
        policy = Policy.from_file(write_policy(
            'category:\n  weight:\n    hw: 100\n'))
        f_out = tmp_path / 'mine.csv'
        f_out.write_text(student.blank_csv())

        with pytest.raises(PolicyError, match='no assignments'):
            policy(str(f_out))


class TestBlankIsNotZero:
    """ work left blank is not counted; work handed in late and badly is

    The distinction the sheet turns on, and the one a student can get wrong:
    an assignment with no score is treated as never assigned, so leaving a
    missed assignment blank flatters the estimate.  Typing 0 is what says
    "I did not hand this in".
    """

    @pytest.fixture
    def policy(self, write_policy):
        return Policy.from_file(write_policy(
            'category:\n  weight:\n    hw: 100\n'
            'assignments:\n  planned:\n    hw1: 10\n    hw2: 10\n'))

    def test_blank_is_not_counted_at_all(self, policy, tmp_path):
        text = student.add_scores(student.blank_csv(), {'hw1': 8},
                                  point_dict={'hw1': 10, 'hw2': 10})

        assert graded_one(text, policy, tmp_path) == pytest.approx(.8)

    def test_a_typed_zero_is(self, policy, tmp_path):
        text = student.add_scores(student.blank_csv(),
                                  {'hw1': 8, 'hw2': 0},
                                  point_dict={'hw1': 10, 'hw2': 10})

        assert graded_one(text, policy, tmp_path) == pytest.approx(.4)


class TestTheRoster:
    """ the term's work, which is a fact about the course and not about
    anybody in it """

    def test_every_assignment_travels_with_its_max_points(self, f_scope_std,
                                                          write_policy):
        policy = Policy.from_file(write_policy(
            'category:\n  weight:\n    hw: 50\n    quiz: 50\n'))

        plan = yaml.load(student.policy_text(policy,
                                             f_scope_std))['assignments'][
                                                 'planned']

        assert plan == {'hw1': 10., 'hw2': 10., 'hw3': 10., 'quiz1': 10.}

    def test_the_instructors_own_plan_outranks_the_export(self, f_scope_std,
                                                          write_policy):
        """ theirs is the deliberate figure """
        policy = Policy.from_file(write_policy(
            'category:\n  weight:\n    hw: 100\n'
            'assignments:\n  planned:\n    hw1: 99\n'))

        plan = yaml.load(student.policy_text(policy,
                                             f_scope_std))['assignments'][
                                                 'planned']

        assert plan['hw1'] == 99

    def test_without_the_gradebook_there_is_no_roster(self, write_policy):
        policy = Policy.from_file(write_policy(
            'category:\n  weight:\n    hw: 100\n'))

        assert 'planned' not in student.policy_text(policy)

    def test_a_canvas_export_makes_one_too(self, tmp_path, write_policy):
        """ the sheet is the same shape whatever the instructor exported """
        import pathlib

        f_canvas = pathlib.Path('web/ex_canvas.csv')
        policy = Policy.from_file(write_policy(
            'category:\n  weight:\n    hw: 50\n    exam: 50\n'))

        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            text = student.policy_text(policy, f_canvas)

        plan = yaml.load(text)['assignments']['planned']

        assert plan['exam1'] == 100
        assert 'hw1' in plan


class TestWhatWasEntered:
    """ scores typed onto a sheet, and the lateness that is its own answer """

    POINT_DICT = {'hw1': 10, 'hw2': 10, 'hw3': 10}

    @pytest.fixture
    def policy(self, write_policy):
        return Policy.from_file(write_policy(
            'category:\n  weight:\n    hw: 100\n'
            'assignments:\n  planned:\n    hw1: 10\n    hw2: 10\n'
            '    hw3: 10\n'))

    @pytest.fixture
    def policy_late(self, write_policy):
        return Policy.from_file(write_policy(
            'category:\n  weight:\n    hw: 100\n'
            '  late_penalty:\n    hw:\n      penalty_per_day: 0.1\n'
            '      excuse_day: 0\n'
            'assignments:\n  planned:\n    hw1: 10\n    hw2: 10\n'
            '    hw3: 10\n', 'late.yaml'))

    def sheet(self, score_dict, day_dict=None):
        return student.add_scores(student.blank_csv(), score_dict,
                                  point_dict=self.POINT_DICT,
                                  day_dict=day_dict)

    def test_a_score_typed_in_moves_the_grade(self, policy, tmp_path):
        one = self.sheet({'hw1': 6})
        two = self.sheet({'hw1': 6, 'hw2': 10})

        assert graded_one(one, policy, tmp_path) == pytest.approx(.6)
        assert graded_one(two, policy, tmp_path) == pytest.approx(.8)

    def test_a_planned_assignment_gets_the_columns_it_never_had(self, policy,
                                                                tmp_path):
        text = self.sheet({'hw1': 10})

        assert 'hw1 - Max Points' in text
        assert graded_one(text, policy, tmp_path) == pytest.approx(1.)

    def test_an_unanswered_question_is_left_alone(self, policy, tmp_path):
        """ blank is a zero nobody handed in, which is not "no answer yet" """
        blank = student.blank_csv()

        assert self.sheet({'hw1': None, 'hw2': None}) == blank

    def test_taking_an_answer_back_out(self, policy, tmp_path):
        """ asked again without it, from the sheet as it came """
        self.sheet({'hw1': 10})
        back = self.sheet({})

        assert back == student.blank_csv()

    def test_days_late_cost_what_the_policy_says(self, policy_late, tmp_path):
        score = {'hw1': 10, 'hw2': 10}
        on_time = self.sheet(score)
        late = self.sheet(score, {'hw1': 3})

        assert graded_one(on_time, policy_late, tmp_path) == pytest.approx(1.)
        # three days at a tenth of an average hw, over the two that count
        assert graded_one(late, policy_late, tmp_path) == \
            pytest.approx(1 - .3 / 2)

    def test_a_grace_period_still_applies_to_them(self, tmp_path,
                                                  write_policy):
        """ a day entered here is a day late, and the policy's grace then
        acts on it exactly as it would on a real submission """
        policy = Policy.from_file(write_policy(
            'category:\n  weight:\n    hw: 100\n'
            '  late_penalty:\n    hw:\n      penalty_per_day: 0.5\n'
            '      excuse_day: 0\n'
            '      grace_period_minutes: 2880\n'
            'assignments:\n  planned:\n    hw1: 10\n', 'grace.yaml'))
        text = student.add_scores(student.blank_csv(), {'hw1': 10},
                                  point_dict={'hw1': 10}, day_dict={'hw1': 2})

        assert graded_one(text, policy, tmp_path) == pytest.approx(1.)

    def test_a_score_says_nothing_about_when_it_arrived(self, policy_late,
                                                        tmp_path):
        """ answering a score by also forgiving lateness would flatter it """
        text = self.sheet({'hw1': 10, 'hw2': 10}, {'hw1': 3})
        more = student.add_scores(text, {'hw3': 10},
                                  point_dict=self.POINT_DICT)

        # hw1 is still three days late, now over the three that count
        assert graded_one(more, policy_late, tmp_path) == \
            pytest.approx(1 - .3 / 3)

    def test_days_against_work_with_no_score_are_ignored(self):
        """ there is nothing yet to be late on """
        assert self.sheet({}, {'hw1': 3}) == student.blank_csv()

    def test_an_assignment_with_no_max_points(self):
        with pytest.raises(FinalgradeError, match='hw9'):
            student.add_scores(student.blank_csv(), {'hw9': 10})

    def test_a_class_needs_to_be_told_which_student(self, f_scope_std):
        with pytest.raises(FinalgradeError, match='3'):
            student.add_scores(f_scope_std.read_text(), {'hw3': 10})

    def test_a_class_can_be_told_which_student(self, f_scope_std,
                                               tmp_path, write_policy):
        policy = Policy.from_file(write_policy(
            'category:\n  weight:\n    hw: 100\n'))
        text = student.add_scores(f_scope_std.read_text(), {'hw3': 10},
                                  email='alice@u.edu')

        f_out = tmp_path / 'scope.csv'
        f_out.write_text(text)
        got = graded(f_out, policy)

        assert got['alice@u.edu'][0] == pytest.approx(28 / 30)
        assert got['bob@u.edu'][0] == pytest.approx(1.)

    def test_nothing_to_do_is_the_csv_it_was_given(self, f_scope_std):
        text = f_scope_std.read_text()

        assert student.add_scores(text, {}) == text

    def test_a_canvas_export_has_no_lateness_to_set(self):
        """ canvas records none, so there is no column to put days into """
        import pathlib

        text = pathlib.Path('web/ex_canvas.csv').read_text()

        with pytest.raises(FinalgradeError, match='no lateness'):
            student.add_scores(text, {'HW1 (101000)': 9},
                               email='dan.doesntdohw@uni.edu',
                               day_dict={'HW1 (101000)': 2})


class TestTheWholeExample:
    """ the hundred students behind the page's "try an example" button

    The three student fixture above is where a difference gets diagnosed;
    this is where one gets found.  The example is built to be awkward on
    purpose -- somebody who hands in nothing, somebody who is always late,
    an assignment that stands in for another -- so it is the population an
    off-by-one in the cut would show up in.
    """

    def test_every_one_it_singles_out_for_nothing_gets_their_own_number(
            self, f_example, policy_example, email_list, adjusted_tup,
            tmp_path):
        want_dict = graded(f_example, policy_example)
        text = student.policy_text(policy_example, f_example)

        assert len(email_list) == 100

        n = 0
        for email in email_list:
            if email in adjusted_tup:
                continue
            got_dict = student_grade(
                own_sheet(f_example, policy_example, email), text, tmp_path)
            assert got_dict[ME] == want_dict[email], email
            n += 1

        assert n == 97

    def test_the_one_file_names_nobody(self, policy_example, email_list,
                                       f_example):
        """ a hundred students, and the file posted for them mentions none """
        text = student.policy_text(policy_example, f_example)

        for email in email_list:
            assert email not in text
            assert email.split('@')[0] not in text


def graded_one(csv_text, policy, tmp_path):
    """ the one student in csv_text's mean """
    f_out = tmp_path / 'one.csv'
    f_out.write_text(csv_text)
    got_dict = graded(f_out, policy)
    assert len(got_dict) == 1
    return list(got_dict.values())[0][0]
