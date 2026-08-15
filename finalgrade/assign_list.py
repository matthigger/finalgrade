import warnings

from .errors import AssignmentNotFoundError

__all__ = ['AssignmentList', 'AssignmentNotFoundError', 'normalize']


def normalize(s):
    """ removes spaces, makes lowercase """
    return s.replace(' ', '').lower()


class AssignmentList(list):
    """ lookup assignment string with partial match without spaces or capitals

    Holds normalized assignment names.  Building one is cheap and side effect
    free; the gradescope-specific parsing (and the ambiguity warning that goes
    with it) lives in from_columns(), which runs once per csv.
    """
    MAX_PTS = normalize(' - max points')
    LATE = normalize(' - lateness (h:m:s)')
    SUB_TIME = normalize(' - submission time')

    # every column gradescope emits for a single assignment
    SUFFIX_TUP = ('', MAX_PTS, LATE, SUB_TIME)

    @classmethod
    def from_columns(cls, columns):
        """ builds from the raw columns of a gradescope csv

        An assignment is any column with a matching ' - Max Points' column.

        Args:
            columns (iterable): column names (normalized or not)

        Returns:
            ass_list (AssignmentList)
        """
        col_list = [normalize(col) for col in columns]
        ass_norm_list = [ass.replace(cls.MAX_PTS, '') for ass in col_list
                         if cls.MAX_PTS in ass]

        if len(ass_norm_list) != len(set(ass_norm_list)):
            raise AssignmentNotFoundError(
                'two assignment names differ by only capitalization or '
                'spacing')

        cls._warn_prefix(ass_norm_list)

        return cls(sorted(ass_norm_list))

    @staticmethod
    def _warn_prefix(ass_norm_list):
        """ warns when one name prefixes another (match() can't tell them
        apart) """
        link = 'https://github.com/matthigger/finalgrade/issues/28'
        sort_list = sorted(ass_norm_list, key=len)
        for idx, ass in enumerate(sort_list):
            for _ass in sort_list[idx + 1:]:
                if _ass.startswith(ass):
                    warnings.warn(f'{ass} prefixes {_ass}, youll have '
                                  f'trouble referencing {ass}\n{link}',
                                  UserWarning)

    def get_column_set(self):
        """ every gradescope column belonging to these assignments """
        return {ass + suffix
                for ass in self
                for suffix in self.SUFFIX_TUP}

    def match_iter(self, s_assign):
        """ iterates through all matching assignments

        Args:
            s_assign (str): input string to match to assignment

        Returns:
            s_assign_tup (tup): all matching assignments
        """
        ass_search_norm = normalize(s_assign)

        for ass in self:
            if ass_search_norm in ass:
                yield ass

    def match(self, s_assign):
        """ finds the unique match to an assignment"""
        # get all matches
        s_assign_tup = tuple(self.match_iter(s_assign))

        # ensure match is unique
        if len(s_assign_tup) != 1:
            s_error = f'no unique assignment: {s_assign} in {s_assign_tup}'
            raise AssignmentNotFoundError(s_error)

        return s_assign_tup[0]
