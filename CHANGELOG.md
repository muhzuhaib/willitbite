# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.1.3] - 2026-09-11

### Fixed

- A second name made by an assignment rather than by an import hid callers from
  the call-site pass. A package that re-exports with `from lib import collect`
  followed by `c = collect`, read by a caller writing `from pkg import c`,
  spells the connection as an import nowhere, so the call was filed under `c`
  alone; one visible caller that supplied the argument then read as the whole
  story and the warning was cleared `LATENT` with the omitting call two files
  away. A plain `handler = collect` in the caller's own file hid one the same
  way. Assignments now make binding edges alongside imports, so a chain can
  alternate between the two kinds for as many hops as it takes.

### Changed

- The README's known-boundary section claimed every unresolved route leaves its
  warning at `BITES`. That holds only when such a route is the function's only
  caller; when other callers are visible, they become the whole evidence and a
  warning can be cleared on a partial view. The section now says so, and lists
  what is still unresolved: a star import, a module-level `__getattr__`, a name
  arriving through a data structure or runtime dispatch, and a value built by a
  call rather than bound to a name.

## [0.1.2] - 2026-09-10

### Fixed

- Call sites written through a package re-export were invisible to the call-site
  pass. When `pkg/__init__.py` holds `from lib import collect as c` and a caller
  writes `from pkg import c`, the caller's own file aliases nothing, so the call
  was filed under `c` alone and a warning could be cleared `LATENT` while the
  call that omits the argument sat in the same tree. Each module's import
  bindings are now collected first and every call is filed under all spellings
  its chain of bindings reaches, however many re-exports it passes through.

## [0.1.1] - 2026-09-09

### Fixed

- Call sites written through an import alias (`from lib import collect as c`,
  then `c(...)`) were invisible to the call-site pass. A warning whose only
  visible caller supplied the argument could be cleared as `LATENT` while the
  call that omits the argument sat in the same tree. Aliased calls are now
  indexed under the imported name as well as the alias.

## [0.1.0] - 2026-09-08

### Added

- First release.

- B023 escape analysis: decides whether a closure that captures a loop variable
  can still be called after the loop has moved on.
- B006 mutable default analysis: decides whether a shared default is ever
  actually mutated, accounting for the common `items = items or []` rebind and
  for augmented assignment, which mutates a list in place rather than rebinding.
- A third verdict, `CALLEE`, for the cases where the answer depends on a
  function the tool cannot see into. It names that function instead of guessing.
- Call-site analysis for B006. A mutable default can only be corrupted by a
  caller that omits the argument, so warnings that survive the first pass are
  checked against every call site under the path. When all of them pass the
  argument explicitly the verdict becomes `LATENT`: the defect is real and is
  still reported, but nothing in the tree can trigger it today. Anything the
  scan cannot resolve stays at `BITES`, including a `*args` or `**kwargs` splat
  at the call site and the case of no caller at all, which usually means a
  public entry point called from outside the tree.
- `LATENT` does not set a failing exit code. The exit code answers whether
  something can bite today.
- Command line with `--json` input, `--json-out`, `--all` and `--exit-zero`.
