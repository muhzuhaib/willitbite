"""Get the warnings from ruff, or from a file ruff already wrote.

This does not reimplement the rules. Ruff decides what is a candidate and does
it faster and more correctly than a hand-rolled matcher would; the value here is
entirely in what happens to the list afterwards. Two consequences follow.

Ruff is invoked with ``--isolated`` so the answer does not depend on whether the
project being inspected happens to enable these rules. A team that has not
adopted B006 and B023 yet is exactly the team that wants this, and their config
would otherwise return nothing.

Ruff is not a dependency. It is looked up as a subprocess and its absence is
reported as the ordinary situation it is, with the ``--json`` route available
for anyone who would rather run their own ruff and pipe the result in.
"""

import json
import shutil
import subprocess
import sys

#: The rules this tool can decide. Adding one means adding an analyser.
SUPPORTED = ("B006", "B023")


class RuffMissing(RuntimeError):
    """ruff is not on PATH."""


def ruff_available():
    return shutil.which("ruff") is not None or _module_available()


def _module_available():
    try:
        subprocess.run(
            [sys.executable, "-m", "ruff", "--version"],
            capture_output=True,
            check=True,
        )
        return True
    except (subprocess.CalledProcessError, OSError):
        return False


def _ruff_command():
    if shutil.which("ruff"):
        return ["ruff"]
    if _module_available():
        return [sys.executable, "-m", "ruff"]
    raise RuffMissing(
        "ruff was not found. Install it with `pip install ruff`, or run ruff "
        "yourself and pass its output with --json."
    )


def run(path, rules=SUPPORTED):
    """Run ruff over ``path`` and return its findings for ``rules``."""
    command = _ruff_command() + [
        "check",
        # The project's own configuration is deliberately ignored: the people
        # who need this are the ones who have not enabled these rules yet.
        "--isolated",
        "--select",
        ",".join(rules),
        "--output-format",
        "json",
        str(path),
    ]
    # A non-zero exit only means ruff found something, which is the normal case
    # here, so the return code is not checked. A real failure shows up as
    # unparseable output and is reported as that.
    finished = subprocess.run(command, capture_output=True, text=True)
    if not finished.stdout.strip():
        if finished.returncode not in (0, 1):
            raise RuntimeError(finished.stderr.strip() or "ruff failed")
        return []
    return parse(finished.stdout)


def parse(text):
    """Parse ruff's JSON output into the shape the analysers want."""
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"could not read ruff output as JSON: {exc}") from exc

    findings = []
    for item in raw:
        code = item.get("code")
        if code not in SUPPORTED:
            continue
        location = item.get("location") or {}
        findings.append(
            {
                "code": code,
                "filename": item.get("filename", ""),
                "line": location.get("row", 0),
                "message": item.get("message", ""),
            }
        )
    return findings
