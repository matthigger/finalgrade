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
import io
import json
import pathlib
import tempfile
import warnings

import pandas as pd

from . import edit
from .check import build_report, render
from .config import F_CONFIG_DEFAULT, Config
from .errors import GradescopeMeanError
from .gradebook import Gradebook
from .inspect import build_table, build_view, histogram
from .seed import seed_text

__all__ = ['load_csv', 'check_config', 'grade', 'seed_config', 'default_yaml',
           'form_state', 'edit_config', 'bin_values', 'canvas_export',
           'banner_export', 'student_csv']


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
                      for ass in gradebook.ass_list],
            # the roster, so waivers are picked rather than typed: an email
            # the user never types is an email they cannot misspell
            student_list=_student_list(gradebook))


def _student_list(gradebook):
    """ one entry per student, for the waiver picker """
    meta = gradebook.df_meta
    return [dict(email=str(email),
                 first=str(meta.at[email, 'firstname'])
                 if 'firstname' in meta.columns else '',
                 last=str(meta.at[email, 'lastname'])
                 if 'lastname' in meta.columns else '')
            for email in gradebook.df_perc.index]


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
    """ final grades: the csv to download, and the numbers behind it

    One call does both, because the second is only ever wanted alongside the
    first and the expensive half (reading the csv, running the pipeline) is
    shared.  The raw series come from averaging the same prepared gradebook
    a second time with the drops and late penalties taken out, so the two
    differ by exactly the policy and nothing else.

    Args:
        csv_text (str): contents of a gradescope or canvas export
        yaml_text (str): contents of a config.yaml
        name (str): the csv's filename

    Returns:
        result (dict): ok, the output csv, a distribution, and every series
            the inspector can draw
    """
    config, error = _read_config(yaml_text)
    if config is None:
        return dict(ok=False, error=error, warn_list=[])

    with _Csv(csv_text, name) as f_csv:
        try:
            (gradebook, df_grade, df_raw), warn_list = _warn_list(
                lambda: _grade_twice(config, f_csv))
        except GradescopeMeanError as e:
            return dict(ok=False, error=str(e), warn_list=[])

    s_mean = df_grade['mean'].dropna()
    letter_count = df_grade['letter'].value_counts()

    out = dict(
        ok=True,
        error=None,
        # averaging twice would otherwise say everything twice
        warn_list=list(dict.fromkeys(warn_list)),
        csv=df_grade.to_csv(),
        n_student=len(df_grade),
        mean_list=[float(x) for x in s_mean],
        mean_avg=float(s_mean.mean()) if len(s_mean) else None,
        mean_median=float(s_mean.median()) if len(s_mean) else None,
        # ordered by grade, best first, rather than by how many earned it
        letter_list=[dict(letter=str(letter), n=int(letter_count[letter]))
                     for letter in _letter_order(config, letter_count)],
        thresh_list=_thresh_list(config.grade_thresh),
        student_list=_graded_student_list(gradebook, df_grade, config),
        row_list=build_table(gradebook, config))

    out.update(build_view(gradebook, config, df_grade, df_raw))
    return out


def canvas_export(csv_text, yaml_text, canvas_text, name='scope.csv',
                  scale100=True):
    """ the grades, merged into a canvas gradebook ready to re-import

    Canvas matches on its own SIS User ID, so this needs the gradebook canvas
    exported -- the ids are the only thing the two files share.

    Args:
        csv_text (str): the grade source
        yaml_text (str): contents of a config.yaml
        canvas_text (str): a canvas gradebook export to merge into
        name (str): the source csv's filename
        scale100 (bool): grades out of 100 rather than 1, which avoids
            canvas rounding them to two decimal places

    Returns:
        result (dict): ok, and the csv text to upload
    """
    from .canvas import canvas_merge

    result = grade(csv_text, yaml_text, name)
    if not result['ok']:
        return result

    df_grade = pd.read_csv(io.StringIO(result['csv']), dtype={'sid': str})

    with _Csv(canvas_text, 'canvas.csv') as f_canvas:
        try:
            (df_out, _), warn_list = _warn_list(
                lambda: (canvas_merge(f_canvas=f_canvas, df_grade=df_grade,
                                      rm_gradescope_meta=True,
                                      scale100=scale100), None))
        except GradescopeMeanError as e:
            return dict(ok=False, error=str(e), warn_list=[])
        except Exception as e:
            return dict(ok=False, error=f'could not merge into canvas: {e}',
                        warn_list=[])

    return dict(ok=True, error=None, warn_list=warn_list,
                csv=df_out.to_csv(index=False), n_row=len(df_out))


