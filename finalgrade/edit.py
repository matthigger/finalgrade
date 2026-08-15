""" editing a policy file without losing what the user wrote around it

The browser's widgets and the yaml textarea are the same document: a widget
edits the file, and the file is what grading reads.  That only works if an
edit can be applied without rewriting everything else, which is why this
module loads in ruamel's round-trip mode rather than the safe mode the rest
of the package uses -- round-trip keeps comments, key order and formatting,
so the seeded assignment list and anyone's own notes survive being edited by
a form.

Each edit is small and total: given a document and a few values, produce the
document that says the new thing.  Nothing here validates policy; Policy
does that when the result is read back.
"""
import io

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq

from .errors import PolicyError

# round trip: the default mode, spelled out because it is the whole point
yaml_rt = YAML()
yaml_rt.preserve_quotes = True
# the seeded policy's comment table is wide; don't let dumping reflow it
yaml_rt.width = 4096

LATE_DEFAULT = {'penalty_per_day': .1, 'excuse_day': 0}


def load(text):
    """ a policy document, comments and all

    Args:
        text (str): contents of a policy.yaml

    Returns:
        data (CommentedMap)
    """
    try:
        data = yaml_rt.load(text or '')
    except Exception as e:
        raise PolicyError(f'could not read policy: {e}') from e

    if data is None:
        return CommentedMap()
    if not isinstance(data, dict):
        raise PolicyError('policy must be a mapping of settings')
    return data


def dump(data):
    """ a policy document back to text """
    stream = io.StringIO()
    yaml_rt.dump(data, stream)
    return stream.getvalue()


def _put(section, key, value):
    """ sets section[key], keeping any blank line that followed the block

    ruamel attaches the blank line separating a block from the next section
    to that block's *last key*.  Appending a key after it would put the new
    setting below the blank line and take the separator with it, so the file
    slowly loses its shape every time a widget touches it.  Move the blank
    along to whatever is last now.
    """
    token = _take_blank(section, key if key in section else
                        (next(reversed(section), None) if len(section)
                         else None))

    if token is not None and isinstance(value, list) and len(value):
        value = CommentedSeq(value)

    section[key] = value

    if token is None:
        return

    if isinstance(value, CommentedSeq) and len(value):
        # a block sequence writes its key on one line and its items on the
        # next, so a blank hung on the key lands between the two and the
        # list reads as though it belonged to whatever follows.  hang it on
        # the last item instead, which is where the block actually ends
        value.ca.items[len(value) - 1] = [token, None, None, None]
    else:
        section.ca.items.setdefault(key, [None, None, None, None])[2] = token


def _take_blank(section, key):
    """ removes and returns the blank line trailing key, if there is one

    It may be hung on the key, or -- when the value is a block sequence --
    on that sequence's last item, which is where this module puts it.
    """
    if key is None:
        return None

    value = section.get(key)
    if isinstance(value, CommentedSeq) and len(value):
        # index 0 is the comment following a sequence item
        entry = value.ca.items.get(len(value) - 1)
        token = _blank_of(entry, 0)
        if token is not None:
            entry[0] = None
            return token

    # index 2 is the comment following a mapping's value
    entry = section.ca.items.get(key)
    token = _blank_of(entry, 2)
    if token is not None:
        entry[2] = None
    return token


def _blank_of(entry, idx):
    """ the token at idx, when it is a blank line and nothing else """
    if not entry or entry[idx] is None or entry[idx].value.strip():
        return None
    return entry[idx]


def _section(data, *key_tup):
    """ the mapping at key_tup, creating it (over a null) when needed """
    node = data
    for key in key_tup:
        val = node.get(key)
        if not isinstance(val, dict):
            val = CommentedMap()
            _put(node, key, val)
        node = val
    return node


def _clear_if_empty(data, *key_tup):
    """ an emptied section reads as null, the way the packaged policy does """
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

    _put(weight_dict, cat, 0)
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
    _put(_section(data, 'category', 'weight'), cat, _num(weight))


def set_drop_low(data, cat, n):
    """ sets how many of a category's lowest scores to drop (0 removes) """
    if not n:
        section = _section(data, 'category', 'drop_low')
        section.pop(cat, None)
    else:
        _put(_section(data, 'category', 'drop_low'), cat, int(n))
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
            _put(section, key, _num(val))


def set_excuse_offset(data, cat, email, days):
    """ adjusts one student's excused late days (0 removes the entry)

    Per student rather than per category, which is why it is edited from the
    student panel: it exists for accommodations, one person at a time.
    """
    late_dict = data.get('category', {}).get('late_penalty') \
        if isinstance(data.get('category'), dict) else None
    if not isinstance(late_dict, dict) or cat not in late_dict:
        raise PolicyError(
            f'no late penalty on category "{cat}" to excuse days against')

    if days:
        _put(_section(data, 'category', 'late_penalty', cat,
                      'excuse_day_offset'), email, _num(days))
        return

    section = late_dict.get(cat)
    if isinstance(section, dict) \
            and isinstance(section.get('excuse_day_offset'), dict):
        section['excuse_day_offset'].pop(email, None)
        if not section['excuse_day_offset']:
            section.pop('excuse_day_offset', None)


