"""Tests for the B023 escape analysis.

Every case here is a real shape taken from a real codebase, not an invented one.
The safe cases come from ragflow and prefect, where all 108 B023 warnings
between them turned out to be false alarms; the biting cases are the textbook
late-binding bug that the rule exists to catch.

The point of the safe cases is that a tool which answers BITES for everything
would pass a suite made only of bugs, and would be useless on the codebases
people actually run it on.
"""

import ast

import pytest

from willitbite.escape import analyse
from willitbite.verdict import BITES, CALLEE, SAFE


def verdict(src, line):
    return analyse(ast.parse(src), line)


# --------------------------------------------------------------------------
# Real bugs. These must come back BITES.
# --------------------------------------------------------------------------

CLASSIC_APPEND = """
handlers = []
for i in range(3):
    def handler():
        return i
    handlers.append(handler)
"""

LAMBDA_IN_LIST = """
callbacks = []
for i in range(3):
    callbacks.append(lambda: i)
"""

LAMBDA_BOUND = """
for i in range(3):
    f = lambda: i
    register(f)
"""

RETURNED = """
def outer():
    for i in range(3):
        def inner():
            return i
        return inner
"""


@pytest.mark.parametrize(
    "src,line",
    [
        (CLASSIC_APPEND, 5),
        (LAMBDA_IN_LIST, 4),
        (LAMBDA_BOUND, 3),
        (RETURNED, 5),
    ],
)
def test_escaping_closures_bite(src, line):
    assert verdict(src, line).kind == BITES


def test_bites_reason_names_the_closure():
    """The reason has to be checkable against the source, not a rule restatement."""
    v = verdict(CLASSIC_APPEND, 5)
    assert "handler" in v.reason
    assert "stored" in v.reason


# --------------------------------------------------------------------------
# False alarms. These must NOT come back BITES.
# --------------------------------------------------------------------------

CALLED_IN_ITERATION = """
for page in pages:
    def find_layout(kind):
        return [x for x in page if x == kind]
    for kind in ("header", "footer"):
        find_layout(kind)
"""

SORTED_KEY = """
for column in columns:
    rows = sorted(rows, key=lambda r: r[column])
"""


def test_def_called_in_same_iteration_is_safe():
    v = verdict(CALLED_IN_ITERATION, 4)
    assert v.kind == SAFE
    assert "same iteration" in v.reason


def test_lambda_consumed_by_sorted_is_safe():
    assert verdict(SORTED_KEY, 3).kind == SAFE


# --------------------------------------------------------------------------
# The honest third answer.
# --------------------------------------------------------------------------

PASSED_TO_HELPER = """
for doc_id in docs:
    def merge_attempt():
        return merge(doc_id)
    result = run_with_retry(merge_attempt, attempts=3)
"""

LAZY_MAP = """
for column in columns:
    out = map(lambda r: r[column], rows)
"""


def test_closure_passed_to_unknown_function_names_it():
    """We cannot see into run_with_retry, so we say so and name it.

    Guessing SAFE here would have cleared a real bug in a codebase where the
    helper stores the callable; guessing BITES would have raised a false alarm
    on ragflow, where it calls it immediately. Neither guess is worth making.
    """
    v = verdict(PASSED_TO_HELPER, 4)
    assert v.kind == CALLEE
    assert "run_with_retry" in v.reason


def test_lazy_map_is_flagged_as_dependent_not_safe():
    v = verdict(LAZY_MAP, 3)
    assert v.kind == CALLEE
    assert "lazy" in v.reason


def test_unused_closure_bites():
    """Defined in a loop and never called there: something else holds it."""
    src = "for i in range(3):\n    def orphan():\n        return i\n"
    assert verdict(src, 3).kind == BITES


def test_verdict_actionable_only_for_bites():
    assert verdict(CLASSIC_APPEND, 5).actionable is True
    assert verdict(SORTED_KEY, 3).actionable is False
    assert verdict(PASSED_TO_HELPER, 4).actionable is False