def student_csv(csv_text, yaml_text, email, name='scope.csv'):
    """ one student's whole row, the way --per_student writes it

    The same file an instructor attaches to an email asking why a grade is
    what it is, so it holds everything: the metadata, every category mean,
    the final grade and every assignment behind it.

    Args:
        csv_text (str): the grade source
        yaml_text (str): contents of a config.yaml
        email (str): the student, as the gradebook keys them
        name (str): the source csv's filename

    Returns:
        result (dict): ok, the csv text, and a filename to save it under
    """
    config, error = _read_config(yaml_text)
    if config is None:
        return dict(ok=False, error=error)

    with _Csv(csv_text, name) as f_csv:
        try:
            df_grade, _ = _warn_list(lambda: config(f_csv)[1])
        except GradescopeMeanError as e:
            return dict(ok=False, error=str(e))

    if email not in df_grade.index:
        return dict(ok=False,
                    error=f'{email} is not among the students being graded')

    row = df_grade.loc[email]

    return dict(ok=True, error=None,
                csv=pd.DataFrame(row).to_csv(),
                filename=_student_stem(row, email) + '.csv')


def _student_stem(row, email):
    """ a filename for one student, as the cli's per_student folder names """
    def safe(text):
        stem = ''.join(c if (c.isalnum() or c in '-_') else '_'
                       for c in str(text)).strip('_')
        return stem or 'unknown'

    last = safe(row.get('lastname', ''))
    first = safe(row.get('firstname', ''))
    if last == 'unknown' and first == 'unknown':
        return safe(str(email).split('@')[0])
    return f'{last}_{first}'


def banner_export(csv_text, yaml_text, term_code, crn_json='[]',
                  name='scope.csv'):
    """ the grades as a banner-ready xlsx, base64 encoded

    Banner matches on CRN, term code and a 9 digit student id together, so
    all three have to be right; see doc/upload_banner.md.

    Returned as base64 because a workbook is bytes, and bytes are the one
    thing that does not cross into javascript cleanly.

    Args:
        csv_text (str): the grade source
        yaml_text (str): contents of a config.yaml
        term_code (str): banner's 6 digit term, e.g. '202310'
        crn_json (str): json list of 5 digit CRNs
        name (str): the source csv's filename

    Returns:
        result (dict): ok, and the workbook as base64
    """
    import base64

    from .banner import to_banner, to_xlsx_bytes

    result = grade(csv_text, yaml_text, name)
    if not result['ok']:
        return result

    if not str(term_code).strip():
        return dict(ok=False, warn_list=[],
                    error='banner needs a term code (6 digits, e.g. 202310) '
                          'to match these grades to a course')

    df_grade = pd.read_csv(io.StringIO(result['csv']), dtype={'sid': str})

    try:
        df_out = to_banner(df_grade, term_code=str(term_code).strip(),
                           crn_list=json.loads(crn_json or '[]'))
        data = to_xlsx_bytes(df_out)
    except KeyError as e:
        return dict(ok=False, warn_list=[], error=str(e).strip('"'))
    except ImportError:
        return dict(ok=False, warn_list=[],
                    error='the excel writer did not load, so no xlsx can be '
                          'built here (the command line tool still can)')
    except Exception as e:
        return dict(ok=False, warn_list=[],
                    error=f'could not build the banner workbook: {e}')

    return dict(ok=True, error=None, warn_list=[],
                xlsx_b64=base64.b64encode(data).decode('ascii'),
                n_row=len(df_out))


def _grade_twice(config, f_csv):
    """ the prepared gradebook, averaged with the policy and without it """
    gradebook = Gradebook.from_file(f_csv)
    config.prepare(gradebook)

    def average(cat_drop_dict, cat_late_dict):
        return gradebook.average_full(
            cat_weight_dict=config.cat_weight_dict,
            cat_drop_dict=cat_drop_dict,
            cat_late_dict=cat_late_dict,
            grade_thresh=config.grade_thresh,
            late_waive_dict=config.late_waive_dict)

    df_grade = average(config.cat_drop_dict, config.cat_late_dict)
    df_raw = average(dict(), dict())
    return gradebook, df_grade, df_raw


def _graded_student_list(gradebook, df_grade, config):
    """ one row per student: who they are and what they got """
    import pandas as pd

    meta = gradebook.df_meta
    cat_list = list(config.cat_weight_dict)

    def val(row, col):
        if col not in df_grade.columns:
            return None
        x = row[col]
        return None if pd.isna(x) else float(x)

    out_list = []
    for email, row in df_grade.iterrows():
        out_list.append(dict(
            email=str(email),
            first=str(meta.at[email, 'firstname'])
            if 'firstname' in meta.columns else '',
            last=str(meta.at[email, 'lastname'])
            if 'lastname' in meta.columns else '',
            mean=val(row, 'mean'),
            letter=str(row['letter']) if 'letter' in df_grade.columns else '',
            cat_dict={cat: val(row, f'mean_{cat}') for cat in cat_list},
            ass_dict={ass: val(row, ass) for ass in gradebook.ass_list}))
    return out_list


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