# ----------------------------------------------------------------- waivers


def set_waive(data, email, ass_list, field='waive'):
    """ sets what is waived for one student (an empty list removes them)

    Written as 'hw1, hw2' rather than a yaml list: it is the form the readme
    documents, and it stays on one line per student, which is what makes a
    term's worth of waivers readable.
    """
    if field not in ('waive', 'waive_late'):
        raise PolicyError(f'not a waiver section: {field}')

    section = _section(data, field)
    if ass_list:
        _put(section, email, ', '.join(ass_list))
    else:
        section.pop(email, None)
    _clear_if_empty(data, field)


# -------------------------------------------------------------- assignments


def set_exclude(data, ass_list):
    """ replaces the list of excluded assignments """
    if ass_list:
        _put(_section(data, 'assignments'), 'exclude', list(ass_list))
    else:
        section = data.get('assignments')
        if isinstance(section, dict):
            section['exclude'] = None


def set_extra(data, ass_list):
    """ replaces the list of extra credit assignments """
    if ass_list:
        _put(_section(data, 'assignments'), 'extra_credit', list(ass_list))
    else:
        section = data.get('assignments')
        if isinstance(section, dict):
            section['extra_credit'] = None


def set_note(data, email, note):
    """ sets one student's note (an empty note removes it) """
    section = _section(data, 'note')
    if note and str(note).strip():
        _put(section, email, str(note).strip())
    else:
        section.pop(email, None)
    _clear_if_empty(data, 'note')


def set_max(data, email, target, ass_list):
    """ lets one student's target take the best of ass_list

    Written per student because that is how it arises: a makeup one person
    sat, a quiz two people retook.  An empty list removes the entry.
    """
    section = _section(data, 'max')

    if ass_list:
        _put(_section(data, 'max', email), target,
             ', '.join(ass_list))
    else:
        stud = section.get(email)
        if isinstance(stud, dict):
            stud.pop(target, None)
            if not stud:
                section.pop(email, None)

    _clear_if_empty(data, 'max')


def set_planned(data, ass, points):
    """ adds (or with points 0, removes) work that hasn't been set yet

    So that a whole term's policy can be written in one sitting: the
    assignment exists to be weighted and categorised, and weighs on nobody
    until real scores replace it.
    """
    section = _section(data, 'assignments', 'planned')
    if points:
        _put(section, ass, _num(points))
    else:
        section.pop(ass, None)
    _clear_if_empty(data, 'assignments', 'planned')


def set_complete_thresh(data, thresh):
    """ sets the completion threshold (None or 0 removes it) """
    section = _section(data, 'assignments')
    _put(section, 'exclude_complete_thresh',
         _num(thresh) if thresh else None)


def set_substitute(data, target, ass_list):
    """ sets which assignments may stand in for target (empty removes it)

    The alternates almost always want excluding too, or they count twice --
    but that is the caller's call to make and to show, not a silent edit.
    """
    section = _section(data, 'assignments', 'substitute')
    if ass_list:
        _put(section, target, list(ass_list))
    else:
        section.pop(target, None)
    _clear_if_empty(data, 'assignments', 'substitute')


# ------------------------------------------------------- letters and roster


def set_grade_thresh(data, thresh_list):
    """ replaces the letter thresholds

    Args:
        thresh_list (list): dicts of perc (0-1) and letter, any order.  an
            empty list restores the package default by removing the section
    """
    if not thresh_list:
        data['grade_thresh'] = None
        return

    # highest first, which is the order a reader expects and the order the
    # packaged policy ships in
    pair_list = sorted(((row['perc'], str(row['letter']))
                        for row in thresh_list), reverse=True)

    section = CommentedMap()
    for perc, letter in pair_list:
        section[_num(perc)] = letter
    data['grade_thresh'] = section


def set_email_list(data, email_list):
    """ replaces the roster filter (empty removes it) """
    data['email_list'] = list(email_list) if email_list else None


ACTION_DICT = {
    'add_category': add_category,
    'remove_category': remove_category,
    'set_weight': set_weight,
    'set_drop_low': set_drop_low,
    'set_late': set_late,
    'set_excuse_offset': set_excuse_offset,
    'set_waive': set_waive,
    'set_exclude': set_exclude,
    'set_extra': set_extra,
    'set_note': set_note,
    'set_complete_thresh': set_complete_thresh,
    'set_substitute': set_substitute,
    'set_planned': set_planned,
    'set_max': set_max,
    'set_grade_thresh': set_grade_thresh,
    'set_email_list': set_email_list,
}


def apply(text, action, arg_dict=None):
    """ applies one named edit to a policy document

    Args:
        text (str): contents of a policy.yaml
        action (str): a key of ACTION_DICT
        arg_dict (dict): keyword arguments for it

    Returns:
        text (str): the edited policy
    """
    fn = ACTION_DICT.get(action)
    if fn is None:
        raise PolicyError(f'not an edit this understands: {action}')

    data = load(text)
    fn(data, **(arg_dict or {}))
    return dump(data)
