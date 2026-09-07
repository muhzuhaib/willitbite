# Contributing

Thanks for looking. This is a small tool with one job: decide which of ruff's
B006 and B023 warnings can actually reach you at runtime. The bar for a change
is whether it makes that decision more trustworthy.

## The most valuable report

**A verdict that is wrong.** This tool does not just count warnings, it claims
things about your code: that a warning is `SAFE`, that a defect is `LATENT`,
that a closure `DEPENDS ON A CALLEE`. A warning marked `SAFE` that can really
bite is the worst defect this tool can have, because the whole point is that
you stop reading the ones it clears. A `BITES` verdict on code that is fine
costs the trust the tool lives on too. There is an issue form for exactly this.
Please include the tool's output for the file and the code of the function in
question; both together make a report reproducible in minutes.

## Known limitations, stated so they do not come back as bug reports

- **A warning with no caller found anywhere stays `BITES`.** Absence of
  evidence never downgrades anything. If the call site is behind a decorator,
  a framework, or a language we do not model, the tool refuses to guess.
- **`*args` and `**kwargs` splats keep a warning.** A splat can pass anything,
  including the omitted argument, so the honest verdict is the loud one.
- **`CALLEE` is a verdict on purpose.** When safety depends on what some other
  function does with your callable, the tool names that function instead of
  pretending to know. It will not chase into other modules for you.
- **Call sites are found within the path you scanned.** Point it at `./src`
  and that is the world it reasons about.

## Running the tests

```console
pip install -e ".[dev]"
pytest -q
```

Nothing in the suite touches the network and it does not need ruff installed:
the tests build ruff's own JSON output shape inline and run the real code path
over files written to a temporary directory.

## What a change needs

- **A test that fails without it.** For anything that changes a verdict, the
  test should be a control case: it must fail if the behaviour is removed, not
  merely pass while it is present.
- **A note in the README if it changes what a verdict means.** The Design
  decisions section is the contract people read before trusting an exit code.
- **One concern per pull request.** Small is easy to read and easy to merge.

## What is deliberately out of scope

- **Other ruff rules.** B006 and B023 produce most of the noise when a project
  adopts ruff's bugbear set, and depth on two rules beats shallowness on twenty.
  A third rule is welcome as a proposal, with the same four-verdict honesty.
- **Fixing the code.** This decides what is worth a person's time; it does not
  rewrite your functions.
- **Runtime dependencies.** The analysis uses the standard library's `ast`
  module, and ruff is invoked as a subprocess only when it is already on your
  PATH. A tool that tells you about your linter should not force a version of
  it on you.

## Code style

Plain Python, type hints on anything that crosses a module boundary, and
comments that say why rather than what. Line length 100.
