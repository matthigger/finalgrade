import pytest

from finalgrade.assign_list import *

columns = ['skip me', 'H W 1 - max points', 'hw1', 'HW2 - max points', 'hw2']


@pytest.fixture
def ass_list():
    return AssignmentList.from_columns(columns)


class TestAssignmentList:
    def test_normalize(self):
        assert normalize('  A B C 1 2 3') == 'abc123'

    def test_from_columns(self, ass_list):
        # only columns with a matching ' - max points' are assignments
        ass_list_exp = ['hw1', 'hw2']
        assert ass_list == ass_list_exp

    def test_init_is_plain_list(self):
        # building from known names is side effect free (no filtering, no
        # warnings) so that it is cheap to derive from a dataframe's columns
        assert AssignmentList(['hw2', 'hw1']) == ['hw2', 'hw1']

    def test_from_columns_warns_prefix(self):
        with pytest.warns(UserWarning, match='prefixes'):
            col_list = [s + AssignmentList.MAX_PTS for s in
                        ('hw1', 'hw10', 'hw_another')]
            AssignmentList.from_columns(col_list)

    def test_get_column_set(self):
        col_set = AssignmentList(['hw1']).get_column_set()
        assert 'hw1' in col_set
        assert 'hw1' + AssignmentList.MAX_PTS in col_set
        assert 'hw1' + AssignmentList.LATE in col_set
        assert 'hw1' + AssignmentList.SUB_TIME in col_set

    def test_match(self, ass_list):
        assert ass_list.match('  hw1  ') == 'hw1'

        # ambiguous match (hw matches both hw1 and hw2)
        with pytest.raises(AssignmentNotFoundError):
            ass_list.match('hw')

        # assignment that doesn't exist at all
        with pytest.raises(AssignmentNotFoundError):
            ass_list.match('ghost assignment')

    def test_match_iter(self, ass_list):
        s_assign_exp = ['hw1', 'hw2']
        s_assign = sorted(ass_list.match_iter(s_assign='hw'))
        assert s_assign == s_assign_exp

    def test_match_iter_no_match(self, ass_list):
        s_assign = list(ass_list.match_iter(s_assign='nonexistent'))
        assert s_assign == []
