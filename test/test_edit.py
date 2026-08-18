""" editing a policy the way the browser's widgets do

The point of every test here is the same: an edit changes what it was asked
to change and nothing else.  A form that quietly dropped the user's comments,
or a section it has no widget for, would make the file worth less every time
it was touched.
"""
import pytest

from finalgrade import edit, web
from finalgrade.policy import Policy
from finalgrade.errors import PolicyError

# a file with something in every corner the widgets don't touch
YAML_FULL = """\
# my course, spring 2026
category:
  weight:
    hw: 60      # the homeworks
    exam: 40
  drop_low:
    hw: 2

assignments:
  substitute:
    quiz1:
      - quiz1 v2

waive:
  alice@u.edu: hw1

grade_thresh:
  .9: A
  0: F
"""


def cfg(text):
    """ the policy a policy text means """
    import pathlib
    import tempfile

    with tempfile.TemporaryDirectory() as folder:
        f = pathlib.Path(folder) / 'policy.yaml'
        f.write_text(text)
        return Policy.from_file(f)


class TestKeepsEverythingElse:
    def test_comments_survive(self):
        out = edit.apply(YAML_FULL, 'set_weight', dict(cat='hw', weight=70))

        assert '# my course, spring 2026' in out
        assert '# the homeworks' in out

    def test_sections_with_no_widget_survive(self):
        out = edit.apply(YAML_FULL, 'set_weight', dict(cat='hw', weight=70))

        assert cfg(out).sub_dict == {'quiz1': ['quiz1v2']}
        assert cfg(out).grade_thresh == {.9: 'A', 0: 'F'}

    def test_key_order_survives(self):
        out = edit.apply(YAML_FULL, 'set_drop_low', dict(cat='hw', n=3))

        assert out.index('category:') < out.index('assignments:') \
            < out.index('waive:') < out.index('grade_thresh:')

    def test_a_seeded_config_keeps_its_assignment_table(self, f_scope_std):
        seeded = web.seed_policy(f_scope_std.read_text(), 'scope.csv')

        out = edit.apply(seeded, 'add_category', dict(cat='hw'))

        assert 'the 4 assignments found' in out
        assert '# a guess at your categories' in out

    def test_the_commented_guess_stays_commented(self, f_scope_std):
        """ round-tripping must not un-comment the block it sits next to """
        seeded = web.seed_policy(f_scope_std.read_text(), 'scope.csv')

        out = edit.apply(seeded, 'add_category', dict(cat='hw'))

        bare_list = [ln for ln in out.splitlines() if ln == 'category:']
        assert len(bare_list) == 1


class TestCategory:
    def test_add_shares_the_weight_evenly(self):
        out = edit.apply('', 'add_category', dict(cat='hw'))
        out = edit.apply(out, 'add_category', dict(cat='exam'))

        assert cfg(out).cat_weight_dict == {'hw': 50, 'exam': 50}

    def test_add_three(self):
        out = ''
        for cat in ('hw', 'exam', 'quiz'):
            out = edit.apply(out, 'add_category', dict(cat=cat))

        assert cfg(out).cat_weight_dict == {'hw': 33, 'exam': 33, 'quiz': 33}

    def test_add_is_idempotent(self):
        out = edit.apply('', 'add_category', dict(cat='hw'))
        again = edit.apply(out, 'add_category', dict(cat='hw'))

        assert cfg(again).cat_weight_dict == cfg(out).cat_weight_dict

    def test_set_weight(self):
        out = edit.apply(YAML_FULL, 'set_weight', dict(cat='hw', weight=70))

        assert cfg(out).cat_weight_dict == {'hw': 70, 'exam': 40}

    def test_weight_is_written_without_a_decimal(self):
        """ a widget hands over 70.0; nobody types that into a policy """
        out = edit.apply(YAML_FULL, 'set_weight', dict(cat='hw', weight=70.0))

        assert 'hw: 70' in out
        assert 'hw: 70.0' not in out

    def test_remove_takes_its_drop_and_late_with_it(self):
        out = edit.apply(YAML_FULL, 'set_late', dict(
            cat='hw', late_dict={'penalty_per_day': .1}))
        out = edit.apply(out, 'remove_category', dict(cat='hw'))

        policy = cfg(out)
        assert policy.cat_weight_dict == {'exam': 40}
        assert policy.cat_drop_dict == {}
        assert policy.cat_late_dict == {}

    def test_removing_the_last_one_leaves_a_readable_file(self):
        out = YAML_FULL
        for cat in ('hw', 'exam'):
            out = edit.apply(out, 'remove_category', dict(cat=cat))

        assert cfg(out).cat_weight_dict == {}

    def test_drop_low_zero_is_kept_and_clear_rule_removes_it(self):
        """ a 0 is written rather than taken as "remove", so that a form can
        show the rule before the number is typed """
        out = edit.apply(YAML_FULL, 'set_drop_low', dict(cat='hw', n=0))
        assert cfg(out).cat_drop_dict == {'hw': 0}

        out = edit.apply(out, 'clear_rule', dict(cat='hw'))
        assert cfg(out).cat_drop_dict == {}


