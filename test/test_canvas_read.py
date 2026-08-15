"""Reading a canvas gradebook export as a source of grades.

Written against the public boundary (a canvas csv in, a Gradebook out), with
expected values hand-computed inline rather than snapshotted.

The fixtures mirror the structural features of a real canvas export that a
hand-written one tends to omit, because every one of them has bitten us:
the leading 'Points Possible' row, the trailing test student, canvas' own
'(read only)' rollup columns, and the assignment id glued to every name.
"""
import pandas as pd
import pytest

from finalgrade.canvas.read import is_canvas_export
from finalgrade.policy import Policy
from finalgrade.errors import CanvasError, PolicyError, GradebookError
from finalgrade.gradebook import Gradebook

# --------------------------------------------------------------------------
# the shared 2-student canvas export
#
#            hw 1   hw 2   exam 1
#   points     10     20      100
#   alice      10     18       90
#   bob         5     EX        _        (_ = blank, EX = excused)
#
# so, as percentages: alice 1.0 / .9 / .9,  bob .5 / waived / 0
#
# note there is no 0 point assignment here: the suite runs with
# filterwarnings=error, so the warning that one raises belongs only in the
# test that is about it.
# --------------------------------------------------------------------------
ROW_POINTS = {
    'Student': '    Points Possible', 'ID': '', 'SIS User ID': '',
    'SIS Login ID': '', 'Section': '',
    'HW 1 (2958072)': '10', 'HW 2 (2958073)': '20',
    'Exam 1 (2958074)': '100',
    'HW Current Points': '(read only)', 'Current Score': '(read only)'}
ROW_ALICE = {
    'Student': 'Anders, Alice', 'ID': '100', 'SIS User ID': '001234567S',
    'SIS Login ID': '001234567S', 'Section': 'DS4400 SEC 01',
    'HW 1 (2958072)': '10', 'HW 2 (2958073)': '18',
    'Exam 1 (2958074)': '90',
    'HW Current Points': '28', 'Current Score': '93'}
ROW_BOB = {
    'Student': 'Baker, Bob', 'ID': '101', 'SIS User ID': '007654321S',
    'SIS Login ID': '007654321S', 'Section': 'DS4400 SEC 02',
    'HW 1 (2958072)': '5', 'HW 2 (2958073)': 'EX',
    'Exam 1 (2958074)': '',
    'HW Current Points': '5', 'Current Score': '50'}
ROW_TEST_STUDENT = {
    'Student': 'Student, Test', 'ID': '999', 'SIS User ID': '',
    'SIS Login ID': 'abc123', 'Section': 'DS4400 SEC 01',
    'HW 1 (2958072)': '', 'HW 2 (2958073)': '', 'Exam 1 (2958074)': '',
    'HW Current Points': '', 'Current Score': ''}


def write_canvas(f_out, row_list=None):
    """ writes a canvas-style csv (points row first, test student last) """
    if row_list is None:
        row_list = [ROW_ALICE, ROW_BOB]
    pd.DataFrame([ROW_POINTS] + row_list + [ROW_TEST_STUDENT]).to_csv(
        f_out, index=False)
    return str(f_out)


@pytest.fixture
def f_canvas(tmp_path):
    return write_canvas(tmp_path / 'canvas.csv')


class TestStructure:
    def test_detected_as_canvas(self, f_canvas, f_scope_std):
        assert is_canvas_export(f_canvas)
        assert not is_canvas_export(str(f_scope_std))

    def test_from_file_dispatches(self, f_canvas, f_scope_std):
        # the canvas export has no lateness, the gradescope one does
        assert not Gradebook.from_file(f_canvas).has_lateness
        assert Gradebook.from_file(str(f_scope_std)).has_lateness

    def test_scaffolding_rows_are_not_students(self, f_canvas):
        """ the points row and the test student are course scaffolding """
        gradebook = Gradebook.from_canvas(f_canvas)
        assert len(gradebook.df_perc) == 2
        assert 'abc123' not in gradebook.df_perc.index

    def test_rollup_columns_are_not_assignments(self, f_canvas):
        """ canvas' own totals are marked '(read only)' in the points row """
        gradebook = Gradebook.from_canvas(f_canvas)
        assert list(gradebook.ass_list) == ['exam1', 'hw1', 'hw2']

    def test_assignment_id_is_stripped(self, f_canvas):
        """ canvas ids change when an assignment is recreated, so a policy
        file can't be made to depend on them """
        assert list(Gradebook.from_canvas(f_canvas).ass_list) == [
            'exam1', 'hw1', 'hw2']

    def test_assignment_id_kept_when_it_disambiguates(self, tmp_path):
        """ ...unless it's the only thing telling two assignments apart """
        row_point = dict(ROW_POINTS)
        row_alice = dict(ROW_ALICE)
        for row, val in ((row_point, '10'), (row_alice, '7')):
            row['HW 1 (3000001)'] = val
        f = write_canvas(tmp_path / 'canvas.csv', [row_alice])
        # 'HW 1 (2958072)' and 'HW 1 (3000001)' both strip to 'hw1'
        pd.DataFrame([row_point, row_alice]).to_csv(f, index=False)

        ass_list = list(Gradebook.from_canvas(f).ass_list)
        assert 'hw1(2958072)' in ass_list
        assert 'hw1(3000001)' in ass_list


