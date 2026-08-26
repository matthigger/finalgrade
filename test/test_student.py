""" the policy a student may be handed, and the estimate they make with it

Two claims are being defended here.  The first is privacy: nothing about any
other student survives into the file, whatever section it was written in.
The second is that the student's own grade comes out the same as the
instructor's -- an estimate that disagrees with the grade is worse than no
estimate at all, because it is the one the student will quote back.
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
    """ what the student's own two files come to, the way the page does it """
    f_csv = tmp_path / name
    f_csv.write_text(csv_text)
    f_policy = tmp_path / 'student.yaml'
    f_policy.write_text(yaml_text)
    return graded(f_csv, Policy.from_file(f_policy))


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
def policy_example(tmp_path_factory, email_list):
    """ a plausible course policy, singling three of the hundred out """
    first, second, third = email_list[:3]
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
    """ the claim the whole feature rests on """

    def test_every_student_gets_their_own_number(self, f_scope_std,
                                                 policy_full, tmp_path):
        want_dict = graded(f_scope_std, policy_full)
        csv_text = f_scope_std.read_text()

        for email in EMAIL_TUP:
            text = student.policy_text(policy_full, email=email)
            got_dict = student_grade(student.one_row_csv(csv_text, email),
                                     text, tmp_path)

            assert list(got_dict) == [email]
            assert got_dict[email] == want_dict[email], email

    def test_the_late_penalty_comes_along(self, f_scope_std, policy_full,
                                          tmp_path):
        """ carol is late, short an excuse day, and forgiven one of them

        Three per-student settings that all move one number: if any of them
        were dropped this is the assertion that would notice.
        """
        want = graded(f_scope_std, policy_full)['carol@u.edu']
        text = student.policy_text(policy_full, email='carol@u.edu')

        assert 'excuse_day_offset' in text
        got = student_grade(
            student.one_row_csv(f_scope_std.read_text(), 'carol@u.edu'),
            text, tmp_path)

        assert got['carol@u.edu'] == want

    def test_a_class_wide_file_is_right_for_the_unadjusted(
            self, f_scope_std, tmp_path, write_policy):
        """ one file for everyone, when the policy singles nobody out """
        text_plain = ('category:\n  weight:\n    hw: 50\n    quiz: 50\n'
                      '  drop_low:\n    hw: 1\n')
        policy = Policy.from_file(write_policy(text_plain))
        want_dict = graded(f_scope_std, policy)

        text = student.policy_text(policy)

        for email in EMAIL_TUP:
            got = student_grade(
                student.one_row_csv(f_scope_std.read_text(), email),
                text, tmp_path)
            assert got[email] == want_dict[email], email

    def test_the_thresholds_come_along(self, policy_full):
        """ a letter needs the cutoffs that produced it """
        assert 'grade_thresh' in student.policy_text(policy_full)


class TestNobodyElse:
    """ what may not be in the file, section by section """

    def test_no_other_student_is_named(self, policy_full):
        for email in EMAIL_TUP:
            text = student.policy_text(policy_full, email=email)

            for other in set(EMAIL_TUP) - {email}:
                assert other not in text, f'{other} leaked into {email}'

    def test_a_class_wide_file_names_nobody(self, policy_full):
        text = student.policy_text(policy_full)

        for email in EMAIL_TUP:
            assert email not in text

    def test_the_note_stays_behind(self, policy_full):
        """ it moves no grade, and the wording is the instructor's """
        for email in (None,) + EMAIL_TUP:
            text = student.policy_text(policy_full, email=email)

            assert 'dean' not in text
            assert 'note' not in text

    def test_the_roster_stays_behind(self, policy_full):
        text = student.policy_text(policy_full, email='alice@u.edu')

        assert 'email_list' not in text

    def test_only_this_students_waiver(self, policy_full):
        text = student.policy_text(policy_full, email='bob@u.edu')
        data = yaml.load(text)

        assert data['waive'] == {'bob@u.edu': ['hw2']}
        assert 'waive_late' not in data
        assert 'max' not in data

    def test_only_this_students_excuse_days(self, policy_full):
        text = student.policy_text(policy_full, email='alice@u.edu')
        late = yaml.load(text)['category']['late_penalty']['hw']

        assert late['excuse_day_offset'] == {'alice@u.edu': 2}
        assert late['penalty_per_day'] == .1
        assert late['excuse_day'] == 1

    def test_the_course_wide_late_rate_survives_alone(self, policy_full):
        """ a student the offsets don't mention still needs the penalty """
        text = student.policy_text(policy_full, email='bob@u.edu')
        late = yaml.load(text)['category']['late_penalty']['hw']

        assert late == {'penalty_per_day': .1, 'excuse_day': 1,
                        'grace_period_minutes': 30}

    def test_a_comment_cannot_carry_what_a_section_could_not(
            self, write_policy):
        """ the file is rebuilt, not edited down, so comments do not travel """
        policy = Policy.from_file(write_policy(
            '# alice gets an extra week, per the dean\n'
            'category:\n  weight:\n    hw: 100\n'))

        assert 'dean' not in student.policy_text(policy)