class TestLate:
    def test_set_and_read_back(self):
        out = edit.apply(YAML_FULL, 'set_late', dict(
            cat='hw', late_dict={'penalty_per_day': .15, 'excuse_day': 3}))

        assert cfg(out).cat_late_dict == {
            'hw': {'penalty_per_day': .15, 'excuse_day': 3}}

    def test_partial_update_keeps_the_rest(self):
        """ the widgets send one field at a time """
        out = edit.apply(YAML_FULL, 'set_late', dict(
            cat='hw', late_dict={'penalty_per_day': .15, 'excuse_day': 3}))
        out = edit.apply(out, 'set_late', dict(
            cat='hw', late_dict={'excuse_day': 5}))

        assert cfg(out).cat_late_dict == {
            'hw': {'penalty_per_day': .15, 'excuse_day': 5}}

    def test_none_removes_it(self):
        out = edit.apply(YAML_FULL, 'set_late', dict(
            cat='hw', late_dict={'penalty_per_day': .15}))
        out = edit.apply(out, 'set_late', dict(cat='hw', late_dict=None))

        assert cfg(out).cat_late_dict == {}

    def test_it_reaches_grading(self, f_scope_std):
        """ a policy built only by widget edits still grades """
        out = edit.apply('', 'add_category', dict(cat='hw'))
        # quiz1 too, or it would fall in no category and warn
        out = edit.apply(out, 'add_category', dict(cat='quiz'))
        out = edit.apply(out, 'set_late', dict(
            cat='hw', late_dict={'penalty_per_day': .5, 'excuse_day': 0}))

        gradebook, df_grade = cfg(out)(str(f_scope_std))

        # bob has full marks on every hw but is a day late on hw1
        assert df_grade.loc['bob@u.edu', 'mean_hw'] < 1


class TestWaive:
    def test_written_as_one_line_per_student(self):
        out = edit.apply('', 'set_waive',
                         dict(email='a@u.edu', ass_list=['hw1', 'hw2']))

        assert 'a@u.edu: hw1, hw2' in out

    def test_read_back_as_a_policy(self):
        out = edit.apply('', 'set_waive',
                         dict(email='a@u.edu', ass_list=['hw1', 'hw2']))

        assert cfg(out).waive_dict == {'a@u.edu': ['hw1', 'hw2']}

    def test_empty_list_removes_the_student(self):
        out = edit.apply(YAML_FULL, 'set_waive',
                         dict(email='alice@u.edu', ass_list=[]))

        assert cfg(out).waive_dict == {}

    def test_late_only_goes_to_its_own_section(self):
        out = edit.apply('', 'set_waive', dict(
            email='a@u.edu', ass_list=['hw1'], field='waive_late'))

        policy = cfg(out)
        assert policy.late_waive_dict == {'a@u.edu': ['hw1']}
        assert policy.waive_dict == {}

    def test_a_made_up_section_is_refused(self):
        with pytest.raises(PolicyError, match='waiver section'):
            edit.apply('', 'set_waive', dict(
                email='a@u.edu', ass_list=['hw1'], field='waive_everything'))


class TestAssignments:
    def test_set_exclude(self):
        out = edit.apply(YAML_FULL, 'set_exclude',
                         dict(ass_list=['practice', 'survey']))

        assert cfg(out).remove_list == ['practice', 'survey']

    def test_empty_exclude_clears_it(self):
        out = edit.apply(YAML_FULL, 'set_exclude',
                         dict(ass_list=['practice']))
        out = edit.apply(out, 'set_exclude', dict(ass_list=[]))

        assert cfg(out).remove_list == []

    def test_complete_thresh(self):
        out = edit.apply(YAML_FULL, 'set_complete_thresh', dict(thresh=.6))

        assert cfg(out).exclude_complete_thresh == .6

    def test_complete_thresh_zero_clears_it(self):
        out = edit.apply(YAML_FULL, 'set_complete_thresh', dict(thresh=.6))
        out = edit.apply(out, 'set_complete_thresh', dict(thresh=0))

        assert cfg(out).exclude_complete_thresh == 0


