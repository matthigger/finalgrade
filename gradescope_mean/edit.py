""" editing a config file without losing what the user wrote around it

The browser's widgets and the yaml textarea are the same document: a widget
edits the file, and the file is what grading reads.  That only works if an
edit can be applied without rewriting everything else, which is why this
module loads in ruamel's round-trip mode rather than the safe mode the rest
of the package uses -- round-trip keeps comments, key order and formatting,
so the seeded assignment list and anyone's own notes survive being edited by
a form.

Each edit is small and total: given a document and a few values, produce the
document that says the new thing.  Nothing here validates policy; Config
does that when the result is read back.
"""
import io

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap

from .errors import ConfigError

# round trip: the default mode, spelled out because it is the whole point
yaml_rt = YAML()
yaml_rt.preserve_quotes = True
# the seeded config's comment table is wide; don't let dumping reflow it
yaml_rt.width = 4096

LATE_DEFAULT = {'penalty_per_day': .1, 'excuse_day': 0}


def load(text):
    """ a config document, comments and all

    Args:
        text (str): contents of a config.yaml

    Returns:
        data (CommentedMap)
    """
    try:
        data = yaml_rt.load(text or '')
    except Exception as e:
        raise ConfigError(f'could not read config: {e}') from e

    if data is None:
        return CommentedMap()
    if not isinstance(data, dict):
        raise ConfigError('config must be a mapping of settings')
    return data


def dump(data):
    """ a config document back to text """
    stream = io.StringIO()
    yaml_rt.dump(data, stream)
    return stream.getvalue()


def _section(data, *key_tup):
    """ the mapping at key_tup, creating it (over a null) when needed """
    node = data
    for key in key_tup:
        val = node.get(key)
        if not isinstance(val, dict):
            val = CommentedMap()
            node[key] = val
        node = val
    return node


def _clear_if_empty(data, *key_tup):
    """ an emptied section reads as null, the way the packaged config does """
    node = data
    for key in key_tup[:-1]:
        node = node.get(key)
        if not isinstance(node, dict):
            return
    if isinstance(node.get(key_tup[-1]), dict) and not node[key_tup[-1]]:
        node[key_tup[-1]] = None


def _num(x):
    """ 50.0 written back as 50: a weight nobody typed a decimal into """
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return x
    return int(x) if float(x).is_integer() else float(x)


# ------------------------------------------------------------- categories


def add_category(data, cat, rebalance=True):
    """ adds a weighted category, sharing the weight evenly with the rest """
    weight_dict = _section(data, 'category', 'weight')
    if cat in weight_dict:
        return

    weight_dict[cat] = 0
    if rebalance:
        share = _num(round(100 / len(weight_dict)))
        for key in weight_dict:
            weight_dict[key] = share
    else:
        weight_dict[cat] = 1


def remove_category(data, cat):
    """ removes a category, and anything that only made sense with it """
    for key_tup in (('category', 'weight'), ('category', 'drop_low'),
                    ('category', 'late_penalty')):
        node = data
        for key in key_tup[:-1]:
            node = node.get(key) if isinstance(node, dict) else None
        section = node.get(key_tup[-1]) if isinstance(node, dict) else None
        if isinstance(section, dict):
            section.pop(cat, None)
        _clear_if_empty(data, *key_tup)


def set_weight(data, cat, weight):
    """ sets one category's weight """
    _section(data, 'category', 'weight')[cat] = _num(weight)


def set_drop_low(data, cat, n):
    """ sets how many of a category's lowest scores to drop (0 removes) """
    if not n:
        section = _section(data, 'category', 'drop_low')
        section.pop(cat, None)
    else:
        _section(data, 'category', 'drop_low')[cat] = int(n)
    _clear_if_empty(data, 'category', 'drop_low')


def set_late(data, cat, late_dict=None):
    """ sets (or with late_dict None, removes) a category's late penalty """
    if late_dict is None:
        _section(data, 'category', 'late_penalty').pop(cat, None)
        _clear_if_empty(data, 'category', 'late_penalty')
        return

    section = _section(data, 'category', 'late_penalty', cat)
    for key, val in late_dict.items():
        if val is None:
            section.pop(key, None)
        else:
            section[key] = _num(val)


# ----------------------------------------------------------------- waivers


def set_waive(data, email, ass_list, field='waive'):
    """ sets what is waived for one student (an empty list removes them)

    Written as 'hw1, hw2' rather than a yaml list: it is the form the readme
    documents, and it stays on one line per student, which is what makes a
    term's worth of waivers readable.
    """
    if field not in ('waive', 'waive_late'):
        raise ConfigError(f'not a waiver section: {field}')

    section = _section(data, field)
    if ass_list:
        section[email] = ', '.join(ass_list)
    else:
        section.pop(email, None)
    _clear_if_empty(data, field)


# -------------------------------------------------------------- assignments


def set_exclude(data, ass_list):
    """ replaces the list of excluded assignments """
    if ass_list:
        _section(data, 'assignments')['exclude'] = list(ass_list)
    else:
        section = data.get('assignments')
        if isinstance(section, dict):
            section['exclude'] = None


def set_complete_thresh(data, thresh):
    """ sets the completion threshold (None or 0 removes it) """
    section = _section(data, 'assignments')
    section['exclude_complete_thresh'] = _num(thresh) if thresh else None


ACTION_DICT = {
    'add_category': add_category,
    'remove_category': remove_category,
    'set_weight': set_weight,
    'set_drop_low': set_drop_low,
    'set_late': set_late,
    'set_waive': set_waive,
    'set_exclude': set_exclude,
    'set_complete_thresh': set_complete_thresh,
}


def apply(text, action, arg_dict=None):
    """ applies one named edit to a config document

    Args:
        text (str): contents of a config.yaml
        action (str): a key of ACTION_DICT
        arg_dict (dict): keyword arguments for it

    Returns:
        text (str): the edited config
    """
    fn = ACTION_DICT.get(action)
    if fn is None:
        raise ConfigError(f'not an edit this understands: {action}')

    data = load(text)
    fn(data, **(arg_dict or {}))
    return dump(data)
