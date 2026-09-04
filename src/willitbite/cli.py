"""The command line: run ruff, decide every warning, report what can bite."""

import argparse
import ast
import io
import json
import sys
from collections import defaultdict

from . import __version__, escape, mutation, ruffrun
from .verdict import BITES, CALLEE, ORDER, SAFE, Verdict

ANALYSERS = {"B023": escape.analyse, "B006": mutation.analyse}

RULE_TITLES = {
    "B023": "closures capturing a loop variable",
    "B006": "mutable default arguments",
}


def decide(findings):
    """Attach a verdict to every finding, parsing each file once."""
    by_file = defaultdict(list)
    for finding in findings:
        by_file[finding["filename"]].append(finding)

    decided = []
    for filename, group in by_file.items():
        try:
            source = io.open(filename, encoding="utf-8").read()
            tree = ast.parse(source)
        except (OSError, SyntaxError) as exc:
            for finding in group:
                decided.append({**finding, "verdict": Verdict(CALLEE, f"unreadable: {exc}")})
            continue
        parents = escape.parent_map(tree)
        for finding in group:
            analyse = ANALYSERS.get(finding["code"])
            if analyse is None:
                continue
            decided.append(
                {**finding, "verdict": analyse(tree, finding["line"], parents)}
            )
    return decided


def _counts(rows):
    tally = defaultdict(int)
    for row in rows:
        tally[row["verdict"].kind] += 1
    return tally


def render(decided, show_all=False):
    """Human-readable report. Returns the lines."""
    lines = []
    by_rule = defaultdict(list)
    for row in decided:
        by_rule[row["code"]].append(row)

    total_bites = 0
    for code in sorted(by_rule):
        rows = by_rule[code]
        tally = _counts(rows)
        total_bites += tally[BITES]
        lines.append(f"{code}  {RULE_TITLES.get(code, '')}")
        lines.append(
            f"  {len(rows)} warning(s)   {tally[BITES]} can bite   "
            f"{tally[CALLEE]} depend on a callee   {tally[SAFE]} safe"
        )
        wanted = ORDER if show_all else (BITES, CALLEE)
        for kind in wanted:
            for row in sorted(rows, key=lambda r: (r["filename"], r["line"])):
                if row["verdict"].kind != kind:
                    continue
                lines.append(f"    [{kind}] {row['filename']}:{row['line']}")
                lines.append(f"           {row['verdict'].reason}")
        lines.append("")

    if not decided:
        lines.append("No B006 or B023 warnings found.")
    elif total_bites == 0:
        lines.append(
            f"Nothing here can bite. {len(decided)} warning(s), 0 reachable defects."
        )
    else:
        lines.append(f"{total_bites} of {len(decided)} warning(s) can actually bite.")
    return lines


def as_json(decided):
    return json.dumps(
        {
            "warnings": len(decided),
            "bites": sum(1 for r in decided if r["verdict"].kind == BITES),
            "results": [
                {
                    "code": r["code"],
                    "filename": r["filename"],
                    "line": r["line"],
                    "verdict": r["verdict"].kind,
                    "reason": r["verdict"].reason,
                }
                for r in decided
            ],
        },
        indent=2,
    )


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="willitbite",
        description=(
            "Decide which of ruff's loop-closure and mutable-default warnings "
            "can actually reach you at runtime."
        ),
    )
    parser.add_argument("path", nargs="?", default=".", help="file or directory to inspect")
    parser.add_argument("--version", action="version", version=f"willitbite {__version__}")
    parser.add_argument(
        "--json", dest="json_in", metavar="FILE",
        help="read ruff's JSON output from FILE instead of running ruff",
    )
    parser.add_argument("--json-out", action="store_true", help="print results as JSON")
    parser.add_argument("--all", action="store_true", help="list the safe warnings too")
    parser.add_argument(
        "--exit-zero", action="store_true",
        help="always exit 0, even when something can bite",
    )
    args = parser.parse_args(argv)

    try:
        if args.json_in:
            findings = ruffrun.parse(io.open(args.json_in, encoding="utf-8").read())
        else:
            findings = ruffrun.run(args.path)
    except (ruffrun.RuffMissing, RuntimeError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    decided = decide(findings)

    if args.json_out:
        print(as_json(decided))
    else:
        print("\n".join(render(decided, show_all=args.all)))

    if args.exit_zero:
        return 0
    return 1 if any(r["verdict"].kind == BITES for r in decided) else 0


if __name__ == "__main__":
    raise SystemExit(main())
