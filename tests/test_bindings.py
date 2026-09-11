"""Tests for module naming and import binding tables.

A caller that reaches a function through a package re-export is invisible to
a per-file alias table: the caller's own file imports the name under its
re-exported spelling and aliases nothing. Making that caller visible needs
to know where each module's imports come from, which needs each file's
module name first, and both halves are worth testing on their own before
the index is wired to follow them.
"""

import ast

from willitbite import callsites


def _write(tmp_path, name, source=""):
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    return str(path)


def _bindings(source, module="pkg.mod", is_package=False):
    return callsites.import_bindings(ast.parse(source), module, is_package)


def _rebindings(source, module="pkg.mod"):
    return callsites.rebindings(ast.parse(source), module)


# --------------------------------------------------------------------------
# Module names.
# --------------------------------------------------------------------------


def test_a_module_name_walks_up_only_while_init_files_exist(tmp_path):
    _write(tmp_path, "src/pkg/__init__.py")
    assert callsites.module_name(_write(tmp_path, "src/pkg/lib.py")) == "pkg.lib"


def test_an_init_file_names_itself_as_the_package(tmp_path):
    assert callsites.module_name(_write(tmp_path, "pkg/__init__.py")) == "pkg"


def test_a_tree_of_loose_scripts_stays_flat(tmp_path):
    assert callsites.module_name(_write(tmp_path, "app.py")) == "app"


# --------------------------------------------------------------------------
# Binding tables.
# --------------------------------------------------------------------------


def test_a_from_import_records_where_each_name_came_from():
    assert _bindings("from lib import collect as c\n") == {"c": {("lib", "collect")}}


def test_a_binding_without_an_as_keeps_an_edge_for_later_hops():
    assert _bindings("from pkg import c\n") == {"c": {("pkg", "c")}}


def test_a_relative_level_resolves_against_the_owning_package():
    assert _bindings("from .lib import collect as c\n") == {
        "c": {("pkg.lib", "collect")}
    }


def test_a_package_resolves_relative_imports_against_itself():
    assert _bindings("from .lib import collect as c\n", module="pkg", is_package=True) == {
        "c": {("pkg.lib", "collect")}
    }


def test_two_dots_resolv_one_level_further_up():
    assert _bindings("from ..base import collect as c\n") == {
        "c": {("base", "collect")}
    }


def test_from_import_of_a_name_resolves_to_the_package():
    assert _bindings("from . import lib\n") == {"lib": {("pkg", "lib")}}


def test_a_level_past_the_top_keeps_the_bare_module():
    assert _bindings("from ..lib import collect as c\n", module="app") == {
        "c": {("lib", "collect")}
    }


def test_a_star_import_records_no_binding():
    assert _bindings("from lib import *\n") == {}


def test_two_imports_of_one_local_name_keep_both_branches():
    assert _bindings("from a import x\nfrom b import x\n") == {
        "x": {("a", "x"), ("b", "x")}
    }


# --------------------------------------------------------------------------
# Rebinding tables. An import is not the only way a second name reaches a
# function. An assignment makes one too, and a package that re-exports by
# assignment hides its callers exactly as an alias does.
# --------------------------------------------------------------------------


def test_an_assignment_binds_a_second_spelling_in_its_own_module():
    assert _rebindings("c = collect\n") == {"c": {("pkg.mod", "collect")}}


def test_the_edge_stays_in_the_binding_module_so_the_next_hop_resolves_it():
    # `pkg` re-exports by assignment, so `c` reaches `collect` in `pkg`, and
    # `pkg`'s own import table carries `collect` the rest of the way to `lib`.
    assert _rebindings("from lib import collect\nc = collect\n", module="pkg") == {
        "c": {("pkg", "collect")}
    }


def test_an_attribute_value_records_the_attribute_name():
    assert _rebindings("c = mod.collect\n") == {"c": {("pkg.mod", "collect")}}


def test_an_annotated_assignment_binds_too():
    assert _rebindings("c: Callable = collect\n") == {"c": {("pkg.mod", "collect")}}


def test_an_annotation_without_a_value_binds_nothing():
    assert _rebindings("c: Callable\n") == {}


def test_a_chained_assignment_binds_every_target():
    assert _rebindings("a = b = collect\n") == {
        "a": {("pkg.mod", "collect")},
        "b": {("pkg.mod", "collect")},
    }


def test_a_value_that_builds_a_new_object_binds_nothing():
    assert _rebindings("c = collect()\nd = [collect]\ne = 3\n") == {}


def test_a_name_bound_to_itself_records_no_edge():
    assert _rebindings("collect = collect\n") == {}


def test_two_assignments_of_one_name_keep_both_branches():
    assert _rebindings("c = collect\nc = gather\n") == {
        "c": {("pkg.mod", "collect"), ("pkg.mod", "gather")}
    }


def test_an_assignment_inside_a_function_is_collected_like_the_import_table():
    assert _rebindings("def f():\n    c = collect\n") == {"c": {("pkg.mod", "collect")}}


def test_unpacking_binds_nothing_because_the_value_is_not_one_name():
    assert _rebindings("a, b = collect, gather\n") == {}
