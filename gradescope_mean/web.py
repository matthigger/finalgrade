""" the api the browser build calls, and the only thing its javascript knows

Everything here takes and returns text or plain data, so that the page never
handles a dataframe and the two halves can't disagree about what a category
caught: the browser shows what `check` shows because it calls the same code.

Nothing in here reads or writes anything outside a temp file: the csv arrives
as a string from a file input the user picked, and the grades leave as a
string the browser offers as a download.  No grade is ever sent anywhere,
which is the entire reason this runs in the page instead of on a server.
"""
import dataclasses
import pathlib
import tempfile
import warnings

from .check import build_report, render
from .config import F_CONFIG_DEFAULT, Config
from .errors import GradescopeMeanError
from .gradebook import Gradebook
from .seed import seed_text

# letters are ordered by the threshold that earns them, best first, so a
# distribution reads the way a gradebook does
__all__ = ['load_csv', 'check_config', 'grade', 'seed_config', 'default_yaml']


class _Csv:
    """ a csv string as a file, for the readers that want a path """

    def __init__(self, csv_text, name='scope.csv'):
        self.folder = tempfile.TemporaryDirectory()
        self.path = pathlib.Path(self.folder.name) / name
        self.path.write_text(csv_text)

    def __enter__(self):
        return str(self.path)

    def __exit__(self, *exc_tup):
        self.folder.cleanup()
        return False


def _warn_list(fn):
    """ runs fn, returning (result, warnings) instead of emitting them

    The page shows warnings next to what they are about, so they have to be
    values rather than something printed to a console nobody opens.
    """
    with warnings.catch_warnings(record=True) as caught_list:
        warnings.simplefilter('always')
        result = fn()
    return result, [str(w.message) for w in caught_list]


def default_yaml():
    """ the packaged config, for a page with no csv yet """
    return F_CONFIG_DEFAULT.read_text()


def load_csv(csv_text, name='scope.csv'):
    """ what this csv is, before any config is applied

    Args:
        csv_text (str): contents of a gradescope or canvas export
        name (str): its filename, used only in messages

    Returns:
        info (dict): source, students, assignments and any complaint
    """
    with _Csv(csv_text, name) as f_csv:
        from .canvas.read import is_canvas_export

        try:
            gradebook, warn_list = _warn_list(
                lambda: Gradebook.from_file(f_csv))
        except GradescopeMeanError as e:
            return dict(ok=False, error=str(e), warn_list=[])

        complete = (gradebook.df_perc.fillna(0) != 0).sum()

        return dict(
            ok=True,
            error=None,
            warn_list=warn_list,
            source='canvas' if is_canvas_export(f_csv) else 'gradescope',
            n_student=len(gradebook.df_perc),
            cat_hint_list=list(gradebook.cat_hint_list),
            zero_point_list=list(gradebook.zero_point_list),
            ass_list=[dict(name=ass,
                           points=float(gradebook.points[ass]),
                           n_complete=int(complete[ass]),
                           n_student=len(gradebook.df_perc))
                      for ass in gradebook.ass_list])


def check_config(csv_text, yaml_text, name='scope.csv'):
    """ what this config would do to this csv, as plain data

    Args:
        csv_text (str): contents of a gradescope or canvas export
        yaml_text (str): contents of a config.yaml
        name (str): the csv's filename

    Returns:
        report (dict): a check.Report, plus its rendered text
    """
    config, error = _read_config(yaml_text)
    if config is None:
        return dict(ok=False, error_list=[error], warn_list=[],
                    ass_list=[], excluded_list=[], cat_list=[], text=error)

    with _Csv(csv_text, name) as f_csv:
        report = build_report(config=config, f_grade=f_csv)

    out = dataclasses.asdict(report)
    # the page names the file the user picked, not a temp directory
    out['f_grade'] = name
    out['ok'] = report.ok
    out['text'] = render(report).replace(str(f_csv), name)
    return out


def grade(csv_text, yaml_text, name='scope.csv'):
    """ final grades, as the csv text the page offers for download

    Args:
        csv_text (str): contents of a gradescope or canvas export
        yaml_text (str): contents of a config.yaml
        name (str): the csv's filename

    Returns:
        result (dict): ok, the output csv text, and a grade distribution
    """
    config, error = _read_config(yaml_text)
    if config is None:
        return dict(ok=False, error=error, warn_list=[])

    with _Csv(csv_text, name) as f_csv:
        try:
            df_grade, warn_list = _warn_list(lambda: config(f_csv)[1])
        except GradescopeMeanError as e:
            return dict(ok=False, error=str(e), warn_list=[])

    s_mean = df_grade['mean'].dropna()
    letter_count = df_grade['letter'].value_counts()

    return dict(
        ok=True,
        error=None,
        warn_list=warn_list,
        csv=df_grade.to_csv(),
        n_student=len(df_grade),
        mean_list=[float(x) for x in s_mean],
        mean_avg=float(s_mean.mean()) if len(s_mean) else None,
        mean_median=float(s_mean.median()) if len(s_mean) else None,
        # ordered by grade, best first, rather than by how many earned it
        letter_list=[dict(letter=str(letter), n=int(letter_count[letter]))
                     for letter in _letter_order(config, letter_count)])


def seed_config(csv_text, name='scope.csv'):
    """ a config.yaml written for this csv's assignments

    Returns the packaged default when the csv can't be read: an editable
    file beats an error raised while trying to be helpful about one.
    """
    with _Csv(csv_text, name) as f_csv:
        try:
            gradebook, _ = _warn_list(lambda: Gradebook.from_file(f_csv))
            return seed_text(gradebook, name, default_yaml())
        except Exception:
            return default_yaml()


def _letter_order(config, letter_count):
    """ the letters actually earned, ordered by the threshold earning them """
    from .perc_to_letter import GRADE_THRESH

    thresh_dict = config.grade_thresh or GRADE_THRESH
    order_list = [letter for _, letter in
                  sorted(thresh_dict.items(), reverse=True)]

    seen_set = set(letter_count.index)
    ordered_list = [ltr for ltr in order_list if ltr in seen_set]
    # any letter the thresholds don't name still has to appear somewhere
    return ordered_list + sorted(seen_set - set(ordered_list))


def _read_config(yaml_text):
    """ a Config from yaml text, or (None, why not) """
    folder = tempfile.TemporaryDirectory()
    try:
        f_yaml = pathlib.Path(folder.name) / 'config.yaml'
        f_yaml.write_text(yaml_text)
        return Config.from_file(f_yaml), None
    except GradescopeMeanError as e:
        return None, str(e)
    except Exception as e:
        return None, f'could not read config: {e}'
    finally:
        folder.cleanup()