class TestBlankLines:
    """ a widget must not slowly flatten the file it edits """

    SPACED = """\
category:
  weight:
    hw: 50

  late_penalty:
    hw:
      penalty_per_day: 0.1

assignments:
  exclude:

waive:
"""

    def test_a_new_nested_key_lands_inside_its_block(self):
        out = edit.apply(self.SPACED, 'set_late', dict(
            cat='hw', late_dict={'excuse_day': 3}))

        line_list = out.splitlines()
        at = line_list.index('      excuse_day: 3')
        assert line_list[at - 1].strip() == 'penalty_per_day: 0.1'

    def test_the_separating_blank_line_survives(self):
        out = edit.apply(self.SPACED, 'set_late', dict(
            cat='hw', late_dict={'excuse_day': 3}))

        at = out.splitlines().index('assignments:')
        assert out.splitlines()[at - 1] == ''

    def test_repeated_edits_do_not_accumulate_damage(self):
        out = self.SPACED
        for n in range(4):
            out = edit.apply(out, 'set_late',
                             dict(cat='hw', late_dict={'excuse_day': n}))
            out = edit.apply(out, 'set_weight', dict(cat='hw', weight=50 + n))

        assert out.count('\n\n') == self.SPACED.count('\n\n')
        assert cfg(out).cat_late_dict['hw']['excuse_day'] == 3


class TestExcuseOffset:
    LATE = """\
category:
  weight:
    hw: 100
  late_penalty:
    hw:
      penalty_per_day: .1
      excuse_day: 2
"""

    def test_set(self):
        out = edit.apply(self.LATE, 'set_excuse_offset',
                         dict(cat='hw', email='a@u.edu', days=3))

        assert cfg(out).cat_late_dict['hw']['excuse_day_offset'] == \
            {'a@u.edu': 3}

    def test_negative_is_allowed(self):
        """ an offset takes days away as readily as it gives them """
        out = edit.apply(self.LATE, 'set_excuse_offset',
                         dict(cat='hw', email='a@u.edu', days=-2))

        assert cfg(out).cat_late_dict['hw']['excuse_day_offset'] == \
            {'a@u.edu': -2}

    def test_zero_removes_the_student(self):
        out = edit.apply(self.LATE, 'set_excuse_offset',
                         dict(cat='hw', email='a@u.edu', days=3))
        out = edit.apply(out, 'set_excuse_offset',
                         dict(cat='hw', email='a@u.edu', days=0))

        assert 'excuse_day_offset' not in cfg(out).cat_late_dict['hw']

    def test_without_a_late_penalty_it_is_refused(self):
        """ it would be a setting under a category nothing penalises """
        with pytest.raises(PolicyError, match='no late penalty'):
            edit.apply('category:\n  weight:\n    hw: 100\n',
                       'set_excuse_offset',
                       dict(cat='hw', email='a@u.edu', days=3))


class TestSubstitute:
    def test_set(self):
        out = edit.apply('', 'set_substitute',
                         dict(target='quiz1', ass_list=['quiz1v2']))

        assert cfg(out).sub_dict == {'quiz1': ['quiz1v2']}

    def test_empty_removes_it(self):
        out = edit.apply(YAML_FULL, 'set_substitute',
                         dict(target='quiz1', ass_list=[]))

        assert cfg(out).sub_dict == {}


class TestGradeThresh:
    def test_written_highest_first(self):
        out = edit.apply('', 'set_grade_thresh', dict(thresh_list=[
            dict(perc=0, letter='F'),
            dict(perc=.9, letter='A'),
            dict(perc=.8, letter='B')]))

        assert list(cfg(out).grade_thresh.items()) == \
            [(.9, 'A'), (.8, 'B'), (0, 'F')]

    def test_empty_restores_the_default(self):
        out = edit.apply(YAML_FULL, 'set_grade_thresh', dict(thresh_list=[]))

        assert cfg(out).grade_thresh is None

    def test_it_reaches_grading(self, f_scope_std):
        out = edit.apply('', 'set_grade_thresh', dict(thresh_list=[
            dict(perc=.5, letter='pass'), dict(perc=0, letter='no')]))

        gradebook, df_grade = cfg(out)(str(f_scope_std))

        assert set(df_grade['letter']) <= {'pass', 'no'}


class TestEmailList:
    def test_set(self):
        out = edit.apply('', 'set_email_list',
                         dict(email_list=['a@u.edu', 'b@u.edu']))

        assert cfg(out).email_list == ['a@u.edu', 'b@u.edu']

    def test_empty_grades_everyone(self):
        out = edit.apply('email_list:\n  - a@u.edu\n', 'set_email_list',
                         dict(email_list=[]))

        assert cfg(out).email_list == []