class TestEverySectionIsAccountedFor:
    def test_no_section_is_unclassified(self):
        """ the guard that makes the two tuples above a decision, not a list

        A section added to Policy and to neither tuple has to fail here
        rather than be handed to a class by default.
        """
        every_set = set(student.SHARE_TUP + student.MINE_TUP
                        + student.DROP_TUP)

        assert every_set == set(YAML_KEY_DICT)

    def test_no_section_is_in_two_minds(self):
        every_list = list(student.SHARE_TUP + student.MINE_TUP
                          + student.DROP_TUP)

        assert len(every_list) == len(set(every_list))

    def test_every_per_student_section_is_mine_or_dropped(self, policy_full):
        """ iter_email is Policy's own list of what names a student """
        where_set = {where.split('/')[0]
                     for _, where in policy_full.iter_email()}
        # spelled as yaml keys, which is how iter_email reports them
        key_dict = {key_tup[0]: attr
                    for attr, key_tup in YAML_KEY_DICT.items()}
        ok_set = set(student.MINE_TUP + student.DROP_TUP)

        for where in where_set:
            if where == 'late_penalty':
                # the one that lives inside a course-wide section
                assert student.LATE_MINE == 'excuse_day_offset'
                continue
            assert key_dict[where] in ok_set, where


class TestCompletionThreshold:
    """ a completion rate over a class of one is 100% or 0% """

    @pytest.fixture
    def policy_thresh(self, write_policy):
        return Policy.from_file(write_policy(
            'category:\n  weight:\n    hw: 50\n    quiz: 50\n'
            'assignments:\n  exclude_complete_thresh: 0.5\n'))

    def test_it_is_written_out_as_the_exclusions_it_came_to(
            self, f_scope_std, policy_thresh, tmp_path):
        """ hw1: alice and bob have it, carol has a 0 -- 67%, so it stays """
        from conftest import ASSIGN_STD, STUDENT_STD, write_scope

        # one assignment nobody did: below any threshold, and gone
        stud_list = [dict(s, scores=dict(s['scores'], Quiz2=0))
                     for s in STUDENT_STD]
        f_grade = write_scope(tmp_path / 'scope2.csv',
                              dict(ASSIGN_STD, Quiz2=10), stud_list)

        text = student.policy_text(policy_thresh, email='alice@u.edu',
                                   f_grade=str(f_grade))
        data = yaml.load(text)

        assert 'exclude_complete_thresh' not in data['assignments']
        assert data['assignments']['exclude'] == ['quiz2']

    def test_the_student_still_gets_the_same_grade(self, policy_thresh,
                                                   tmp_path):
        from conftest import ASSIGN_STD, STUDENT_STD, write_scope

        stud_list = [dict(s, scores=dict(s['scores'], Quiz2=0))
                     for s in STUDENT_STD]
        f_grade = write_scope(tmp_path / 'scope2.csv',
                              dict(ASSIGN_STD, Quiz2=10), stud_list)
        want_dict = graded(f_grade, policy_thresh)

        for email in EMAIL_TUP:
            text = student.policy_text(policy_thresh, email=email,
                                       f_grade=str(f_grade))
            got = student_grade(
                student.one_row_csv(f_grade.read_text(), email), text,
                tmp_path)
            assert got[email] == want_dict[email], email

    def test_without_the_gradebook_it_is_refused(self, policy_thresh):
        """ handing it over meaning something else is the one bad option """
        with pytest.raises(PolicyError, match='exclude_complete_thresh'):
            student.policy_text(policy_thresh, email='alice@u.edu')