class TestValues:
    def test_points_come_from_the_points_row(self, f_canvas):
        points = Gradebook.from_canvas(f_canvas).points
        assert points['hw1'] == 10
        assert points['hw2'] == 20
        assert points['exam1'] == 100

    def test_scores_are_fractions_of_max_points(self, f_canvas):
        df_perc = Gradebook.from_canvas(f_canvas).df_perc
        assert df_perc.loc['001234567s', 'hw1'] == 1.0
        assert df_perc.loc['001234567s', 'hw2'] == pytest.approx(.9)
        assert df_perc.loc['001234567s', 'exam1'] == pytest.approx(.9)
        assert df_perc.loc['007654321s', 'hw1'] == .5

    def test_blank_is_ungraded_and_counts_zero(self, f_canvas):
        """ same meaning a blank gradescope cell has """
        assert Gradebook.from_canvas(f_canvas).df_perc.loc[
            '007654321s', 'exam1'] == 0

    def test_excused_is_waived(self, f_canvas):
        """ canvas' 'EX' is exactly what a waiver means here: nan """
        assert pd.isna(Gradebook.from_canvas(f_canvas).df_perc.loc[
            '007654321s', 'hw2'])

    def test_zero_point_assignment_dropped(self, tmp_path):
        """ canvas courses collect these: solution handouts, and the mean /
        letter columns this tool uploads """
        row_point = {**ROW_POINTS, 'Handout (2958075)': '0'}
        row_alice = {**ROW_ALICE, 'Handout (2958075)': '0'}
        f = tmp_path / 'canvas.csv'
        pd.DataFrame([row_point, row_alice]).to_csv(f, index=False)

        with pytest.warns(UserWarning, match='worth 0 points'):
            gradebook = Gradebook.from_canvas(str(f))
        assert 'handout' not in gradebook.ass_list
        assert list(gradebook.ass_list) == ['exam1', 'hw1', 'hw2']

    def test_metadata(self, f_canvas):
        df_meta = Gradebook.from_canvas(f_canvas).df_meta
        row = df_meta.loc['001234567s']
        # canvas writes 'Last, First'
        assert row['firstname'] == 'alice'
        assert row['lastname'] == 'anders'
        # the sis id keeps its case and leading zeros: canvas_merge joins on it
        assert row['sid'] == '001234567S'
        assert row['sections'] == 'ds4400 sec 01'


class TestStudentKey:
    def test_falls_back_to_sis_id(self, f_canvas):
        """ this export's SIS Login ID is an id, not an email """
        gradebook = Gradebook.from_canvas(f_canvas)
        assert gradebook.df_perc.index.name == 'student'
        assert list(gradebook.df_perc.index) == ['001234567s', '007654321s']

    def test_uses_login_id_when_it_is_an_email(self, tmp_path):
        row_list = []
        for row, email in ((ROW_ALICE, 'alice@u.edu'), (ROW_BOB, 'bob@u.edu')):
            row_list.append({**row, 'SIS Login ID': email})
        f = write_canvas(tmp_path / 'canvas.csv', row_list)

        gradebook = Gradebook.from_canvas(f)
        assert gradebook.df_perc.index.name == 'email'
        assert list(gradebook.df_perc.index) == ['alice@u.edu', 'bob@u.edu']

    def test_email_key_still_matches_by_prefix(self, tmp_path):
        """ the policy's domain-insensitive matching must keep working """
        row_list = [{**ROW_ALICE, 'SIS Login ID': 'alice@northeastern.edu'}]
        f = write_canvas(tmp_path / 'canvas.csv', row_list)

        gradebook = Gradebook.from_canvas(f)
        gradebook.waive({'alice@husky.neu.edu': ['hw1']})
        assert pd.isna(gradebook.df_perc.loc['alice@northeastern.edu', 'hw1'])

    def test_student_with_no_id_raises(self, tmp_path):
        f = write_canvas(tmp_path / 'canvas.csv',
                         [ROW_ALICE, {**ROW_BOB, 'SIS User ID': ''}])
        with pytest.raises(CanvasError, match='Baker, Bob'):
            Gradebook.from_canvas(f)

    def test_duplicate_student_raises(self, tmp_path):
        f = write_canvas(tmp_path / 'canvas.csv',
                         [ROW_ALICE, {**ROW_BOB,
                                      'SIS User ID': ROW_ALICE['SIS User ID']}])
        with pytest.raises(CanvasError, match='001234567s'):
            Gradebook.from_canvas(f)