def form_state(yaml_text):
    """ the config as the widgets need it: sections, in file order

    Read from the file rather than from a Config, so that a half-typed
    policy still draws something.  Whether it is *valid* is check_config's
    question, and the page asks that separately.

    Args:
        yaml_text (str): contents of a config.yaml

    Returns:
        state (dict): ok, and one entry per section the widgets edit
    """
    try:
        data = _plain(edit.load(yaml_text))
    except GradescopeMeanError as e:
        return dict(ok=False, error=str(e))

    cat_dict = data.get('category') or {}
    weight_dict = cat_dict.get('weight') or {}
    drop_dict = cat_dict.get('drop_low') or {}
    late_dict = cat_dict.get('late_penalty') or {}
    ass_dict = data.get('assignments') or {}

    total = sum(w for w in weight_dict.values()
                if isinstance(w, (int, float))) or 0

    return dict(
        ok=True,
        error=None,
        cat_list=[dict(name=str(cat),
                       weight=weight,
                       weight_frac=_share(weight, total),
                       drop_low=drop_dict.get(cat) or 0,
                       late=late_dict.get(cat))
                  for cat, weight in weight_dict.items()],
        waive_list=_waive_list(data.get('waive')),
        waive_late_list=_waive_list(data.get('waive_late')),
        exclude_list=_str_list(ass_dict.get('exclude')),
        complete_thresh=ass_dict.get('exclude_complete_thresh'),
        email_list=_str_list(data.get('email_list')),
        sub_list=_sub_list(ass_dict.get('substitute')),
        thresh_list=_thresh_list(data.get('grade_thresh')))


def bin_values(value_json, name_json, n_bin=20):
    """ a histogram with the students in each bar, for the page to draw

    Binned here rather than by the plotting library so that every bar can
    say who is in it -- which is the question that makes a distribution
    worth looking at when you are deciding a cutoff.

    Args:
        value_json (str): json list of numbers, null where a student has none
        name_json (str): json list of labels, same order
        n_bin (int): number of bins

    Returns:
        hist (dict): edge_list, count_list, who_list
    """
    return histogram(json.loads(value_json), json.loads(name_json),
                     n_bin=int(n_bin))


def _sub_list(section):
    """ a substitute section as one entry per target assignment """
    if not isinstance(section, dict):
        return []
    return [dict(target=str(target), ass_list=_str_list(val))
            for target, val in section.items()]


def _thresh_list(section):
    """ letter thresholds, highest first; the defaults when none are set """
    from .perc_to_letter import GRADE_THRESH

    is_default = not isinstance(section, dict) or not section
    if is_default:
        section = GRADE_THRESH

    pair_list = []
    for perc, letter in section.items():
        try:
            pair_list.append((float(perc), str(letter)))
        except (TypeError, ValueError):
            # a threshold that isn't a number: Config will refuse it, and
            # saying so is check's job, not this one's
            continue

    return [dict(perc=perc, letter=letter, is_default=is_default)
            for perc, letter in sorted(pair_list, reverse=True)]


def edit_config(yaml_text, action, args_json='{}'):
    """ applies one widget edit, keeping the rest of the file as written

    Arguments arrive as json rather than as keywords: it is one unambiguous
    thing to pass across the language boundary, and it cannot leave a proxy
    object alive on the other side.

    Args:
        yaml_text (str): contents of a config.yaml
        action (str): a key of edit.ACTION_DICT
        args_json (str): json object of keyword arguments

    Returns:
        result (dict): ok, and the edited yaml
    """
    try:
        arg_dict = json.loads(args_json or '{}')
        return dict(ok=True, error=None,
                    yaml=edit.apply(yaml_text, action, arg_dict))
    except GradescopeMeanError as e:
        return dict(ok=False, error=str(e), yaml=yaml_text)
    except Exception as e:
        return dict(ok=False, error=f'could not apply that edit: {e}',
                    yaml=yaml_text)


def _share(weight, total):
    """ one category's share of the whole, or None while it can't be told """
    if not total or not isinstance(weight, (int, float)):
        return None
    return weight / total


def _waive_list(section):
    """ a waiver section as one entry per student """
    if not isinstance(section, dict):
        return []
    return [dict(email=str(email), ass_list=_str_list(val))
            for email, val in section.items()]


def _str_list(val):
    """ a yaml list, or a comma separated string, as a list of strings """
    if val is None:
        return []
    if isinstance(val, str):
        return [s.strip() for s in val.split(',') if s.strip()]
    if isinstance(val, list):
        return [str(s).strip() for s in val if str(s).strip()]
    return [str(val)]


def _plain(obj):
    """ ruamel's types are dict / str subclasses; javascript wants neither """
    if isinstance(obj, dict):
        return {str(k): _plain(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_plain(v) for v in obj]
    if isinstance(obj, bool) or obj is None:
        return obj
    if isinstance(obj, int):
        return int(obj)
    if isinstance(obj, float):
        return float(obj)
    if isinstance(obj, str):
        return str(obj)
    return obj


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
