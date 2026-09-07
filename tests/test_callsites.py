"""Tests for the call-site pass.

A mutable default that a function mutates is a real defect in that function.
Whether it can fire is a different question, and it is answered somewhere else
entirely: in the callers. This pass exists because the answer to "is this
function wrong" and the answer to "can this reach me today" are not the same
answer, so the tests below are mostly about the gap between them.

The conservative direction matters more than the permissive one. Reporting a
defect that nobody can trigger costs a reader two minutes. Clearing one that
somebody can trigger is the failure this tool exists to avoid, so every case
where the callers cannot be resolved is expected to stay at BITES.
"""

import ast

from willitbite import callsites, cli
from willitbite.mutation import analyse
from willitbite.verdict import BITES, LATENT, SAFE

MUTATES = '''
def collect(seen, items=[]):
    items.append(seen)
    return items
'''


def project(tmp_path, files):
    """Write a small tree and return its call index."""
    for name, source in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")
    return callsites.index(tmp_path)


def decide(tmp_path, files, defining="lib.py", line=2):
    calls = project(tmp_path, files)
    return analyse(ast.parse(files[defining]), line, calls=calls)


# --------------------------------------------------------------------------
# The distinction the pass exists to draw.
# --------------------------------------------------------------------------


def test_a_caller_that_omits_the_argument_keeps_it_biting(tmp_path):
    v = decide(
        tmp_path,
        {
            "lib.py": MUTATES,
            "app.py": "from lib import collect\ncollect(1)\n",
        },
    )
    assert v.kind == BITES


def test_every_caller_supplying_it_makes_it_latent(tmp_path):
    v = decide(
        tmp_path,
        {
            "lib.py": MUTATES,
            "app.py": "from lib import collect\ncollect(1, [])\ncollect(2, items=[])\n",
        },
    )
    assert v.kind == LATENT
    assert "2" in v.reason


def test_the_latent_reason_still_describes_the_defect(tmp_path):
    v = decide(
        tmp_path,
        {"lib.py": MUTATES, "app.py": "collect(1, [])\n"},
    )
    assert "items.append()" in v.reason
    assert "collect" in v.reason


def test_a_caller_in_another_directory_is_found(tmp_path):
    v = decide(
        tmp_path,
        {"lib.py": MUTATES, "pkg/deep/user.py": "collect(1)\n"},
    )
    assert v.kind == BITES


# --------------------------------------------------------------------------
# Every unresolvable case stays at BITES. These are the ones that matter.
# --------------------------------------------------------------------------


def test_no_call_site_anywhere_is_not_evidence_of_safety(tmp_path):
    """Zero callers means dead code, a dynamic call, or a public entry point.

    None of those is proof that nobody omits the argument, and a public entry
    point with no in-tree caller is the most likely shape of the three.
    """
    v = decide(tmp_path, {"lib.py": MUTATES})
    assert v.kind == BITES
    assert "no call site" in v.reason


def test_a_keyword_splat_is_not_proof_the_argument_was_passed(tmp_path):
    v = decide(
        tmp_path,
        {"lib.py": MUTATES, "app.py": "collect(1, **options)\n"},
    )
    assert v.kind == BITES


def test_a_positional_splat_is_not_proof_either(tmp_path):
    v = decide(
        tmp_path,
        {"lib.py": MUTATES, "app.py": "collect(*args)\n"},
    )
    assert v.kind == BITES


def test_one_omitting_caller_among_many_is_enough(tmp_path):
    v = decide(
        tmp_path,
        {
            "lib.py": MUTATES,
            "app.py": "collect(1, [])\ncollect(2, [])\ncollect(3)\n",
        },
    )
    assert v.kind == BITES


# --------------------------------------------------------------------------
# Signature shapes.
# --------------------------------------------------------------------------

KEYWORD_ONLY = '''
def collect(seen, *, items=[]):
    items.append(seen)
'''


def test_keyword_only_parameter_supplied_by_name_is_latent(tmp_path):
    v = decide(
        tmp_path,
        {"lib.py": KEYWORD_ONLY, "app.py": "collect(1, items=[])\n"},
    )
    assert v.kind == LATENT


def test_keyword_only_parameter_cannot_be_supplied_positionally(tmp_path):
    v = decide(
        tmp_path,
        {"lib.py": KEYWORD_ONLY, "app.py": "collect(1, [])\n"},
    )
    assert v.kind == BITES


METHOD = '''
class Sender:
    def send(self, extra={}):
        extra["sent"] = True
'''


def test_a_bound_method_call_does_not_count_self(tmp_path):
    """``s.send({})`` supplies ``extra`` even though it looks like one argument."""
    v = decide(
        tmp_path,
        {"lib.py": METHOD, "app.py": "Sender().send({})\n"},
        line=3,
    )
    assert v.kind == LATENT


def test_a_bound_method_call_that_omits_it_still_bites(tmp_path):
    v = decide(
        tmp_path,
        {"lib.py": METHOD, "app.py": "Sender().send()\n"},
        line=3,
    )
    assert v.kind == BITES


# --------------------------------------------------------------------------
# The index itself.
# --------------------------------------------------------------------------


def test_index_skips_directories_nobody_wants_scanned(tmp_path):
    calls = project(
        tmp_path,
        {
            "app.py": "collect(1)\n",
            ".venv/lib/vendored.py": "collect(2)\n",
            "node_modules/x/y.py": "collect(3)\n",
            "__pycache__/stale.py": "collect(4)\n",
        },
    )
    assert len(calls["collect"]) == 1


def test_index_survives_a_file_it_cannot_parse(tmp_path):
    calls = project(
        tmp_path,
        {"good.py": "collect(1)\n", "broken.py": "def (:\n"},
    )
    assert len(calls["collect"]) == 1


def test_index_records_attribute_calls_under_the_attribute_name(tmp_path):
    calls = project(tmp_path, {"app.py": "obj.send(1)\nsend(2)\n"})
    assert len(calls["send"]) == 2


# --------------------------------------------------------------------------
# The pass must not disturb anything else.
# --------------------------------------------------------------------------

READ_ONLY = '''
def summarise(items=[]):
    return len(items)
'''


def test_a_safe_default_is_unaffected_by_call_sites(tmp_path):
    v = decide(tmp_path, {"lib.py": READ_ONLY, "app.py": "summarise()\n"})
    assert v.kind == SAFE


def test_analysis_without_an_index_behaves_as_before():
    """The pass is additive: no index, no change of answer."""
    assert analyse(ast.parse(MUTATES), 2).kind == BITES


# --------------------------------------------------------------------------
# End to end, through the command line.
# --------------------------------------------------------------------------


def findings_for(path):
    return [{"code": "B006", "filename": str(path), "line": 2, "message": ""}]


def latent_project(tmp_path):
    (tmp_path / "lib.py").write_text(MUTATES, encoding="utf-8")
    (tmp_path / "app.py").write_text("collect(1, [])\n", encoding="utf-8")
    return cli.decide(findings_for(tmp_path / "lib.py"), root=tmp_path)


def test_cli_separates_latent_from_biting(tmp_path):
    decided = latent_project(tmp_path)
    assert decided[0]["verdict"].kind == LATENT
    assert "latent" in "\n".join(cli.render(decided)).lower()


def test_latent_alone_does_not_fail_the_build(tmp_path):
    """The exit code answers "can this bite today", and a latent defect cannot."""
    assert not any(r["verdict"].actionable for r in latent_project(tmp_path))
