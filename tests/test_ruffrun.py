"""Input that is valid JSON but is not a ruff report."""

import pytest

from willitbite import cli, ruffrun

NOT_A_REPORT = ["null", "3", '{"version": "2.1.0", "runs": []}', "[1, 2]"]


@pytest.mark.parametrize("text", NOT_A_REPORT)
def test_json_that_is_not_a_list_of_findings_is_refused(text):
    with pytest.raises(RuntimeError, match="not a list of findings"):
        ruffrun.parse(text)


@pytest.mark.parametrize("text", NOT_A_REPORT)
def test_the_command_line_exits_2_on_it(tmp_path, capsys, text):
    payload = tmp_path / "report.json"
    payload.write_text(text, encoding="utf-8")

    assert cli.main([str(tmp_path), "--json", str(payload)]) == 2
    assert "not a list of findings" in capsys.readouterr().err


def test_an_empty_report_is_still_clean():
    assert ruffrun.parse("[]") == []
