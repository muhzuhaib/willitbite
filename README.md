# willitbite

[![CI](https://github.com/muhzuhaib/willitbite/actions/workflows/ci.yml/badge.svg)](https://github.com/muhzuhaib/willitbite/actions/workflows/ci.yml)

Ruff will tell you that 99 closures in your codebase capture a loop variable. It will not tell you
that none of them can actually bite you.

`willitbite` takes the two rules that produce most of the noise when a project first adopts ruff and
asks the question the linter cannot: **can this one reach you at runtime?**

```
$ willitbite ./src
B023  closures capturing a loop variable
  99 warning(s)   0 can bite   15 depend on a callee   84 safe

B006  mutable default arguments
  34 warning(s)   1 can bite   0 depend on a callee   33 safe
    [BITES] agent/component/message.py:159
            `kwargs` is mutated before it is rebound (kwargs[...] assigned on
            line 181), so every call that omits it sees the previous call's changes

1 of 133 warning(s) can actually bite.
```

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

**There are three verdicts, not two.** A linter has two states, warned and silent. Reachability has a
third, because whether a closure escapes sometimes depends on a function this tool cannot see into.
When a closure is handed to `run_with_retry(...)`, it is safe if that helper calls it and dangerous
if it stores it. Guessing safe would clear a real defect; guessing unsafe would raise a false alarm
on the codebases this was built against. So `CALLEE` names the function you have to look at and stops
there.

**Ruff finds the candidates; this decides them.** Reimplementing the rules would be slower, less
correct, and would drift from ruff's behaviour. Ruff is invoked with `--isolated` on purpose, so the
answer does not depend on whether the project has enabled these rules: a team that has not adopted
them yet is exactly the team that wants this.

**Ruff is not a dependency.** A tool that reports on your linter should not pin a version of it.

**Every verdict carries a reason you can check without rerunning anything.** The reason names the
identifier and the line, never restates the rule. A verdict you have to take on trust is worth about
as much as the warning it replaced.

## Known boundary: call sites are not read yet

The B006 answer is about the function, not about the program. If a function mutates its shared
default, this reports `BITES`, and that is a genuine latent defect. But it only fires in practice
when some caller omits the argument, and this does not yet check whether any caller does.

That distinction is not hypothetical. The `kwargs` example in the output above is real, and every
current caller of it passes an explicit dict, so today it never triggers. It is still a defect
waiting for the first caller who does not.

## Where this came from

It was written while triaging 138 ruff warnings across two large open-source Python codebases by
hand. All 99 loop-closure warnings turned out to be false alarms, as did every mutable-default
warning that was actually reachable. Reading them one at a time to learn that took most of a day,
which seemed like a poor way to spend the next one.

## License

MIT
