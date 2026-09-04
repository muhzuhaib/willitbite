# willitbite

Ruff will tell you that 99 closures in your codebase capture a loop variable. It will not tell
you that none of them can actually bite you.

`willitbite` takes the warnings that are famous for being mostly false alarms and asks the
question the linter cannot: **can this one reach you at runtime?**

```
$ willitbite ./src
B023  closures capturing a loop variable
  99 warnings   0 can bite   84 consumed in the same iteration   15 safe on inspection

B006  mutable default arguments
  39 warnings   0 can bite   39 never mutated

Nothing here can bite. 138 warnings, 0 reachable defects.
```

## Why this exists

Two lint rules generate most of the noise in a Python codebase that has just adopted ruff, and
both of them describe a shape rather than a bug:

- **B023** flags every closure inside a loop that reads the loop variable. That is only wrong when
  the closure outlives the iteration that made it. A closure built and called in the same
  iteration reads the value it was written next to, which is what the author meant.
- **B006** flags every mutable default argument. That is only wrong when the function changes it,
  because the same object is reused on every call that omits the argument. A default that is only
  read is harmless.

So a team adopting these rules faces a few hundred warnings, most of which are fine, and no way to
tell which is which except by reading all of them. That is the job this does.

## Install and run

```
pip install willitbite
willitbite ./src
```

## Status

Early. B023 and B006 are implemented and tested. See CHANGELOG.md.

## License

MIT
