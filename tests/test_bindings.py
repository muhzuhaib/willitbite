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
