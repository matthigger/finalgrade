import pathlib
import shutil
from datetime import datetime

from ruamel.yaml import YAML

from .assign_list import normalize
from .gradebook import Gradebook

F_CONFIG_DEFAULT = (pathlib.Path(__file__).parent / 'config.yaml').resolve()
yaml = YAML(typ='safe')


class Config:
    def __init__(self, cat_weight_dict=None, cat_drop_dict=None,
                 remove_list=tuple(), sub_dict=None, waive_dict=None,
                 email_list=None, cat_late_dict=None,
                 exclude_complete_thresh=0, grade_thresh=None,
                 late_waive_dict=None):
        if cat_weight_dict is None:
            self.cat_weight_dict = dict()
        else:
            self.cat_weight_dict = cat_weight_dict

        if cat_drop_dict is None:
            self.cat_drop_dict = dict()
        else:
            self.cat_drop_dict = cat_drop_dict

        if remove_list is None:
            self.remove_list = list()
        else:
            self.remove_list = remove_list

        if sub_dict is None:
            self.sub_dict = dict()
        else:
            self.sub_dict = sub_dict

        if waive_dict is None:
            self.waive_dict = dict()
        else:
            self.waive_dict = waive_dict

        if email_list is None:
            self.email_list = list()
        else:
            self.email_list = email_list

        if cat_late_dict is None:
            self.cat_late_dict = dict()
        else:
            self.cat_late_dict = cat_late_dict

        if late_waive_dict is None:
            self.late_waive_dict = dict()
        else:
            self.late_waive_dict = late_waive_dict

        if exclude_complete_thresh is None:
            self.exclude_complete_thresh = 0
        else:
            self.exclude_complete_thresh = exclude_complete_thresh
        self.grade_thresh = grade_thresh

        self._normalize()

    @staticmethod
    def _parse_waive_value(a_list, email, field_name):
        """Parse a waive value (str or list) into a list of normalized names.

        Handles:
          - comma-separated string: "hw1, hw2"
          - YAML list: [hw1, hw2]
          - None / empty string: warns and returns empty list
        """
        from warnings import warn
        if a_list is None or (isinstance(a_list, str) and not a_list.strip()):
            warn(f'{field_name}: empty assignment list for {email} (ignored)')
            return []
        if isinstance(a_list, list):
            return [normalize(a) for a in a_list if a]
        return [normalize(a) for a in str(a_list).split(',') if a.strip()]

    def _normalize(self):
        """Normalizes category/assignment names and validates config values."""
        from warnings import warn

        # normalize assignment names in category dicts
        self.cat_weight_dict = {normalize(c): w
                                for c, w in self.cat_weight_dict.items()}

        self.cat_drop_dict = {normalize(c): d
                              for c, d in self.cat_drop_dict.items()}

        self.remove_list = [normalize(a) for a in self.remove_list]

        self.sub_dict = {normalize(s0): list(map(normalize, s1_list))
                         for s0, s1_list in self.sub_dict.items()}

        self.waive_dict = {
            email.lower(): self._parse_waive_value(a_list, email, 'waive')
            for email, a_list in self.waive_dict.items()
        }
        # drop entries that ended up empty
        self.waive_dict = {k: v for k, v in self.waive_dict.items() if v}

        self.cat_late_dict = {normalize(c): l
                              for c, l in self.cat_late_dict.items()}

        # lowercase email keys inside excuse_day_offset
        for cat, d in self.cat_late_dict.items():
            if isinstance(d, dict) and 'excuse_day_offset' in d:
                offset = d['excuse_day_offset']
                if isinstance(offset, dict):
                    d['excuse_day_offset'] = {
                        e.lower(): v for e, v in offset.items()}

        self.late_waive_dict = {
            email.lower(): self._parse_waive_value(
                a_list, email, 'waive_late')
            for email, a_list in self.late_waive_dict.items()
        }
        self.late_waive_dict = {k: v for k, v in self.late_waive_dict.items()
                                if v}

        # lowercase email list entries
        self.email_list = [e.lower() for e in self.email_list]

        self._validate()

    @staticmethod
    def _is_number(x):
        """ bool is an int subclass, but never a meaningful weight / count """
        return not isinstance(x, bool) and isinstance(x, (int, float))

    def _check_category_keys(self, d, field_name):
        """ raises unless every category in d also has a weight

        a category with no weight is never visited when averaging, so an
        entry here would otherwise be silently ignored.
        """
        if not d:
            return
        unknown_set = set(d.keys()) - set(self.cat_weight_dict.keys())
        if unknown_set:
            known = ', '.join(sorted(self.cat_weight_dict)) or '<none given>'
            raise ValueError(
                f'{field_name} category has no entry in category/weight: '
                f'{", ".join(sorted(unknown_set))}.  '
                f'weighted categories are: {known}')

    def _validate_grade_thresh(self):
        for thresh, letter in self.grade_thresh.items():
            if not self._is_number(thresh):
                raise ValueError(
                    f'grade_thresh keys must be numbers, got {thresh!r} '
                    f'for "{letter}"')
            if not 0 <= thresh <= 1:
                raise ValueError(
                    f'grade_thresh must be a fraction between 0 and 1, got '
                    f'{thresh!r} for "{letter}" (write .93 rather than 93)')

        if self.grade_thresh and min(self.grade_thresh) > 0:
            raise ValueError(
                'grade_thresh needs an entry at 0 so that every grade maps '
                f'to a letter, lowest given is {min(self.grade_thresh)}')

    def _validate(self):
        """ validates config values against each other (no gradebook needed)
        """
        # category weights: non-negative numbers, not all zero
        for cat, w in self.cat_weight_dict.items():
            if not self._is_number(w) or w < 0:
                raise ValueError(
                    f'category weight must be a non-negative number, '
                    f'got {w!r} for "{cat}"')
        if self.cat_weight_dict and sum(self.cat_weight_dict.values()) <= 0:
            raise ValueError(
                'at least one category weight must be positive, got all '
                f'zero: {self.cat_weight_dict}')

        # drop counts are non-negative integers
        for cat, d in self.cat_drop_dict.items():
            if not isinstance(d, int) or isinstance(d, bool) or d < 0:
                raise ValueError(
                    f'drop_low must be a non-negative integer, '
                    f'got {d!r} for "{cat}"')

        # categories referenced elsewhere must be weighted, or they'd be
        # silently ignored
        self._check_category_keys(self.cat_drop_dict, 'drop_low')
        self._check_category_keys(self.cat_late_dict, 'late_penalty')

        # validate exclude_complete_thresh
        if self.exclude_complete_thresh:
            t = self.exclude_complete_thresh
            if not self._is_number(t) or not (0 <= t <= 1):
                raise ValueError(
                    f'exclude_complete_thresh must be between 0 and 1, '
                    f'got {t!r}')

        if self.grade_thresh is not None:
            self._validate_grade_thresh()

    def __call__(self, f_scope):
        """ runs a typical processing pipeline given config and f_scop

        Args:
            f_scope (str): raw gradescope csv

        Returns:
            gradebook (Gradebook): processed gradebook
            df_grade_full (pd.DataFrame): full data frame
        """
        gradebook = Gradebook(f_scope=f_scope)

        if self.email_list:
            gradebook.prune_email(email_list=self.email_list)

        if self.sub_dict:
            gradebook.substitute(sub_dict=self.sub_dict)

        for ass in self.remove_list:
            gradebook.remove(ass, multi=True)

        gradebook.remove_thresh(
            min_complete_thresh=self.exclude_complete_thresh)

        if self.waive_dict:
            gradebook.waive(waive_dict=self.waive_dict)

        df_grade_full = gradebook.average_full(
            cat_weight_dict=self.cat_weight_dict,
            cat_drop_dict=self.cat_drop_dict,
            cat_late_dict=self.cat_late_dict,
            grade_thresh=self.grade_thresh,
            late_waive_dict=self.late_waive_dict)

        return gradebook, df_grade_full

    @classmethod
    def from_file(cls, f_config):
        """ loads config from yaml file

        Args:
            f_config (str): yaml file

        Returns:
            config (Config): configuration
        """
        # load yaml
        f_config = pathlib.Path(f_config)
        try:
            d = yaml.load(f_config)
        except Exception as e:
            raise ValueError(
                f'failed to parse config file {f_config}: {e}') from e

        if not isinstance(d, dict):
            raise ValueError(
                f'config file must be a YAML mapping, got {type(d).__name__} '
                f'in {f_config}')

        def _get(d, *keys, default=None):
            """Safely navigate nested dicts, returning default for missing/null."""
            val = d
            for k in keys:
                if not isinstance(val, dict) or k not in val:
                    return default
                val = val[k]
            return val if val is not None else default

        cat_weight_dict = _get(d, 'category', 'weight')
        cat_drop_n = _get(d, 'category', 'drop_low')
        cat_late_dict = _get(d, 'category', 'late_penalty')
        exclude_list = _get(d, 'assignments', 'exclude')
        sub_dict = _get(d, 'assignments', 'substitute')
        waive_dict = _get(d, 'waive')
        email_list = _get(d, 'email_list')
        exclude_complete_thresh = _get(d, 'assignments',
                                       'exclude_complete_thresh')
        grade_thresh = _get(d, 'grade_thresh')
        late_waive_dict = _get(d, 'waive_late')

        return cls(cat_weight_dict, cat_drop_n, exclude_list, sub_dict,
                   waive_dict, email_list, cat_late_dict,
                   exclude_complete_thresh, grade_thresh=grade_thresh,
                   late_waive_dict=late_waive_dict)

    @classmethod
    def resolve_config(cls, folder, force_new=False):
        """Resolve config: use existing config.yaml or copy default.

        Non-interactive replacement for the old cli_copy_config. When no
        --config is specified:
          - If config.yaml exists in *folder* and force_new is False, use it.
          - Otherwise copy the default config.yaml into *folder* and use that.
          - If force_new and config.yaml already exists, it is timestamped to
            avoid overwriting.

        Args:
            folder (pathlib.Path): directory to look for / place config
            force_new (bool): if True, always create a fresh config
        """
        import logging
        logger = logging.getLogger('gradescope_mean')

        f_config = pathlib.Path(folder) / F_CONFIG_DEFAULT.name

        if f_config.exists() and not force_new:
            logger.info(f'using existing config: {f_config.resolve()}')
            return cls.from_file(f_config)

        # need to create a new config
        if f_config.exists():
            # don't overwrite — timestamp the new one
            s_now = datetime.now().strftime('_%Y_%b_%d@%H:%M:%S')
            f_config = pathlib.Path(
                str(f_config).replace('.yaml', f'{s_now}.yaml'))

        shutil.copy(F_CONFIG_DEFAULT, f_config)
        logger.info(
            f'created default config — edit as needed, see '
            f'https://github.com/matthigger/gradescope_mean#configuration'
            f' for details:\n  {f_config}')

        return cls.from_file(f_config)

    @classmethod
    def cli_copy_config(cls, folder):
        """Deprecated: use resolve_config instead."""
        import warnings
        warnings.warn('cli_copy_config is deprecated, use resolve_config',
                      DeprecationWarning, stacklevel=2)
        return cls.resolve_config(folder)
