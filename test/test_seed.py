""" a new policy that already knows the course's assignment names

The seeded block is comments, so these tests care about two things only: that
the names in it are the ones the policy would have to use, and that reading
the file back yields exactly the same policy as the packaged default (the
guess must not grade anybody until someone uncomments it).
"""
import warnings

import pytest

from finalgrade.policy import F_POLICY_DEFAULT, NAME_PRIVATE, Policy
from finalgrade.gradebook import Gradebook
from finalgrade.seed import guess_cat_list, seed_text

from test_canvas_read import write_canvas


@pytest.fixture
def text_seed(f_scope_std):
    gradebook = Gradebook.from_file(str(f_scope_std))
    return seed_text(gradebook, str(f_scope_std),
                     F_POLICY_DEFAULT.read_text())


class TestGuess:
    def test_groups_by_leading_word(self):
        assert guess_cat_list(['hw1', 'hw2', 'quiz1']) == ['hw', 'quiz']

    def test_canvas_groups_win_when_they_match(self):
        """ the instructor already named these categories in canvas """
        cat_list = guess_cat_list(['hw1', 'hw2', 'exammidterm'],
                                  cat_hint_list=['HW', 'Exam'])
        assert cat_list == ['hw', 'exam']

    def test_canvas_group_matching_nothing_is_dropped(self):
        """ a canvas group 'Problem Sets' says nothing about 'ps1' """
        cat_list = guess_cat_list(['ps1', 'ps2'],
                                  cat_hint_list=['Problem Sets'])
        assert cat_list == ['ps']

    def test_assignments_no_canvas_group_covers_still_get_one(self):
        cat_list = guess_cat_list(['hw1', 'final1'], cat_hint_list=['HW'])
        assert cat_list == ['hw', 'final']

    def test_name_with_no_leading_letter_is_its_own_category(self):
        assert guess_cat_list(['1intro']) == ['1intro']

    def test_no_assignments_no_categories(self):
        assert guess_cat_list([]) == []


class TestSeedText:
    def test_names_every_assignment(self, text_seed):
        for ass in ('hw1', 'hw2', 'hw3', 'quiz1'):
            assert ass in text_seed

    def test_names_them_as_the_config_must_spell_them(self, f_scope_std,
                                                      text_seed):
        """ the csv says 'HW1'; a policy has to say hw1 """
        assert 'HW1' not in text_seed
        assert 'hw1' in text_seed

    def test_guess_is_commented_out(self, text_seed, tmp_path):
        """ an uninvited weight is a wrong grade, so it must not take effect
        """
        f_policy = tmp_path / 'seeded.yaml'
        f_policy.write_text(text_seed)

        assert Policy.from_file(f_policy).cat_weight_dict == {}

    def test_reads_back_as_the_packaged_default(self, text_seed, tmp_path):
        f_seed = tmp_path / 'seeded.yaml'
        f_seed.write_text(text_seed)

        policy_seed = Policy.from_file(f_seed)
        policy_default = Policy.from_file(F_POLICY_DEFAULT)
        assert policy_seed == policy_default

    def test_guess_shows_what_each_category_would_catch(self, text_seed):
        line = next(ln for ln in text_seed.splitlines()
                    if ln.strip().startswith('#     hw:'))
        assert 'hw1, hw2, hw3' in line

    def test_keeps_the_packaged_examples(self, text_seed):
        """ the seeded block is an addition, not a replacement """
        assert 'excuse_day_offset' in text_seed
        assert 'grade_thresh' in text_seed

    def test_names_the_csv_it_was_written_for(self, text_seed):
        assert 'scope.csv' in text_seed

    def test_zero_point_assignment_is_called_out(self, tmp_path):
        from conftest import ASSIGN_STD, STUDENT_STD, write_scope

        assign_dict = dict(ASSIGN_STD, Survey=0)
        f_scope = write_scope(tmp_path / 'scope.csv', assign_dict,
                              STUDENT_STD)

        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            gradebook = Gradebook.from_file(str(f_scope))
        text = seed_text(gradebook, str(f_scope), F_POLICY_DEFAULT.read_text())

        assert 'worth 0 points: survey' in text


class TestSeedCanvas:
    def test_uses_canvas_assignment_groups(self, tmp_path):
        gradebook = Gradebook.from_file(write_canvas(tmp_path / 'canvas.csv'))
        text = seed_text(gradebook, 'canvas.csv',
                         F_POLICY_DEFAULT.read_text())

        assert 'your canvas assignment groups' in text
        # 'HW Current Points' is a rollup for a group named HW
        assert gradebook.cat_hint_list == ['HW']

    def test_course_wide_total_is_not_a_category(self, tmp_path):
        """ 'Current Score' is every assignment, not a group """
        gradebook = Gradebook.from_file(write_canvas(tmp_path / 'canvas.csv'))

        assert '' not in gradebook.cat_hint_list

    def test_gradescope_has_no_hints(self, f_scope_std):
        assert Gradebook.from_file(str(f_scope_std)).cat_hint_list == []


class TestResolveConfig:
    def test_new_config_is_seeded(self, f_scope_std):
        Policy.resolve_policy(f_scope_std.parent, f_grade=str(f_scope_std))

        text = (f_scope_std.parent / NAME_PRIVATE).read_text()
        assert 'quiz1' in text

    def test_a_new_one_is_named_private(self, f_scope_std):
        """ it names students, so the name is the warning not to hand it out
        """
        Policy.resolve_policy(f_scope_std.parent, f_grade=str(f_scope_std))

        assert (f_scope_std.parent / NAME_PRIVATE).exists()
        assert not (f_scope_std.parent / 'policy.yaml').exists()

    def test_a_policy_yaml_already_there_is_still_read(self, f_scope_std):
        """ a course part way through a term is not asked to rename anything
        """
        f_legacy = f_scope_std.parent / 'policy.yaml'
        f_legacy.write_text('category:\n  weight:\n    quiz: 100\n')

        policy = Policy.resolve_policy(f_scope_std.parent,
                                       f_grade=str(f_scope_std))

        assert policy.cat_weight_dict == {'quiz': 100}
        assert not (f_scope_std.parent / NAME_PRIVATE).exists()

    def test_without_a_csv_the_packaged_default_is_copied(self, tmp_path):
        Policy.resolve_policy(tmp_path)

        assert (tmp_path / NAME_PRIVATE).read_text() == \
            F_POLICY_DEFAULT.read_text()

    def test_unreadable_csv_still_yields_a_config(self, tmp_path):
        """ failing to be helpful must not stop the tool working """
        f_csv = tmp_path / 'nonsense.csv'
        f_csv.write_text('not,a,gradebook\n1,2,3\n')

        Policy.resolve_policy(tmp_path, f_grade=str(f_csv))

        assert (tmp_path / NAME_PRIVATE).read_text() == \
            F_POLICY_DEFAULT.read_text()

    def test_existing_config_is_left_alone(self, f_scope_std, write_policy):
        write_policy('category:\n  weight:\n    hw: 100\n')

        policy = Policy.resolve_policy(f_scope_std.parent,
                                       f_grade=str(f_scope_std))

        assert policy.cat_weight_dict == {'hw': 100}