class TestOneRow:
    def test_it_is_that_student_and_no_other(self, f_scope_std):
        text = student.one_row_csv(f_scope_std.read_text(), 'bob@u.edu')

        assert 'bob@u.edu' in text
        assert 'alice' not in text
        assert 'carol' not in text

    def test_it_is_still_a_gradebook(self, f_scope_std, tmp_path):
        from finalgrade.gradebook import Gradebook

        f_out = tmp_path / 'mine.csv'
        f_out.write_text(student.one_row_csv(f_scope_std.read_text(),
                                             'alice@u.edu'))
        gradebook = Gradebook.from_file(str(f_out))

        assert list(gradebook.df_perc.index) == ['alice@u.edu']
        assert list(gradebook.ass_list) == ['hw1', 'hw2', 'hw3', 'quiz1']

    def test_lateness_survives_the_cut(self, f_scope_std, tmp_path):
        from finalgrade.gradebook import Gradebook

        f_out = tmp_path / 'mine.csv'
        f_out.write_text(student.one_row_csv(f_scope_std.read_text(),
                                             'carol@u.edu'))
        gradebook = Gradebook.from_file(str(f_out))

        assert gradebook.df_late_minutes.at['carol@u.edu', 'hw1'] == 48 * 60

    def test_an_unhanded_in_assignment_is_still_blank(self, tmp_path):
        """ a blank cell and a submitted zero are different things """
        from conftest import ASSIGN_STD, write_scope
        from finalgrade.gradebook import Gradebook

        f_grade = write_scope(tmp_path / 'scope.csv', ASSIGN_STD, [
            {'email': 'x@u.edu', 'first': 'x', 'last': 'y',
             'scores': {'HW1': 5}}])
        f_out = tmp_path / 'mine.csv'
        f_out.write_text(student.one_row_csv(f_grade.read_text(), 'x@u.edu'))
        gradebook = Gradebook.from_file(str(f_out))

        assert not gradebook.df_submit.at['x@u.edu', 'hw2']

    def test_matched_by_prefix_like_everything_else(self, f_scope_std):
        text = student.one_row_csv(f_scope_std.read_text(),
                                   'alice@husky.u.edu')

        assert 'alice@u.edu' in text

    def test_a_student_who_is_not_there(self, f_scope_std):
        with pytest.raises(FinalgradeError, match='nobody@u.edu'):
            student.one_row_csv(f_scope_std.read_text(), 'nobody@u.edu')

    def test_a_csv_that_is_neither_kind(self):
        with pytest.raises(FinalgradeError, match='gradescope'):
            student.one_row_csv('a,b\n1,2\n', 'x@u.edu')


class TestCanvas:
    @pytest.fixture
    def f_canvas(self):
        import pathlib
        return pathlib.Path('web/ex_canvas.csv')

    def test_the_points_possible_row_comes_along(self, f_canvas, tmp_path):
        """ without it no assignment has a maximum """
        from finalgrade.gradebook import Gradebook

        text = f_canvas.read_text()
        email = 'dan.doesntdohw@uni.edu'
        f_out = tmp_path / 'mine.csv'
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            f_out.write_text(student.one_row_csv(text, email))
            gradebook = Gradebook.from_file(str(f_out))

        assert list(gradebook.df_perc.index) == [email]
        assert gradebook.points['exam1'] == 100

    def test_one_row_and_the_header_over_it(self, f_canvas):
        text = student.one_row_csv(f_canvas.read_text(),
                                   'dan.doesntdohw@uni.edu')

        assert len(text.strip().split('\n')) == 3


