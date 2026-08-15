"""Exceptions raised by finalgrade.

All inherit ValueError so that existing callers catching ValueError keep
working, while the CLI can catch FinalgradeError specifically and print
a single actionable line rather than a traceback.
"""


class FinalgradeError(ValueError):
    """ base for every error this package raises deliberately """


class PolicyError(FinalgradeError):
    """ the policy file asks for something impossible or self-contradictory """


class GradebookError(FinalgradeError):
    """ the gradescope export can't be interpreted """


class AssignmentNotFoundError(FinalgradeError):
    """ an assignment name matched no assignment, or more than one """


class CanvasError(FinalgradeError):
    """ the canvas export can't be merged against the computed grades """