class TestRefusals:
    def test_late_penalty_refused(self, f_canvas):
        """ a canvas csv has no submission times, so a late penalty would
        quietly compute zero for everybody -- which reads as 'nobody was
        late' rather than 'we can't tell' """
        policy = Policy(cat_weight_dict={'hw': 1, 'exam': 1},
                        cat_late_dict={'hw': {'penalty_per_day': .15}})
        with pytest.raises(PolicyError, match='no submission times'):
            policy(f_canvas)

    def test_all_assignments_worth_zero_raises(self, tmp_path):
        """ a canvas course whose only columns are ones this tool uploaded
        (means, letter grades) has nothing gradeable in it """
        row_point = {'Student': '    Points Possible', 'ID': '',
                     'SIS User ID': '', 'SIS Login ID': '', 'Section': '',
                     'mean_hw (1)': '0', 'letter (2)': '0'}
        row_alice = {'Student': 'Anders, Alice', 'ID': '100',
                     'SIS User ID': '001S', 'SIS Login ID': '001S',
                     'Section': 'sec01', 'mean_hw (1)': '93',
                     'letter (2)': ''}
        f = tmp_path / 'canvas.csv'
        pd.DataFrame([row_point, row_alice]).to_csv(f, index=False)

        with pytest.warns(UserWarning, match='worth 0 points'):
            with pytest.raises(GradebookError, match='nothing to grade'):
                Gradebook.from_canvas(str(f))

    def test_missing_points_row_raises(self, tmp_path):
        f = tmp_path / 'canvas.csv'
        pd.DataFrame([ROW_ALICE]).to_csv(f, index=False)
        with pytest.raises(CanvasError, match='Points Possible'):
            Gradebook.from_canvas(str(f))

    def test_non_numeric_grade_raises(self, tmp_path):
        f = write_canvas(tmp_path / 'canvas.csv',
                         [{**ROW_ALICE, 'HW 1 (2958072)': 'A+'}])
        with pytest.raises(CanvasError, match='not a number'):
            Gradebook.from_canvas(f)

    def test_not_a_canvas_export_raises(self, tmp_path, f_scope_std):
        with pytest.raises(CanvasError, match='not a canvas'):
            Gradebook.from_canvas(str(f_scope_std))


class TestEndToEnd:
    def test_grades_through_config(self, f_canvas):
        """ alice: hw (10 + 18) / 30 = .9333, exam .9  -> mean .91667
            bob:   hw 5/10 = .5 (hw2 waived), exam 0   -> mean .25 """
        _, df_full = Policy(cat_weight_dict={'hw': 1, 'exam': 1})(f_canvas)
        assert df_full.loc['001234567s', 'mean'] == pytest.approx(.9166667)
        assert df_full.loc['007654321s', 'mean'] == pytest.approx(.25)

    def test_cli_round_trip_back_to_canvas(self, tmp_path, f_canvas):
        """ grades read from canvas must upload back to canvas: the sid
        metadata is what canvas_merge joins on """
        from finalgrade.canvas.canvas import canvas_merge
        _, df_full = Policy(cat_weight_dict={'hw': 1, 'exam': 1})(f_canvas)

        df_out = canvas_merge(f_canvas=f_canvas,
                              df_grade=df_full.reset_index(), scale100=False)
        # one row per canvas row, and both students matched
        assert len(df_out) == 4
        assert df_out['mean'].notna().sum() == 2
        # the student key is our index, not a grade: uploading it would make
        # canvas invent an assignment out of it
        assert 'student' not in df_out.columns
        assert 'Student' in df_out.columns
