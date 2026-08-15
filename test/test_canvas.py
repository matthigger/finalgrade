import pathlib

import pandas as pd
import pytest

import finalgrade
from finalgrade.canvas.canvas import canvas_merge
from finalgrade.config import Config

test_folder = pathlib.Path(finalgrade.__file__).parents[1] / 'test'


@pytest.fixture
def canvas_csv(tmp_path):
    """Create a minimal canvas CSV for testing"""
    # SIS User IDs must match the 'sid' column from Gradescope (with S suffix)
    df = pd.DataFrame({
        'Student': ['Student, Test0', 'Student, Test1'],
        'ID': [100, 101],
        'SIS User ID': ['0123456789S', '0023456789S'],
        'SIS Login ID': ['last0@nu.edu', 'last1@nu.edu'],
        'Section': ['sec01', 'sec01'],
        'HW (placeholder)': [0, 0],
    })
    f = tmp_path / 'canvas.csv'
    df.to_csv(f, index=False)
    return str(f)


@pytest.fixture
def df_grade():
    """Process test scope.csv and return grade dataframe"""
    config = Config()
    _, df_grade_full = config(f_scope=test_folder / 'scope.csv')
    return df_grade_full


class TestCanvasMerge:
    def test_basic_merge(self, canvas_csv, df_grade):
        df_out = canvas_merge(f_canvas=canvas_csv,
                              df_grade=df_grade,
                              rm_gradescope_meta=False,
                              del_col_list=['firstname', 'lastname', 'sid',
                                            'section_name'],
                              scale100=False)
        assert 'mean' in df_out.columns
        assert 'letter' in df_out.columns
        # should have rows from canvas (2 students)
        assert df_out.shape[0] == 2
        # meta columns should be deleted
        assert 'firstname' not in df_out.columns

    def test_scale100(self, canvas_csv, df_grade):
        df_out = canvas_merge(f_canvas=canvas_csv,
                              df_grade=df_grade,
                              rm_gradescope_meta=False,
                              del_col_list=['firstname', 'lastname', 'sid',
                                            'section_name'],
                              scale100=True)
        # mean should be scaled by 100 (original is 0-1)
        assert df_out['mean'].max() <= 100
        assert df_out['mean'].min() >= 0

    def test_no_rm_meta(self, canvas_csv, df_grade):
        df_out = canvas_merge(f_canvas=canvas_csv,
                              df_grade=df_grade,
                              rm_gradescope_meta=False,
                              scale100=False)
        # firstname/lastname should still be present
        assert 'firstname' in df_out.columns
