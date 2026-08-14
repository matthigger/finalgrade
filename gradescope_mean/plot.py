import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots


def plot_hist(df_grade_full, cat_weight_dict):
    """ plots a histogram of grades

    example:
    https://github.com/matthigger/gradescope_mean/blob/main/doc/hist.png

    Args:
        df_grade_full (pd.DataFrame):
        cat_weight_dict (dict): keys are categories, values are weights

    Returns:
        fig (plotly):
    """

    # always plot mean grade histogram
    feat_list = ['mean']
    if cat_weight_dict is not None:
        # plot histogram per category (if specified)
        feat_list += [f'mean_{feat}' for feat in cat_weight_dict.keys()]

    # bins span the observed range (a fixed .5 floor hides failing students)
    s_all = pd.concat([df_grade_full[feat] for feat in feat_list]).dropna()
    start = min(0., float(s_all.min())) if len(s_all) else 0.
    end = max(1., float(s_all.max())) if len(s_all) else 1.
    size = (end - start) / 20

    # make histogram subplots
    fig = make_subplots(cols=len(feat_list), rows=1, subplot_titles=feat_list)
    for col_idx, feat in enumerate(feat_list):
        trace = go.Histogram(y=df_grade_full[feat], name='feat',
                             ybins=dict(start=start, end=end, size=size),
                             opacity=0.75)
        fig.add_trace(trace, col=col_idx + 1, row=1)

        mean = df_grade_full[feat].mean()
        fig.add_hline(y=mean, annotation_text=f'mean: {mean:.3f}',
                      col=col_idx + 1, row=1)
    fig.update_layout(showlegend=False)

    return fig
