"""End to end tests for the command line.

These run against a real file on disk through the real code path, using ruff's
own JSON shape as the input so no ruff installation is needed to test the
decision logic.
"""

import io
import json

import pytest

from willitbite import cli, ruffrun

BITING_SOURCE = '''
handlers = []
for i in range(3):
    def handler():
        return i
    handlers.append(handler)


def collect(items=[]):
    items.append(1)
    return items
'''

SAFE_SOURCE = '''
for page in pages:
    def find(kind):
        return page[kind]
    find("header")


def summarise(items=[]):
    return len(items)
'''


def write(tmp_path, name, source):
    path = tmp_path / name
    path.write_text(source, encoding="utf-8")
    return path


def ruff_json(path, entries):
    """Build ruff's output shape without needing ruff."""
    return json.dumps(
        [
            {
                "code": code,
                "filename": str(path),
                "location": {"row": row, "column": 1},
                "message": "",
            }
            for code, row in entries
        ]
    )


def test_decides_biting_and_safe(tmp_path, capsys):
    src = write(tmp_path, "biting.py", BITING_SOURCE)
    payload = write(tmp_path, "ruff.json", ruff_json(src, [("B023", 5), ("B006", 9)]))

    code = cli.main([str(tmp_path), "--json", str(payload)])
    out = capsys.readouterr().out

    assert code == 1, "a reachable defect must set a non-zero exit code"
    assert "2 of 2 warning(s) can actually bite" in out
    assert "handler" in out
    assert "items" in out


def test_clean_tree_exits_zero(tmp_path, capsys):
    src = write(tmp_path, "safe.py", SAFE_SOURCE)
    payload = write(tmp_path, "ruff.json", ruff_json(src, [("B023", 4), ("B006", 8)]))

    code = cli.main([str(tmp_path), "--json", str(payload)])
    out = capsys.readouterr().out

    assert code == 0
    assert "Nothing here can bite" in out


def test_exit_zero_flag_overrides(tmp_path, capsys):
    src = write(tmp_path, "biting.py", BITING_SOURCE)
    payload = write(tmp_path, "ruff.json", ruff_json(src, [("B023", 5)]))
    assert cli.main([str(tmp_path), "--json", str(payload), "--exit-zero"]) == 0


def test_json_output_is_machine_readable(tmp_path, capsys):
    src = write(tmp_path, "biting.py", BITING_SOURCE)
    payload = write(tmp_path, "ruff.json", ruff_json(src, [("B023", 5), ("B006", 9)]))

    cli.main([str(tmp_path), "--json", str(payload), "--json-out"])
    data = json.loads(capsys.readouterr().out)

    assert data["warnings"] == 2
    assert data["bites"] == 2
    assert {r["verdict"] for r in data["results"]} == {"BITES"}
    assert all(r["reason"] for r in data["results"]), "every verdict carries a reason"


def test_safe_warnings_hidden_unless_asked(tmp_path, capsys):
    src = write(tmp_path, "safe.py", SAFE_SOURCE)
    payload = write(tmp_path, "ruff.json", ruff_json(src, [("B023", 4)]))

    cli.main([str(tmp_path), "--json", str(payload)])
    assert "[SAFE]" not in capsys.readouterr().out

    cli.main([str(tmp_path), "--json", str(payload), "--all"])
    assert "[SAFE]" in capsys.readouterr().out


def test_unreadable_file_does_not_crash(tmp_path, capsys):
    payload = write(
        tmp_path, "ruff.json", ruff_json(tmp_path / "gone.py", [("B023", 1)])
    )
    assert cli.main([str(tmp_path), "--json", str(payload)]) == 0
    assert "unreadable" in capsys.readouterr().out


def test_syntax_error_is_reported_not_raised(tmp_path, capsys):
    src = write(tmp_path, "broken.py", "def f(:\n")
    payload = write(tmp_path, "ruff.json", ruff_json(src, [("B006", 1)]))
    assert cli.main([str(tmp_path), "--json", str(payload)]) == 0
    assert "unreadable" in capsys.readouterr().out


def test_parse_ignores_unsupported_rules():
    text = json.dumps(
        [
            {"code": "E501", "filename": "a.py", "location": {"row": 1}, "message": ""},
            {"code": "B006", "filename": "a.py", "location": {"row": 2}, "message": ""},
        ]
    )
    findings = ruffrun.parse(text)
    assert [f["code"] for f in findings] == ["B006"]


def test_parse_rejects_non_json():
    with pytest.raises(RuntimeError, match="could not read ruff output"):
        ruffrun.parse("not json at all")


def test_no_warnings_says_so(tmp_path, capsys):
    payload = write(tmp_path, "ruff.json", "[]")
    assert cli.main([str(tmp_path), "--json", str(payload)]) == 0
    assert "No B006 or B023 warnings found" in capsys.readouterr().out
