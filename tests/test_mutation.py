"""Tests for the B006 mutable-default analysis.

The safe cases matter more than the biting ones here. Across ragflow and prefect
there were 73 B006 warnings and not one of them was a reachable defect, so a
tool that answers BITES on the shape alone is wrong 73 times out of 73 and would
still pass a suite made only of textbook bugs.
"""

import ast

import pytest

from willitbite.mutation import analyse, analyse_param, mutable_defaults
from willitbite.verdict import BITES, CALLEE, SAFE


def verdict(src, line):
    return analyse(ast.parse(src), line)


# --------------------------------------------------------------------------
# Real bugs.
# --------------------------------------------------------------------------

APPEND_TO_DEFAULT = """
def collect(items=[]):
    items.append(1)
    return items
"""

DICT_ITEM_SET = """
def remember(key, cache={}):
    cache[key] = True
    return cache
"""

AUGMENTED = """
def grow(acc=[]):
    acc += [1]
    return acc
"""

DEL_FROM_DEFAULT = """
def forget(key, cache={}):
    del cache[key]
"""

FACTORY_DEFAULT = """
def collect(items=list()):
    items.append(1)
"""


@pytest.mark.parametrize(
    "src,line",
    [
        (APPEND_TO_DEFAULT, 2),
        (DICT_ITEM_SET, 2),
        (AUGMENTED, 2),
        (DEL_FROM_DEFAULT, 2),
        (FACTORY_DEFAULT, 2),
    ],
)
def test_mutated_defaults_bite(src, line):
    assert verdict(src, line).kind == BITES


def test_bites_reason_points_at_the_line():
    v = verdict(APPEND_TO_DEFAULT, 2)
    assert "items.append()" in v.reason
    assert "line 3" in v.reason


# --------------------------------------------------------------------------
# False alarms.
# --------------------------------------------------------------------------

REBOUND_OR = """
def collect(items=[]):
    items = items or []
    items.append(1)
    return items
"""

REBOUND_COPY = """
def collect(items=[]):
    items = list(items)
    items.append(1)
    return items
"""

READ_ONLY = """
def summarise(items=[]):
    return len(items), sorted(items)
"""


def test_rebind_before_mutation_is_safe():
    v = verdict(REBOUND_OR, 2)
    assert v.kind == SAFE
    assert "rebound" in v.reason


def test_rebind_by_copy_is_safe():
    assert verdict(REBOUND_COPY, 2).kind == SAFE


def test_read_only_default_is_safe():
    v = verdict(READ_ONLY, 2)
    assert v.kind == SAFE
    assert "never mutated" in v.reason


def test_copying_call_does_not_count_as_escape():
    """sorted(items) cannot mutate items, so it must not trigger the CALLEE answer."""
    assert verdict(READ_ONLY, 2).kind == SAFE


# --------------------------------------------------------------------------
# The honest third answer.
# --------------------------------------------------------------------------

PASSED_ON = """
def register(items=[]):
    install(items)
"""


def test_default_passed_elsewhere_names_the_callee():
    """Not mutated here, but handed to something that might mutate it.

    This is the blind spot in asking only "is it mutated in this body": a
    default can be corrupted a frame down without its own name ever appearing
    on the left of an append.
    """
    v = verdict(PASSED_ON, 2)
    assert v.kind == CALLEE
    assert "install" in v.reason


# --------------------------------------------------------------------------
# Signature reading.
# --------------------------------------------------------------------------


def test_mutable_defaults_finds_literals_and_factories():
    src = "def f(a, b=[], c=3, d={}, *, e=set(), g=None):\n    pass\n"
    fn = ast.parse(src).body[0]
    assert sorted(mutable_defaults(fn)) == ["b", "d", "e"]


def test_mutable_defaults_ignores_immutable():
    src = "def f(a=1, b='x', c=(), d=None, e=frozenset()):\n    pass\n"
    fn = ast.parse(src).body[0]
    assert mutable_defaults(fn) == []


def test_analyse_param_is_usable_directly():
    fn = ast.parse(APPEND_TO_DEFAULT).body[0]
    assert analyse_param(fn, "items").kind == BITES
