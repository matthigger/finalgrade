import pathlib

import pytest

import finalgrade
from finalgrade.config import Config
from finalgrade.plot import plot_hist

test_folder = pathlib.Path(finalgrade.__file__).parents[1] / 'test'


@pytest.fixture
def grade_data():
    """Return (gradebook, df_grade_full, cat_weight_dict) for test data"""
    cat_weight_dict = {'hw': 3, 'quiz': 1}
    config = Config(cat_weight_dict=cat_weight_dict)
    gradebook, df_grade_full = config(f_scope=test_folder / 'scope.csv')
    return gradebook, df_grade_full, cat_weight_dict


class TestPlot:
    def test_plot_hist(self, grade_data):
        gradebook, df_grade_full, cat_weight_dict = grade_data
        fig = plot_hist(df_grade_full=df_grade_full,
                        cat_weight_dict=cat_weight_dict)
        # should return a plotly figure with traces
        assert fig is not None
        assert len(fig.data) > 0

    def test_plot_hist_no_categories(self):
        config = Config()
        gradebook, df_grade_full = config(f_scope=test_folder / 'scope.csv')
        fig = plot_hist(df_grade_full=df_grade_full, cat_weight_dict=None)
        assert fig is not None