class TestExtraCredit:
    def test_set(self):
        out = edit.apply('', 'set_extra', dict(ass_list=['hw4', 'bonus']))

        assert cfg(out).extra_list == ['hw4', 'bonus']

    def test_empty_clears_it(self):
        out = edit.apply('assignments:\n  extra_credit:\n    - hw4\n',
                         'set_extra', dict(ass_list=[]))

        assert cfg(out).extra_list == []

    def test_leaves_the_other_assignment_settings_alone(self):
        out = edit.apply(YAML_FULL, 'set_extra', dict(ass_list=['hw4']))

        assert cfg(out).sub_dict == {'quiz1': ['quiz1v2']}

    def test_the_list_lands_under_its_own_key(self):
        """ a blank line separating two sections must not land inside one

        The blank after the last key of a block is ruamel's, hung on that
        key; a list written there would appear below it, so the items read
        as though they belonged to the section that follows.
        """
        text = 'assignments:\n  exclude_complete_thresh:\n  exclude:\n' \
               '  substitute:\n\nwaive:\n\ngrade_thresh:\n  .9: A\n  0: F\n'

        out = edit.apply(text, 'set_extra', dict(ass_list=['hw8']))

        assert '  extra_credit:\n  - hw8\n\nwaive:\n' in out
        assert cfg(out).extra_list == ['hw8']

    def test_the_blank_survives_a_second_edit(self):
        text = 'assignments:\n  exclude:\n\nwaive:\n'

        out = edit.apply(text, 'set_extra', dict(ass_list=['hw8']))
        out = edit.apply(out, 'set_extra', dict(ass_list=['hw8', 'hw7']))

        assert '  - hw8\n  - hw7\n\nwaive:\n' in out


class TestNote:
    """ text about one student, kept in the policy that adjusted their grade
    """

    def test_set_and_read_back(self):
        out = edit.apply('', 'set_note', dict(
            email='alice@u.edu', note='extension agreed with the dean'))

        assert cfg(out).note_dict == {
            'alice@u.edu': 'extension agreed with the dean'}

    def test_empty_removes_it(self):
        out = edit.apply('note:\n  alice@u.edu: why\n', 'set_note',
                         dict(email='alice@u.edu', note=''))

        assert cfg(out).note_dict == {}
        assert 'alice' not in out

    def test_whitespace_only_removes_it(self):
        out = edit.apply('note:\n  alice@u.edu: why\n', 'set_note',
                         dict(email='alice@u.edu', note='   '))

        assert cfg(out).note_dict == {}

    def test_one_student_at_a_time(self):
        out = edit.apply('', 'set_note', dict(email='alice@u.edu', note='a'))
        out = edit.apply(out, 'set_note', dict(email='bob@u.edu', note='b'))

        assert cfg(out).note_dict == {'alice@u.edu': 'a', 'bob@u.edu': 'b'}

    def test_changes_no_grade(self, f_scope_std):
        plain = edit.apply('', 'add_category', dict(cat='hw'))
        plain = edit.apply(plain, 'add_category', dict(cat='quiz'))
        noted = edit.apply(plain, 'set_note',
                           dict(email='alice@u.edu', note='hospital'))

        _, df_plain = cfg(plain)(str(f_scope_std))
        _, df_noted = cfg(noted)(str(f_scope_std))

        assert df_plain.to_csv() == df_noted.to_csv()

    def test_comments_survive(self):
        out = edit.apply(YAML_FULL, 'set_note',
                         dict(email='alice@u.edu', note='hospital'))

        assert '# my course, spring 2026' in out
        assert cfg(out).waive_dict == {'alice@u.edu': ['hw1']}


class TestBadInput:
    def test_unknown_edit(self):
        with pytest.raises(PolicyError, match='not an edit'):
            edit.apply('', 'set_everything', dict())

    def test_unreadable_yaml(self):
        with pytest.raises(PolicyError, match='could not read'):
            edit.apply('category:\n\tweight: 1\n', 'add_category',
                       dict(cat='hw'))

    def test_a_document_that_is_not_a_mapping(self):
        with pytest.raises(PolicyError, match='mapping'):
            edit.apply('- one\n- two\n', 'add_category', dict(cat='hw'))

    def test_empty_document_is_fine(self):
        out = edit.apply('', 'add_category', dict(cat='hw'))

        assert cfg(out).cat_weight_dict == {'hw': 100}
