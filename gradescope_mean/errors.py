"""Exceptions raised by gradescope_mean.

All inherit ValueError so that existing callers catching ValueError keep
working, while the CLI can catch GradescopeMeanError specifically and print
a single actionable line rather than a traceback.
"""


class GradescopeMeanError(ValueError):
    """ base for every error this package raises deliberately """


class ConfigError(GradescopeMeanError):
    """ the config file asks for something impossible or self-contradictory """


class GradebookError(GradescopeMeanError):
    """ the gradescope export can't be interpreted """


class AssignmentNotFoundError(GradescopeMeanError):
    """ an assignment name matched no assignment, or more than one """


class CanvasError(GradescopeMeanError):
    """ the canvas export can't be merged against the computed grades """
