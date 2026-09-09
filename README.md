# willitbite

[![CI](https://github.com/muhzuhaib/willitbite/actions/workflows/ci.yml/badge.svg)](https://github.com/muhzuhaib/willitbite/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/willitbite.svg)](https://pypi.org/project/willitbite/)

Ruff will tell you that 99 closures in your codebase capture a loop variable. It will not tell you
that none of them can actually bite you.

`willitbite` takes the two rules that produce most of the noise when a project first adopts ruff and
asks the question the linter cannot: **can this one reach you at runtime?**

Here it is on [ragflow](https://github.com/infiniflow/ragflow), 1,259 files of Python, at commit
`0c28d59`:

```
$ willitbite .
B006  mutable default arguments
  34 warning(s)   0 can bite   1 latent   13 depend on a callee   20 safe
    [LATENT] agent/component/message.py:159
             `kwargs` is mutated before it is rebound (kwargs[...] assigned on line
             181), but all 2 call sites of `get_kwargs()` pass it explicitly, so the
             shared default is never the one being changed

B023  closures capturing a loop variable
  99 warning(s)   0 can bite   15 depend on a callee   84 safe

Nothing here can bite today. 133 warning(s), 0 reachable defects, 1 latent.
```

133 warnings, ten seconds, and 29 of them are worth a person's time: the one latent
defect and the 28 that turn on a function the tool cannot see into. The other 104 need nobody.

## Why this exists

Both rules describe a shape, and the shape is not the bug.

**B023** flags every closure inside a loop that reads the loop variable. The bug it is looking for is
late binding: if the closure is still callable after the loop moves on, every copy sees the loop
variable's final value. A closure that is built and called inside the same iteration sees the value
it was written next to, which is what the author meant.

**B006** flags every mutable default argument. A mutable default is evaluated once and shared by
every call that omits it, but that only matters if the function changes it. A default that is only
read behaves exactly like the immutable one the author probably had in mind.

So a team switching these rules on faces a few hundred warnings, most of which are fine, with no way
to tell which is which except by reading all of them. That is the job this does.

## Install and run

```
pip install willitbite
willitbite ./src
```

Python 3.10 or newer. To work from a checkout instead:

```
git clone https://github.com/muhzuhaib/willitbite
pip install ./willitbite
```

Ruff is called as a subprocess if it is on your PATH. If you would rather run your own:

```
ruff check --select B006,B023 --output-format json ./src > warnings.json
willitbite --json warnings.json
```

| Flag | Effect |
| --- | --- |
| `--all` | list the safe warnings too, not just the actionable ones |
| `--json-out` | print results as JSON |
| `--exit-zero` | always exit 0, for a first run that should not fail a build |

Exit code is 1 when something can bite, 0 when nothing can, 2 when the tool could not run.

## Design decisions

**A linter has two states, warned and silent. This has four.** Two of the four exist because the
honest answer is sometimes neither of the other two.

`CALLEE` is for a closure handed to `run_with_retry(...)`, which is safe if that helper calls it and
dangerous if it stores it. Guessing safe would clear a real defect. Guessing unsafe would raise a
false alarm on every codebase this was built against. So it names the function you have to look at
and stops there.

`LATENT` is for a function that is genuinely wrong and that nothing currently calls in the way that
would hurt. It has its own section below.

**Ruff finds the candidates; this decides them.** Reimplementing the rules would be slower, less
correct, and would drift from ruff's behaviour. Ruff is invoked with `--isolated` on purpose, so the
answer does not depend on whether the project has enabled these rules: a team that has not adopted
them yet is exactly the team that wants this.

**Ruff is not a dependency.** A tool that reports on your linter should not pin a version of it.

**Every verdict carries a reason you can check without rerunning anything.** The reason names the
identifier and the line, never restates the rule. A verdict you have to take on trust is worth about
as much as the warning it replaced.

## Latent defects: real, but nothing calls them that way

A function that mutates its own mutable default is wrong on its own terms. Whether the wrongness can
reach you is a separate question, and it is answered in the callers: the shared default is only ever
the object being mutated when somebody omits the argument.

So B006 warnings that survive the first pass get a second one, across every `.py` file under the
path you gave. If some caller omits the argument, the verdict stays `BITES`. If every caller passes
it explicitly, the verdict becomes `LATENT`: still a defect, still reported, but nothing in the tree
triggers it today.

```
B006  mutable default arguments
  2 warning(s)   1 can bite   1 latent   0 depend on a callee   0 safe
    [BITES] live.py:1
           `cache` is mutated before it is rebound (cache[...] assigned on line 2),
           so every call that omits it sees the previous call's changes
    [LATENT] lib.py:1
           `items` is mutated before it is rebound (items.append() on line 2), but all
           2 call sites of `collect()` pass it explicitly, so the shared default is
           never the one being changed
```

Those two functions have the same shape. Only their callers differ.

**A latent defect does not fail the build.** The exit code answers "can this bite today", and this
one cannot, so failing on it would fail every build until somebody rewrote code that currently
works. It is in the report because it will bite the first caller who leaves the argument out.

## Known boundary: which callers get matched

Call sites are matched **by name**. Resolving `x.send()` to a definition properly needs type
inference, which this does not do, so a call counts whenever the called name matches, wherever it
appears. That over-matches, and the over-matching is deliberate: an unrelated `send` elsewhere can
only add an omission, and an omission is the answer that keeps the warning.

Import aliases are resolved before the name match runs: `from lib import collect as c` followed by
`c(...)` is counted as a call to `collect`, including through relative imports. This matters because
an alias hides callers without adding any, and a caller the index cannot see counts as absent, which
is the direction a false `LATENT` comes from.

Four things count as no evidence at all, and each of them leaves a warning at `BITES`:

- a `**kwargs` splat at the call site, which might be carrying the argument
- a `*args` splat, which might be filling the position
- **no caller anywhere**, which usually means a public entry point called from outside the tree you
  scanned, and is the case most likely to bite a stranger
- a name that reaches the function some other way: a star import, a rebinding like
  `handler = collect`, or dispatch that only exists at runtime

The index is only built when something came back `BITES`, so a run that finds nothing reachable
never pays for the scan.

## Where this came from

It was written while triaging 138 ruff warnings across two large open-source Python codebases by
hand. All 99 loop-closure warnings turned out to be false alarms, as did every mutable-default
warning that was actually reachable. Reading them one at a time to learn that took most of a day,
which seemed like a poor way to spend the next one.

## License

MIT