class TestWhatIf:
    def test_a_score_typed_in_moves_the_grade(self, f_scope_std, tmp_path,
                                              write_policy):
        policy = Policy.from_file(write_policy(
            'category:\n  weight:\n    hw: 100\n'))
        mine = student.one_row_csv(f_scope_std.read_text(), 'alice@u.edu')

        before = graded_one(mine, policy, tmp_path)
        after = graded_one(student.add_scores(mine, {'hw3': 10}), policy,
                           tmp_path)

        assert before == pytest.approx(24 / 30)
        assert after == pytest.approx(28 / 30)

    def test_a_planned_assignment_gets_the_columns_it_never_had(
            self, f_scope_std, tmp_path, write_policy):
        policy = Policy.from_file(write_policy(
            'category:\n  weight:\n    hw: 100\n'
            'assignments:\n  planned:\n    hw4: 10\n'))
        mine = student.one_row_csv(f_scope_std.read_text(), 'alice@u.edu')

        # planned, so it counts for nobody and the mean is over three
        assert graded_one(mine, policy, tmp_path) == pytest.approx(24 / 30)

        text = student.add_scores(mine, {'hw4': 10}, point_dict={'hw4': 10})

        assert graded_one(text, policy, tmp_path) == pytest.approx(34 / 40)

    def test_a_score_typed_in_is_not_late(self, f_scope_std, tmp_path,
                                          write_policy):
        """ without a lateness cell the reader takes it as never submitted """
        policy = Policy.from_file(write_policy(
            'category:\n  weight:\n    hw: 100\n'
            '  late_penalty:\n    hw:\n      penalty_per_day: 0.5\n'
            'assignments:\n  planned:\n    hw4: 10\n'))
        mine = student.one_row_csv(f_scope_std.read_text(), 'alice@u.edu')
        text = student.add_scores(mine, {'hw4': 10}, point_dict={'hw4': 10})

        assert graded_one(text, policy, tmp_path) == pytest.approx(34 / 40)

    def test_an_unanswered_question_is_left_alone(self, f_scope_std,
                                                  tmp_path, write_policy):
        """ blank is a zero nobody handed in, which is not "no answer yet" """
        policy = Policy.from_file(write_policy(
            'category:\n  weight:\n    hw: 100\n'
            'assignments:\n  planned:\n    hw4: 10\n'))
        mine = student.one_row_csv(f_scope_std.read_text(), 'alice@u.edu')

        text = student.add_scores(mine, {'hw3': None, 'hw4': None},
                                  point_dict={'hw4': 10})

        assert text == mine
        assert graded_one(text, policy, tmp_path) == pytest.approx(24 / 30)

    def test_the_lateness_beside_it_is_left_alone(self, f_scope_std,
                                                  tmp_path, write_policy):
        """ what a score would have been is a question about the score

        Answering it by also forgiving the days it was late would quietly
        take a penalty off the estimate.
        """
        policy = Policy.from_file(write_policy(
            'category:\n  weight:\n    hw: 100\n'
            '  late_penalty:\n    hw:\n      penalty_per_day: 0.1\n'))
        # bob is a day late on hw1, and has 30/30 before the penalty
        mine = student.one_row_csv(f_scope_std.read_text(), 'bob@u.edu')

        assert graded_one(mine, policy, tmp_path) == pytest.approx(1 - .1 / 3)

        text = student.add_scores(mine, {'hw1': 5})

        assert graded_one(text, policy, tmp_path) == \
            pytest.approx(25 / 30 - .1 / 3)

    def test_taking_an_answer_back_out(self, f_scope_std, tmp_path,
                                       write_policy):
        """ asked again without it, from the csv as it came """
        policy = Policy.from_file(write_policy(
            'category:\n  weight:\n    hw: 100\n'
            'assignments:\n  planned:\n    hw4: 10\n'))
        mine = student.one_row_csv(f_scope_std.read_text(), 'alice@u.edu')
        point_dict = {'hw4': 10}

        was = graded_one(mine, policy, tmp_path)
        student.add_scores(mine, {'hw4': 10}, point_dict=point_dict)
        back = student.add_scores(mine, {}, point_dict=point_dict)

        assert graded_one(back, policy, tmp_path) == pytest.approx(was)

    def test_a_planned_assignment_with_no_max_points(self, f_scope_std):
        mine = student.one_row_csv(f_scope_std.read_text(), 'alice@u.edu')

        with pytest.raises(FinalgradeError, match='hw4'):
            student.add_scores(mine, {'hw4': 10})

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


def graded_one(csv_text, policy, tmp_path):
    """ the one student in csv_text's mean """
    f_out = tmp_path / 'one.csv'
    f_out.write_text(csv_text)
    got_dict = graded(f_out, policy)
    assert len(got_dict) == 1
    return list(got_dict.values())[0][0]


class TestTheWholeExample:
    """ the hundred students behind the page's "try an example" button

    The three student fixture above is where a difference gets diagnosed;
    this is where one gets found.  The example is built to be awkward on
    purpose -- somebody who hands in nothing, somebody who is always late,
    an assignment that stands in for another -- so it is the population an
    off-by-one in the cut would show up in.
    """

    def test_every_one_of_them_gets_their_own_number(
            self, f_example, policy_example, email_list, tmp_path):
        want_dict = graded(f_example, policy_example)
        csv_text = f_example.read_text()

        assert len(email_list) == 100

        for email in email_list:
            text = student.policy_text(policy_example, email=email)
            got_dict = student_grade(student.one_row_csv(csv_text, email),
                                     text, tmp_path)

            assert got_dict[email] == want_dict[email], email

    def test_no_other_student_is_named_in_any_of_them(
            self, policy_example, email_list):
        """ a hundred files, and none of them mentions ninety nine people """
        other_set = set(email_list)

        for email in email_list:
            text = student.policy_text(policy_example, email=email)

            for other in other_set - {email}:
                assert other not in text, f'{other} leaked into {email}'
